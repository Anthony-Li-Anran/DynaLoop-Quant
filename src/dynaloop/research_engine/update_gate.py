"""Statistically-gated model updates: promote a candidate only with evidence.

This is the system's differentiator -- statistical evidence decides not only
which factors are trusted (Part A certification) but WHEN the system updates.
A candidate model (or rule) must beat the incumbent on paired per-period loss
with a one-sided block-bootstrap significance test AND a positive lower
confidence bound before it may be promoted. A point estimate of "lower error"
is deliberately not enough: that is exactly how adaptive loops promote noise.

The paired design uses the SAME resampled time-index path for the loss
differentials, preserving serial dependence. This reuses the shared maths in
``resampling_tools`` with its own salt, so the update gate's random stream is
independent of the two Part A channels. It is a single-comparison test against
one incumbent; the multi-candidate family correction lives in Part A, not here.

No threshold here is invented for factor acceptance: ``alpha`` is the standard
one-sided significance level, the block size is the serial-dependence window,
and the improvement must be positive in both the point estimate and the CI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from dynaloop.research_engine.resampling_tools import shared_time_paths
from dynaloop.research_engine.spec import fingerprint

UPDATE_GATE_PATH_SALT = 0xA5A5E7


@dataclass(frozen=True, slots=True)
class UpdateGateConfig:
    """All free parameters of one promotion decision."""

    alpha: float = 0.05
    reps: int = 1000
    block_size: int = 5
    seed: int = 2026
    min_periods: int = 12
    min_improvement: float = 0.0
    bootstrap: str = "stationary"

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must lie in (0, 1)")
        if type(self.reps) is not int or self.reps < 100:
            raise ValueError("reps must be an integer >= 100")
        if type(self.block_size) is not int or self.block_size < 1:
            raise ValueError("block_size must be a positive integer")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if type(self.min_periods) is not int or self.min_periods < 2:
            raise ValueError("min_periods must be an integer >= 2")
        if not math.isfinite(self.min_improvement) or self.min_improvement < 0:
            raise ValueError("min_improvement must be finite and >= 0")
        if self.bootstrap not in ("stationary", "circular"):
            raise ValueError("bootstrap must be 'stationary' or 'circular'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha, "reps": self.reps,
            "block_size": self.block_size, "seed": self.seed,
            "min_periods": self.min_periods,
            "min_improvement": self.min_improvement,
            "bootstrap": self.bootstrap,
        }


@dataclass(frozen=True, slots=True)
class PeriodRecord:
    """One decision period with paired squared errors for incumbent/candidate."""

    date: str
    incumbent_error: float
    candidate_error: float

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.incumbent_error)) or self.incumbent_error < 0:
            raise ValueError("incumbent_error must be finite and >= 0")
        if not math.isfinite(float(self.candidate_error)) or self.candidate_error < 0:
            raise ValueError("candidate_error must be finite and >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "incumbent_error": self.incumbent_error,
            "candidate_error": self.candidate_error,
        }


@dataclass(frozen=True, slots=True)
class UpdateDecision:
    """Auditable promotion verdict for one candidate against one incumbent."""

    promote: bool
    mean_improvement: float
    one_sided_p_value: float
    ci_lower: float
    ci_upper: float
    periods: int
    reasons: tuple[str, ...]
    spec_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "promote": self.promote,
            "mean_improvement": self.mean_improvement,
            "one_sided_p_value": self.one_sided_p_value,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "periods": self.periods,
            "reasons": list(self.reasons),
            "spec_fingerprint": self.spec_fingerprint,
        }


def decide_update(
    records: Sequence[PeriodRecord],
    config: UpdateGateConfig | None = None,
    *,
    incumbent_version: str = "incumbent",
    candidate_version: str = "candidate",
) -> UpdateDecision:
    """Promote iff the paired improvement is both significant and positive.

    Improvement per period = incumbent_error - candidate_error (positive means
    the candidate is better). The null is recentred to zero improvement. The
    one-sided p-value and the lower CI bound must BOTH clear the bar; either one
    alone cannot promote. Returns a non-promoting decision (never raises) when
    there are too few periods, so a data-scarce update is conservative.
    """
    cfg = config or UpdateGateConfig()
    spec_fp = fingerprint({
        "config": cfg.to_dict(),
        "incumbent_version": incumbent_version,
        "candidate_version": candidate_version,
    })
    ordered = sorted(records, key=lambda r: r.date)
    if len(ordered) < cfg.min_periods:
        return UpdateDecision(
            promote=False, mean_improvement=float("nan"),
            one_sided_p_value=1.0, ci_lower=float("nan"), ci_upper=float("nan"),
            periods=len(ordered),
            reasons=(f"only {len(ordered)} periods < min_periods={cfg.min_periods}",),
            spec_fingerprint=spec_fp,
        )

    diff = np.asarray(
        [r.incumbent_error - r.candidate_error for r in ordered], dtype=float)
    n = len(diff)
    mean = float(diff.mean())
    paths = shared_time_paths(
        n, reps=cfg.reps, block_size=cfg.block_size, seed=cfg.seed,
        bootstrap=cfg.bootstrap, salt=UPDATE_GATE_PATH_SALT,
    )
    boot_means = diff[paths].mean(axis=1)
    # Null: candidate is no better. Recentre the bootstrap at zero improvement.
    centered = boot_means - mean
    p_value = float((1 + np.count_nonzero(centered >= mean)) / (cfg.reps + 1))
    ci_lower, ci_upper = (float(v) for v in np.quantile(boot_means, [cfg.alpha, 1 - cfg.alpha]))

    reasons: list[str] = []
    if mean <= cfg.min_improvement:
        reasons.append(f"mean improvement {mean:.6g} <= required {cfg.min_improvement:.6g}")
    if p_value > cfg.alpha:
        reasons.append(f"one-sided p={p_value:.4f} > alpha={cfg.alpha}")
    if ci_lower <= 0:
        reasons.append(f"CI lower bound {ci_lower:.6g} <= 0")
    promote = not reasons

    return UpdateDecision(
        promote=promote,
        mean_improvement=mean,
        one_sided_p_value=p_value,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        periods=n,
        reasons=tuple(reasons),
        spec_fingerprint=spec_fp,
    )
