"""Single-round training step: evaluations -> reward -> advantage -> new policy.

Stage 2 deliberately stops at one-module update semantics. The multi-round
wake/sleep state machine and per-round experiment runs belong to the
Orchestrator (stage 4); nothing here schedules loops or writes results back to
Data, Research or the backtest engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from dynaloop.inference_engine.sampling import CandidateBatch
from dynaloop.research_engine.evaluation import FactorEvaluation
from dynaloop.research_engine.exploration import ExplorationPolicy, PolicyError
from dynaloop.research_engine.spec import fingerprint, library_versions
from dynaloop.training_engine.reward import (
    RewardSpec,
    factor_reward,
    group_advantages,
)
from dynaloop.training_engine.updaters import PolicyUpdater, RewardWeightedUpdater

TRAINING_SCHEMA_VERSION = 1


class TrainingError(ValueError):
    """The feedback group is inconsistent with the candidate group."""


@dataclass(frozen=True, slots=True)
class TrainingStep:
    """One immutable, fully specified update of the exploration policy."""

    round_index: int
    policy_before: ExplorationPolicy
    policy_after: ExplorationPolicy
    rewards: tuple[float, ...]
    advantages: tuple[float, ...]
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "policy_before": self.policy_before.to_dict(),
            "policy_after": self.policy_after.to_dict(),
            "rewards": list(self.rewards),
            "advantages": list(self.advantages),
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


class TrainingEngine:
    """Stateless updater facade; every free parameter is written into the spec."""

    def __init__(
        self,
        *,
        updater: PolicyUpdater | None = None,
        reward_spec: RewardSpec | None = None,
    ) -> None:
        self.updater: PolicyUpdater = updater or RewardWeightedUpdater()
        self.reward_spec = reward_spec or RewardSpec()

    def update(
        self,
        policy: ExplorationPolicy,
        batch: CandidateBatch,
        evaluations: Sequence[FactorEvaluation],
        *,
        updater: PolicyUpdater | None = None,
        reward_spec: RewardSpec | None = None,
    ) -> tuple[ExplorationPolicy, TrainingStep]:
        active_updater = updater or self.updater
        active_reward = reward_spec or self.reward_spec
        if len(batch.candidates) != len(evaluations):
            raise TrainingError("Each candidate needs exactly one FactorEvaluation.")
        if not evaluations:
            raise TrainingError("Cannot update a policy from an empty feedback group.")
        for position, (candidate, evaluation) in enumerate(zip(batch.candidates, evaluations)):
            if evaluation.candidate.factor_id != candidate.factor_id:
                raise TrainingError(
                    f"Evaluation {position} does not belong to candidate {candidate.factor_id[:8]}."
                )

        rewards = tuple(factor_reward(evaluation, active_reward) for evaluation in evaluations)
        advantages = group_advantages(
            rewards,
            scale_rewards=active_reward.scale_rewards,
            epsilon=active_reward.epsilon,
        )
        try:
            next_policy = active_updater.update(policy, batch.choices, advantages)
        except PolicyError as error:
            raise TrainingError(str(error)) from error

        spec = {
            "schema_version": TRAINING_SCHEMA_VERSION,
            "round_index": batch.round_index,
            "sampling": batch.spec,
            "reward": active_reward.to_dict(),
            "updater": active_updater.spec(),
            "policy_before": {
                "version": policy.version,
                "fingerprint": policy.fingerprint(),
                "weights": dict(sorted(policy.weights.items())),
            },
            "policy_after": {
                "version": next_policy.version,
                "fingerprint": next_policy.fingerprint(),
                "weights": dict(sorted(next_policy.weights.items())),
            },
            "feedback": [
                {
                    "factor_id": candidate.factor_id,
                    "expression": candidate.expression,
                    "choice": batch.choices[position],
                    "parts": list(batch.parts[position]),
                    "reward": rewards[position],
                    "advantage": advantages[position],
                    "evaluation_fingerprint": evaluation.fingerprint(),
                    "statistics": dict(evaluation.statistics),
                }
                for position, (candidate, evaluation) in enumerate(
                    zip(batch.candidates, evaluations)
                )
            ],
            "library_versions": library_versions(),
        }
        step = TrainingStep(
            round_index=batch.round_index,
            policy_before=policy,
            policy_after=next_policy,
            rewards=rewards,
            advantages=advantages,
            spec=spec,
        )
        return next_policy, step
