"""Statistical reports and the ⑥→① feedback edge.

The within-family selection embeds a real guarantee: block sign-flip +
max-statistic step-down controls the family-wise error rate (FWER) of the
simultaneous test (Romano-Wolf / Westfall-Young max-T), no iid assumption
required. Reliability itself remains a descriptive composite that aggregates
descriptive diagnostics together with that FWER-controlled selection result; it
is not a probability, a loop-level significance statement, or a coverage
guarantee (conformal coverage is deliberately not claimed). New directions name
the exploration choices that produced the weakest (least stable, most uncertain)
non-selected factors, so the next round can tilt the policy away from them
without touching any frozen object.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from dynaloop.research_engine.spec import fingerprint
from dynaloop.statistical_uncertainty_engine.calibration import CalibrationResult
from dynaloop.statistical_uncertainty_engine.family import ValidationFamily
from dynaloop.statistical_uncertainty_engine.resampling import (
    BootstrapInterval,
    SelectionResult,
)

FEEDBACK_SCHEMA_VERSION = 1

RELIABILITY_RULE = (
    "mean of available descriptive components: cross-round IC sign consistency, "
    "1/(1 + |proxy bias| + mean absolute proxy error), observed interval coverage, "
    "and family-wise selection share"
)


def reliability_score(robustness: dict[str, Any]) -> float:
    parts: list[float] = []
    for key in ("sign_consistency", "empirical_coverage", "rejected_share"):
        value = robustness.get(key)
        if value is not None and math.isfinite(float(value)):
            parts.append(min(1.0, max(0.0, float(value))))
    bias = robustness.get("proxy_model_bias")
    mae = robustness.get("proxy_mean_absolute_error")
    if bias is not None and mae is not None:
        penalty = abs(float(bias)) + abs(float(mae))
        parts.append(1.0 / (1.0 + penalty))
    return float(sum(parts) / len(parts)) if parts else 0.0


def build_flags(robustness: dict[str, Any], *, bias_threshold: float) -> tuple[str, ...]:
    flags: list[str] = []
    if not robustness.get("selection_applied"):
        flags.append("selection_unavailable")
    if not robustness.get("calibration_applied"):
        flags.append("calibration_unavailable")
    bias = robustness.get("proxy_model_bias")
    if bias is not None and abs(float(bias)) > bias_threshold:
        flags.append("bias_detected")
    coverage = robustness.get("empirical_coverage")
    if coverage is not None and float(coverage) < 0.5:
        flags.append("low_observed_coverage")
    return tuple(flags) or ("stable",)


def new_directions(
    family: ValidationFamily,
    selection: SelectionResult,
    *,
    limit: int,
) -> tuple[str, ...]:
    """Deterministic, weakest-first exploration keys (never frozen objects)."""
    if limit < 1:
        return ()
    choice_map = family.choice_map
    uncertainty = {
        item.factor_id: item.uncertainty for item in family.estimations
    }
    rejected = set(
        factor_id
        for factor_id, flag in zip(selection.factor_ids, selection.rejected or ())
        if flag
    )
    grouped: dict[str, list[tuple[float, float]]] = {}
    for evaluation in family.evaluations:
        factor_id = evaluation.candidate.factor_id
        choice = choice_map.get(factor_id)
        if choice is None or factor_id in rejected:
            continue
        value = evaluation.statistics.get("ic")
        ic = abs(float(value)) if value is not None and math.isfinite(float(value)) else 0.0
        unc = float(uncertainty.get(factor_id, 0.0))
        grouped.setdefault(choice, []).append((ic, unc))
    scored = [
        (
            sum(ic for ic, _ in rows) / len(rows),
            -sum(unc for _, unc in rows) / len(rows),
            choice,
        )
        for choice, rows in grouped.items()
    ]
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return tuple(choice for _, _, choice in scored[:limit])


@dataclass(frozen=True, slots=True)
class StatisticalReport:
    round_index: int
    family_id: str
    method_name: str
    selection: SelectionResult
    calibration: CalibrationResult
    intervals: tuple[BootstrapInterval, ...]
    robustness: dict[str, Any]
    reliability: float
    flags: tuple[str, ...]
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "round_index": self.round_index,
            "family_id": self.family_id,
            "method_name": self.method_name,
            "selection": self.selection.to_dict(),
            "calibration": self.calibration.to_dict(),
            "intervals": [item.to_dict() for item in self.intervals],
            "robustness": self.robustness,
            "reliability": self.reliability,
            "flags": list(self.flags),
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class StatisticalFeedback:
    """⑥ → ①: descriptive reliability and directions for the next round."""

    round_index: int
    reliability: float
    flags: tuple[str, ...]
    new_directions: tuple[str, ...]
    report_fingerprint: str
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "round_index": self.round_index,
            "reliability": self.reliability,
            "flags": list(self.flags),
            "new_directions": list(self.new_directions),
            "report_fingerprint": self.report_fingerprint,
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


def build_report(
    family: ValidationFamily,
    *,
    method_name: str,
    selection: SelectionResult,
    calibration: CalibrationResult,
    intervals: Sequence[BootstrapInterval],
    robustness: dict[str, Any],
    bias_threshold: float,
    method_spec: dict[str, Any],
) -> StatisticalReport:
    reliability = reliability_score(robustness)
    flags = build_flags(robustness, bias_threshold=bias_threshold)
    spec = {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "round_index": family.round_index,
        "family_id": family.family_id,
        "method": method_spec,
        "calibrator": calibration.spec,
        "reliability_rule": RELIABILITY_RULE,
        "reliability_is_descriptive": True,
        "within_family_fwer_control": bool(selection.spec.get("fwer_control_claimed", False)),
        "fwer_basis": selection.spec.get("fwer_basis", "no verified error-control guarantee"),
        "fdr_control_available": "BH-FDR baseline reference; its FDR guarantee "
        "requires iid / independent tests, which the adaptive loop violates, so "
        "FDR is NOT claimed here",
        "loop_level_sequential_significance": False,
        "coverage_guarantee": False,
        "coverage_guarantee_note": "no conformal (CP) coverage guarantee is "
        "claimed; CP is optional and disabled by default",
        "statistical_tool_selection": "replaceable method protocol; default is "
        "empirical step-down diagnostics, CP off",
    }
    return StatisticalReport(
        round_index=family.round_index,
        family_id=family.family_id,
        method_name=method_name,
        selection=selection,
        calibration=calibration,
        intervals=tuple(intervals),
        robustness=dict(robustness),
        reliability=reliability,
        flags=flags,
        spec=spec,
    )


def build_feedback(
    report: StatisticalReport,
    family: ValidationFamily,
    *,
    direction_limit: int,
) -> StatisticalFeedback:
    directions = new_directions(
        family, report.selection, limit=direction_limit
    )
    spec = {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "round_index": report.round_index,
        "report_fingerprint": report.fingerprint(),
        "direction_rule": "non-selected choice keys ordered by ascending mean |IC| "
        "then descending mean proxy uncertainty",
        "direction_limit": direction_limit,
        "descriptive_only": True,
        "does_not_update_frozen_objects": True,
    }
    return StatisticalFeedback(
        round_index=report.round_index,
        reliability=report.reliability,
        flags=report.flags,
        new_directions=directions,
        report_fingerprint=report.fingerprint(),
        spec=spec,
    )
