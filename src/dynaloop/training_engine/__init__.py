"""Training Engine: reward, group advantages and policy update semantics.

Stage 2. Reward reads only ``FactorEvaluation.statistics`` (never backtest P&L);
advantages follow TRL's GRPO group normalisation; the exploration policy is
updated by an interchangeable ``PolicyUpdater``. Multi-round orchestration is
stage 4 and deliberately not implemented here.
"""

from dynaloop.training_engine.engine import (
    TRAINING_SCHEMA_VERSION,
    TrainingEngine,
    TrainingError,
    TrainingStep,
)
from dynaloop.training_engine.reward import (
    REWARD_LABELS,
    RewardError,
    RewardSpec,
    factor_reward,
    group_advantages,
)
from dynaloop.training_engine.updaters import (
    UPDATER_REGISTRY,
    UPDATER_SCHEMA_VERSION,
    GRPOGroupUpdater,
    PolicyUpdater,
    RewardWeightedUpdater,
    build_updater,
    register_updater,
)

__all__ = [
    "SleepConfig",
    "SleepController",
    "DiffusionConfig",
    "ConditionalDiffusion",
    "WakeConfig",
    "WakeEvent",
    "WakeLearner",
    "GRPOGroupUpdater",
    "PolicyUpdater",
    "REWARD_LABELS",
    "RewardError",
    "RewardSpec",
    "RewardWeightedUpdater",
    "TRAINING_SCHEMA_VERSION",
    "TrainingEngine",
    "TrainingError",
    "TrainingStep",
    "UPDATER_REGISTRY",
    "UPDATER_SCHEMA_VERSION",
    "build_updater",
    "factor_reward",
    "group_advantages",
    "register_updater",
]


def __getattr__(name):
    if name in {"SleepConfig", "SleepController"}:
        from dynaloop.training_engine import sleep
        return getattr(sleep, name)
    if name in {"DiffusionConfig", "ConditionalDiffusion"}:
        from dynaloop.training_engine import diffusion
        return getattr(diffusion, name)
    if name in {"WakeConfig", "WakeEvent", "WakeLearner"}:
        from dynaloop.training_engine import wake
        return getattr(wake, name)
    raise AttributeError(name)
