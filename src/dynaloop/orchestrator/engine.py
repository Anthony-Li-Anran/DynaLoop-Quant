"""Orchestrator: one deterministic multi-round six-stage loop with run tracing.

Execution order follows data dependencies, not the numbering of the original
diagram: Wake verdicts (④) must be frozen before Sleep (③) can fit a proxy,
and the Statistical Feedback produced by ⑥ is consumed by ① of the *next*
round, exactly as the diagram's feedback arrow specifies.

Every edge calls the callee's public interface. Data, the backtest engine,
Research, Model, Inference, Training, Market Environment and the frontend are
used as-is; no parsing, matching or metric code is duplicated here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

from dynaloop.experiment_management.domain.errors import (
    ExperimentNotFoundError,
    ExperimentRunConflictError,
)
from dynaloop.experiment_management.domain.models import (
    ArtifactReference,
    Experiment,
    ExperimentRunStatus,
)
from dynaloop.experiment_management.facade import ExperimentManagementFacade
from dynaloop.infrastructure import (
    LoopSchedule,
    StageFailure,
    StageRecord,
    StageStatus,
    execute_stage,
    get_runtime_info,
)
from dynaloop.inference_engine import CandidateBatch, InferenceEngine, SamplingRequest
from dynaloop.market_environment import (
    BiasInjection,
    EnvironmentDefinition,
    EnvironmentRegistry,
    EnvironmentRuntime,
    EnvironmentType,
    ProxyCalibration,
    ProxyConfig,
    SimulatedEstimation,
    SimulationFeedback,
)
from dynaloop.model import CandidateGenerator, build_generator
from dynaloop.orchestrator.config import ORCHESTRATOR_SCHEMA_VERSION, LoopConfig
from dynaloop.orchestrator.directions import (
    DirectionAdapter,
    ReliabilityDirectionAdapter,
)
from dynaloop.orchestrator.state import (
    STAGE_ORDER,
    LoopResult,
    LoopStage,
    RoundRecord,
)
from dynaloop.research_engine import (
    ExplorationPolicy,
    FactorEvaluation,
    FactorResearch,
    uniform_policy,
    window_records,
)
from dynaloop.research_engine.spec import fingerprint, library_versions
from dynaloop.statistical_uncertainty_engine import (
    CalibrationConfig,
    ResamplingConfig,
    StatisticalConfig,
    StatisticalEngine,
    StatisticalFeedback,
    StatisticalReport,
    build_family,
)
from dynaloop.training_engine import TrainingEngine, TrainingStep

T = TypeVar("T")


class LoopError(RuntimeError):
    """A round failed; ``stages`` keeps the records produced before failure."""

    def __init__(self, message: str, *, stages: tuple[StageRecord, ...] = ()) -> None:
        super().__init__(message)
        self.stages = stages


@dataclass(frozen=True, slots=True)
class _RoundOutcome:
    record: RoundRecord
    policy: ExplorationPolicy
    calibration: ProxyCalibration
    feedback: StatisticalFeedback
    family: Any
    run_id: str
    ic_map: dict[str, float | None]


class LoopOrchestrator:
    """Drive the six stages for N rounds and emit one reproducible spec."""

    def __init__(
        self,
        config: LoopConfig | None = None,
        *,
        schedule: LoopSchedule | None = None,
        research: FactorResearch | None = None,
        inference: InferenceEngine | None = None,
        training: TrainingEngine | None = None,
        statistical: StatisticalEngine | None = None,
        generator: CandidateGenerator | None = None,
        direction_adapter: DirectionAdapter | None = None,
        runtime: EnvironmentRuntime | None = None,
        registry: EnvironmentRegistry | None = None,
        experiment_facade: ExperimentManagementFacade | None = None,
    ) -> None:
        self.config = config or LoopConfig()
        self.schedule = schedule or LoopSchedule(
            rounds=self.config.rounds, seed=self.config.seed
        )
        self.research = research or FactorResearch()
        self.inference = inference or InferenceEngine()
        self.training = training or TrainingEngine()
        self.statistical = statistical or StatisticalEngine(
            config=StatisticalConfig(
                resampling=ResamplingConfig(
                    reps=self.config.statistical_reps,
                    block_size=self.config.statistical_block_size,
                    alpha=self.config.alpha,
                    seed=self.config.seed,
                ),
                calibration=CalibrationConfig(alpha=self.config.alpha),
            )
        )
        self.generator = generator or build_generator(self.config.generator)
        self.direction_adapter = direction_adapter or ReliabilityDirectionAdapter(
            strength=self.config.direction_strength
        )
        self.registry = registry or self._default_registry()
        self.runtime = runtime or EnvironmentRuntime(self.registry)
        self.experiment_facade = experiment_facade
        self.real_reference, self.simulated_reference = self._resolve_references(
            self.registry
        )

    def _default_registry(self) -> EnvironmentRegistry:
        # The run owns its inclusive window. Environment TimeRange is an
        # optional half-open applicability range, not a second run filter.
        return EnvironmentRegistry(
            [
                EnvironmentDefinition(
                    "wake-real", "1", EnvironmentType.REAL,
                    source="frozen-stage1-evaluation",
                ),
                EnvironmentDefinition(
                    "sleep-simulated", "1", EnvironmentType.SIMULATED,
                    source="resampled-backtest-proxy",
                ),
            ]
        )

    @staticmethod
    def _resolve_references(
        registry: EnvironmentRegistry,
    ) -> tuple[Any, Any]:
        real: list[Any] = []
        simulated: list[Any] = []
        for reference in registry.references():
            definition = registry.spec(reference)
            if definition.environment_type is EnvironmentType.REAL:
                real.append(reference)
            elif definition.environment_type is EnvironmentType.SIMULATED:
                simulated.append(reference)
        if not real or not simulated:
            raise LoopError("The environment registry needs one REAL and one SIMULATED definition.")
        return real[0], simulated[0]

    def _sampling_request(self, round_index: int) -> SamplingRequest:
        config = self.config
        return SamplingRequest(
            seed=config.seed,
            round_index=round_index,
            group_size=config.group_size,
            features=config.features,
            windows=config.windows,
        )

    def _stage(
        self,
        stages: list[StageRecord],
        stage: LoopStage,
        operation: Callable[[], T],
        *,
        digest: Callable[[T], str] | None = None,
        describe: Callable[[T], dict[str, Any]] | None = None,
    ) -> T:
        try:
            value, attempts = execute_stage(
                stage.value, operation, retry_policy=self.schedule.retry_policy
            )
        except StageFailure as error:
            stages.append(
                StageRecord(
                    stage.value,
                    StageStatus.FAILED,
                    None,
                    error.attempts,
                    {"error": str(error)},
                )
            )
            raise LoopError(str(error), stages=tuple(stages)) from error
        stages.append(
            StageRecord(
                stage=stage.value,
                status=StageStatus.COMPLETED,
                fingerprint=digest(value) if digest else None,
                attempts=attempts,
                spec=describe(value) if describe else {},
            )
        )
        return value

    def run(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> LoopResult:
        rows = tuple(dict(row) for row in records)
        if not rows:
            raise LoopError("A loop run needs frozen bar records.")
        windowed = tuple(
            window_records(rows, start=self.config.start, end=self.config.end)
        )
        if not windowed:
            raise LoopError("The configured window contains no bar records.")
        data_fingerprint = fingerprint([dict(row) for row in windowed])

        generation_request = self._sampling_request(0).generation_request(
            self.config.group_size
        )
        keys = self.generator.choice_keys(generation_request)
        initial_policy = uniform_policy(keys)
        policy = initial_policy
        pending_feedback: StatisticalFeedback | None = None
        history: list[dict[str, float | None]] = []
        round_records: list[RoundRecord] = []
        run_ids: list[str] = []
        final_calibration: ProxyCalibration | None = None
        final_reliability = 0.0

        for round_index in range(self.schedule.rounds):
            outcome = self._run_round(
                rows=rows,
                windowed=windowed,
                data_fingerprint=data_fingerprint,
                round_index=round_index,
                policy=policy,
                pending_feedback=pending_feedback,
                previous_calibration=final_calibration,
                history=tuple(history),
                source_metadata=source_metadata,
            )
            round_records.append(outcome.record)
            run_ids.append(outcome.run_id)
            policy = outcome.policy
            pending_feedback = outcome.feedback
            final_calibration = outcome.calibration
            final_reliability = outcome.feedback.reliability
            history.append(outcome.ic_map)
            if self.schedule.should_stop(
                round_index=round_index,
                rounds_completed=len(round_records),
                reliability=final_reliability,
            ):
                break

        if final_calibration is None:
            raise LoopError("The loop produced no proxy calibration.")
        spec = {
            "schema_version": ORCHESTRATOR_SCHEMA_VERSION,
            "config": self.config.to_dict(),
            "schedule": self.schedule.to_dict(),
            "stage_order": [stage.value for stage in STAGE_ORDER],
            "initial_policy": initial_policy.to_dict(),
            "generator": self.generator.spec(generation_request),
            "statistical": self.statistical.spec(),
            "direction": self.direction_adapter.spec(),
            "environment_registry": self.registry.fingerprint(),
            "data_fingerprint": data_fingerprint,
            "source_metadata": dict(source_metadata or {}),
            "rounds": [item.spec for item in round_records],
            "round_fingerprints": [item.fingerprint() for item in round_records],
            "run_ids": list(run_ids),
            "final": {
                "policy_fingerprint": policy.fingerprint(),
                "policy_version": policy.version,
                "calibration_fingerprint": final_calibration.fingerprint(),
                "calibration_version": final_calibration.version,
                "reliability": final_reliability,
            },
            "library_versions": library_versions(),
        }
        info = get_runtime_info()
        environment = {
            "python_version": info.python_version,
            "os_name": info.os_name,
            "platform": info.platform,
            "project_version": info.project_version,
            "excluded_from_fingerprint": True,
        }
        return LoopResult(
            rounds=tuple(round_records),
            final_policy=policy,
            final_calibration=final_calibration,
            final_reliability=final_reliability,
            run_ids=tuple(run_ids),
            spec=spec,
            environment=environment,
        )

    def _run_round(
        self,
        *,
        rows: tuple[dict[str, Any], ...],
        windowed: tuple[dict[str, Any], ...],
        data_fingerprint: str,
        round_index: int,
        policy: ExplorationPolicy,
        pending_feedback: StatisticalFeedback | None,
        previous_calibration: ProxyCalibration | None,
        history: tuple[Mapping[str, float | None], ...],
        source_metadata: Mapping[str, Any] | None,
    ) -> _RoundOutcome:
        stages: list[StageRecord] = []
        config = self.config

        # ① Exploration Policy: apply last round's ⑥ feedback, build the request.
        def exploration_policy() -> tuple[ExplorationPolicy, SamplingRequest, dict[str, Any]]:
            active, detail = policy, {
                "adapter": self.direction_adapter.name,
                "applied_keys": [],
                "skipped_keys": [],
                "feedback_fingerprint": None,
            }
            if pending_feedback is not None:
                active, detail = self.direction_adapter.adapt(policy, pending_feedback)
            return active, self._sampling_request(round_index), detail

        active_policy, request, direction_detail = self._stage(
            stages, LoopStage.EXPLORATION_POLICY, exploration_policy,
            digest=lambda value: fingerprint(
                {"policy": value[0].fingerprint(), "request": value[1].to_dict()}
            ),
            describe=lambda value: {
                "policy": value[0].to_dict(),
                "request": value[1].to_dict(),
                "direction": value[2],
            },
        )

        # ② Factor Discovery: sample the candidate family.
        batch: CandidateBatch = self._stage(
            stages, LoopStage.FACTOR_DISCOVERY,
            lambda: self.inference.sample(self.generator, active_policy, request),
            digest=lambda value: value.fingerprint(),
            describe=lambda value: value.spec,
        )

        # ④ Wake: freeze the only verdicts, reusing stage 1's deterministic engine.
        evaluations: tuple[FactorEvaluation, ...] = self._stage(
            stages, LoopStage.WAKE_VALIDATION,
            lambda: self.research.evaluate_batch(
                [candidate.expression for candidate in batch.candidates],
                rows,
                symbol=config.symbol,
                start=config.start,
                end=config.end,
                source_metadata=source_metadata,
            ),
            digest=lambda value: fingerprint([item.fingerprint() for item in value]),
            describe=lambda value: {
                "data_fingerprint": data_fingerprint,
                "adjudicator": "stage1 FactorEvaluation / deterministic backtest engine",
                "evaluations": [
                    {
                        "factor_id": item.candidate.factor_id,
                        "fingerprint": item.fingerprint(),
                        "statistics": dict(item.statistics),
                    }
                    for item in value
                ],
            },
        )

        # ③ Sleep: proxy estimation, bias feedback, proxy model update.
        def sleep() -> tuple[Any, tuple[SimulatedEstimation, ...], SimulationFeedback, ProxyCalibration]:
            proxy_config = ProxyConfig(
                reward=self.training.reward_spec,
                seed=config.seed,
                round_index=round_index,
                reps=config.proxy_reps,
                block_size=config.proxy_block_size,
                interval_size=1.0 - config.alpha,
            )
            bias = BiasInjection(
                magnitude=config.bias_magnitude, mode=config.bias_mode
            )
            session = self.runtime.open(
                self.real_reference,
                self.simulated_reference,
                evaluations,
                tuple(batch.candidates),
                config=proxy_config,
                bias=bias,
                calibration=previous_calibration,
            )
            estimations = session.estimate()
            simulation_feedback = session.feedback(estimations)
            calibration = session.recalibrate()
            return session, estimations, simulation_feedback, calibration

        session, estimations, simulation_feedback, calibration = self._stage(
            stages, LoopStage.SLEEP_SIMULATION, sleep,
            digest=lambda value: fingerprint(
                {
                    "estimations": [item.fingerprint() for item in value[1]],
                    "feedback": value[2].fingerprint(),
                    "calibration": value[3].fingerprint(),
                }
            ),
            describe=lambda value: {
                "session": value[0].spec(),
                "estimations": [item.to_dict() for item in value[1]],
                "simulation_feedback": value[2].to_dict(),
                "calibration": value[3].to_dict(),
            },
        )

        # ⑤ Joint Adaptation: policy update from the Wake verdicts.
        def joint() -> tuple[ExplorationPolicy, TrainingStep]:
            return self.training.update(active_policy, batch, evaluations)

        next_policy, training_step = self._stage(
            stages, LoopStage.JOINT_UPDATE, joint,
            digest=lambda value: fingerprint(
                {
                    "policy": value[0].fingerprint(),
                    "step": value[1].fingerprint(),
                    "calibration": calibration.fingerprint(),
                }
            ),
            describe=lambda value: {
                "training": value[1].spec,
                "policy_after": value[0].to_dict(),
                "proxy_model_update": calibration.to_dict(),
            },
        )

        # ⑥ Statistical Validation: descriptive report + feedback to next ①.
        def statistical() -> tuple[Any, StatisticalReport, StatisticalFeedback]:
            choices = tuple(
                (evaluation.candidate.factor_id, batch.choices[position])
                for position, evaluation in enumerate(evaluations)
            )
            family = build_family(
                evaluations,
                round_index=round_index,
                estimations=estimations,
                feedback=simulation_feedback,
                records=windowed,
                choices=choices,
                history=history,
                reward_spec=self.training.reward_spec,
            )
            report = self.statistical.validate(family)
            feedback = self.statistical.feedback(report, family)
            return family, report, feedback

        family, report, feedback = self._stage(
            stages, LoopStage.STATISTICAL_VALIDATION, statistical,
            digest=lambda value: value[1].fingerprint(),
            describe=lambda value: {
                "family_id": value[0].family_id,
                "method": self.statistical.method.name,
                "report": {
                    "reliability": value[1].reliability,
                    "flags": list(value[1].flags),
                    "robustness": value[1].robustness,
                    "selection": value[1].selection.to_dict(),
                    "calibration": value[1].calibration.to_dict(),
                },
                "statistical_feedback": value[2].to_dict(),
            },
        )

        stage_specs = {item.stage: item.spec for item in stages}
        round_spec = {
            "schema_version": ORCHESTRATOR_SCHEMA_VERSION,
            "round_index": round_index,
            "data_fingerprint": data_fingerprint,
            "stages": [item.to_dict() for item in stages],
            "direction": direction_detail,
            "sampling": batch.spec,
            "wake": stage_specs[LoopStage.WAKE_VALIDATION.value],
            "sleep": stage_specs[LoopStage.SLEEP_SIMULATION.value],
            "training": stage_specs[LoopStage.JOINT_UPDATE.value],
            "statistics": stage_specs[LoopStage.STATISTICAL_VALIDATION.value],
            "family_id": family.family_id,
            "final": {
                "policy_fingerprint": next_policy.fingerprint(),
                "policy_version": next_policy.version,
                "calibration_fingerprint": calibration.fingerprint(),
                "calibration_version": calibration.version,
                "reliability": feedback.reliability,
            },
        }
        run_id = fingerprint(
            {
                "loop": config.fingerprint(),
                "round_index": round_index,
                "spec": round_spec,
            }
        )[:32]
        round_spec["run_id"] = run_id
        round_spec["experiment_persisted"] = bool(
            self.experiment_facade and config.experiment_id
        )
        self._record_experiment(
            round_index=round_index,
            run_id=run_id,
            spec=round_spec,
            report=report,
            simulation_feedback=simulation_feedback,
            feedback=feedback,
            policy=next_policy,
            calibration=calibration,
        )
        record = RoundRecord(
            round_index=round_index,
            stages=tuple(stages),
            spec=round_spec,
            run_id=run_id,
        )
        ic_map = {
            item.candidate.factor_id: (
                float(item.statistics["ic"])
                if item.statistics.get("ic") is not None
                and math.isfinite(float(item.statistics["ic"]))
                else None
            )
            for item in evaluations
        }
        return _RoundOutcome(
            record=record,
            policy=next_policy,
            calibration=calibration,
            feedback=feedback,
            family=family,
            run_id=run_id,
            ic_map=ic_map,
        )

    def _record_experiment(
        self,
        *,
        round_index: int,
        run_id: str,
        spec: dict[str, Any],
        report: StatisticalReport,
        simulation_feedback: SimulationFeedback,
        feedback: StatisticalFeedback,
        policy: ExplorationPolicy,
        calibration: ProxyCalibration,
    ) -> bool:
        facade = self.experiment_facade
        experiment_id = self.config.experiment_id
        if facade is None or not experiment_id:
            return False
        try:
            facade.get_experiment(experiment_id)
        except ExperimentNotFoundError:
            facade.create_experiment(
                Experiment(
                    experiment_id=experiment_id,
                    name="DynaLoop six-stage loop",
                    configuration_version=str(ORCHESTRATOR_SCHEMA_VERSION),
                )
            )

        raw_metrics: tuple[tuple[str, Any], ...] = (
            ("reliability", feedback.reliability),
            ("proxy_model_bias", simulation_feedback.model_bias),
            ("proxy_mean_absolute_error", simulation_feedback.mean_absolute_error),
            ("proxy_mean_uncertainty", simulation_feedback.mean_uncertainty),
            ("proxy_amplification", simulation_feedback.amplification),
            ("rejected_count", report.selection.rejected_count),
            ("empirical_coverage", report.calibration.empirical_coverage),
            ("family_size", report.robustness.get("family_size")),
            ("policy_version", policy.version),
            ("calibration_version", calibration.version),
        )
        metrics = tuple(
            (name, float(value))
            for name, value in raw_metrics
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        )
        artifacts = (
            ArtifactReference("statistical_report", report.fingerprint()[:16], "1"),
            ArtifactReference(
                "exploration_policy", policy.fingerprint()[:16], str(policy.version)
            ),
            ArtifactReference(
                "proxy_calibration",
                calibration.fingerprint()[:16],
                str(calibration.version),
            ),
        )
        result_id = fingerprint({"run_id": run_id, "round": round_index, "kind": "result"})[:32]
        try:
            existing = facade.get_run(run_id)
        except ExperimentNotFoundError:
            existing = None
        if existing is not None and existing.status is ExperimentRunStatus.COMPLETED:
            return True
        if existing is None:
            try:
                facade.create_run(
                    experiment_id,
                    spec,
                    configuration_version=str(ORCHESTRATOR_SCHEMA_VERSION),
                    run_id=run_id,
                )
            except ExperimentRunConflictError:
                return True
            facade.start_run(run_id)
        facade.complete_run(run_id, metrics, artifacts, result_id=result_id)
        return True
