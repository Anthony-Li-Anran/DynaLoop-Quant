"""Descriptive robustness measures for a frozen validation family.

These are the quantities the loop is actually judged by: stability of the
evaluation value, proxy bias and its amplification under a known injection,
selection noise and observed interval coverage. No significance language is
attached to any of them.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from dynaloop.statistical_uncertainty_engine.calibration import CalibrationResult
from dynaloop.statistical_uncertainty_engine.family import ValidationFamily
from dynaloop.statistical_uncertainty_engine.resampling import (
    BootstrapInterval,
    SelectionResult,
)


def _finite(values: Sequence[Any]) -> list[float]:
    return [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]


def sign_consistency(family: ValidationFamily) -> float | None:
    """Mean share of the dominant IC sign across rounds, per factor."""
    series: dict[str, list[float]] = {}
    for round_ in family.history:
        for factor_id, value in round_.items():
            if value is not None and math.isfinite(float(value)) and float(value) != 0:
                series.setdefault(factor_id, []).append(float(value))
    for evaluation in family.evaluations:
        value = evaluation.statistics.get("ic")
        if value is not None and math.isfinite(float(value)) and float(value) != 0:
            series.setdefault(evaluation.candidate.factor_id, []).append(float(value))
    shares = []
    for values in series.values():
        if len(values) < 2:
            continue
        positive = sum(value > 0 for value in values)
        shares.append(max(positive, len(values) - positive) / len(values))
    return float(sum(shares) / len(shares)) if shares else None


def descriptive_statistics(
    family: ValidationFamily,
    *,
    selection: SelectionResult,
    calibration: CalibrationResult,
    intervals: Sequence[BootstrapInterval],
    errors: Mapping[str, float],
) -> dict[str, Any]:
    """One flat, JSON-safe record of every measured quantity."""
    evaluations = family.evaluations
    ic = _finite([item.statistics.get("ic") for item in evaluations])
    rank_ic = _finite([item.statistics.get("rank_ic") for item in evaluations])
    observations = _finite([item.statistics.get("observations") for item in evaluations])
    error_values = _finite(list(errors.values()))
    feedback = family.feedback.to_dict() if family.feedback else {}

    result: dict[str, Any] = {
        "family_size": len(evaluations),
        "unique_factors": len({item.candidate.factor_id for item in evaluations}),
        "ic_mean": float(sum(ic) / len(ic)) if ic else None,
        "ic_median": float(sorted(ic)[len(ic) // 2]) if ic else None,
        "ic_std": float(_std(ic)) if len(ic) > 1 else None,
        "ic_positive_share": float(sum(v > 0 for v in ic) / len(ic)) if ic else None,
        "rank_ic_mean": float(sum(rank_ic) / len(rank_ic)) if rank_ic else None,
        "observations_min": int(min(observations)) if observations else None,
        "observations_max": int(max(observations)) if observations else None,
        "sign_consistency": sign_consistency(family),
        "proxy_error_mean": float(sum(error_values) / len(error_values)) if error_values else None,
        "proxy_error_max": float(max(abs(v) for v in error_values)) if error_values else None,
        "proxy_model_bias": feedback.get("model_bias"),
        "proxy_mean_absolute_error": feedback.get("mean_absolute_error"),
        "proxy_mean_uncertainty": feedback.get("mean_uncertainty"),
        "proxy_amplification": feedback.get("amplification"),
        "injected_bias": feedback.get("injected_bias"),
        "expected_bias": feedback.get("expected_bias"),
        "selection_applied": selection.applied,
        "rejected_count": selection.rejected_count,
        "rejected_share": (
            float(selection.rejected_count / len(evaluations))
            if selection.rejected_count is not None and evaluations else None
        ),
        "calibration_applied": calibration.applied,
        "calibration_quantile": calibration.quantile,
        "empirical_coverage": calibration.empirical_coverage,
        "intervals": {item.name: item.to_dict() for item in intervals},
    }
    return result


def _std(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))
