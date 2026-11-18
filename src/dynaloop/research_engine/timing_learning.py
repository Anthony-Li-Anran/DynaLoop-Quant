"""Learn a timing rule from search-period data, then certify it out-of-sample.

Authority (see docs/factor_research_foundations.md and the walk-forward sources
reviewed 2026-11-17): a trading threshold must be derived from the cost
assumption, not cherry-picked on a test set; the rule is learned with a
purged walk-forward over the search period; and the frozen shortlist is then
judged on a later historical window with the timing channel's search-robust
family test. Verification data never enters learning.

The unit of learning is a decision-time signal and its matured forward return.
A candidate rule predicts ``mu_on`` (the training mean return when the signal
clears the entry hurdle) while active and zero when flat. ``mu_on`` is estimated
from the portion of the search period BEFORE each walk-forward block, so no
block sees its own outcome -- that is the purge.

Only candidates whose terminal state is ``effective`` may become a frozen
``TimingRule``. This module produces certified candidates; the orchestrator
turns them into executable rules. It never reads a backtest result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from dynaloop.research_engine.channels import CHANNEL_TIMING, enforce_channel
from dynaloop.research_engine.effectiveness import (
    EffectivenessConfig,
    EffectivenessReport,
    EffectivenessRequest,
    FrozenCandidate,
    VerificationRow,
    assess_effectiveness,
    STATUS_EFFECTIVE,
)
from dynaloop.research_engine.spec import fingerprint


@dataclass(frozen=True, slots=True)
class TimingSample:
    """One matured decision: signal known at ``date``, return realised later."""

    date: str
    signal: float | None
    target: float

    def __post_init__(self) -> None:
        if not isinstance(self.date, str) or not self.date:
            raise ValueError("date must be a non-empty ISO date string")
        if not math.isfinite(float(self.target)):
            raise ValueError("target must be finite")


@dataclass(frozen=True, slots=True)
class TimingLearningConfig:
    """All free parameters of timing-rule learning and certification."""

    round_trip_cost: float
    entry_grid: tuple[float, ...]
    exit_fraction: float = 0.5
    walk_forward_blocks: int = 4
    min_block_samples: int = 6
    stability_fraction: float = 0.75
    top_m: int = 1
    min_train_samples: int = 12
    # Certification parameters (timing channel).
    cert_reps: int = 500
    cert_block_size: int = 3
    cert_alpha: float = 0.10
    cert_min_periods: int = 12
    cert_blocks: int = 4
    cert_seed: int = 7

    def __post_init__(self) -> None:
        if not math.isfinite(self.round_trip_cost) or self.round_trip_cost < 0:
            raise ValueError("round_trip_cost must be finite and >= 0")
        if not self.entry_grid:
            raise ValueError("entry_grid must be non-empty")
        if any((not math.isfinite(v)) for v in self.entry_grid):
            raise ValueError("entry_grid values must be finite")
        if any(v < self.round_trip_cost for v in self.entry_grid):
            raise ValueError("entry thresholds must clear the round-trip cost hurdle")
        if len(set(self.entry_grid)) != len(self.entry_grid):
            raise ValueError("entry_grid values must be unique")
        if not 0 <= self.exit_fraction <= 1:
            raise ValueError("exit_fraction must lie in [0, 1]")
        if self.walk_forward_blocks < 2 or self.min_block_samples < 2:
            raise ValueError("need >= 2 blocks of >= 2 samples")
        if not 0.5 <= self.stability_fraction <= 1.0:
            raise ValueError("stability_fraction must lie in [0.5, 1]")
        if self.top_m < 1:
            raise ValueError("top_m must be >= 1")
        if self.min_train_samples < self.walk_forward_blocks * self.min_block_samples:
            raise ValueError("min_train_samples cannot support the walk-forward blocks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_trip_cost": float(self.round_trip_cost),
            "entry_grid": [float(v) for v in self.entry_grid],
            "exit_fraction": float(self.exit_fraction),
            "walk_forward_blocks": self.walk_forward_blocks,
            "min_block_samples": self.min_block_samples,
            "stability_fraction": float(self.stability_fraction),
            "top_m": self.top_m,
            "min_train_samples": self.min_train_samples,
            "certification": {
                "reps": self.cert_reps, "block_size": self.cert_block_size,
                "alpha": self.cert_alpha, "min_periods": self.cert_min_periods,
                "blocks": self.cert_blocks, "seed": self.cert_seed,
            },
        }


@dataclass(frozen=True, slots=True)
class TimingCandidate:
    """A search-period-learned threshold pair with its frozen mu_on estimate."""

    rule_id: str
    entry_threshold: float
    exit_threshold: float
    mu_on: float
    train_mean_improvement: float
    positive_blocks: int
    total_blocks: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "mu_on": self.mu_on,
            "train_mean_improvement": self.train_mean_improvement,
            "positive_blocks": self.positive_blocks,
            "total_blocks": self.total_blocks,
        }


def _finite_signal(sample: TimingSample) -> bool:
    return sample.signal is not None and math.isfinite(float(sample.signal))


def _active(sample: TimingSample, entry: float) -> bool:
    return _finite_signal(sample) and float(sample.signal) >= entry


def _mu_on(samples: Sequence[TimingSample], entry: float) -> float | None:
    values = [s.target for s in samples if _active(s, entry)]
    return float(sum(values) / len(values)) if values else None


def _differential(target: float, prediction: float, global_mean: float) -> float:
    """Beat BOTH the zero forecast and the trailing historical mean."""
    loss = (prediction - target) ** 2
    return min(target ** 2, (global_mean - target) ** 2) - loss


def _blocks(samples: Sequence[TimingSample], n_blocks: int) -> list[list[TimingSample]]:
    n = len(samples)
    edges = [round(i * n / n_blocks) for i in range(n_blocks + 1)]
    return [list(samples[edges[i]:edges[i + 1]]) for i in range(n_blocks)]


def learn_timing_candidates(
    samples: Sequence[TimingSample],
    config: TimingLearningConfig,
    *,
    cutoff: str,
) -> tuple[TimingCandidate, ...]:
    """Learn and freeze a shortlist using ONLY samples dated <= cutoff."""
    search = sorted(
        (s for s in samples if s.date <= cutoff),
        key=lambda s: (s.date, float(s.signal) if _finite_signal(s) else math.inf),
    )
    if len(search) < config.min_train_samples:
        raise ValueError(
            f"search period has {len(search)} samples, need {config.min_train_samples}")
    blocks = _blocks(search, config.walk_forward_blocks)
    if any(len(b) < config.min_block_samples for b in blocks):
        raise ValueError("a walk-forward block has too few samples")
    global_mean = float(sum(s.target for s in search) / len(search))
    required = int(math.ceil(config.stability_fraction * len(blocks)))

    learned: list[TimingCandidate] = []
    for entry in config.entry_grid:
        exit_t = entry * config.exit_fraction
        block_improvements: list[float] = []
        mu_history: list[TimingSample] = []
        for block in blocks:
            # Estimate mu_on strictly from samples before this block (purged).
            mu = _mu_on(mu_history, entry)
            if mu is None:
                mu = 0.0
            improvements = [_differential(s.target, mu if _active(s, entry) else 0.0,
                                          global_mean) for s in block]
            block_improvements.append(float(sum(improvements) / len(improvements)))
            mu_history.extend(block)
        positive = sum(v > 0 for v in block_improvements)
        if positive < required:
            continue
        final_mu = _mu_on(search, entry)
        if final_mu is None:
            continue
        mean_improvement = float(sum(block_improvements) / len(block_improvements))
        rule_id = fingerprint({
            "entry": float(entry), "exit": float(exit_t), "mu_on": float(final_mu),
            "cutoff": cutoff, "config": config.to_dict(),
        })
        learned.append(TimingCandidate(
            rule_id=rule_id,
            entry_threshold=float(entry),
            exit_threshold=float(exit_t),
            mu_on=float(final_mu),
            train_mean_improvement=mean_improvement,
            positive_blocks=positive,
            total_blocks=len(blocks),
        ))
    if not learned:
        return ()
    learned.sort(key=lambda c: (-c.train_mean_improvement, c.rule_id))
    shortlist = learned[:config.top_m]
    return tuple(sorted(shortlist, key=lambda c: c.rule_id))


def verification_rows(
    candidates: Sequence[TimingCandidate],
    samples: Sequence[TimingSample],
    *,
    cutoff: str,
    verification_start: str,
    search_mean: float,
) -> tuple[VerificationRow, ...]:
    """Build out-of-sample rows; no learning happens here."""
    verify = sorted(
        (s for s in samples if s.date > cutoff and s.date >= verification_start),
        key=lambda s: s.date,
    )
    grid = [s.date for s in verify]
    if len(grid) != len(set(grid)):
        raise ValueError("duplicate verification dates")
    rows: list[VerificationRow] = []
    for c in candidates:
        for s in verify:
            prediction = c.mu_on if _active(s, c.entry_threshold) else 0.0
            rows.append(VerificationRow(
                factor_id=c.rule_id,
                date=s.date,
                target=float(s.target),
                prediction=float(prediction),
                baseline_zero_error=float(s.target) ** 2,
                baseline_mean_error=(float(search_mean) - float(s.target)) ** 2,
            ))
    return tuple(rows)


def certify_timing(
    candidates: Sequence[TimingCandidate],
    samples: Sequence[TimingSample],
    config: TimingLearningConfig,
    *,
    cutoff: str,
    verification_start: str,
    search_mean: float,
) -> tuple[EffectivenessReport, tuple[str, ...]]:
    """Certify the frozen shortlist on later data. Returns (report, effective ids)."""
    if not candidates:
        raise ValueError("no frozen timing candidates to certify")
    if not verification_start > cutoff:
        raise ValueError("verification_start must be strictly after cutoff")
    frozen = tuple(FrozenCandidate(
        factor_id=c.rule_id,
        expression=f"timing(entry={c.entry_threshold},exit={c.exit_threshold})",
        symbol="", frozen_at=cutoff,
        metadata=c.to_dict(),
    ) for c in candidates)
    enforce_channel(CHANNEL_TIMING, frozen)
    rows = verification_rows(
        candidates, samples, cutoff=cutoff,
        verification_start=verification_start, search_mean=search_mean,
    )
    cert_cfg = EffectivenessConfig(
        reps=config.cert_reps, block_size=config.cert_block_size,
        alpha=config.cert_alpha, min_periods=config.cert_min_periods,
        blocks=config.cert_blocks, min_block_periods=2,
        seed=config.cert_seed,
    )
    request = EffectivenessRequest(
        candidates=frozen, rows=rows, cutoff=cutoff,
        verification_start=verification_start, config=cert_cfg,
        provenance={"stage": "timing_rule_certification", "channel": CHANNEL_TIMING},
    )
    report = assess_effectiveness(request)
    effective = tuple(
        v.factor_id for v in report.candidates if v.status == STATUS_EFFECTIVE)
    return report, effective


def search_mean(samples: Sequence[TimingSample], *, cutoff: str) -> float:
    """Search-period mean target, the trailing-history baseline constant."""
    values = [s.target for s in samples if s.date <= cutoff]
    if not values:
        raise ValueError("no search-period samples for the baseline")
    return float(sum(values) / len(values))
