"""End-to-end orchestration of the select-then-time pipeline.

Wires the four separated stages into one auditable run:

  (1) selection research  : certified Part A evidence -> frozen SelectionRule
  (2) selection execution : frozen rule + decision scores -> target weights
  (3) timing research     : purged walk-forward learning + out-of-sample
                            certification -> frozen TimingRule (or a refusal)
  (4) timing execution    : frozen rules drive the deterministic engine via
                            TwoStageStrategy -> net/gross backtest result
  (5) audit               : a full fingerprint chain, every stage's identity

The pipeline NEVER re-runs a Part A certification on an already-inspected
window. Effective evidence and (optionally) already-learned/certified timing
candidates are passed in by the caller, produced by new, pre-registered rounds.
If no certified timing candidate is supplied, stage 3 runs learning +
certification on the samples provided and refuses to freeze when nothing is
effective. An update gate can be applied to a sequence of shadow runs to decide
whether a candidate configuration may replace the incumbent.

This module is deliberately free of any real-data I/O so it can be tested
end-to-end without touching a frozen window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from dynaloop.orchestrator.two_stage import (
    SelectionResearch,
    SelectionRule,
    TimingResearch,
    TimingRule,
)
from dynaloop.orchestrator.two_stage_strategy import (
    SignalProvider,
    TwoStageStrategy,
)
from dynaloop.research_engine.portfolio_weights import WeightConfig
from dynaloop.research_engine.spec import fingerprint
from dynaloop.research_engine.timing_learning import (
    TimingCandidate,
    TimingLearningConfig,
    TimingSample,
    certify_timing,
    learn_timing_candidates,
    search_mean,
)
from dynaloop.research_engine.update_gate import (
    PeriodRecord,
    UpdateGateConfig,
    decide_update,
)
from dynaloop.validation_backtesting_engine.domain.models import BacktestConfig
from dynaloop.validation_backtesting_engine.facade import run_backtest
from dynaloop.validation_backtesting_engine.feed import StaticFeed


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Self-describing output of one full pipeline run."""

    selection_rule: SelectionRule | None
    timing_rule: TimingRule | None
    target_weights: dict[str, float]
    actions: dict[str, str]
    certification: dict[str, Any]
    backtest: dict[str, Any] | None
    update_decision: dict[str, Any] | None
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_rule": self.selection_rule.to_dict() if self.selection_rule else None,
            "timing_rule": self.timing_rule.to_dict() if self.timing_rule else None,
            "target_weights": dict(self.target_weights),
            "actions": dict(self.actions),
            "certification": dict(self.certification),
            "backtest": dict(self.backtest) if self.backtest else None,
            "update_decision": dict(self.update_decision) if self.update_decision else None,
            "audit": dict(self.audit),
        }


def run_two_stage_pipeline(
    *,
    effective_evidence: Sequence[Any],
    top_k: int,
    round_id: str,
    signal_provider: SignalProvider,
    decision_scores: Mapping[str, float],
    records: Sequence[Mapping[str, Any]],
    backtest_config: BacktestConfig | None = None,
    weight_config: WeightConfig | None = None,
    # Timing learning / certification inputs (new, unconsumed window).
    timing_samples: Sequence[TimingSample] | None = None,
    timing_config: TimingLearningConfig | None = None,
    cutoff: str | None = None,
    verification_start: str | None = None,
    certified_candidate: TimingCandidate | None = None,
    certification_fingerprint: str = "",
    # Optional shadow comparison for the update gate.
    shadow_periods: Sequence[PeriodRecord] | None = None,
    gate_config: UpdateGateConfig | None = None,
) -> PipelineResult:
    """Run the four stages and return a fingerprinted, auditable result.

    ``certified_candidate`` lets a caller reuse a candidate that was already
    certified in a fresh pre-registered round; when absent, learning and
    certification run here on ``timing_samples``. Either way a timing rule is
    frozen ONLY if a candidate is effective.
    """
    if not effective_evidence:
        raise ValueError("no certified effective evidence to select on")

    # (1) selection research -> frozen rule
    selection = SelectionResearch(
        effective_evidence, top_k=top_k, round_id=round_id,
        weight_config=weight_config).freeze()

    # (2) selection execution -> target weights from decision-time scores
    from dynaloop.orchestrator.two_stage import SelectionExecution
    target = SelectionExecution(selection).target_weights(decision_scores)

    # (3) timing research -> learn + certify, then freeze only if effective
    certification: dict[str, Any] = {"status": "not_run"}
    timing: TimingRule | None = None
    candidate = certified_candidate
    if candidate is None:
        if not (timing_samples and timing_config and cutoff and verification_start):
            raise ValueError(
                "provide certified_candidate OR timing_samples+config+cutoff+verification_start")
        learned = learn_timing_candidates(timing_samples, timing_config, cutoff=cutoff)
        if learned:
            report, effective_ids = certify_timing(
                learned, timing_samples, timing_config,
                cutoff=cutoff, verification_start=verification_start,
                search_mean=search_mean(timing_samples, cutoff=cutoff))
            certification = {
                "status": "certified",
                "family_p": report.family.p_value,
                "effective_ids": list(effective_ids),
                "report_fingerprint": report.fingerprint,
            }
            if effective_ids:
                candidate = next(c for c in learned if c.rule_id == effective_ids[0])
        else:
            certification = {"status": "no_stable_candidate"}
    else:
        certification = {
            "status": "pre_certified",
            "candidate_id": candidate.rule_id,
            "certification_fingerprint": certification_fingerprint,
        }

    selected_symbols = tuple(sorted({name for name in target if name}))
    if candidate is not None and selected_symbols:
        research = TimingResearch.from_certified(selection, candidate, round_id=round_id)
        timing = research.freeze(
            selected_symbols, certification_fingerprint=certification_fingerprint)

    # (4) timing execution -> deterministic backtest (only with a frozen rule)
    backtest: dict[str, Any] | None = None
    actions: dict[str, str] = {}
    if timing is not None:
        strategy = TwoStageStrategy(selection, timing, signal_provider)
        feed = StaticFeed.from_records(records, symbol_col="symbol")
        result = run_backtest(feed, strategy, backtest_config)
        actions = dict(strategy.last_actions)
        backtest = {
            "metrics": dict(result.metrics),
            "fingerprint": result.fingerprint(),
            "fill_count": len(result.fills),
            "warnings": list(result.warnings),
        }

    # (5) update gate -> decide whether a shadow candidate may replace incumbent
    decision = None
    if shadow_periods:
        decision = decide_update(shadow_periods, gate_config).to_dict()

    audit = {
        "round_id": round_id,
        "selection_fingerprint": selection.fingerprint,
        "timing_fingerprint": timing.fingerprint if timing else None,
        "pipeline_fingerprint": fingerprint({
            "selection": selection.to_dict(),
            "timing": timing.to_dict() if timing else None,
            "target": target,
            "certification": certification,
            "backtest": backtest,
            "update": decision,
        }),
        "stage_order": [
            "selection_research", "selection_execution",
            "timing_research", "timing_execution", "audit",
        ],
        "evidence_count": len(effective_evidence),
    }
    return PipelineResult(
        selection_rule=selection, timing_rule=timing,
        target_weights=target, actions=actions,
        certification=certification, backtest=backtest,
        update_decision=decision, audit=audit,
    )
