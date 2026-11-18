"""Statistical & Uncertainty engine: replaceable methods, one default.

The default method is chosen for this system: block resampling for serially
correlated per-bar data and a max-statistic step-down for family-wise
selection noise. An independent-iid baseline (statsmodels ``multipletests``)
is kept only as a comparison method; its assumptions are known to fail here,
so it is never the default and never the verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from dynaloop.statistical_uncertainty_engine.calibration import (
    CalibrationConfig,
    CalibrationMethod,
    build_calibrator,
)
from dynaloop.statistical_uncertainty_engine.family import (
    STATISTICAL_SCHEMA_VERSION,
    ValidationFamily,
)
from dynaloop.statistical_uncertainty_engine.feedback import (
    StatisticalFeedback,
    StatisticalReport,
    build_feedback,
    build_report,
)
from dynaloop.statistical_uncertainty_engine.resampling import (
    BootstrapInterval,
    ResamplingConfig,
    SelectionResult,
    bootstrap_interval,
    resampling_library_versions,
    selection_stepdown,
)
from dynaloop.statistical_uncertainty_engine.robustness import (
    descriptive_statistics,
)
from dynaloop.training_engine import RewardSpec, factor_reward


@dataclass(frozen=True, slots=True)
class StatisticalConfig:
    resampling: ResamplingConfig = field(default_factory=ResamplingConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    calibrator: str = "empirical_residual"
    bias_threshold: float = 0.01
    direction_limit: int = 3

    def __post_init__(self) -> None:
        if not 0 <= float(self.bias_threshold) < 1:
            raise ValueError("bias_threshold must lie in [0, 1).")
        if not isinstance(self.direction_limit, int) or self.direction_limit < 0:
            raise ValueError("direction_limit must be a non-negative integer.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATISTICAL_SCHEMA_VERSION,
            "resampling": self.resampling.to_dict(),
            "calibration": self.calibration.to_dict(),
            "calibrator": self.calibrator,
            "bias_threshold": self.bias_threshold,
            "direction_limit": self.direction_limit,
        }


@runtime_checkable
class UncertaintyMethod(Protocol):
    name: str

    def spec(self) -> dict[str, Any]: ...

    def evaluate(
        self, family: ValidationFamily, config: ResamplingConfig
    ) -> SelectionResult: ...


class BlockResamplingMethod:
    """Default: sequence-aware family-wise selection."""

    name = "block_sign_flip_stepdown"

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": "default method",
            "selection": "block sign-flip null + max-statistic step-down",
            "uncertainty": "arch IID bootstrap for cross-sectional batch quantities",
            "why": "per-bar factor values are serially correlated and factors "
            "are evaluated as a family over a reused frozen window",
            "assumptions_valid_in_adaptive_loop": False,
        }

    def evaluate(
        self, family: ValidationFamily, config: ResamplingConfig
    ) -> SelectionResult:
        return selection_stepdown(family, config)


class IndependentBaselineMethod:
    """Comparison only: iid-normal t approximation + statsmodels BH-FDR."""

    name = "independent_bh_baseline"

    def __init__(self, method: str = "fdr_bh") -> None:
        if method not in ("fdr_bh", "bonferroni", "holm"):
            raise ValueError(f"Unsupported baseline correction '{method}'.")
        self.method = method

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": "comparison only, not the verdict",
            "p_values": "two-sided t approximation of a Pearson IC",
            "correction": f"statsmodels.stats.multitest.multipletests({self.method})",
            "fdr_control": "BH-FDR controls FDR under independence / positive "
                           "regression dependence; Bonferroni/Holm control FWER",
            "assumptions": "iid normal observations, independent tests",
            "assumptions_valid_in_adaptive_loop": False,
            "note": "financial IC is serially correlated and rounds reuse one "
            "frozen window; BH-FDR's FDR guarantee therefore does NOT hold here, "
            "kept to expose the gap, not to decide reliability",
        }

    def evaluate(
        self, family: ValidationFamily, config: ResamplingConfig
    ) -> SelectionResult:
        from scipy import stats as scipy_stats
        from statsmodels.stats.multitest import multipletests

        factor_ids = tuple(item.candidate.factor_id for item in family.evaluations)
        observed: list[float | None] = []
        raw: list[float] = []
        for evaluation in family.evaluations:
            ic = evaluation.statistics.get("ic")
            count = int(evaluation.statistics.get("observations") or 0)
            if ic is None or not math.isfinite(float(ic)) or abs(float(ic)) > 1 or count < 3:
                observed.append(None)
                raw.append(1.0)
                continue
            value = abs(float(ic))
            observed.append(value)
            if value == 1.0:
                raw.append(0.0)
                continue
            statistic = value * math.sqrt((count - 2) / (1 - value * value))
            raw.append(float(min(1.0, 2 * scipy_stats.t.sf(statistic, count - 2))))
        reject, corrected, _, bonferroni = multipletests(
            raw, alpha=config.alpha, method=self.method
        )
        return SelectionResult(
            factor_ids=factor_ids,
            observed_statistics=tuple(observed),
            p_values=tuple(float(value) for value in corrected),
            rejected=tuple(bool(value) for value in reject),
            applied=True,
            spec={
                **self.spec(),
                "alpha": config.alpha,
                "raw_p_values": raw,
                "alphac_bonferroni": float(bonferroni),
                "descriptive_only": False,
                "guarantee_claimed": "BH-FDR controls FDR under independence / PRDS, "
                "but those assumptions are violated in the adaptive loop, so FDR "
                "control is NOT claimed here; reference method only",
            },
        )


DEFAULT_METHOD: UncertaintyMethod = BlockResamplingMethod()
UNCERTAINTY_METHODS: dict[str, UncertaintyMethod] = {
    DEFAULT_METHOD.name: DEFAULT_METHOD,
}


def build_method(name: str = "block_sign_flip_stepdown", **kwargs: Any) -> UncertaintyMethod:
    if name == "independent_bh_baseline":
        return IndependentBaselineMethod(**kwargs)
    try:
        return UNCERTAINTY_METHODS[name]
    except KeyError as error:
        raise ValueError(f"Unknown uncertainty method '{name}'.") from error


class StatisticalEngine:
    """⑥ Statistical Validation: family -> report -> feedback to ①."""

    def __init__(
        self,
        *,
        config: StatisticalConfig | None = None,
        method: UncertaintyMethod | None = None,
        calibrator: CalibrationMethod | None = None,
    ) -> None:
        self.config = config or StatisticalConfig()
        self.method: UncertaintyMethod = method or DEFAULT_METHOD
        self.calibrator: CalibrationMethod = calibrator or build_calibrator(
            self.config.calibrator
        )

    def spec(self) -> dict[str, Any]:
        return {
            **self.config.to_dict(),
            "method": self.method.spec(),
            "calibrator": self.calibrator.spec(),
            "library_versions": resampling_library_versions(),
        }

    @staticmethod
    def _proxy_observation(
        family: ValidationFamily,
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        """Points, residuals and observed rewards, all on the reward scale."""
        reward_spec = family.reward_spec
        observed = {
            item.candidate.factor_id: float(factor_reward(item, reward_spec))
            for item in family.evaluations
        }
        points = {
            item.factor_id: float(item.reward) for item in family.estimations
        }
        residuals = {
            factor_id: points[factor_id] - observed[factor_id]
            for factor_id in points
            if factor_id in observed
        }
        return points, residuals, observed

    def validate(self, family: ValidationFamily) -> StatisticalReport:
        config = self.config
        points, errors, observed = self._proxy_observation(family)
        selection = self.method.evaluate(family, config.resampling)
        intervals: tuple[BootstrapInterval, ...] = (
            bootstrap_interval(
                [item.statistics.get("ic") for item in family.evaluations],
                name="ic_mean",
                config=config.resampling,
                round_index=family.round_index,
                salt=2,
            ),
            bootstrap_interval(
                list(errors.values()),
                name="proxy_error",
                config=config.resampling,
                round_index=family.round_index,
                salt=3,
            ),
            bootstrap_interval(
                [item.uncertainty for item in family.estimations],
                name="proxy_uncertainty",
                config=config.resampling,
                round_index=family.round_index,
                salt=4,
            ),
        )
        calibration = self.calibrator.calibrate(
            points, list(errors.values()), observed, config.calibration
        )
        robustness = descriptive_statistics(
            family,
            selection=selection,
            calibration=calibration,
            intervals=intervals,
            errors=errors,
        )
        return build_report(
            family,
            method_name=self.method.name,
            selection=selection,
            calibration=calibration,
            intervals=intervals,
            robustness=robustness,
            bias_threshold=config.bias_threshold,
            method_spec=self.spec(),
        )

    def feedback(
        self, report: StatisticalReport, family: ValidationFamily
    ) -> StatisticalFeedback:
        return build_feedback(
            report, family, direction_limit=self.config.direction_limit
        )
