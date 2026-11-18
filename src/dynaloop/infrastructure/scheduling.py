"""Deterministic scheduling vocabulary for multi-round loop execution.

State names follow Prefect's ``StateType`` (PENDING / RUNNING / COMPLETED /
FAILED) and the run lifecycle mirrors the existing ``ExperimentRunStatus``.
No Prefect dependency is added: our stages are pure functions over frozen
objects, so retries are safe and no async runtime / server is needed.

Wall-clock time and machine resources are never written into a stage record,
because every stage spec must be reproducible from the seed and configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

SCHEDULING_SCHEMA_VERSION = 1

T = TypeVar("T")


class SchedulingError(ValueError):
    """Invalid schedule or stage declaration."""


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One immutable stage outcome; ``fingerprint`` belongs to the stage output."""

    stage: str
    status: StageStatus
    fingerprint: str | None = None
    attempts: int = 1
    spec: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "fingerprint": self.fingerprint,
            "attempts": self.attempts,
            "spec": self.spec,
        }


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Deterministic retry count for a pure stage operation."""

    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise SchedulingError("max_attempts must be a positive integer.")

    def to_dict(self) -> dict[str, Any]:
        return {"max_attempts": self.max_attempts}


class StageFailure(RuntimeError):
    """A stage exhausted its retry budget."""

    def __init__(self, stage: str, attempts: int, cause: BaseException) -> None:
        super().__init__(f"Stage '{stage}' failed after {attempts} attempt(s): {cause}")
        self.stage = stage
        self.attempts = attempts
        self.cause = cause


def execute_stage(
    stage: str,
    operation: Callable[[], T],
    *,
    retry_policy: RetryPolicy | None = None,
) -> tuple[T, int]:
    """Run one pure stage; return its value and the number of attempts used."""
    policy = retry_policy or RetryPolicy()
    last: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation(), attempt
        except Exception as error:  # deterministic re-run of a pure function
            last = error
    raise StageFailure(stage, policy.max_attempts, last or RuntimeError("unknown"))


@runtime_checkable
class StopCondition(Protocol):
    name: str

    def spec(self) -> dict[str, Any]: ...

    def should_stop(
        self,
        *,
        round_index: int,
        rounds_completed: int,
        reliability: float | None,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class MaxRoundsStop:
    """Default: stop after the configured number of completed rounds."""

    max_rounds: int
    name: str = "max_rounds"

    def __post_init__(self) -> None:
        if not isinstance(self.max_rounds, int) or self.max_rounds < 1:
            raise SchedulingError("max_rounds must be a positive integer.")

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "max_rounds": self.max_rounds}

    def should_stop(
        self, *, round_index: int, rounds_completed: int, reliability: float | None
    ) -> bool:
        return rounds_completed >= self.max_rounds


@dataclass(frozen=True, slots=True)
class ReliabilityThresholdStop:
    """Optional: early stop once descriptive reliability reaches a threshold."""

    threshold: float
    max_rounds: int
    min_rounds: int = 1
    name: str = "reliability_threshold"

    def __post_init__(self) -> None:
        if not 0 <= float(self.threshold) <= 1:
            raise SchedulingError("threshold must lie in [0, 1].")
        if not isinstance(self.max_rounds, int) or self.max_rounds < 1:
            raise SchedulingError("max_rounds must be a positive integer.")
        if not isinstance(self.min_rounds, int) or self.min_rounds < 1:
            raise SchedulingError("min_rounds must be a positive integer.")
        if self.min_rounds > self.max_rounds:
            raise SchedulingError("min_rounds cannot exceed max_rounds.")

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "threshold": self.threshold,
            "max_rounds": self.max_rounds,
            "min_rounds": self.min_rounds,
            "reliability_is_descriptive": True,
        }

    def should_stop(
        self, *, round_index: int, rounds_completed: int, reliability: float | None
    ) -> bool:
        if rounds_completed >= self.max_rounds:
            return True
        return (
            rounds_completed >= self.min_rounds
            and reliability is not None
            and reliability >= self.threshold
        )


@dataclass(frozen=True, slots=True)
class LoopSchedule:
    """All scheduling semantics that are allowed to affect the loop result."""

    rounds: int
    seed: int
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    stop_condition: StopCondition | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rounds, int) or self.rounds < 1:
            raise SchedulingError("rounds must be a positive integer.")

    @property
    def condition(self) -> StopCondition:
        return self.stop_condition or MaxRoundsStop(self.rounds)

    def should_stop(
        self, *, round_index: int, rounds_completed: int, reliability: float | None
    ) -> bool:
        return self.condition.should_stop(
            round_index=round_index,
            rounds_completed=rounds_completed,
            reliability=reliability,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEDULING_SCHEMA_VERSION,
            "rounds": self.rounds,
            "seed": self.seed,
            "retry_policy": self.retry_policy.to_dict(),
            "stop_condition": self.condition.spec(),
        }
