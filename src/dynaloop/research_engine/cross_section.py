"""Statistical certification of cross-sectional effective factors (Part A, channel one).

This is NOT the timing verdict in ``effectiveness.py`` with a different input.
The assertion here is relative RANKING ability within a point-in-time universe:
"at the same decision date, which instrument is stronger". The null is
E[RankIC] = 0 (random ordering); the baselines are random ordering and the
equal-weight universe. Both differ from the timing channel's "zero forecast /
trailing mean" baselines, which are constant vectors across a cross-section and
therefore have identically tied ranks. See ``docs/cross_section_factor.md``.

Three pillars (on a frozen historical out-of-sample window):
  (0) Informational causal isolation - one-shot freeze of the family and every
      parameter BEFORE the verification window is read, point-in-time universe,
      decision/execution separation, matured labels. The verification window is
      later HISTORICAL data, not calendar-future data; isolation is procedural.
  (1) Search-robust family test - period-by-period Rank IC (Qlib calc_ic's
      Spearman series) relative to the random-ordering null, width-weighted by
      sqrt(N_t - 1), with one SHARED stationary/circular block-bootstrap
      time-index path across the whole family and a max-statistic step-down
      (White Reality Check / Hansen SPA framing, arch.bootstrap tooling).
  (2) Stability - disjoint-block agreement and leave-one-period-out.

Evaluation metrics follow Qlib SigAnaRecord / qlib.contrib.eva.alpha and
alphalens-reloaded, NOT project-invented acceptance rules. Rank IC, Rank ICIR,
IC t statistic, quantile excess returns, long/short gross and net spread,
turnover and information ratio are REPORTED. Quantile monotonicity and the
signs of the two legs are descriptive (alphalens/qweave treat monotonicity as a
Kendall-tau diagnostic, not a gate). They are no longer vetoes by default:
see docs/factor_evaluation_baseline.md for the per-metric source table.
Legacy vetoes remain available via report_only_gates=False for compatibility.

Width reduces the MEASUREMENT noise of each period's Rank IC. It does NOT
create independent decision periods; short windows still carry a power note.
A non-rejection is weak evidence of no effect, never proof of absence.

The resampling maths is shared with the timing channel through
``resampling_tools.py``. The family, statistic, null and baseline are NOT.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
from scipy.stats import binom, kendalltau, rankdata

from dynaloop.research_engine.channels import (
    CHANNEL_ASSERTIONS,
    CHANNEL_CROSS_SECTION,
    CHANNEL_LABELS,
    CHANNEL_SCOPE_LIMITS,
    channel_fields,
    enforce_channel,
)
from dynaloop.research_engine.evaluation_metrics import (
    factor_autocorrelation,
    hac_t_statistic,
)
from dynaloop.research_engine.resampling_tools import (
    CROSS_SECTION_PATH_SALT,
    shared_time_paths,
    stepdown,
    studentized_statistics,
)
from dynaloop.research_engine.spec import fingerprint

# Additive report-only diagnostics MUST NOT bump this value. It is embedded in
# CrossSectionConfig.to_dict(), which is part of the frozen report fingerprint;
# bumping it would silently invalidate every historical certification digest.
CROSS_SECTION_SCHEMA_VERSION = 1

CS_STATUS_EFFECTIVE = "effective"
CS_STATUS_INSUFFICIENT = "insufficient_evidence"
CS_STATUS_REFUTED = "refuted"
CS_STATUS_FOUND = "effective_factors_found"

MEMBERSHIP_BASES = ("point_in_time", "static", "approximate")


class CrossSectionIsolationError(ValueError):
    """Freeze, point-in-time or family separation violated. Never downgrade silently."""


@dataclass(frozen=True, slots=True)
class CostModel:
    """Simplified personal-research execution cost model for the L4 diagnostic.

    Every field participates in the computation. Bar-level settlement rules
    (T+1, price limits, suspensions) are NOT modelled here: this is a
    tradability diagnostic, not a matching engine. That limitation is written
    into the spec and the not-claimed list.
    """

    commission_rate: float = 0.0003
    stamp_duty_rate: float = 0.001
    slippage_rate: float = 0.0005
    assume_shortable: bool = False

    def __post_init__(self) -> None:
        for name in ("commission_rate", "stamp_duty_rate", "slippage_rate"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if type(self.assume_shortable) is not bool:
            raise ValueError("assume_shortable must be a boolean")

    @property
    def round_trip_rate(self) -> float:
        """Both-side commission + sell-side stamp duty + both-side slippage."""
        return 2 * self.commission_rate + self.stamp_duty_rate + 2 * self.slippage_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "commission_rate": self.commission_rate,
            "stamp_duty_rate": self.stamp_duty_rate,
            "slippage_rate": self.slippage_rate,
            "assume_shortable": self.assume_shortable,
            "round_trip_rate": self.round_trip_rate,
            "basis": "turnover-weighted two-sided cost; long-only implementable return "
                     "unless assume_shortable is True",
            "settlement_constraints_modeled": False,
            "settlement_note": "T+1, price limits and suspension matching are bar-level "
                               "execution concerns (Part C), not modelled in this diagnostic.",
        }


@dataclass(frozen=True, slots=True)
class CrossSectionConfig:
    """All free parameters of the channel-one certification procedure."""

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
    quantiles: int = 5
    min_universe: int = 30
    min_monotonicity: float = 0.9
    min_decay_ratio: float = 0.5
    require_both_legs: bool = True
    require_net_positive: bool = True
    # Alignment with Qlib SigAnaRecord / alphalens: quantile monotonicity,
    # leg signs and net spread are reported diagnostics, not promotion vetoes.
    # Set False only to restore the legacy project-specific hard gates.
    report_only_gates: bool = True

    def __post_init__(self) -> None:
        for name in ("reps", "block_size", "min_periods", "blocks",
                     "min_block_periods", "seed", "quantiles", "min_universe"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.reps < 100:
            raise ValueError("reps must be >= 100 for a usable empirical p-value")
        if self.block_size < 1 or self.quantiles < 2:
            raise ValueError("block_size must be positive and quantiles >= 2")
        if self.min_universe < self.quantiles * 2:
            raise ValueError("min_universe must be at least twice the number of quantiles")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must lie in (0, 1)")
        if self.blocks < 2 or self.min_block_periods < 1:
            raise ValueError("at least two blocks of >= 1 period are required")
        if self.min_periods < self.blocks * self.min_block_periods:
            raise ValueError("min_periods cannot support the requested blocks")
        if not 0.5 <= self.stability_fraction <= 1.0:
            raise ValueError("stability_fraction must lie in [0.5, 1]")
        if not 0.0 <= self.min_monotonicity <= 1.0:
            raise ValueError("min_monotonicity must lie in [0, 1]")
        if not 0.0 <= self.min_decay_ratio <= 1.0:
            raise ValueError("min_decay_ratio must lie in [0, 1]")
        if self.bootstrap not in ("stationary", "circular"):
            raise ValueError("bootstrap must be 'stationary' or 'circular'")
        if type(self.report_only_gates) is not bool:
            raise ValueError("report_only_gates must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CROSS_SECTION_SCHEMA_VERSION,
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
            "quantiles": self.quantiles,
            "min_universe": self.min_universe,
            "min_monotonicity": self.min_monotonicity,
            "min_decay_ratio": self.min_decay_ratio,
            "require_both_legs": self.require_both_legs,
            "require_net_positive": self.require_net_positive,
            "report_only_gates": self.report_only_gates,
        }


@dataclass(frozen=True, slots=True)
class CrossSectionCandidate:
    """A ranking formula frozen at the cutoff. Parameters are evidence, never refitted."""

    factor_id: str
    expression: str
    frozen_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "frozen_at": self.frozen_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CrossSectionSlice:
    """One decision period's complete cross-section (see docs §3)."""

    date: str
    execution_date: str
    maturity: str
    symbols: tuple[str, ...]
    scores: Mapping[str, tuple[float | None, ...]]
    targets: tuple[float | None, ...]
    feature_as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "execution_date": self.execution_date,
            "maturity": self.maturity,
            "feature_as_of": self.feature_as_of,
            "symbols": list(self.symbols),
            "scores": {key: list(value) for key, value in sorted(self.scores.items())},
            "targets": list(self.targets),
        }


@dataclass(frozen=True, slots=True)
class CrossSectionRequest:
    """Everything the verdict consumes; nothing may be estimated from verification."""

    candidates: tuple[CrossSectionCandidate, ...]
    slices: tuple[CrossSectionSlice, ...]
    cutoff: str
    verification_start: str
    universe_provenance: Mapping[str, Any] = field(default_factory=dict)
    config: CrossSectionConfig = field(default_factory=CrossSectionConfig)
    cost: CostModel = field(default_factory=CostModel)
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CrossSectionVerdict:
    factor_id: str
    expression: str
    status: str
    adjusted_p_value: float
    raw_statistic: float
    mean_rank_ic: float
    periods: int
    stability: dict[str, Any]
    diagnostics: dict[str, Any]
    reasons: tuple[str, ...]
    error_statement: str
    channel: str = CHANNEL_CROSS_SECTION
    channel_label: str = CHANNEL_LABELS[CHANNEL_CROSS_SECTION]
    assertion: str = CHANNEL_ASSERTIONS[CHANNEL_CROSS_SECTION]
    scope_limit: str = CHANNEL_SCOPE_LIMITS[CHANNEL_CROSS_SECTION]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "status": self.status,
            "adjusted_p_value": self.adjusted_p_value,
            "raw_statistic": self.raw_statistic,
            "mean_rank_ic": self.mean_rank_ic,
            "periods": self.periods,
            "stability": self.stability,
            "diagnostics": self.diagnostics,
            "reasons": list(self.reasons),
            "error_statement": self.error_statement,
            "channel": self.channel,
            "channel_label": self.channel_label,
            "assertion": self.assertion,
            "scope_limit": self.scope_limit,
        }


@dataclass(frozen=True, slots=True)
class CrossSectionFamilyTest:
    method: str
    observed_max_statistic: float
    p_value: float
    alpha: float
    family_size: int
    periods: int
    rejected_count: int
    widths: tuple[int, ...]
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
            "widths": list(self.widths),
            "spec": self.spec,
        }


@dataclass(frozen=True, slots=True)
class CrossSectionReport:
    status: str
    candidates: tuple[CrossSectionVerdict, ...]
    family: CrossSectionFamilyTest
    spec: dict[str, Any]
    fingerprint: str
    channel: str = CHANNEL_CROSS_SECTION

    @property
    def effective_count(self) -> int:
        return sum(v.status == CS_STATUS_EFFECTIVE for v in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CROSS_SECTION_SCHEMA_VERSION,
            "status": self.status,
            "effective_count": self.effective_count,
            "candidates": [v.to_dict() for v in self.candidates],
            "family": self.family.to_dict(),
            "spec": self.spec,
            "fingerprint": self.fingerprint,
            "channel": self.channel,
            "channel_label": CHANNEL_LABELS[self.channel],
        }


def _finite(value: Any) -> bool:
    return value is not None and math.isfinite(float(value))


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2:
        return float("nan")
    ac, bc = a - a.mean(), b - b.mean()
    denominator = math.sqrt(float(ac @ ac) * float(bc @ bc))
    return float(ac @ bc / denominator) if denominator > 1e-12 else 0.0


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    return _pearson(rankdata(a), rankdata(b))


def _check_isolation(request: CrossSectionRequest) -> tuple[list[CrossSectionSlice], list[str]]:
    """Enforce the freeze, point-in-time contract, and one shared family grid."""
    cfg = request.config
    candidates = request.candidates
    if not candidates:
        raise CrossSectionIsolationError("no frozen candidates")
    ids = [c.factor_id for c in candidates]
    if len(ids) != len(set(ids)):
        raise CrossSectionIsolationError("duplicate frozen candidate ids")
    if not request.cutoff or not request.verification_start:
        raise CrossSectionIsolationError("cutoff and verification_start are required")
    if request.verification_start <= request.cutoff:
        raise CrossSectionIsolationError("verification_start must be strictly after the freeze cutoff")

    basis = request.universe_provenance.get("membership_basis")
    if basis not in MEMBERSHIP_BASES:
        raise CrossSectionIsolationError(
            "universe_provenance.membership_basis must declare one of " + ", ".join(MEMBERSHIP_BASES)
        )
    slices = sorted(request.slices, key=lambda s: s.date)
    if not slices:
        raise CrossSectionIsolationError("no verification cross-sections")
    if len({s.date for s in slices}) != len(slices):
        raise CrossSectionIsolationError("duplicate decision dates")
    if len(slices) < cfg.min_periods:
        raise CrossSectionIsolationError(
            f"{len(slices)} periods, fewer than min_periods={cfg.min_periods}"
        )
    if request.verification_start > slices[0].date:
        raise CrossSectionIsolationError("verification_start is later than the first observation")

    for item in slices:
        if item.date <= request.cutoff or item.date < request.verification_start:
            raise CrossSectionIsolationError(
                f"cross-section {item.date} is not strictly after the cutoff {request.cutoff}"
            )
        if not item.feature_as_of or item.feature_as_of > item.date:
            raise CrossSectionIsolationError(
                f"feature_as_of for {item.date} is missing or later than the decision date"
            )
        if item.execution_date <= item.date:
            raise CrossSectionIsolationError(
                f"{item.date}: execution must be on a LATER bar than the decision"
            )
        if item.maturity <= item.execution_date:
            raise CrossSectionIsolationError(
                f"{item.date}: labels must mature AFTER execution before scoring"
            )
        symbols = tuple(item.symbols)
        if len(symbols) != len(set(symbols)):
            raise CrossSectionIsolationError(f"{item.date}: duplicate symbols in the universe")
        if len(symbols) < cfg.min_universe:
            raise CrossSectionIsolationError(
                f"{item.date}: universe width {len(symbols)} < min_universe={cfg.min_universe}"
            )
        if len(item.targets) != len(symbols):
            raise CrossSectionIsolationError(f"{item.date}: targets/symbols length mismatch")
        if set(item.scores) != set(ids):
            raise CrossSectionIsolationError(
                f"{item.date}: scores must contain exactly the frozen candidate ids "
                "(an unfrozen or missing candidate changes the family)"
            )
        targets = np.asarray([float(v) if _finite(v) else np.nan for v in item.targets])
        for key in ids:
            values = item.scores[key]
            if len(values) != len(symbols):
                raise CrossSectionIsolationError(f"{item.date}/{key}: scores/symbols length mismatch")
            scores = np.asarray([float(v) if _finite(v) else np.nan for v in values])
            usable = int((np.isfinite(scores) & np.isfinite(targets)).sum())
            if usable < cfg.min_universe:
                raise CrossSectionIsolationError(
                    f"{item.date}/{key}: only {usable} usable pairs, fewer than "
                    f"min_universe={cfg.min_universe}; missing labels are never filled with zero"
                )
    return slices, ids


def _rank_ic(scores: np.ndarray, targets: np.ndarray) -> tuple[float, int]:
    valid = np.isfinite(scores) & np.isfinite(targets)
    return _spearman(scores[valid], targets[valid]), int(valid.sum())


def _turnover(previous: frozenset[str] | None, current: frozenset[str]) -> float:
    if previous is None:
        return 1.0
    size = max(len(current), 1)
    return len(previous ^ current) / (2 * size)


def _period_diagnostics(
    item: CrossSectionSlice,
    scores: np.ndarray,
    cfg: CrossSectionConfig,
    cost: CostModel,
    previous: tuple[frozenset[str] | None, frozenset[str] | None],
) -> tuple[dict[str, Any], frozenset[str], frozenset[str]]:
    """One period's quantile, leg, turnover and gross/net diagnostics."""
    targets = np.asarray([float(v) if _finite(v) else np.nan for v in item.targets])
    valid = np.isfinite(scores) & np.isfinite(targets)
    symbols = np.asarray(item.symbols, dtype=object)
    usable_scores = scores[valid]
    usable_targets = targets[valid]
    usable_symbols = symbols[valid]
    order = np.argsort(usable_scores, kind="stable")
    groups = np.array_split(order, cfg.quantiles)
    universe_mean = float(usable_targets.mean())
    excess = np.asarray([float(usable_targets[g].mean()) - universe_mean for g in groups])
    top_mean = float(usable_targets[groups[-1]].mean())
    bottom_mean = float(usable_targets[groups[0]].mean())
    gross_spread = top_mean - bottom_mean
    long_excess = float(excess[-1])
    short_excess = float(-excess[0])
    top_set = frozenset(str(s) for s in usable_symbols[groups[-1]])
    bottom_set = frozenset(str(s) for s in usable_symbols[groups[0]])
    long_turnover = _turnover(previous[0], top_set)
    short_turnover = _turnover(previous[1], bottom_set)
    turnover = (long_turnover + short_turnover) / 2 if cost.assume_shortable else long_turnover
    period_cost = turnover * cost.round_trip_rate
    implementable = gross_spread if cost.assume_shortable else long_excess
    record = {
        "date": item.date,
        "width": int(valid.sum()),
        "group_excess_returns": [float(v) for v in excess],
        "gross_long_short_spread": gross_spread,
        "long_leg_excess": long_excess,
        "short_leg_excess": short_excess,
        "implementable_return": implementable,
        "turnover": turnover,
        "cost": period_cost,
        "net_return": implementable - period_cost,
        "complete": bool(all(np.isfinite(excess))),
    }
    return record, top_set, bottom_set


def _stability(rank_ic: np.ndarray, cfg: CrossSectionConfig) -> dict[str, Any]:
    n = len(rank_ic)
    edges = np.linspace(0, n, cfg.blocks + 1).astype(int)
    if np.any(np.diff(edges) < cfg.min_block_periods):
        raise CrossSectionIsolationError("a stability block has too few periods")
    block_means = [float(rank_ic[edges[i]:edges[i + 1]].mean()) for i in range(cfg.blocks)]
    positive = int(sum(value > 0 for value in block_means))
    required = int(math.ceil(cfg.stability_fraction * cfg.blocks))
    sorted_ic = np.sort(rank_ic)
    leave_one_out = (
        float(sorted_ic[:-1].mean()) if cfg.leave_one_out and n > 1 else None
    )
    half = n // 2
    early = float(rank_ic[:half].mean())
    late = float(rank_ic[half:].mean())
    if early > 1e-12:
        decay_ratio = late / early
        no_decay = late >= cfg.min_decay_ratio * early
    else:
        decay_ratio = None
        no_decay = late > 0
    promotion_checks = {
        "block_agreement": positive >= required,
        "leave_one_out_positive": True if leave_one_out is None else leave_one_out > 0,
    }
    # Qlib / alphalens do not impose a "late-half decay ratio" acceptance
    # rule. Regime robustness is reported (GitHub practice: regime splits,
    # PBO / DSR) but is not a veto on the factor's information content.
    descriptive_checks = {"no_late_decay": no_decay}
    checks = {**promotion_checks, **descriptive_checks}
    return {
        "blocks": cfg.blocks,
        "block_means": block_means,
        "positive_blocks": positive,
        "required_positive_blocks": required,
        "exact_sign_test_p_value": float(binom.sf(positive - 1, cfg.blocks, 0.5)),
        "sign_test_note": "diagnostic only; few blocks give low power, no independent significance claimed",
        "leave_one_out_mean_rank_ic": leave_one_out,
        "early_half_mean_rank_ic": early,
        "late_half_mean_rank_ic": late,
        "decay_ratio": decay_ratio,
        "min_decay_ratio": cfg.min_decay_ratio,
        "checks": checks,
        "promotion_checks": promotion_checks,
        "descriptive_checks": descriptive_checks,
        "gate_policy": "qlib_alphalens: block agreement and leave-one-out are promotion "
                       "checks; late-half decay is reported as a regime diagnostic only",
        "passed": all(promotion_checks.values()),
    }


@dataclass(frozen=True, slots=True)
class CrossSectionDiagnostics:
    """L1-L4 diagnostics only. Structurally incapable of an effectiveness claim.

    The seven-layer research process makes L5 the sole exit for an ``effective``
    assertion. Inspected or retrospective windows may still be diagnosed, but
    running a family test on them would manufacture a verdict that cannot be
    certified. This object deliberately carries no status, p-value or verdict.
    """

    channel: str
    periods: int
    dates: tuple[str, ...]
    candidates: dict[str, Any]
    limitations: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": "L1-L4 diagnostics only",
            "certification": "not_performed",
            "certification_reason": "L5 frozen-window family test is the only exit for an "
                                    "effective-factor assertion; this call never runs it",
            "channel": self.channel,
            "channel_label": CHANNEL_LABELS[self.channel],
            "periods": self.periods,
            "dates": list(self.dates),
            "candidates": self.candidates,
            "limitations": list(self.limitations),
            "fingerprint": self.fingerprint,
        }


def _summarize_diagnostics(
    records: list[dict[str, Any]], cfg: CrossSectionConfig, cost: CostModel,
    rank_ic: np.ndarray | None = None,
    score_frames: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Qlib/alphalens-style evaluation metrics from the per-period L1-L4 records.

    Only ``complete_periods_sufficient`` is a promotion check by default.
    Quantile monotonicity, leg signs and the net spread are reported alongside
    their thresholds, matching how Qlib SigAnaRecord, alphalens and qweave
    present them: as diagnostics, not as factor acceptance rules.
    """
    complete = [r for r in records if r["complete"]]
    group_matrix = np.asarray([r["group_excess_returns"] for r in complete], dtype=float)
    mean_groups = group_matrix.mean(axis=0) if len(complete) else np.zeros(cfg.quantiles)
    monotonicity = _spearman(np.arange(cfg.quantiles, dtype=float), mean_groups)
    long_leg = float(np.mean([r["long_leg_excess"] for r in complete])) if complete else 0.0
    short_leg = float(np.mean([r["short_leg_excess"] for r in complete])) if complete else 0.0
    gross = float(np.mean([r["gross_long_short_spread"] for r in complete])) if complete else 0.0
    net = float(np.mean([r["net_return"] for r in complete])) if complete else 0.0
    turnover_mean = float(np.mean([r["turnover"] for r in complete])) if complete else 0.0
    cost_mean = float(np.mean([r["cost"] for r in complete])) if complete else 0.0
    # A mathematically exact 0.9 rank correlation may evaluate to
    # 0.8999999999999998; compare with a numerical tolerance only.
    promotion_checks = {"complete_periods_sufficient": len(complete) >= cfg.min_periods}
    descriptive_checks = {
        "quantile_monotonicity": monotonicity >= cfg.min_monotonicity - 1e-9,
        "both_legs_correctly_signed": (long_leg > 0 and short_leg > 0)
        if cfg.require_both_legs else True,
        "net_return_positive": net > 0 if cfg.require_net_positive else True,
    }
    checks = {**promotion_checks, **descriptive_checks}
    passed = (all(promotion_checks.values()) if cfg.report_only_gates
              else all(checks.values()))

    # Qlib SigAnaRecord: IC, ICIR, Rank IC, Rank ICIR; qlib risk_analysis:
    # mean, std, annualized return, information ratio, max drawdown.
    ic_series = (np.asarray(rank_ic, dtype=float) if rank_ic is not None
                 else np.asarray([], dtype=float))
    ic_series = ic_series[np.isfinite(ic_series)]
    if ic_series.size > 1 and float(ic_series.std(ddof=1)) > 0:
        mean_rank_ic = float(ic_series.mean())
        std_rank_ic = float(ic_series.std(ddof=1))
        rank_icir = mean_rank_ic / std_rank_ic
        ic_t_stat = mean_rank_ic / (std_rank_ic / np.sqrt(ic_series.size))
    else:
        mean_rank_ic = float(ic_series.mean()) if ic_series.size else None
        std_rank_ic, rank_icir, ic_t_stat = None, None, None
    # qweave t_nw / Newey-West HAC: overlapping or persistent IC series inflate
    # the conventional t statistic. Reported alongside, never used as a gate.
    hac = hac_t_statistic(ic_series)
    autocorr = (factor_autocorrelation(score_frames)
                if score_frames is not None else None)
    gross_series = np.asarray([r["gross_long_short_spread"] for r in complete], dtype=float)
    if gross_series.size > 1 and float(gross_series.std(ddof=1)) > 0:
        long_short_ir = float(gross_series.mean() / gross_series.std(ddof=1) * np.sqrt(12))
        long_short_ann_return = float(gross_series.mean() * 12)
    else:
        long_short_ir, long_short_ann_return = None, None
    kendall = float(kendalltau(np.arange(cfg.quantiles), mean_groups).correlation)
    return {
        "quantiles": cfg.quantiles,
        "complete_periods": len(complete),
        "total_periods": len(records),
        "mean_group_excess_returns": [float(v) for v in mean_groups],
        "quantile_monotonicity": monotonicity,
        "quantile_monotonicity_kendall": kendall,
        "min_monotonicity": cfg.min_monotonicity,
        "mean_rank_ic": mean_rank_ic,
        "std_rank_ic": std_rank_ic,
        "rank_icir": rank_icir,
        "ic_t_stat": ic_t_stat,
        "ic_t_stat_hac": hac["hac_t_stat"],
        "hac": hac,
        "factor_autocorrelation": autocorr,
        "long_short_annualized_return": long_short_ann_return,
        "long_short_information_ratio": long_short_ir,
        "annualization_scaler": 12,
        "report_only_metric_note": "HAC t and factor autocorrelation are Qlib/qweave/"
                                   "alphalens descriptive metrics; none of them "
                                   "participates in promotion or error-rate statements",
        "metric_sources": {
            "rank_ic": "Qlib qlib.contrib.eva.alpha.calc_ic (per-date Spearman)",
            "rank_icir": "Qlib SigAnaRecord: Rank ICIR = mean(rank_ic)/std(rank_ic)",
            "ic_t_stat": "standard IC t statistic; industry convention t > 2",
            "ic_t_stat_hac": "Newey & West (1987) Bartlett HAC; qweave t_nw; lag rule "
                             "Newey & West (1994)",
            "factor_autocorrelation": "Qlib pred_autocorr (values) and alphalens "
                                      "factor_rank_autocorrelation (ranks), lag=1",
            "quantile_monotonicity": "alphalens mean_return_by_quantile / qweave Kendall tau (descriptive)",
            "long_short": "Qlib calc_long_short_return and risk_analysis (gross/net, ann_scaler=12)",
            "turnover": "alphalens quantile_turnover",
        },
        "long_leg_mean_excess": long_leg,
        "short_leg_mean_excess": short_leg,
        "short_leg_note": "diagnostic relative return; not an executable short when assume_shortable=False",
        "gross_long_short_spread": gross,
        "net_return": net,
        "mean_turnover": turnover_mean,
        "mean_cost": cost_mean,
        "cost_model": cost.to_dict(),
        "checks": checks,
        "promotion_checks": promotion_checks,
        "descriptive_checks": descriptive_checks,
        "gate_policy": ("qlib_alphalens_report_only: monotonicity, leg signs and net "
                        "spread are descriptive; only complete periods is a gate"
                        if cfg.report_only_gates else
                        "legacy_vetoes: all four checks are promotion gates"),
        "passed": passed,
        "per_period": records,
    }


def _collect_periods(
    request: CrossSectionRequest,
) -> tuple[CrossSectionConfig, CostModel, list[CrossSectionSlice], list[str],
           dict[str, list[dict[str, Any]]], np.ndarray, np.ndarray,
           dict[str, list[dict[str, float]]]]:
    """Shared L1-L4 materialisation; no resampling, no verdict."""
    cfg, cost = request.config, request.cost
    enforce_channel(CHANNEL_CROSS_SECTION, request.candidates)
    slices, ids = _check_isolation(request)
    n, k = len(slices), len(ids)
    rank_ic = np.empty((n, k), dtype=float)
    widths = np.empty((n, k), dtype=float)
    per_period: dict[str, list[dict[str, Any]]] = {key: [] for key in ids}
    score_frames: dict[str, list[dict[str, float]]] = {key: [] for key in ids}
    held: dict[str, tuple[frozenset[str] | None, frozenset[str] | None]] = {
        key: (None, None) for key in ids
    }
    for t, item in enumerate(slices):
        targets = np.asarray([float(v) if _finite(v) else np.nan for v in item.targets])
        symbols = [str(symbol) for symbol in item.symbols]
        for j, key in enumerate(ids):
            scores = np.asarray(
                [float(v) if _finite(v) else np.nan for v in item.scores[key]]
            )
            ic, width = _rank_ic(scores, targets)
            rank_ic[t, j], widths[t, j] = ic, width
            # Per-symbol scores are kept only for the report-only Qlib/alphalens
            # autocorrelation metrics; they never enter a verdict or fingerprint.
            score_frames[key].append({
                symbol: float(value) for symbol, value in zip(symbols, scores)
                if np.isfinite(value)
            })
            record, top_set, bottom_set = _period_diagnostics(
                item, scores, cfg, cost, held[key]
            )
            held[key] = (top_set, bottom_set)
            per_period[key].append(record)
    return cfg, cost, slices, ids, per_period, rank_ic, widths, score_frames


def diagnose_cross_section(request: CrossSectionRequest) -> CrossSectionDiagnostics:
    """L1-L4 only, for windows that must NOT be turned into a verdict.

    Use this on inspected / retrospective data. It enforces the same isolation
    contract and emits the same per-period diagnostics as ``assess_cross_section``,
    but never runs the family test and never produces a status.
    """
    cfg, cost, slices, ids, per_period, rank_ic, _widths, frames = _collect_periods(request)
    candidates: dict[str, Any] = {}
    for j, key in enumerate(ids):
        diagnostics = _summarize_diagnostics(
            per_period[key], cfg, cost, rank_ic[:, j], frames[key])
        candidates[key] = {
            "expression": next(c.expression for c in request.candidates if c.factor_id == key),
            "mean_rank_ic": float(rank_ic[:, j].mean()),
            "periods": len(slices),
            "diagnostics": diagnostics,
            "note": "descriptive diagnostic on an inspected window; NOT an effective-factor "
                    "assertion, NOT a multiple-testing-corrected result",
        }
    digest = fingerprint({
        "scope": "L1-L4 diagnostics only",
        "config": cfg.to_dict(),
        "cost": cost.to_dict(),
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "candidates": [c.to_dict() for c in request.candidates],
        "slices": [s.to_dict() for s in request.slices],
        "universe_provenance": dict(request.universe_provenance),
    })
    return CrossSectionDiagnostics(
        channel=CHANNEL_CROSS_SECTION,
        periods=len(slices),
        dates=tuple(s.date for s in slices),
        candidates=candidates,
        limitations=(
            "L5 family test deliberately not run; no error-rate statement applies",
            "inspected or retrospective windows cannot certify an effective factor",
            "quantile, leg, turnover and cost figures are descriptive only",
            "missing matured labels are kept as None; group figures necessarily use only "
            "symbols with matured labels, so survivorship is not eliminated",
        ),
        fingerprint=digest,
    )


def assess_cross_section(request: CrossSectionRequest) -> CrossSectionReport:
    """Produce the terminal, auditable verdict for a frozen ranking family.

    Same request -> same report (including fingerprint). No parameter is
    estimated from the verification window; the only computation there is the
    period statistics and the resampling null built from them.
    """
    cfg, cost, slices, ids, per_period, rank_ic, widths, frames = _collect_periods(request)
    k = len(ids)
    n = len(slices)

    # Width weighting: Rank IC sampling sd ~ 1/sqrt(N-1). Width reduces the
    # measurement noise of each period; it does NOT create extra periods.
    differentials = np.sqrt(np.maximum(widths - 1.0, 1.0)) * rank_ic
    paths = shared_time_paths(
        n, reps=cfg.reps, block_size=cfg.block_size, seed=cfg.seed,
        bootstrap=cfg.bootstrap, salt=CROSS_SECTION_PATH_SALT,
    )
    observed, t_star, _mean_d, _scale = studentized_statistics(differentials, paths)
    adjusted, family_p, order, max_star = stepdown(observed, t_star)
    rejected = adjusted <= cfg.alpha

    small_window = n < 24
    power_note = (
        f"Only {n} verification periods across {cfg.blocks} disjoint blocks: power is low. "
        "A wider universe reduces the measurement noise of each period's Rank IC but does "
        "NOT create independent decision periods. A non-rejection is weak evidence of no "
        "effect, and any rejection rests on a short out-of-sample window."
    ) if small_window else (
        f"{n} verification periods across {cfg.blocks} disjoint blocks; "
        "width weighting reduces per-period measurement noise, not the period count."
    )

    survivor_unresolved = request.universe_provenance.get("membership_basis") != "point_in_time"
    family_spec = {
        "method": "cross_section_rank_ic_shared_path_max_statistic_stepdown",
        "reference": "White (2000) Reality Check; Hansen (2005) SPA (framing); "
                     "Romano-Wolf / Westfall-Young step-down; Politis-Romano (1994)",
        "null": "no relative ranking ability: E[RankIC] = 0 (random ordering)",
        "baselines": ["random ordering (Rank IC expectation zero)", "equal-weight universe"],
        "statistic": "sqrt(T) * mean(sqrt(N_t-1) * RankIC_t) / observed_sample_std, max over family",
        "width_note": "width reduces per-period measurement noise, never the independent period count",
        "recentring": "conservative Reality-Check / least-favourable-configuration style",
        "spa_simplification": "Full SPA refinements are NOT implemented: the studentising "
                              "scale is fixed at its observed value and poor alternatives "
                              "are not data-dependently discarded.",
        "method_boundary": "NOT a full SPA test, NOT a Fama-MacBeth robust t test, "
                           "NOT a multi-variable cross-sectional test",
        "dependence": "one shared stationary/circular block-bootstrap index path across all candidates",
        "config": cfg.to_dict(),
        "cost": cost.to_dict(),
        "replicates": cfg.reps,
        "verification_periods": n,
        "verification_dates": [s.date for s in slices],
        "universe_widths": [int(v) for v in widths.min(axis=1)],
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "observed_statistics": [float(v) for v in observed],
        "adjusted_p_values": [float(v) for v in adjusted],
        "stepdown_order": [ids[i] for i in order],
        "bootstrap_max_quantiles": {
            str(level): float(value)
            for level, value in zip(
                ("0.5", "0.9", "0.95", "0.99"),
                np.quantile(max_star, [.5, .9, .95, .99]),
            )
        },
        "assumptions": [
            "candidate family and every parameter frozen once at the cutoff, before any "
            "verification slice was read",
            "verification window is later HISTORICAL data, not calendar-future data; "
            "isolation is informational and procedural - no verification data was used "
            "to build, select or tune the frozen family",
            "universe membership is available at the decision date (or explicitly flagged otherwise)",
            "features use only [t-w, t] and execution is on a later bar than the decision",
            "labels are scored only after maturity; missing labels are never filled with zero",
            "block bootstrap preserves serial and cross-candidate dependence",
            "Rank IC series is stationary over the verification window",
        ],
        "within_family_fwer_control": True,
        "fwer_statement": (
            "FWER <= alpha within the frozen ranking family, conditional on the assumptions "
            "above; this is NOT a statement about the timing channel's family"
        ),
        "loop_level_sequential_guarantee": False,
        "sequential_statement": "adaptivity is removed by causal isolation, NOT bounded by a sequential test",
        "coverage_guarantee": False,
        "profitability_claimed": False,
        "tradability_claimed": False,
        "causal_claim": False,
        "survivorship_bias_unresolved": survivor_unresolved,
        "small_window": small_window,
        "power_note": power_note,
        **channel_fields(CHANNEL_CROSS_SECTION),
    }
    if survivor_unresolved:
        family_spec["survivorship_note"] = (
            "Universe membership is not a certified point-in-time reconstruction; "
            "survivorship bias is NOT eliminated and must not be claimed away."
        )

    family = CrossSectionFamilyTest(
        method="cross_section_rank_ic_shared_path_max_statistic_stepdown",
        observed_max_statistic=float(observed.max()),
        p_value=family_p,
        alpha=cfg.alpha,
        family_size=k,
        periods=n,
        rejected_count=int(rejected.sum()),
        widths=tuple(int(v) for v in widths.min(axis=1)),
        spec=family_spec,
    )

    verdicts: list[CrossSectionVerdict] = []
    for j, key in enumerate(ids):
        column = rank_ic[:, j]
        stability = _stability(column, cfg)
        records = per_period[key]
        diagnostics = _summarize_diagnostics(records, cfg, cost, column, frames[key])
        checks = diagnostics["checks"]

        reasons: list[str] = []
        if not rejected[j]:
            reasons.append(
                f"search-corrected adjusted p={adjusted[j]:.4f} > alpha={cfg.alpha}"
            )
        if not stability["passed"]:
            reasons.append("stability conditions not met: " + ", ".join(
                name for name, ok in stability["checks"].items() if not ok
            ))
        if not diagnostics["passed"]:
            failed = [name for name, ok in
                      diagnostics.get("promotion_checks", checks).items() if not ok]
            reasons.append("promotion gates not met: " + ", ".join(failed))
        if cfg.report_only_gates:
            descriptive_failures = [
                name for name, ok in diagnostics["descriptive_checks"].items() if not ok
            ]
            if descriptive_failures:
                reasons.append(
                    "descriptive diagnostics below threshold (reported, NOT a veto): "
                    + ", ".join(descriptive_failures)
                )
        mean_ic = float(column.mean())
        consistently_worse = (
            mean_ic < 0
            and stability["positive_blocks"] <= cfg.blocks // 4
            and (stability["leave_one_out_mean_rank_ic"] is None
                 or stability["leave_one_out_mean_rank_ic"] < 0)
        )
        if rejected[j] and stability["passed"] and diagnostics["passed"]:
            status = CS_STATUS_EFFECTIVE
        elif consistently_worse:
            status = CS_STATUS_REFUTED
            reasons.append("consistently worse than random ordering across blocks")
        else:
            status = CS_STATUS_INSUFFICIENT
        statement = (
            f"{CHANNEL_LABELS[CHANNEL_CROSS_SECTION]}：在含 {k} 个候选的冻结族内，"
            f"族级错误率 ≤ {cfg.alpha}（以上述假设为条件）；本候选搜索校正后的调整后 "
            f"p 值为 {adjusted[j]:.4f}。断言仅限同一时点标的池内的相对排序能力，"
            "跨轮自适应错误率、盈利、因果与未来持续一概不宣称。"
        ) if status == CS_STATUS_EFFECTIVE else ""
        if status == CS_STATUS_EFFECTIVE and small_window:
            statement += " " + power_note
        verdicts.append(CrossSectionVerdict(
            factor_id=key,
            expression=next(c.expression for c in request.candidates if c.factor_id == key),
            status=status,
            adjusted_p_value=float(adjusted[j]),
            raw_statistic=float(observed[j]),
            mean_rank_ic=mean_ic,
            periods=n,
            stability=stability,
            diagnostics=diagnostics,
            reasons=tuple(reasons),
            error_statement=statement,
        ))

    spec = {
        "schema_version": CROSS_SECTION_SCHEMA_VERSION,
        "config": cfg.to_dict(),
        "cost": cost.to_dict(),
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "candidates": [c.to_dict() for c in request.candidates],
        "universe_provenance": dict(request.universe_provenance),
        "provenance": dict(request.provenance),
        "slices_fingerprint": fingerprint([s.to_dict() for s in request.slices]),
        "power_note": power_note,
        "small_window": small_window,
        "family": family_spec,
        "pillar_0": "informational causal isolation on historical data: freeze once at the "
                    "cutoff before verification data is read, point-in-time universe, "
                    "decision/execution separation, matured labels, enforced by _check_isolation",
        "pillar_1": "search-robust family test: width-weighted Rank IC (Qlib calc_ic), "
                    "shared-path block bootstrap max statistic + step-down (White RC / SPA framing)",
        "pillar_2": "stability/repeatability: disjoint blocks, leave-one-out; late-half decay "
                    "is reported as a regime diagnostic, not a veto",
        "evaluation_baseline": {
            "authority": "docs/factor_evaluation_baseline.md",
            "primary_metrics": ["Rank IC", "Rank ICIR", "IC t statistic",
                                "Newey-West HAC t statistic",
                                "factor value/rank autocorrelation lag 1",
                                "long-short gross/net spread", "information ratio", "turnover"],
            "sources": [
                "Qlib qlib.workflow.record_temp.SigAnaRecord (IC, ICIR, Rank IC, Rank ICIR)",
                "Qlib qlib.contrib.eva.alpha.calc_ic / calc_long_short_return / pred_autocorr",
                "Qlib qlib.contrib.evaluate.risk_analysis (mean, std, annualized return, IR, MDD)",
                "alphalens-reloaded (per-date Spearman IC, factor_rank_autocorrelation, turnover)",
                "qweave (Kendall-tau quantile monotonicity; Newey-West t_nw)",
                "Newey & West (1987, 1994) HAC with Bartlett kernel and automatic bandwidth",
                "arch.bootstrap SPA / Reality Check / StepM for data-snooping control",
            ],
            "gate_policy": "report_only_gates=True: Qlib/alphalens metrics are reported, "
                           "not used as acceptance vetoes; only the family test, "
                           "block agreement, leave-one-out and period sufficiency decide status",
        },
        "channel_diagnostics": "quantile monotonicity; long/short legs separately; explicit "
                               "turnover and cost, gross and net reported side by side "
                               "(descriptive, aligned with Qlib/alphalens)",
        "terminal_states": [CS_STATUS_EFFECTIVE, CS_STATUS_INSUFFICIENT, CS_STATUS_REFUTED],
        **channel_fields(CHANNEL_CROSS_SECTION),
        "channel_note": "This report judges the cross-sectional channel only. Timing candidates "
                        "must be judged by effectiveness.py with its own family, null and baselines; "
                        "the two families are never merged.",
    }
    report_status = (
        CS_STATUS_FOUND if any(v.status == CS_STATUS_EFFECTIVE for v in verdicts)
        else CS_STATUS_INSUFFICIENT
    )
    digest = fingerprint({
        "config": cfg.to_dict(),
        "cost": cost.to_dict(),
        "cutoff": request.cutoff,
        "verification_start": request.verification_start,
        "candidates": [c.to_dict() for c in request.candidates],
        "slices": [s.to_dict() for s in request.slices],
        "universe_provenance": dict(request.universe_provenance),
        "provenance": dict(request.provenance),
    })
    return CrossSectionReport(
        status=report_status,
        candidates=tuple(verdicts),
        family=family,
        spec=spec,
        fingerprint=digest,
    )
