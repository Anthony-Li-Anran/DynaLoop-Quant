"""Statistical certification of effective factors on a pre-registered frozen window.

Evaluation metrics follow Qlib / alphalens (see docs/factor_evaluation_baseline.md);
the certification layer adds the data-snooping controls those frameworks do NOT
provide. Qlib and RD-Agent(Q) de-duplicate candidates, backtest them and update
a SOTA set using IC/RankIC (RD-Agent(Q), NeurIPS 2025, Sec. 2.4).
It does not correct for the many adaptive searches that produced the shortlist,
and it does not state an error rate for the assertion "this factor is effective".
A shortlist produced by an adaptive loop is a multiple-testing generator: the
winner's apparent edge is the maximum of many noisy draws (White 2000; Hansen
2005; Harvey, Liu & Zhu 2016).

The deeper obstacle is adaptivity itself. A self-evolving researcher queries
its data repeatedly, so a holdout reused by the loop is itself overfit
(Dwork et al., Science 2015 / NeurIPS 2015, "reusable holdout" / Thresholdout),
and fixed-family multiple-testing assumptions break down. We do NOT try to
control sequential error inside the adaptive loop. Instead we use the one
structural advantage financial time series have: the causal arrow of time.

Three pillars, all evaluated on a frozen historical out-of-sample window
(later historical data, not calendar-future data; isolation is informational
and procedural, with the freeze written before verification rows are built):

(0) Causal isolation (removes adaptivity by design, not by a stronger test).
    Every degree of freedom - generation, tuning, feedback, policy update - is
    confined to the search period. At one declared cutoff the candidate family
    and ALL its parameters are frozen once, with data/source fingerprints.
    Future data cannot leak into a past search. The verdict therefore becomes a
    standard pre-registered FAMILY hypothesis, and reusable-holdout machinery
    is unnecessary. Isolation is enforced here (dates, fingerprints, frozen
    parameters); a violation is a hard error, never a silent downgrade.

(1) Search-robust family test (White's Reality Check / Hansen SPA framing).
    The object of inference is the BEST of the frozen family, not a single
    pre-specified factor. Loss differentials are measured against the STRICTER
    of two baselines (zero forecast and trailing historical mean) period by
    period. A stationary (Politis-Romano 1994) block bootstrap draws ONE shared
    time-index path per replicate across the whole T x K matrix, preserving both
    serial dependence and cross-candidate dependence. Recentring by each
    candidate's sample mean builds a null with no superiority. A conservative
    conservative RC-style studentized max statistic plus Romano-Wolf /
    Westfall-Young max-statistic step-down yields adjusted p-values and a
    family-wise error rate statement. This is the correction for "we searched
    a lot". The studentising scale is fixed at its observed value and poor
    alternatives are not discarded: this is the conservative Reality-Check
    variant, NOT a full SPA test, and the spec says so explicitly.

(2) Stability and repeatability as an INDEPENDENT NECESSARY condition.
    Disjoint time blocks must agree (at least 75% positive improvement), the
    result must survive leave-one-period-out (no single lucky period), and
    predictions must align with realised targets on average. An exact block
    sign-test p-value is reported as a diagnostic; with few blocks it is
    deliberately NOT claimed as an independent significance guarantee.

A factor is ``effective`` only if the search-corrected family test rejects it
AND the stability conditions hold. Otherwise the terminal state is
``insufficient_evidence`` (or ``refuted`` when it is consistently worse).

What is claimed, precisely:
  * Within the frozen family: family-wise error rate <= alpha, CONDITIONAL on
    frozen isolation, the block bootstrap preserving the dependence structure,
    and an approximately pivotal/symmetric null. Conservative recentring.
  * NO across-round / sequential adaptive error control: adaptivity is removed
    by isolation, not bounded by a test. This is the honest boundary.
  * NO conformal coverage, NO profitability or tradability, NO causal claim,
    NO guarantee that the relation persists beyond the verification window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import binom

from dynaloop.research_engine.channels import (
    CHANNEL_ASSERTIONS,
    CHANNEL_LABELS,
    CHANNEL_SCOPE_LIMITS,
    CHANNEL_TIMING,
    channel_fields,
    enforce_channel,
)
from dynaloop.research_engine.evaluation_metrics import (
    hac_t_statistic,
    series_lag1_autocorrelation,
)
from dynaloop.research_engine.resampling_tools import (
    TIMING_PATH_SALT,
    shared_time_paths,
    stepdown,
    studentized_statistics,
)
from dynaloop.research_engine.spec import fingerprint

# Additive report-only diagnostics MUST NOT bump this value. It is embedded in
# EffectivenessConfig.to_dict(), which is part of the frozen report fingerprint.
EFFECTIVENESS_SCHEMA_VERSION = 1

STATUS_EFFECTIVE = "effective"
STATUS_INSUFFICIENT = "insufficient_evidence"
STATUS_REFUTED = "refuted"
STATUS_FOUND = "effective_factors_found"


class IsolationError(ValueError):
    """The frozen/verification separation was violated. Never downgrade silently."""


@dataclass(frozen=True, slots=True)
class EffectivenessConfig:
    """All free parameters of the certification procedure."""

    reps: int = 1000
    block_size: int = 5
    alpha: float = 0.10
    min_periods: int = 12
    blocks: int = 4
    min_block_periods: int = 3
    stability_fraction: float = 0.75
    seed: int = 0
    bootstrap: str = "stationary"
    leave_one_out: bool = True

    def __post_init__(self) -> None:
        for name in ("reps", "block_size", "min_periods", "blocks", "min_block_periods", "seed"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.reps < 100:
            raise ValueError("reps must be >= 100 for a usable empirical p-value")
        if self.block_size < 1:
            raise ValueError("block_size must be positive")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must lie in (0, 1)")
        if self.blocks < 2 or self.min_block_periods < 1:
            raise ValueError("at least two blocks of >= 1 period are required")
        if self.min_periods < self.blocks * self.min_block_periods:
            raise ValueError("min_periods cannot support the requested blocks")
        if not 0.5 <= self.stability_fraction <= 1.0:
            raise ValueError("stability_fraction must lie in [0.5, 1]")
        if self.bootstrap not in ("stationary", "circular"):
            raise ValueError("bootstrap must be 'stationary' or 'circular'")

    def rng(self) -> np.random.Generator:
        return np.random.default_rng(np.random.SeedSequence([int(self.seed), 0xC0FFEE]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EFFECTIVENESS_SCHEMA_VERSION,
            "reps": self.reps,
            "block_size": self.block_size,
            "alpha": self.alpha,
            "min_periods": self.min_periods,
            "blocks": self.blocks,
            "min_block_periods": self.min_block_periods,
            "stability_fraction": self.stability_fraction,
            "seed": self.seed,
            "bootstrap": self.bootstrap,
            "leave_one_out": self.leave_one_out,
        }


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    """A candidate frozen at the cutoff. Parameters are evidence, never refitted."""

    factor_id: str
    expression: str
    symbol: str = ""
    frozen_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "symbol": self.symbol,
            "frozen_at": self.frozen_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class VerificationRow:
    """One out-of-sample decision period for one frozen candidate.

    ``baseline_zero_error`` and ``baseline_mean_error`` are the squared errors
    of the two required baselines on the same period. The stricter (smaller)
    one is used, so a positive differential means the factor beat BOTH.
    """

    factor_id: str
    date: str
    target: float
    prediction: float | None
    baseline_zero_error: float
    baseline_mean_error: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "date": self.date,
            "target": self.target,
            "prediction": self.prediction,
            "baseline_zero_error": self.baseline_zero_error,
            "baseline_mean_error": self.baseline_mean_error,
        }


@dataclass(frozen=True, slots=True)
class EffectivenessRequest:
    """Everything the verdict consumes; nothing may be estimated from verification."""

    candidates: tuple[FrozenCandidate, ...]
    rows: tuple[VerificationRow, ...]
    cutoff: str
    verification_start: str
    config: EffectivenessConfig = field(default_factory=EffectivenessConfig)
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateVerdict:
    factor_id: str
    expression: str
    status: str
    adjusted_p_value: float
    raw_statistic: float | None
    mean_improvement: float | None
    periods: int
    stability: dict[str, Any]
    reasons: tuple[str, ...]
    error_statement: str
    channel: str = CHANNEL_TIMING
    channel_label: str = ""
    assertion: str = ""
    scope_limit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "status": self.status,
            "adjusted_p_value": self.adjusted_p_value,
            "raw_statistic": self.raw_statistic,
            "mean_improvement": self.mean_improvement,
            "periods": self.periods,
            "stability": self.stability,
            "reasons": list(self.reasons),
            "error_statement": self.error_statement,
            "channel": self.channel,
            "channel_label": self.channel_label or CHANNEL_LABELS[self.channel],
            "assertion": self.assertion or CHANNEL_ASSERTIONS[self.channel],
            "scope_limit": self.scope_limit or CHANNEL_SCOPE_LIMITS[self.channel],
        }


@dataclass(frozen=True, slots=True)
class FamilyTest:
    method: str
    observed_max_statistic: float | None
    p_value: float | None
    alpha: float
    family_size: int
    periods: int
    rejected_count: int
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "observed_max_statistic": self.observed_max_statistic,
            "p_value": self.p_value,
            "alpha": self.alpha,
            "family_size": self.family_size,
            "periods": self.periods,
            "rejected_count": self.rejected_count,
            "spec": self.spec,
        }


@dataclass(frozen=True, slots=True)
class EffectivenessReport:
    status: str
    candidates: tuple[CandidateVerdict, ...]
    family: FamilyTest
    spec: dict[str, Any]
    fingerprint: str
    channel: str = CHANNEL_TIMING

    @property
    def effective_count(self) -> int:
        return sum(v.status == STATUS_EFFECTIVE for v in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EFFECTIVENESS_SCHEMA_VERSION,
            "status": self.status,
            "effective_count": self.effective_count,
            "candidates": [v.to_dict() for v in self.candidates],
            "family": self.family.to_dict(),
            "spec": self.spec,
            "fingerprint": self.fingerprint,
            "channel": self.channel,
            "channel_label": CHANNEL_LABELS[self.channel],
        }


def _check_isolation(request: EffectivenessRequest) -> dict[str, list[VerificationRow]]:
    """Enforce the causal freeze. Any violation is a hard error."""
    cfg = request.config
    if not request.candidates:
        raise IsolationError("no frozen candidates")
    if not request.cutoff or not request.verification_start:
        raise IsolationError("cutoff and verification_start are required")
    if request.verification_start <= request.cutoff:
        raise IsolationError("verification_start must be strictly after the freeze cutoff")
    ids = [c.factor_id for c in request.candidates]
    if len(ids) != len(set(ids)):
        raise IsolationError("duplicate frozen candidate ids")
    grouped: dict[str, list[VerificationRow]] = {key: [] for key in ids}
    for row in request.rows:
        if row.factor_id not in grouped:
            raise IsolationError(f"unfrozen factor_id in verification rows: {row.factor_id}")
        if row.date <= request.cutoff or row.date < request.verification_start:
            raise IsolationError(
                f"verification row {row.date} is not strictly after the cutoff {request.cutoff}"
            )
        grouped[row.factor_id].append(row)
    reference: tuple[str, ...] | None = None
    for key in ids:
        rows = sorted(grouped[key], key=lambda r: r.date)
        dates = tuple(r.date for r in rows)
        if len(dates) != len(set(dates)):
            raise IsolationError(f"duplicate verification dates for {key}")
        if reference is None:
            reference = dates
        elif dates != reference:
            raise IsolationError("candidates must share one identical verification grid")
        if len(rows) < cfg.min_periods:
            raise IsolationError(
                f"{key} has {len(rows)} periods, fewer than min_periods={cfg.min_periods}"
            )
        grouped[key] = rows
    if reference is None or len(reference) < cfg.blocks * cfg.min_block_periods:
        raise IsolationError("verification grid cannot support the requested disjoint blocks")
    start_from_rows = min(r.date for r in request.rows)
    if request.verification_start > start_from_rows:
        raise IsolationError("verification_start is later than the first observation")
    return grouped


def _differential(row: VerificationRow) -> float:
    """Positive iff the factor beat BOTH baselines on this period."""
    if row.prediction is None or not math.isfinite(float(row.prediction)):
        return float("nan")
    loss = (float(row.prediction) - float(row.target)) ** 2
    baseline = min(float(row.baseline_zero_error), float(row.baseline_mean_error))
    return baseline - loss


def _block_stability(d: np.ndarray, rows: list[VerificationRow], cfg: EffectivenessConfig) -> dict[str, Any]:
    n = len(d)
    edges = np.linspace(0, n, cfg.blocks + 1).astype(int)
    if np.any(np.diff(edges) < cfg.min_block_periods):
        raise IsolationError("a stability block has too few periods")
    block_means = [float(d[edges[i]:edges[i + 1]].mean()) for i in range(cfg.blocks)]
    positive = int(sum(value > 0 for value in block_means))
    required = int(math.ceil(cfg.stability_fraction * cfg.blocks))
    # Exact one-sided sign test, reported as a diagnostic only.
    sign_p = float(binom.sf(positive - 1, cfg.blocks, 0.5))
    sorted_d = np.sort(d)
    leave_one_out = float(sorted_d[:-1].mean()) if cfg.leave_one_out and n > 1 else None
    alignment = float(np.mean([
        float(r.prediction) * float(r.target)
        for r in rows if r.prediction is not None and math.isfinite(float(r.prediction))
    ])) if rows else 0.0
    promotion_checks = {
        "block_agreement": positive >= required,
        "leave_one_out_positive": True if leave_one_out is None else leave_one_out > 0,
    }
    # Prediction/target alignment is a directional diagnostic (related to IC),
    # not an upstream acceptance rule. Qlib/alphalens report correlation-like
    # quantities; they do not veto on an uncentred cross-product.
    descriptive_checks = {"alignment_positive": alignment > 0}
    checks = {**promotion_checks, **descriptive_checks}
    # Qlib pred_autocorr / qweave t_nw analogues for the single-instrument
    # timing channel. Strictly report-only; they never affect `passed`.
    predictions = np.asarray([
        float(row.prediction) if row.prediction is not None else float("nan")
        for row in rows
    ], dtype=float)
    series_diagnostics = {
        "improvement_hac": hac_t_statistic(d),
        "prediction_lag1_autocorrelation": series_lag1_autocorrelation(predictions),
        "improvement_lag1_autocorrelation": series_lag1_autocorrelation(d),
        "promotion_role": "report_only",
        "note": "Serial-dependence diagnostics aligned with Qlib pred_autocorr and "
                "qweave's Newey-West t_nw. None participates in the family test, "
                "the stability checks or the terminal state.",
    }
    return {
        "blocks": cfg.blocks,
        "block_means": block_means,
        "positive_blocks": positive,
        "required_positive_blocks": required,
        "exact_sign_test_p_value": sign_p,
        "sign_test_note": "diagnostic only; few blocks give low power, no independent significance claimed",
        "leave_one_out_improvement": leave_one_out,
        "alignment": alignment,
        "checks": checks,
        "promotion_checks": promotion_checks,
        "descriptive_checks": descriptive_checks,
        "gate_policy": "block agreement and leave-one-out are promotion checks; "
                       "prediction/target alignment is reported as a directional diagnostic",
        "series_diagnostics": series_diagnostics,
        "passed": all(promotion_checks.values()),
    }


def _bootstrap_paths(n: int, cfg: EffectivenessConfig) -> np.ndarray:
    """One shared resampled time-index path per replicate across ALL candidates.

    Sharing the path is essential: independent per-candidate resampling would
    destroy the cross-factor dependence and invalidate the joint max statistic.
    """
    return shared_time_paths(
        n, reps=cfg.reps, block_size=cfg.block_size, seed=cfg.seed,
        bootstrap=cfg.bootstrap, salt=TIMING_PATH_SALT,
    )


def assess_effectiveness(request: EffectivenessRequest) -> EffectivenessReport:
    """Produce the terminal, auditable verdict for a frozen candidate family.

    Same request -> same report (including fingerprint). No parameter is
    estimated from the verification window; the only computation there is the
    loss differential and the resampling null built from it.
    """
    cfg = request.config
    enforce_channel(CHANNEL_TIMING, request.candidates)
    grouped = _check_isolation(request)
    ids = [c.factor_id for c in request.candidates]
    expressions = {c.factor_id: c.expression for c in request.candidates}
    grid = [r.date for r in grouped[ids[0]]]
    n = len(grid)
    k = len(ids)

    diffs = np.column_stack([
        np.asarray([_differential(r) for r in grouped[key]], dtype=float) for key in ids
    ])
    finite = np.isfinite(diffs).all(axis=1)
    if not finite.all():
        # A missing prediction is missing evidence, not a zero. Drop the period
        # for the whole family so the shared bootstrap path stays honest.
        diffs = diffs[finite]
        grid = [date for date, ok in zip(grid, finite) if ok]
        n = len(grid)
        if n < cfg.blocks * cfg.min_block_periods:
            raise IsolationError("too many non-finite periods to certify the family")

    paths = _bootstrap_paths(n, cfg)
    observed, t_star, mean, _scale = studentized_statistics(diffs, paths)
    adjusted, family_p, order, max_star = stepdown(observed, t_star)
    rejected = adjusted <= cfg.alpha

    small_window = int(n) < 24
    power_note = (
        f"Only {int(n)} verification periods across {cfg.blocks} disjoint blocks: power is "
        "low, a non-rejection is weak evidence of no effect, and any rejection rests on a "
        "short out-of-sample window. This is not evidence of persistence."
    ) if small_window else (
        f"{int(n)} verification periods across {cfg.blocks} disjoint blocks."
    )

    family_spec = {
        "method": "rc_style_shared_path_max_statistic_stepdown",
        "reference": "White (2000) Reality Check; Hansen (2005) SPA (framing); Romano-Wolf / Westfall-Young step-down",
        "null": "no frozen candidate beats both baselines; bootstrap differentials recentred by sample mean",
        "recentring": "conservative RC / least-favourable-configuration style",
        "statistic": "sqrt(n) * mean(loss_differential) / observed_sample_std, max over family",
        "spa_simplification": "Full SPA refinements are NOT implemented: the studentising scale is fixed "
        "at its observed value (not re-estimated per replicate), and poor alternatives are not "
        "data-dependently discarded. This is the conservative RC-style variant, not a full SPA test.",
        "loss_differential": "min(zero_error, trailing_mean_error) - factor_squared_error, per period",
        "baselines": ["zero forecast", "trailing historical mean"],
        "dependence": "one shared stationary/circular block-bootstrap index path across all candidates",
        "config": cfg.to_dict(),
        "replicates": cfg.reps,
        "blocks_in_bootstrap": cfg.block_size,
        "verification_periods": int(n),
        "small_window": small_window,
        "power_note": power_note,
        "verification_dates": [str(d) for d in grid],
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "observed_statistics": [float(v) for v in observed],
        "adjusted_p_values": [float(v) for v in adjusted],
        "stepdown_order": [ids[i] for i in order],
        "bootstrap_max_quantiles": {
            str(level): float(value)
            for level, value in zip(("0.5", "0.9", "0.95", "0.99"), np.quantile(max_star, [.5, .9, .95, .99]))
        },
        "assumptions": [
            "candidate family and every parameter frozen once at the cutoff, before any "
            "verification row was built",
            "verification window is later HISTORICAL data, not calendar-future data; "
            "isolation is informational and procedural - no verification data was used "
            "to build, select or tune the frozen family",
            "block bootstrap preserves serial and cross-candidate dependence",
            "null is approximately pivotal under the shared-path recentred resampling",
            "loss differentials are stationary over the verification window",
        ],
        "within_family_fwer_control": True,
        "fwer_statement": "FWER <= alpha within the frozen family, conditional on the assumptions above",
        "loop_level_sequential_guarantee": False,
        "sequential_statement": "adaptivity is removed by causal isolation, NOT bounded by a sequential test",
        "coverage_guarantee": False,
        "profitability_claimed": False,
        "causal_claim": False,
        **channel_fields(CHANNEL_TIMING),
    }
    family = FamilyTest(
        method="rc_style_shared_path_max_statistic_stepdown",
        observed_max_statistic=float(observed.max()),
        p_value=family_p,
        alpha=cfg.alpha,
        family_size=k,
        periods=int(n),
        rejected_count=int(rejected.sum()),
        spec=family_spec,
    )

    # Rows after the finite filter, per candidate, for alignment computation.
    filtered_rows = {
        key: [r for r, ok in zip(grouped[key], finite) if ok] for key in ids
    }
    verdicts: list[CandidateVerdict] = []
    for position, key in enumerate(ids):
        d = diffs[:, position]
        stability = _block_stability(d, filtered_rows[key], cfg)
        reasons: list[str] = []
        if not rejected[position]:
            reasons.append(
                f"search-corrected adjusted p={adjusted[position]:.4f} > alpha={cfg.alpha}"
            )
        if not stability["passed"]:
            failed = [name for name, ok in
                      stability.get("promotion_checks", stability["checks"]).items()
                      if not ok]
            reasons.append("stability conditions not met: " + ", ".join(failed))
        mean_improvement = float(mean[position])
        consistently_worse = (
            mean_improvement < 0
            and (stability["leave_one_out_improvement"] is None
                 or stability["leave_one_out_improvement"] < 0)
            and stability["positive_blocks"] <= cfg.blocks // 4
        )
        if rejected[position] and stability["passed"]:
            status = STATUS_EFFECTIVE
        elif consistently_worse:
            status = STATUS_REFUTED
            reasons.append("consistently worse than both baselines across blocks")
        else:
            status = STATUS_INSUFFICIENT
        statement = (
            f"Within a frozen family of {k} candidates, family-wise error rate <= {cfg.alpha} "
            f"conditional on the stated assumptions; this factor's search-corrected adjusted "
            f"p-value is {adjusted[position]:.4f}. Across-round adaptive error is not claimed."
        ) if status == STATUS_EFFECTIVE else ""
        if status == STATUS_EFFECTIVE and small_window:
            statement += " " + power_note
        verdicts.append(CandidateVerdict(
            factor_id=key,
            expression=expressions[key],
            status=status,
            adjusted_p_value=float(adjusted[position]),
            raw_statistic=float(observed[position]),
            mean_improvement=mean_improvement,
            periods=int(n),
            stability=stability,
            reasons=tuple(reasons),
            error_statement=statement,
            channel=CHANNEL_TIMING,
            channel_label=CHANNEL_LABELS[CHANNEL_TIMING],
            assertion=CHANNEL_ASSERTIONS[CHANNEL_TIMING],
            scope_limit=CHANNEL_SCOPE_LIMITS[CHANNEL_TIMING],
        ))

    spec = {
        "schema_version": EFFECTIVENESS_SCHEMA_VERSION,
        "config": cfg.to_dict(),
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "candidates": [c.to_dict() for c in request.candidates],
        "provenance": dict(request.provenance),
        "rows_fingerprint": fingerprint([r.to_dict() for r in request.rows]),
        "power_note": power_note,
        "small_window": small_window,
        "family": family_spec,
        "pillar_0": "causal isolation: freeze once, verify only on later data, enforced by _check_isolation",
        "pillar_1": "search-robust family test: RC/SPA-style shared-path block bootstrap max statistic + step-down",
        "pillar_2": "stability/repeatability: disjoint blocks, leave-one-out; "
                    "prediction/target alignment is a reported directional diagnostic",
        "evaluation_baseline": {
            "authority": "docs/factor_evaluation_baseline.md",
            "note": "Qlib/alphalens metrics are reported; family-wise error control "
                    "and preregistration are the additional certification layer",
            "report_only_metrics": ["Newey-West HAC t statistic on the loss differential",
                                    "prediction and improvement lag-1 autocorrelation"],
            "sources": ["Qlib pred_autocorr (lag-1 prediction autocorrelation)",
                        "alphalens factor_rank_autocorrelation",
                        "qweave t_nw / Newey & West (1987, 1994) Bartlett HAC"],
        },
        "terminal_states": [STATUS_EFFECTIVE, STATUS_INSUFFICIENT, STATUS_REFUTED],
        **channel_fields(CHANNEL_TIMING),
        "channel_note": "This report judges the timing channel only. Cross-sectional "
                        "candidates must be judged by cross_section.py with its own family, "
                        "null hypothesis and baselines; the two families are never merged.",
    }
    report_status = STATUS_FOUND if any(v.status == STATUS_EFFECTIVE for v in verdicts) else STATUS_INSUFFICIENT
    digest = fingerprint({
        "config": cfg.to_dict(),
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "candidates": [c.to_dict() for c in request.candidates],
        "rows": [r.to_dict() for r in request.rows],
        "provenance": dict(request.provenance),
    })
    return EffectivenessReport(
        status=report_status,
        candidates=tuple(verdicts),
        family=family,
        spec=spec,
        fingerprint=digest,
    )


def rows_from_frozen_tape(
    tape: Any,
    frozen_models: Sequence[Mapping[str, Any]],
    indices: Sequence[int],
) -> tuple[VerificationRow, ...]:
    """Adapter: build verification rows from a FactorTape and frozen parameters.

    Reuses the same public tape interface and prediction rule as the existing
    holdout experiment. Frozen models must carry ``factor_id``, ``factor``,
    ``mean``, ``scale``, ``slope`` and ``intercept``; nothing is refitted.
    """
    from dynaloop.research_engine.temporal import TemporalResearch

    researcher = TemporalResearch(tape)
    horizon = tape.config.horizon
    rows: list[VerificationRow] = []
    for model in frozen_models:
        factor = int(model["factor"])
        if tape.instances[factor].expression != model.get("expression", tape.instances[factor].expression):
            raise IsolationError("frozen formula differs from the factor catalogue")
        for index in indices:
            index = int(index)
            end_index = index + horizon + 1
            target = float(tape.targets([index], available_at=end_index)[0])
            recent, _memory = researcher.windows(index)
            trailing_mean = float(tape.targets(recent, available_at=index).mean())
            value = float(tape.values[index, factor])
            prediction = None
            if np.isfinite(value):
                z = float(np.clip((value - float(model["mean"])) / float(model["scale"]), -5, 5))
                prediction = float(np.clip(
                    float(model["intercept"]) + float(model["slope"]) * z, -.2, .2
                ))
            rows.append(VerificationRow(
                factor_id=str(model["factor_id"]),
                date=str(tape.dates[index]),
                target=target,
                prediction=prediction,
                baseline_zero_error=target ** 2,
                baseline_mean_error=(trailing_mean - target) ** 2,
            ))
    return tuple(rows)
