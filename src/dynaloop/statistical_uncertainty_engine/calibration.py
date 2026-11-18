"""Optional residual calibration, deliberately not the main uncertainty path.

Conformal prediction (CP) is a poor default here: its exchangeability
assumption is broken by an adaptive loop that reuses one frozen window and
updates its own policy. It is kept as one replaceable method for comparison,
never enabled by default and never used to claim a coverage guarantee.

The default method is a plain empirical residual quantile: it produces a
descriptive interval and reports the observed coverage, nothing more.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from dynaloop.statistical_uncertainty_engine.resampling import (
    resampling_library_versions,
)

CALIBRATION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    alpha: float = 0.1

    def __post_init__(self) -> None:
        if not 0 < float(self.alpha) < 1:
            raise ValueError("alpha must lie in (0, 1).")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": CALIBRATION_SCHEMA_VERSION, "alpha": self.alpha}


@dataclass(frozen=True, slots=True)
class CalibrationInterval:
    factor_id: str
    point: float
    lower: float | None
    upper: float | None
    observed: float | None

    def covers(self) -> bool | None:
        if self.observed is None or self.lower is None or self.upper is None:
            return None
        return self.lower <= self.observed <= self.upper

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "point": self.point,
            "lower": self.lower,
            "upper": self.upper,
            "observed": self.observed,
            "covers": self.covers(),
        }


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    name: str
    quantile: float | None
    intervals: tuple[CalibrationInterval, ...]
    empirical_coverage: float | None
    applied: bool
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "quantile": self.quantile,
            "intervals": [item.to_dict() for item in self.intervals],
            "empirical_coverage": self.empirical_coverage,
            "applied": self.applied,
            "spec": self.spec,
        }


@runtime_checkable
class CalibrationMethod(Protocol):
    name: str

    def spec(self) -> dict[str, Any]: ...

    def calibrate(
        self,
        points: Mapping[str, float],
        residuals: Sequence[float],
        observed: Mapping[str, float],
        config: CalibrationConfig,
    ) -> CalibrationResult: ...


def _clean_residuals(residuals: Sequence[float]) -> np.ndarray:
    return np.asarray(
        [
            abs(float(value))
            for value in residuals
            if value is not None and math.isfinite(float(value))
        ],
        dtype=float,
    )


def _build(
    *,
    name: str,
    points: Mapping[str, float],
    residuals: Sequence[float],
    observed: Mapping[str, float],
    config: CalibrationConfig,
    quantile_level: float,
    spec: dict[str, Any],
) -> CalibrationResult:
    clean = _clean_residuals(residuals)
    common = {
        "method": name,
        "config": config.to_dict(),
        "quantile_level": quantile_level,
        "n_calibration": int(clean.size),
        "coverage_guarantee": False,
        "descriptive_only": True,
        "library_versions": resampling_library_versions(),
        **spec,
    }
    if clean.size == 0:
        return CalibrationResult(name, None, (), None, False, {**common, "applied": False})
    quantile = float(np.quantile(clean, quantile_level, method="higher"))
    intervals = tuple(
        CalibrationInterval(
            factor_id=factor_id,
            point=float(point),
            lower=float(point - quantile),
            upper=float(point + quantile),
            observed=(
                float(observed[factor_id])
                if factor_id in observed and math.isfinite(float(observed[factor_id]))
                else None
            ),
        )
        for factor_id, point in sorted(points.items())
    )
    covered = [item.covers() for item in intervals if item.covers() is not None]
    coverage = float(sum(covered) / len(covered)) if covered else None
    return CalibrationResult(
        name=name,
        quantile=quantile,
        intervals=intervals,
        empirical_coverage=coverage,
        applied=True,
        spec={**common, "applied": True, "intervals": len(intervals)},
    )


class EmpiricalResidualCalibrator:
    """Default: descriptive empirical quantile of absolute proxy residuals."""

    name = "empirical_residual"

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": "default descriptive calibration",
            "exchangeability_assumed": False,
            "finite_sample_correction": False,
            "note": "reports observed coverage only; no CP coverage claim",
        }

    def calibrate(
        self,
        points: Mapping[str, float],
        residuals: Sequence[float],
        observed: Mapping[str, float],
        config: CalibrationConfig,
    ) -> CalibrationResult:
        return _build(
            name=self.name,
            points=points,
            residuals=residuals,
            observed=observed,
            config=config,
            quantile_level=1.0 - config.alpha,
            spec=self.spec(),
        )


class SplitConformalCalibrator:
    """Optional comparison method; CP is not the default in this system.

    Uses the MAPIE v0.9.1 finite-sample level
    ``((n + 1) * (1 - alpha)) / n`` with ``method="higher"``. Exchangeability
    is assumed by CP but violated by an adaptive loop, so no coverage
    guarantee is claimed.
    """

    name = "split_conformal"

    def __init__(self, *, claim_exchangeability: bool = False) -> None:
        self.claim_exchangeability = bool(claim_exchangeability)

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": "optional comparison, not enabled by default",
            "exchangeability_assumed": self.claim_exchangeability,
            "exchangeability_valid_in_adaptive_loop": False,
            "finite_sample_correction": True,
            "quantile_reference": "MAPIE v0.9.1 mapie.utils.compute_quantiles",
            "note": "adaptive policy updates reuse one frozen window; "
            "CP exchangeability fails, so no coverage guarantee is claimed",
        }

    def calibrate(
        self,
        points: Mapping[str, float],
        residuals: Sequence[float],
        observed: Mapping[str, float],
        config: CalibrationConfig,
    ) -> CalibrationResult:
        clean = _clean_residuals(residuals)
        n = int(clean.size)
        level = min(1.0, ((n + 1) * (1.0 - config.alpha)) / n) if n else 1.0
        return _build(
            name=self.name,
            points=points,
            residuals=residuals,
            observed=observed,
            config=config,
            quantile_level=level,
            spec=self.spec(),
        )


DEFAULT_CALIBRATOR: CalibrationMethod = EmpiricalResidualCalibrator()
CALIBRATORS: dict[str, CalibrationMethod] = {
    DEFAULT_CALIBRATOR.name: DEFAULT_CALIBRATOR,
    "split_conformal": SplitConformalCalibrator(),
}


def build_calibrator(name: str = "empirical_residual") -> CalibrationMethod:
    try:
        return CALIBRATORS[name]
    except KeyError as error:
        raise ValueError(f"Unknown calibration method '{name}'.") from error
