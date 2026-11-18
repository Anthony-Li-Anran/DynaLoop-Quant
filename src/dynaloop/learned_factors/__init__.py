"""Local, editable re-implementation of the Qlib factor-research workflow.

Layer map (all local, no qlib import):
    provider   -> qlib.data.data.Calendar/Instrument/Feature providers
    expression -> qlib.data.ops (DataLoader expression semantics)
    alpha158   -> qlib.contrib.data.loader.Alpha158DL / handler.Alpha158
    handler    -> qlib.data.dataset.handler.DataHandlerLP
    dataset    -> qlib.data.dataset.DatasetH
    model      -> qlib.contrib.model.gbdt.LGBModel
    workflow   -> qlib/examples/workflow_by_code.py + SigAnaRecord

The output of this package is a learned prediction signal, not a hand-written
formula. Effectiveness verdicts remain the job of the certification layer.
"""

from dynaloop.learned_factors.alpha158 import (
    DEFAULT_CONFIG,
    DEFAULT_WINDOWS,
    LABEL_EXPRESSION,
    LABEL_NAME,
    config_fingerprint,
    feature_config,
    label_config,
)
from dynaloop.learned_factors.dataset import DatasetConfig, DatasetH
from dynaloop.learned_factors.aligned_dataset import AlignedConfig, AlignedDataset
from dynaloop.learned_factors.expression import (
    ExpressionError,
    ExpressionEvaluator,
    assert_no_future_reference,
    parse,
)
from dynaloop.learned_factors.handler import (
    DEFAULT_LEARN_PROCESSORS,
    DK_I,
    DK_L,
    DK_R,
    Alpha158Handler,
    HandlerConfig,
)
from dynaloop.learned_factors.label_alignment import (
    Decision,
    EvaluationWindow,
    TriggerSpec,
    WindowSpec,
    assign_windows,
    build_windows,
    pick_entry,
    window_target,
)
from dynaloop.learned_factors.model import LGBConfig, LGBModel
from dynaloop.learned_factors.provider import (
    ALL_FIELDS,
    BASE_FIELDS,
    ArchiveDigest,
    ArchiveError,
    QlibBinaryProvider,
    decode_feature,
)
from dynaloop.learned_factors.workflow import (
    WorkflowConfig,
    WorkflowResult,
    run_workflow,
    signal_analysis,
)

__all__ = [
    "ALL_FIELDS",
    "AlignedConfig",
    "AlignedDataset",
    "BASE_FIELDS",
    "DEFAULT_CONFIG",
    "DEFAULT_LEARN_PROCESSORS",
    "DEFAULT_WINDOWS",
    "DK_I",
    "DK_L",
    "DK_R",
    "LABEL_EXPRESSION",
    "LABEL_NAME",
    "Alpha158Handler",
    "ArchiveDigest",
    "ArchiveError",
    "Decision",
    "EvaluationWindow",
    "TriggerSpec",
    "WindowSpec",
    "assign_windows",
    "build_windows",
    "pick_entry",
    "window_target",
    "DatasetConfig",
    "DatasetH",
    "ExpressionError",
    "ExpressionEvaluator",
    "HandlerConfig",
    "LGBConfig",
    "LGBModel",
    "QlibBinaryProvider",
    "WorkflowConfig",
    "WorkflowResult",
    "assert_no_future_reference",
    "config_fingerprint",
    "decode_feature",
    "feature_config",
    "label_config",
    "parse",
    "run_workflow",
    "signal_analysis",
]
