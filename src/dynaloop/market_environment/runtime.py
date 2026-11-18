"""Environment runtime: real Wake context, simulated Sleep context, one session.

Composition follows the system contract: Wake's verdict comes exclusively from
stage 1 ``FactorEvaluation`` objects (the deterministic engine is reused, never
modified), Sleep's estimates come from a replaceable ``BacktestProxy``, and
every write-back produces a new immutable calibration version.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Sequence

from dynaloop.market_environment.definitions import (
    EnvironmentDefinition,
    EnvironmentReference,
    EnvironmentType,
)
from dynaloop.market_environment.feedback import (
    SimulationFeedback,
    SimulatedEstimation,
    compare_estimates,
    expected_bias_shift,
)
from dynaloop.market_environment.observations import (
    FrozenWindow,
    WakeObservation,
    factor_group_key,
    require_same_window,
    wake_observations,
)
from dynaloop.market_environment.proxy import (
    BacktestProxy,
    BiasInjection,
    ProxyCalibration,
    ProxyConfig,
    ResampledBacktestProxy,
    proxy_library_versions,
)
from dynaloop.market_environment.registry import (
    ENVIRONMENT_SCHEMA_VERSION,
    EnvironmentRegistry,
    definition_payload,
)
from dynaloop.research_engine import FactorCandidate, FactorEvaluation
from dynaloop.research_engine.spec import fingerprint


class EnvironmentRuntimeError(ValueError):
    """Raised when a runtime session is opened with inconsistent inputs."""


class RealEnvironment:
    """Read-only Wake context; holds frozen real verdicts, never recomputes them."""

    def __init__(
        self,
        definition: EnvironmentDefinition,
        observations: Sequence[WakeObservation] = (),
    ) -> None:
        if definition.environment_type is not EnvironmentType.REAL:
            raise EnvironmentRuntimeError("RealEnvironment requires a REAL definition.")
        self.definition = definition
        self._observations = tuple(observations)

    @property
    def observations(self) -> tuple[WakeObservation, ...]:
        return self._observations

    def verdict(self) -> tuple[WakeObservation, ...]:
        return self._observations

    def window(self) -> FrozenWindow | None:
        return self._observations[0].window if self._observations else None

    def spec(self) -> dict[str, Any]:
        return {
            "definition": definition_payload(self.definition),
            "observations": [item.to_dict() for item in self._observations],
            "recomputes_backtest": False,
        }


class SimulatedEnvironment:
    """Sleep context: a replaceable proxy plus a versioned calibration."""

    def __init__(
        self,
        definition: EnvironmentDefinition,
        proxy: BacktestProxy | None = None,
    ) -> None:
        if definition.environment_type is not EnvironmentType.SIMULATED:
            raise EnvironmentRuntimeError("SimulatedEnvironment requires a SIMULATED definition.")
        self.definition = definition
        self.proxy: BacktestProxy = proxy or ResampledBacktestProxy()

    def estimate(
        self,
        candidates: Sequence[FactorCandidate],
        calibration: ProxyCalibration,
        config: ProxyConfig,
        bias: BiasInjection | None = None,
    ) -> tuple[SimulatedEstimation, ...]:
        return self.proxy.estimate(candidates, calibration, config, bias)

    def spec(self) -> dict[str, Any]:
        return {
            "definition": definition_payload(self.definition),
            "proxy": self.proxy.name,
            "recomputes_backtest": False,
        }


class EnvironmentRuntime:
    """Registry-driven ``make`` for real / simulated environment instances."""

    def __init__(self, registry: EnvironmentRegistry) -> None:
        if not isinstance(registry, EnvironmentRegistry):
            raise EnvironmentRuntimeError("registry must be an EnvironmentRegistry.")
        self.registry = registry

    def make(
        self,
        reference: EnvironmentReference,
        *,
        observations: Sequence[WakeObservation] = (),
        proxy: BacktestProxy | None = None,
    ) -> RealEnvironment | SimulatedEnvironment:
        definition = self.registry.spec(reference)
        if definition.environment_type is EnvironmentType.REAL:
            return RealEnvironment(definition, observations)
        return SimulatedEnvironment(definition, proxy)

    def open(
        self,
        real_reference: EnvironmentReference,
        simulated_reference: EnvironmentReference,
        evaluations: Iterable[FactorEvaluation],
        candidates: Sequence[FactorCandidate] | None = None,
        *,
        config: ProxyConfig | None = None,
        bias: BiasInjection | None = None,
        proxy: BacktestProxy | None = None,
        calibration: ProxyCalibration | None = None,
    ) -> "RuntimeSession":
        """Open one Wake/Sleep session over a frozen evaluation family."""
        observations = wake_observations(evaluations, (config or ProxyConfig()).reward)
        if not observations:
            raise EnvironmentRuntimeError("A session needs at least one Wake evaluation.")
        require_same_window(observations[0].window, observations)
        family = tuple(candidates) if candidates is not None else tuple(
            _candidate_from_observation(item) for item in observations
        )
        if not family:
            raise EnvironmentRuntimeError("A session needs at least one candidate.")
        real = self.make(real_reference, observations=observations)
        simulated = self.make(simulated_reference, proxy=proxy)
        if not isinstance(real, RealEnvironment) or not isinstance(simulated, SimulatedEnvironment):
            raise EnvironmentRuntimeError("open() needs one REAL and one SIMULATED reference.")
        return RuntimeSession(
            self,
            real,
            simulated,
            observations,
            family,
            config or ProxyConfig(),
            bias or BiasInjection(),
            calibration,
        )


def _candidate_from_observation(observation: WakeObservation) -> FactorCandidate:
    """Rebuild a canonical candidate when the caller supplies no family."""
    return FactorCandidate.from_expression(observation.expression)


class RuntimeSession:
    """One reproducible Sleep round: estimate, measure bias, recalibrate."""

    def __init__(
        self,
        runtime: EnvironmentRuntime,
        real: RealEnvironment,
        simulated: SimulatedEnvironment,
        observations: Sequence[WakeObservation],
        candidates: Sequence[FactorCandidate],
        config: ProxyConfig,
        bias: BiasInjection,
        calibration: ProxyCalibration | None = None,
    ) -> None:
        self.runtime = runtime
        self.real = real
        self.simulated = simulated
        self.config = config
        self.bias = bias
        self._observations = tuple(observations)
        self._candidates = tuple(candidates)
        self._round = 0
        if calibration is not None and calibration.reward_spec != config.reward.to_dict():
            raise EnvironmentRuntimeError("Calibration and session reward definitions differ.")
        self.calibration = calibration if calibration is not None else simulated.proxy.fit(
            self._observations, self._round_config()
        )
        self._calibration_history: tuple[ProxyCalibration, ...] = (self.calibration,)

    @property
    def observations(self) -> tuple[WakeObservation, ...]:
        return self._observations

    @property
    def candidates(self) -> tuple[FactorCandidate, ...]:
        return self._candidates

    @property
    def calibration_history(self) -> tuple[ProxyCalibration, ...]:
        return self._calibration_history

    def _round_config(self) -> ProxyConfig:
        return replace(self.config, round_index=self.config.round_index + self._round)

    def estimate(self) -> tuple[SimulatedEstimation, ...]:
        return self.simulated.estimate(
            self._candidates, self.calibration, self._round_config(), self.bias
        )

    def feedback(
        self, estimations: Sequence[SimulatedEstimation] | None = None
    ) -> SimulationFeedback:
        resolved = tuple(estimations) if estimations is not None else self.estimate()
        report = compare_estimates(self._observations, resolved)
        base_rewards = [item.base_reward for item in resolved]
        expected = expected_bias_shift(self.bias.to_dict(), base_rewards)
        amplification = report.model_bias / expected if expected != 0 else None
        spec = self.spec()
        return SimulationFeedback(
            model_bias=report.model_bias,
            mean_absolute_error=report.mean_absolute_error,
            mean_uncertainty=report.mean_uncertainty,
            injected_bias=float(self.bias.magnitude),
            expected_bias=expected,
            amplification=amplification,
            calibration_version=self.calibration.version,
            environment_reference=definition_payload(self.simulated.definition),
            run_id=self.run_id(),
            spec=spec,
        )

    def recalibrate(self) -> ProxyCalibration:
        """⑤ Proxy Model Update: absorb measured bias, returning a new version."""
        estimations = self.estimate()
        updated = self.simulated.proxy.recalibrate(
            self.calibration, self._observations, estimations, self._round_config()
        )
        self._calibration_history += (updated,)
        self.calibration = updated
        self._round += 1
        return updated

    def spec(self) -> dict[str, Any]:
        window = self.real.window()
        return {
            "schema_version": ENVIRONMENT_SCHEMA_VERSION,
            "run_id": self.run_id(),
            "registry_fingerprint": self.runtime.registry.fingerprint(),
            "real": self.real.spec(),
            "simulated": self.simulated.spec(),
            "window": window.to_dict() if window else None,
            "proxy_config": self._round_config().to_dict(),
            "bias_injection": self.bias.to_dict(),
            "candidates": [
                {
                    "factor_id": item.factor_id,
                    "expression": item.expression,
                    "group_key": factor_group_key(item),
                }
                for item in self._candidates
            ],
            "wake_observations": [item.to_dict() for item in self._observations],
            "calibration": self.calibration.to_dict(),
            "round_index": self._round,
            "library_versions": proxy_library_versions(),
        }

    def run_id(self) -> str:
        window = self.real.window()
        return fingerprint(
            {
                "schema_version": ENVIRONMENT_SCHEMA_VERSION,
                "real": definition_payload(self.real.definition),
                "simulated": definition_payload(self.simulated.definition),
                "window": window.to_dict() if window else None,
                "config": self.config.to_dict(),
                "bias": self.bias.to_dict(),
                "wake": [item.evaluation_fingerprint for item in self._observations],
                "calibration_version": self.calibration.version,
            }
        )[:16]


__all__ = [
    "EnvironmentRuntimeError",
    "EnvironmentRuntime",
    "RealEnvironment",
    "RuntimeSession",
    "SimulatedEnvironment",
]
