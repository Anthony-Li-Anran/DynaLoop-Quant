"""Statistical & Uncertainty: sequence-aware FWER/FDR-controlled validation.

The default selection step (block sign-flip + max-statistic step-down) controls
the family-wise error rate (FWER) of the simultaneous test without an iid
assumption, so a real multiple-testing guarantee is claimed. Conformal coverage
(CP) is deliberately not claimed and is disabled by default; the cross-sectional
bootstrap interval is a plain confidence interval. The loop-level reliability
composite stays descriptive because reusing one frozen window across adaptive
rounds is not a sequential guarantee.
"""

from dynaloop.statistical_uncertainty_engine.calibration import (
    CALIBRATORS,
    CALIBRATION_SCHEMA_VERSION,
    DEFAULT_CALIBRATOR,
    CalibrationConfig,
    CalibrationInterval,
    CalibrationMethod,
    CalibrationResult,
    EmpiricalResidualCalibrator,
    SplitConformalCalibrator,
    build_calibrator,
)
from dynaloop.statistical_uncertainty_engine.engine import (
    UNCERTAINTY_METHODS,
    DEFAULT_METHOD,
    BlockResamplingMethod,
    IndependentBaselineMethod,
    StatisticalConfig,
    StatisticalEngine,
    UncertaintyMethod,
    build_method,
)
from dynaloop.statistical_uncertainty_engine.family import (
    STATISTICAL_SCHEMA_VERSION,
    StatisticalError,
    ValidationFamily,
    build_family,
)
from dynaloop.statistical_uncertainty_engine.feedback import (
    FEEDBACK_SCHEMA_VERSION,
    RELIABILITY_RULE,
    StatisticalFeedback,
    StatisticalReport,
    build_flags,
    build_feedback,
    build_report,
    new_directions,
    reliability_score,
)
from dynaloop.statistical_uncertainty_engine.resampling import (
    UNCERTAINTY_SCHEMA_VERSION,
    BootstrapInterval,
    ResamplingConfig,
    SelectionResult,
    bootstrap_interval,
    resampling_library_versions,
    selection_stepdown,
)
from dynaloop.statistical_uncertainty_engine.robustness import (
    descriptive_statistics,
    sign_consistency,
)

__all__ = [
    "CALIBRATORS",
    "CALIBRATION_SCHEMA_VERSION",
    "DEFAULT_CALIBRATOR",
    "DEFAULT_METHOD",
    "FEEDBACK_SCHEMA_VERSION",
    "RELIABILITY_RULE",
    "STATISTICAL_SCHEMA_VERSION",
    "UNCERTAINTY_METHODS",
    "UNCERTAINTY_SCHEMA_VERSION",
    "BlockResamplingMethod",
    "BootstrapInterval",
    "CalibrationConfig",
    "CalibrationInterval",
    "CalibrationMethod",
    "CalibrationResult",
    "EmpiricalResidualCalibrator",
    "IndependentBaselineMethod",
    "ResamplingConfig",
    "SelectionResult",
    "SplitConformalCalibrator",
    "StatisticalConfig",
    "StatisticalEngine",
    "StatisticalError",
    "StatisticalFeedback",
    "StatisticalReport",
    "UncertaintyMethod",
    "ValidationFamily",
    "bootstrap_interval",
    "build_calibrator",
    "build_family",
    "build_feedback",
    "build_flags",
    "build_method",
    "build_report",
    "descriptive_statistics",
    "new_directions",
    "reliability_score",
    "resampling_library_versions",
    "selection_stepdown",
    "sign_consistency",
]
