"""Research Engine: restricted factor expression, evaluation and compilation.

Stage 1 deliverable. The expression language follows microsoft/qlib's
Expression Engine surface (``$close``, ``Ref($close, 5)``, registered operator
names, infix operators) while parsing with an ``ast`` whitelist like qlib's
current ``expression_parser.py``. A factor column is materialised once and then
shared by the IC/RankIC statistics, the compiled ``BaseStrategy`` and the
deterministic backtest verdict.
"""

from dynaloop.research_engine.catalog import ResearchCatalog
from dynaloop.research_engine.decision_record import (
    DecisionLedger,
    DecisionRecordError,
)
from dynaloop.research_engine.alpha_audit import (
    AuditReport,
    Diagnostic,
    audit_expression,
)
from dynaloop.research_engine.certification_catalog import (
    CertificationCatalog,
    ExecutionCatalog,
    WalkforwardCatalog,
)
from dynaloop.research_engine.evaluation_metrics import (
    HAC_LAG_RULE,
    factor_autocorrelation,
    hac_t_statistic,
    series_lag1_autocorrelation,
)
from dynaloop.research_engine.factor_search import (
    FactorSearchConfig,
    FrozenFamily,
    SearchIsolationError,
    SearchSlice,
    assert_search_isolation,
    freeze_fingerprint,
    search_and_freeze,
)
from dynaloop.research_engine.channels import (
    CHANNEL_ASSERTIONS,
    CHANNEL_CROSS_SECTION,
    CHANNEL_LABELS,
    CHANNEL_SCOPE_LIMITS,
    CHANNEL_TIMING,
    NOT_CLAIMED,
    ChannelIsolationError,
    FactorEvidence,
    channel_fields,
    enforce_channel,
    evidence_from_report,
    require_channel,
)
from dynaloop.research_engine.cross_section import (
    CROSS_SECTION_SCHEMA_VERSION,
    CS_STATUS_EFFECTIVE,
    CS_STATUS_FOUND,
    CS_STATUS_INSUFFICIENT,
    CS_STATUS_REFUTED,
    CostModel,
    CrossSectionCandidate,
    CrossSectionConfig,
    CrossSectionDiagnostics,
    CrossSectionFamilyTest,
    CrossSectionIsolationError,
    CrossSectionReport,
    CrossSectionRequest,
    CrossSectionSlice,
    CrossSectionVerdict,
    assess_cross_section,
    diagnose_cross_section,
)
from dynaloop.research_engine.candidates import (
    FACTOR_STRATEGY_CLASS,
    CompiledFactor,
    EvaluationPolicy,
    FactorCandidate,
    compile_factor,
)
from dynaloop.research_engine.evaluation import (
    IC_LABEL,
    FactorEvaluation,
    build_evaluation_spec,
    information_coefficient,
)
from dynaloop.research_engine.expressions import (
    FACTOR_SCHEMA_VERSION,
    ELEMENTWISE,
    OPERATOR_ARITY,
    PAIRWISE,
    PAIR_WINDOW_OPERATORS,
    SHIFT_OPERATORS,
    WINDOW_OPERATORS,
    Constant,
    ExpressionEvaluationError,
    ExpressionSyntaxError,
    FactorError,
    Feature,
    Node,
    Operator,
    expression_details,
    extended_window_size,
    normalize_expression,
    parse_expression,
)
from dynaloop.research_engine.effectiveness import (
    EFFECTIVENESS_SCHEMA_VERSION,
    STATUS_EFFECTIVE,
    STATUS_FOUND,
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    CandidateVerdict,
    EffectivenessConfig,
    EffectivenessReport,
    EffectivenessRequest,
    FamilyTest,
    FrozenCandidate,
    IsolationError,
    VerificationRow,
    assess_effectiveness,
    rows_from_frozen_tape,
)
from dynaloop.research_engine.exploration import (
    EXPLORATION_SCHEMA_VERSION,
    ExplorationPolicy,
    PolicyError,
    uniform_policy,
)
from dynaloop.research_engine.facade import FactorResearch
from dynaloop.research_engine.frame import FactorFrame, FactorValues, window_records
from dynaloop.research_engine.operators import (
    EvaluationContext,
    Operators,
    evaluate_expression,
    evaluate_node,
)
from dynaloop.research_engine.diagnostic_report import attach_report, build_diagnostic_report
from dynaloop.research_engine.decay import ic_decay_curve, ic_half_life
from dynaloop.research_engine.neutralization import (
    cross_sectional_zscore,
    neutralise_cross_section,
    residual_information_coefficient,
    robust_winsorise,
)
from dynaloop.research_engine.search_bias import (
    backtest_overfitting_probability,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from dynaloop.research_engine.trial_ledger import TrialLedger, TrialRecord
from dynaloop.research_engine.timing_learning import (
    TimingCandidate,
    TimingLearningConfig,
    TimingSample,
    certify_timing,
    learn_timing_candidates,
    search_mean,
    verification_rows,
)
from dynaloop.research_engine.portfolio_weights import (
    WeightConfig,
    WeightScheme,
    build_target_weights,
)
from dynaloop.research_engine.update_gate import (
    PeriodRecord,
    UpdateDecision,
    UpdateGateConfig,
    decide_update,
)
from dynaloop.research_engine.spec import canonical_json, fingerprint, library_versions
from dynaloop.research_engine.strategies import FactorSignalStrategy

__all__ = [
    "ResearchCatalog",
    "CertificationCatalog",
    "ExecutionCatalog",
    "WalkforwardCatalog",
    # Human final-decision audit trail (record only, never decides)
    "DecisionLedger",
    "DecisionRecordError",
    # QBX-style read-only audit shell (report-only, relative-contract guarantee)
    "AuditReport",
    "Diagnostic",
    "audit_expression",
    # Search-intensity accounting and decay (report-only)
    "attach_report",
    "build_diagnostic_report",
    "TrialLedger",
    "TrialRecord",
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
    "backtest_overfitting_probability",
    "robust_winsorise",
    "cross_sectional_zscore",
    "neutralise_cross_section",
    "residual_information_coefficient",
    "ic_decay_curve",
    "ic_half_life",
    # Frozen target-weight construction (qlib WeightStrategyBase analogue)
    "WeightConfig",
    "WeightScheme",
    "build_target_weights",
    # Timing-rule learning + out-of-sample certification
    "TimingSample",
    "TimingLearningConfig",
    "TimingCandidate",
    "learn_timing_candidates",
    "verification_rows",
    "search_mean",
    "certify_timing",
    # Statistically-gated model updates
    "PeriodRecord",
    "UpdateDecision",
    "UpdateGateConfig",
    "decide_update",
    # Report-only upstream-aligned evaluation metrics
    "HAC_LAG_RULE",
    "factor_autocorrelation",
    "hac_t_statistic",
    "series_lag1_autocorrelation",
    "FactorTape",
    "TemporalConfig",
    "TemporalResearch",
    "EFFECTIVENESS_SCHEMA_VERSION",
    "STATUS_EFFECTIVE",
    "STATUS_FOUND",
    "STATUS_INSUFFICIENT",
    "STATUS_REFUTED",
    "CandidateVerdict",
    "EffectivenessConfig",
    "EffectivenessReport",
    "EffectivenessRequest",
    "FamilyTest",
    "FrozenCandidate",
    "IsolationError",
    "VerificationRow",
    "assess_effectiveness",
    "rows_from_frozen_tape",
    "ELEMENTWISE",
    "EXPLORATION_SCHEMA_VERSION",
    "FACTOR_SCHEMA_VERSION",
    "FACTOR_STRATEGY_CLASS",
    "IC_LABEL",
    "OPERATOR_ARITY",
    "PAIRWISE",
    "PAIR_WINDOW_OPERATORS",
    "SHIFT_OPERATORS",
    "WINDOW_OPERATORS",
    "CompiledFactor",
    "Constant",
    "EvaluationContext",
    "EvaluationPolicy",
    "ExplorationPolicy",
    "ExpressionEvaluationError",
    "ExpressionSyntaxError",
    "FactorCandidate",
    "FactorError",
    "FactorEvaluation",
    "FactorFrame",
    "FactorResearch",
    "FactorSignalStrategy",
    "FactorValues",
    "Feature",
    "Node",
    "Operator",
    "Operators",
    "PolicyError",
    "build_evaluation_spec",
    "canonical_json",
    "compile_factor",
    "evaluate_expression",
    "evaluate_node",
    "expression_details",
    "extended_window_size",
    "fingerprint",
    "information_coefficient",
    "library_versions",
    "normalize_expression",
    "parse_expression",
    "uniform_policy",
    "window_records",
    # Part A channel identity and labelled evidence
    "CHANNEL_CROSS_SECTION",
    "CHANNEL_TIMING",
    "CHANNEL_LABELS",
    "CHANNEL_ASSERTIONS",
    "CHANNEL_SCOPE_LIMITS",
    "NOT_CLAIMED",
    "ChannelIsolationError",
    "FactorEvidence",
    "channel_fields",
    "enforce_channel",
    "evidence_from_report",
    "require_channel",
    # Part A channel one: cross-sectional stock selection
    "CROSS_SECTION_SCHEMA_VERSION",
    "CS_STATUS_EFFECTIVE",
    "CS_STATUS_FOUND",
    "CS_STATUS_INSUFFICIENT",
    "CS_STATUS_REFUTED",
    "CostModel",
    "CrossSectionCandidate",
    "CrossSectionConfig",
    "CrossSectionDiagnostics",
    "CrossSectionFamilyTest",
    "CrossSectionIsolationError",
    "CrossSectionReport",
    "CrossSectionRequest",
    "CrossSectionSlice",
    "CrossSectionVerdict",
    "assess_cross_section",
    "diagnose_cross_section",
    # Part A search side: search-period discovery and one-shot freeze
    "FactorSearchConfig",
    "FrozenFamily",
    "SearchIsolationError",
    "SearchSlice",
    "assert_search_isolation",
    "freeze_fingerprint",
    "search_and_freeze",
]


def __getattr__(name):
    if name in {"FactorTape", "TemporalConfig", "TemporalResearch"}:
        from dynaloop.research_engine import temporal
        return getattr(temporal, name)
    raise AttributeError(name)
