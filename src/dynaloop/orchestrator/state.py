"""Immutable per-round and whole-run records for the six-stage loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dynaloop.infrastructure import StageRecord
from dynaloop.market_environment import ProxyCalibration
from dynaloop.research_engine import ExplorationPolicy
from dynaloop.research_engine.spec import fingerprint


class LoopStage(str, Enum):
    """Stage names follow the six blocks of the original architecture diagram."""

    EXPLORATION_POLICY = "exploration_policy"
    FACTOR_DISCOVERY = "factor_discovery"
    WAKE_VALIDATION = "wake_validation"
    SLEEP_SIMULATION = "sleep_simulation"
    JOINT_UPDATE = "joint_update"
    STATISTICAL_VALIDATION = "statistical_validation"


STAGE_ORDER: tuple[LoopStage, ...] = (
    LoopStage.EXPLORATION_POLICY,
    LoopStage.FACTOR_DISCOVERY,
    LoopStage.WAKE_VALIDATION,
    LoopStage.SLEEP_SIMULATION,
    LoopStage.JOINT_UPDATE,
    LoopStage.STATISTICAL_VALIDATION,
)


@dataclass(frozen=True, slots=True)
class RoundRecord:
    """Everything produced in one round, including its stage statuses."""

    round_index: int
    stages: tuple[StageRecord, ...]
    spec: dict[str, Any]
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "stages": [item.to_dict() for item in self.stages],
            "spec": self.spec,
            "run_id": self.run_id,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class LoopResult:
    """A complete reproducible run: same config + same seed = same fingerprint."""

    rounds: tuple[RoundRecord, ...]
    final_policy: ExplorationPolicy
    final_calibration: ProxyCalibration
    final_reliability: float
    run_ids: tuple[str, ...]
    spec: dict[str, Any]
    environment: dict[str, Any]

    def fingerprint(self) -> str:
        return fingerprint(self.spec)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint(),
            "rounds": [item.to_dict() for item in self.rounds],
            "final_policy": self.final_policy.to_dict(),
            "final_calibration": self.final_calibration.to_dict(),
            "final_reliability": self.final_reliability,
            "run_ids": list(self.run_ids),
            "spec": self.spec,
            "environment": self.environment,
        }
