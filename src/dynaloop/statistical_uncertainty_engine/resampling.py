"""Empirical block sign-flip diagnostics and descriptive bootstrap intervals.

Shared block signs and max-statistic step-down implement the joint resampling
calculation. Valid FWER control additionally needs a justified null symmetry,
valid intersection tests and accounting for adaptive candidate selection.
Those conditions are not verified here: neither per-family nor sequential
error control is claimed. IID resampling across dependent candidate rewards
is descriptive, as are intervals calibrated and assessed on the same family.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd
from arch.bootstrap import IIDBootstrap

from dynaloop.statistical_uncertainty_engine.family import ValidationFamily
from dynaloop.research_engine import FactorFrame

UNCERTAINTY_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class ResamplingConfig:
    """All free parameters of the default uncertainty method."""

    reps: int = 300
    block_size: int = 5
    alpha: float = 0.1
    seed: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.reps, int) or self.reps < 20:
            raise ValueError("reps must be an integer >= 20.")
        if not isinstance(self.block_size, int) or self.block_size < 1:
            raise ValueError("block_size must be a positive integer.")
        if not 0 < float(self.alpha) < 1:
            raise ValueError("alpha must lie in (0, 1).")

    def rng(self, round_index: int, salt: int = 0) -> np.random.Generator:
        return np.random.default_rng(
            np.random.SeedSequence([int(self.seed), round_index, salt])
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": UNCERTAINTY_SCHEMA_VERSION,
            "reps": self.reps,
            "block_size": self.block_size,
            "alpha": self.alpha,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    """Descriptive interval; ``applied=False`` means no interval was made."""

    name: str
    point: float | None
    lower: float | None
    upper: float | None
    std: float | None
    samples: int
    applied: bool
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "point": self.point,
            "lower": self.lower,
            "upper": self.upper,
            "std": self.std,
            "samples": self.samples,
            "applied": self.applied,
            "spec": self.spec,
        }


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Family-wise empirical p values from a joint block sign-flip null."""

    factor_ids: tuple[str, ...]
    observed_statistics: tuple[float | None, ...]
    p_values: tuple[float, ...] | None
    rejected: tuple[bool, ...] | None
    applied: bool
    spec: dict[str, Any]

    @property
    def rejected_count(self) -> int | None:
        return sum(self.rejected) if self.rejected is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_ids": list(self.factor_ids),
            "observed_statistics": list(self.observed_statistics),
            "p_values": list(self.p_values) if self.p_values is not None else None,
            "rejected": list(self.rejected) if self.rejected is not None else None,
            "rejected_count": self.rejected_count,
            "applied": self.applied,
            "spec": self.spec,
        }


def bootstrap_interval(
    values: Sequence[float],
    *,
    name: str,
    config: ResamplingConfig,
    round_index: int,
    salt: int = 0,
) -> BootstrapInterval:
    """IID bootstrap interval for a cross-sectional batch quantity."""
    clean = np.asarray(
        [float(value) for value in values if value is not None and math.isfinite(float(value))],
        dtype=float,
    )
    base: dict[str, Any] = {
        "method": "arch.bootstrap.IIDBootstrap",
        "statistic": "np.mean",
        "config": config.to_dict(),
        "round_index": round_index,
        "salt": salt,
        "dependence": "cross-sectional factors can be dependent; IID draws ignore that dependence",
        "interval_kind": "descriptive IID bootstrap interval",
        "descriptive_only": True,
        "coverage_guarantee": False,
    }
    if clean.size == 0:
        return BootstrapInterval(name, None, None, None, None, 0, False, base)
    point = float(np.mean(clean))
    if clean.size == 1:
        return BootstrapInterval(
            name, point, point, point, 0.0, 1, True,
            {**base, "degenerate": "single observation"},
        )
    boot = IIDBootstrap(clean, seed=config.rng(round_index, salt))
    draws = np.asarray(boot.apply(np.mean, reps=config.reps)).reshape(-1)
    lower, upper = np.percentile(
        draws, [100 * config.alpha / 2, 100 * (1 - config.alpha / 2)]
    )
    return BootstrapInterval(
        name=name,
        point=point,
        lower=float(lower),
        upper=float(upper),
        std=float(np.std(draws, ddof=1)),
        samples=int(clean.size),
        applied=True,
        spec={**base, "draws": int(draws.size)},
    )


def _forward_returns(records: Sequence[Any], horizon: int = 1) -> np.ndarray:
    close = pd.Series([row.get("close") for row in records], dtype="float64")
    return (close.shift(-horizon) / close - 1.0).to_numpy(dtype=float)


def selection_stepdown(
    family: ValidationFamily,
    config: ResamplingConfig,
) -> SelectionResult:
    """Family-wise empirical p values using a joint block sign-flip null.

    The observed statistic is the stage-1 IC. Every factor uses the same
    block signs in each replicate. Step-down maxima range over the remaining
    hypotheses and adjusted p values are monotone in observed rank.
    These empirical p values are diagnostic: sign invariance and validity
    after adaptive candidate selection are not established by this code.
    """
    factor_ids = tuple(item.candidate.factor_id for item in family.evaluations)
    observed = tuple(
        None if value is None or not math.isfinite(float(value))
        else abs(float(value))
        for value in (item.statistics.get("ic") for item in family.evaluations)
    )
    base: dict[str, Any] = {
        "method": "block_sign_flip_max_statistic_stepdown",
        "reference": "Westfall-Young / Romano-Wolf max-T family-wise error control",
        "config": config.to_dict(),
        "round_index": family.round_index,
        "statistic": "abs(stage1 IC)",
        "null": "block sign-flip on factor values, forward return unchanged",
        "assumptions": [
            "joint null distribution must be invariant under the chosen block sign flips",
            "candidate selection must be independent of validation or explicitly accounted for",
            "shared signs alone do not establish validity under arbitrary serial dependence",
        ],
        "fwer_control_claimed": False,
        "descriptive_only": True,
        "fwer_basis": "max-statistic step-down reference; assumptions not verified",
        "loop_level_sequential_guarantee": False,
        "adaptive_rounds_note": "reuse of a frozen window for selection and validation "
        "does not establish within-family or sequential error control",
    }
    if not family.records:
        return SelectionResult(
            factor_ids, observed, None, None, False,
            {**base, "applied": False, "missing": "frozen bar records"},
        )

    first = family.evaluations[0]
    timestamp_col = first.spec.get("timestamp_col", "date")
    records_by_time = {str(row.get(timestamp_col)): row for row in family.records}
    timestamps = first.values.timestamps
    if len(records_by_time) != len(family.records) or set(records_by_time) != set(timestamps):
        return SelectionResult(
            factor_ids, observed, None, None, False,
            {**base, "applied": False, "missing": "factor/forward timestamp alignment"},
        )
    ordered_records = [records_by_time[timestamp] for timestamp in timestamps]
    expected_data = first.spec.get("data", {})
    actual_frame = FactorFrame(ordered_records, timestamp_col=timestamp_col, columns=expected_data.get("columns"))
    if actual_frame.fingerprint() != expected_data.get("fingerprint"):
        return SelectionResult(
            factor_ids, observed, None, None, False,
            {**base, "applied": False, "missing": "frozen data fingerprint alignment"},
        )
    series: list[np.ndarray] = []
    forwards: list[np.ndarray] = []
    for evaluation in family.evaluations:
        values = np.asarray(evaluation.values.values, dtype=float)
        if evaluation.values.timestamps != timestamps or values.size != len(timestamps):
            return SelectionResult(
                factor_ids, observed, None, None, False,
                {**base, "applied": False,
                 "missing": "factor/forward alignment",
                 "factor_length": int(values.size),
                 "records_length": len(timestamps)},
            )
        series.append(values)
        forwards.append(_forward_returns(ordered_records, evaluation.policy.ic_horizon))

    rng = config.rng(family.round_index, salt=1)
    n = len(timestamps)
    blocks = int(math.ceil(n / config.block_size))
    signs = rng.choice(np.array([-1.0, 1.0]), size=(config.reps, blocks))
    flips = np.repeat(signs, config.block_size, axis=1)[:, :n]
    null_abs = np.zeros((config.reps, len(series)), dtype=float)
    for position, values in enumerate(series):
        flipped = pd.DataFrame((values[None, :] * flips).T)
        forward_series = pd.Series(forwards[position])
        null_ic = flipped.corrwith(forward_series, axis=0, method="pearson")
        null_abs[:, position] = np.abs(np.nan_to_num(
            null_ic.to_numpy(dtype=float), nan=0.0, posinf=0.0, neginf=0.0
        ))

    null_max = np.max(np.abs(null_abs), axis=1)
    order = sorted(range(len(observed)), key=lambda i: -(observed[i] if observed[i] is not None else -1.0))
    adjusted = [1.0] * len(observed)
    previous = 0.0
    for rank, position in enumerate(order):
        value = observed[position]
        if value is None:
            continue
        remaining_max = null_abs[:, order[rank:]].max(axis=1)
        raw = float((1 + np.count_nonzero(remaining_max >= value)) / (config.reps + 1))
        previous = max(previous, raw)
        adjusted[position] = previous
    p_values = tuple(adjusted)
    rejected = tuple(value <= config.alpha for value in p_values)
    quantiles = np.quantile(null_max, [0.5, 0.9, 0.95, 0.99])
    return SelectionResult(
        factor_ids=factor_ids,
        observed_statistics=observed,
        p_values=p_values,
        rejected=rejected,
        applied=True,
        spec={
            **base,
            "applied": True,
            "replicates": config.reps,
            "blocks": blocks,
            "shared_signs": True,
            "stepdown_order": [factor_ids[i] for i in order],
            "horizons": [item.policy.ic_horizon for item in family.evaluations],
            "null_max_quantiles": {
                str(level): float(value)
                for level, value in zip(("0.5", "0.9", "0.95", "0.99"), quantiles)
            },
        },
    )


def resampling_library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in ("numpy", "pandas", "arch", "scipy", "statsmodels"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", None)
        except ImportError:
            versions[name] = None
    return versions
