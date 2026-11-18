"""Search-period factor discovery and a one-shot preregistration freeze.

This is the search side of Part A. It turns a family of candidate ranking
formulas into ONE frozen family, using only data whose decision date AND label
maturity are on or before a declared cutoff. The verification window is never
an input here: ``search_and_freeze`` rejects any slice that crosses the cutoff,
so the freeze can be audited as having been produced before verification data
was touched.

Causal isolation in this project is *informational and procedural*, not a
requirement that data arrive from the calendar future. Search freedom is
confined to the search period; the family, its expressions, every threshold,
the cost model and the promotion rule are fixed once at the cutoff and written
with a fingerprint; the frozen out-of-sample window (later historical data)
is then scored exactly once. Re-searching after looking at that window
consumes it and requires a NEW freeze with a NEW later cutoff.

Nothing in this module emits an effectiveness verdict. L5 belongs to
``cross_section.py`` / ``effectiveness.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import rankdata

from dynaloop.research_engine.spec import fingerprint

__all__ = [
    "SearchSlice",
    "FactorSearchConfig",
    "FrozenFamily",
    "SearchIsolationError",
    "assert_search_isolation",
    "search_and_freeze",
    "freeze_fingerprint",
]


class SearchIsolationError(ValueError):
    """Raised when search-stage data crosses the declared freeze cutoff."""


@dataclass(frozen=True, slots=True)
class SearchSlice:
    """One search-period decision date; features and matured labels only."""

    date: str
    label_maturity: str
    symbols: tuple[str, ...]
    scores: Mapping[str, tuple[float | None, ...]]
    targets: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class FactorSearchConfig:
    """Every selection threshold is frozen with the family."""

    segments: int = 3
    min_segment_ic: float = 0.0
    min_mean_ic: float = 0.02
    min_t_stat: float = 1.5
    min_monotonicity: float = 0.9
    min_leg_excess: float = 0.0
    min_net_spread: float = 0.0
    # The search stage must NOT pre-enact the L5 promotion gates. Doing so
    # double-filters the family (search period once, verification period again)
    # and can empty it before a family test is ever possible. These are kept as
    # opt-in diagnostics; the default search objective is stable positive
    # ranking information, with all promotion decisions left to L5.
    require_segment_gates: bool = False
    require_no_decay: bool = False
    min_decay_ratio: float = 0.5
    quantiles: int = 5
    top_k: int = 6
    cost_rate: float = 0.0026
    assumed_turnover: float = 0.6
    excluded_factor_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("segments", "quantiles", "top_k"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.segments < 2:
            raise ValueError("at least two search segments are required")
        if not 0.0 <= self.min_monotonicity <= 1.0:
            raise ValueError("min_monotonicity must lie in [0, 1]")
        if not 0.0 <= self.min_decay_ratio <= 1.0:
            raise ValueError("min_decay_ratio must lie in [0, 1]")
        if self.min_leg_excess < 0 or self.min_net_spread < 0:
            raise ValueError("leg and net thresholds must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": self.segments,
            "min_segment_ic": self.min_segment_ic,
            "min_mean_ic": self.min_mean_ic,
            "min_t_stat": self.min_t_stat,
            "min_monotonicity": self.min_monotonicity,
            "min_leg_excess": self.min_leg_excess,
            "min_net_spread": self.min_net_spread,
            "require_segment_gates": self.require_segment_gates,
            "require_no_decay": self.require_no_decay,
            "min_decay_ratio": self.min_decay_ratio,
            "quantiles": self.quantiles,
            "top_k": self.top_k,
            "cost_rate": self.cost_rate,
            "assumed_turnover": self.assumed_turnover,
            "excluded_factor_ids": list(self.excluded_factor_ids),
        }


@dataclass(frozen=True, slots=True)
class FrozenFamily:
    """Immutable output of the search stage."""

    cutoff: str
    verification_start: str
    factor_ids: tuple[str, ...]
    expressions: Mapping[str, str]
    search_statistics: Mapping[str, Mapping[str, Any]]
    search_config: Mapping[str, Any]
    search_window: Mapping[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cutoff": self.cutoff,
            "verification_start": self.verification_start,
            "factor_ids": list(self.factor_ids),
            "expressions": dict(self.expressions),
            "search_statistics": {k: dict(v) for k, v in self.search_statistics.items()},
            "search_config": dict(self.search_config),
            "search_window": dict(self.search_window),
            "fingerprint": self.fingerprint,
        }


def assert_search_isolation(slices: Sequence[SearchSlice], cutoff: str) -> None:
    """Structurally reject any search slice that could carry post-cutoff information."""
    if not slices:
        raise SearchIsolationError("search window is empty")
    if not cutoff:
        raise SearchIsolationError("a freeze cutoff is required")
    previous = ""
    for item in slices:
        if item.date <= previous:
            raise SearchIsolationError("search dates must be strictly increasing and unique")
        previous = item.date
        if item.date > cutoff:
            raise SearchIsolationError(
                f"search decision {item.date} is later than the freeze cutoff {cutoff}"
            )
        if item.label_maturity > cutoff:
            raise SearchIsolationError(
                f"label for {item.date} matures on {item.label_maturity}, after the "
                f"freeze cutoff {cutoff}; its return would leak verification data"
            )
        if len(item.symbols) != len(item.targets):
            raise SearchIsolationError(f"{item.date}: symbols/targets length mismatch")
        if set(item.scores) and any(len(v) != len(item.symbols) for v in item.scores.values()):
            raise SearchIsolationError(f"{item.date}: scores/symbols length mismatch")


def _finite(values: Any) -> np.ndarray:
    out = np.asarray([float(v) if v is not None else np.nan for v in values], dtype=float)
    out[~np.isfinite(out)] = np.nan
    return out


def _rank_ic(scores: np.ndarray, targets: np.ndarray) -> float:
    valid = np.isfinite(scores) & np.isfinite(targets)
    if int(valid.sum()) < 3:
        return float("nan")
    x, y = rankdata(scores[valid]), rankdata(targets[valid])
    if x.std() < 1e-12 or y.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _group_excess(scores: np.ndarray, targets: np.ndarray, quantiles: int) -> np.ndarray:
    valid = np.isfinite(scores) & np.isfinite(targets)
    if int(valid.sum()) < quantiles:
        return np.full(quantiles, np.nan)
    order = np.argsort(scores[valid], kind="stable")
    y = targets[valid][order]
    equal = float(y.mean())
    return np.asarray(
        [float(part.mean() - equal) if part.size else np.nan
         for part in np.array_split(y, quantiles)],
        dtype=float,
    )


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    valid = np.isfinite(x) & np.isfinite(y)
    if int(valid.sum()) < 3:
        return float("nan")
    a, b = rankdata(x[valid]), rankdata(y[valid])
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def search_and_freeze(
    slices: Sequence[SearchSlice],
    *,
    cutoff: str,
    verification_start: str,
    expressions: Mapping[str, str],
    config: FactorSearchConfig = FactorSearchConfig(),
    provenance: Mapping[str, Any] | None = None,
    allow_empty: bool = False,
) -> FrozenFamily:
    """Select and freeze ONE family using search-period data exclusively.

    Selection rule (all thresholds are part of the frozen specification):

      1. split the search window into ``segments`` equal, ordered blocks;
      2. compute per-period Rank IC and quantile excess returns for every
         candidate formula;
      3. keep a candidate only if every segment's mean IC is positive, the
         overall mean IC and its t statistic clear the frozen threshold, the
         mean quantile curve is monotone enough, both legs are correctly
         signed and the cost-adjusted spread is positive. Per-segment gate
         stability and search-window decay are recorded as DIAGNOSTICS and are
         only enforced when ``require_segment_gates`` / ``require_no_decay``
         are explicitly enabled: pre-enacting L5 gates here would double-filter
         the family and is not the search stage's job;
      4. rank survivors by their WEAKEST segment and keep at most ``top_k``.

    ``excluded_factor_ids`` removes formulas whose out-of-sample descriptive
    statistics were previously inspected, so prior human knowledge cannot
    enter the family design. Exclusions are recorded in the freeze.
    """
    assert_search_isolation(slices, cutoff)
    if verification_start <= cutoff:
        raise SearchIsolationError("verification_start must be strictly after the cutoff")
    if not expressions:
        raise SearchIsolationError("candidate expressions are required")

    ids = sorted(expressions)
    excluded = set(config.excluded_factor_ids)
    per_period_ic: dict[str, list[float]] = {key: [] for key in ids}
    per_period_groups: dict[str, list[np.ndarray]] = {key: [] for key in ids}

    for item in slices:
        targets = _finite(item.targets)
        for key in ids:
            scores = _finite(item.scores.get(key, ()))
            if scores.size != targets.size:
                raise SearchIsolationError(f"{item.date}/{key}: scores length mismatch")
            per_period_ic[key].append(_rank_ic(scores, targets))
            per_period_groups[key].append(
                _group_excess(scores, targets, config.quantiles)
            )

    statistics: dict[str, dict[str, Any]] = {}
    selected: list[tuple[float, str]] = []
    for key in ids:
        ic = np.asarray(per_period_ic[key], dtype=float)
        groups = np.asarray(per_period_groups[key], dtype=float)
        finite = np.isfinite(ic)
        usable = int(finite.sum())
        if usable < config.segments * 3:
            statistics[key] = {"eligible": False, "reason": "too few finite periods",
                               "finite_periods": usable}
            continue
        ic_blocks = np.array_split(ic, config.segments)
        group_blocks = np.array_split(groups, config.segments, axis=0)
        segment_means = [float(np.nanmean(part)) for part in ic_blocks]
        segment_details = []
        for ic_part, group_part in zip(ic_blocks, group_blocks):
            seg_groups = np.nanmean(group_part, axis=0)
            seg_mono = _spearman(np.arange(config.quantiles, dtype=float), seg_groups)
            seg_long, seg_short = float(seg_groups[-1]), float(-seg_groups[0])
            segment_details.append({
                "mean_rank_ic": float(np.nanmean(ic_part)),
                "quantile_monotonicity": seg_mono,
                "long_leg_excess": seg_long,
                "short_leg_excess": seg_short,
                "net_spread_estimate": seg_long + seg_short
                - config.cost_rate * config.assumed_turnover,
            })
        mean_ic = float(np.nanmean(ic))
        std_ic = float(np.nanstd(ic, ddof=1))
        t_stat = float(mean_ic / (std_ic / np.sqrt(usable))) if std_ic > 0 else 0.0
        mean_groups = np.nanmean(groups, axis=0)
        monotonicity = _spearman(np.arange(config.quantiles, dtype=float), mean_groups)
        long_leg = float(mean_groups[-1])
        short_leg = float(-mean_groups[0])
        gross = long_leg + short_leg
        net = gross - config.cost_rate * config.assumed_turnover
        first_segment, last_segment = segment_means[0], segment_means[-1]
        if first_segment > 1e-12:
            decay_ok = last_segment >= config.min_decay_ratio * first_segment
        else:
            decay_ok = last_segment > 0
        # L5 judges quantile monotonicity on the FULL verification window, so
        # the search rule does the same. Per-segment checks are limited to the
        # sign of both legs and a positive net spread: a 40-period segment's
        # five-point rank correlation is far too noisy to threshold at 0.9.
        segment_gates_ok = all(
            item["long_leg_excess"] > config.min_leg_excess
            and item["short_leg_excess"] > config.min_leg_excess
            and item["net_spread_estimate"] > config.min_net_spread
            for item in segment_details
        )
        checks = {
            "every_segment_positive": min(segment_means) > config.min_segment_ic,
            "mean_ic_sufficient": mean_ic > config.min_mean_ic,
            "t_stat_sufficient": t_stat >= config.min_t_stat,
            # Rank correlations that are mathematically exactly 0.9 can come
            # back as 0.8999999999999998; compare with a numerical tolerance.
            "monotonicity_sufficient": monotonicity >= config.min_monotonicity - 1e-9,
            "both_legs_positive": (long_leg > config.min_leg_excess
                                   and short_leg > config.min_leg_excess),
            "net_spread_positive": net > config.min_net_spread,
                # Optional diagnostics only. Pre-enacting L5 promotion gates in
                # the search stage double-filters the family; L5 owns promotion.
                "segment_gates_stable": segment_gates_ok
            if config.require_segment_gates else True,
            "no_search_period_decay": decay_ok if config.require_no_decay else True,
            "not_excluded": key not in excluded,
        }
        statistics[key] = {
            "eligible": all(checks.values()),
            "checks": checks,
            "finite_periods": usable,
            "segment_mean_rank_ic": segment_means,
            "segment_details": segment_details,
            "decay_ratio": (last_segment / first_segment
                            if first_segment > 1e-12 else None),
            "weakest_segment": min(segment_means),
            "mean_rank_ic": mean_ic,
            "t_stat": t_stat,
            "mean_group_excess": [float(v) for v in mean_groups],
            "quantile_monotonicity": monotonicity,
            "long_leg_excess": long_leg,
            "short_leg_excess": short_leg,
            "gross_spread": gross,
            "search_net_spread_estimate": net,
        }
        if all(checks.values()):
            selected.append((min(segment_means), key))

    selected.sort(key=lambda pair: (-pair[0], pair[1]))
    family_ids = tuple(key for _score, key in selected[:config.top_k])
    if not family_ids and not allow_empty:
        raise SearchIsolationError(
            "no candidate cleared the frozen search rule; a freeze with an empty "
            "family would not be an honest preregistration"
        )

    body = {
        "document": "Part A search-stage preregistration freeze",
        "schema_version": 1,
        "cutoff": cutoff,
        "verification_start": verification_start,
        "factor_ids": list(family_ids),
        "expressions": {key: expressions[key] for key in family_ids},
        "search_config": config.to_dict(),
        "selection_rule": (
            "all segments positive; mean IC and t statistic above frozen thresholds; "
            "monotone mean quantile curve; both legs positive; positive cost-adjusted "
            "spread; rank by weakest segment; keep top_k; excluded ids removed"
        ),
        "search_window": {
            "first_decision_date": slices[0].date,
            "last_decision_date": slices[-1].date,
            "last_label_maturity": max(s.label_maturity for s in slices),
            "decision_periods": len(slices),
            "candidate_formulas_evaluated": len(ids),
        },
        "isolated_statistics": statistics,
        "provenance": dict(provenance or {}),
    }
    digest = freeze_fingerprint(body)
    return FrozenFamily(
        cutoff=cutoff,
        verification_start=verification_start,
        factor_ids=family_ids,
        expressions={key: expressions[key] for key in family_ids},
        search_statistics=statistics,
        search_config=config.to_dict(),
        search_window=body["search_window"],
        fingerprint=digest,
    )


def freeze_fingerprint(body: Mapping[str, Any]) -> str:
    """Hash a freeze document with its fingerprint field removed."""
    clean = {key: value for key, value in body.items() if key != "fingerprint"}
    return fingerprint(clean)
