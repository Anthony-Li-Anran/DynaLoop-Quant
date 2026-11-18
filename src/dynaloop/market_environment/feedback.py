"""Sleep estimates, measured proxy bias and Simulation Feedback for stage 5.

All quantities here are descriptive. No coverage guarantee, significance
claim or multiple-testing correction is made: those belong to the Statistical
& Uncertainty Engine in stage 4 and remain a deferred design choice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from dynaloop.market_environment.observations import WakeObservation
from dynaloop.research_engine.spec import fingerprint

FEEDBACK_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SimulatedEstimation:
    """Fast reward/uncertainty estimate for one candidate factor."""

    factor_id: str
    expression: str
    group_key: str
    reward: float
    base_reward: float
    uncertainty: float
    interval_lower: float
    interval_upper: float
    calibration_version: int
    bootstrap_applied: bool
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "expression": self.expression,
            "group_key": self.group_key,
            "reward": self.reward,
            "base_reward": self.base_reward,
            "uncertainty": self.uncertainty,
            "interval_lower": self.interval_lower,
            "interval_upper": self.interval_upper,
            "calibration_version": self.calibration_version,
            "bootstrap_applied": self.bootstrap_applied,
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class BiasReport:
    """Proxy estimate versus the frozen Wake verdict, per candidate family."""

    model_bias: float
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_uncertainty: float
    observations: int
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "model_bias": self.model_bias,
            "mean_absolute_error": self.mean_absolute_error,
            "root_mean_squared_error": self.root_mean_squared_error,
            "mean_uncertainty": self.mean_uncertainty,
            "observations": self.observations,
            "spec": self.spec,
        }


def compare_estimates(
    observations: Sequence[WakeObservation],
    estimations: Sequence[SimulatedEstimation],
) -> BiasReport:
    """Measure the proxy's error against real evaluations, matched by factor id."""
    real = {item.factor_id: item.reward for item in observations}
    if len(real) != len(observations):
        raise ValueError("Wake observations contain duplicate factor ids.")
    simulated = {item.factor_id: item for item in estimations}
    if len(simulated) != len(estimations):
        raise ValueError("Simulated estimations contain duplicate factor ids.")
    missing = set(real) ^ set(simulated)
    if missing:
        raise ValueError("Wake observations and simulated estimations must cover the same factors.")
    errors = [simulated[key].reward - real[key] for key in real]
    absolute = [abs(value) for value in errors]
    uncertainties = [simulated[key].uncertainty for key in real]
    count = len(errors)
    if count == 0:
        raise ValueError("At least one paired estimate is required.")
    return BiasReport(
        model_bias=float(sum(errors) / count),
        mean_absolute_error=float(sum(absolute) / count),
        root_mean_squared_error=float(math.sqrt(sum(value * value for value in errors) / count)),
        mean_uncertainty=float(sum(uncertainties) / count),
        observations=count,
        spec={
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "matched_by": "factor_id",
            "real_source": "FactorEvaluation.statistics via factor_reward",
            "simulated_source": "SimulatedEstimation.reward",
            "descriptive_only": True,
        },
    )


@dataclass(frozen=True, slots=True)
class SimulationFeedback:
    """The ③→⑤ edge: measured model bias, uncertainty and the injected bias."""

    model_bias: float
    mean_absolute_error: float
    mean_uncertainty: float
    injected_bias: float
    expected_bias: float
    amplification: float | None
    calibration_version: int
    environment_reference: dict[str, Any]
    run_id: str
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "model_bias": self.model_bias,
            "mean_absolute_error": self.mean_absolute_error,
            "mean_uncertainty": self.mean_uncertainty,
            "injected_bias": self.injected_bias,
            "expected_bias": self.expected_bias,
            "amplification": self.amplification,
            "calibration_version": self.calibration_version,
            "environment_reference": self.environment_reference,
            "run_id": self.run_id,
            "spec": self.spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


def expected_bias_shift(
    bias: Mapping[str, Any],
    rewards: Sequence[float],
) -> float:
    """The bias magnitude the injection was configured to produce."""
    magnitude = float(bias.get("magnitude") or 0.0)
    mode = str(bias.get("mode") or "additive")
    if mode == "additive":
        return magnitude
    mean_reward = float(sum(rewards) / len(rewards)) if rewards else 0.0
    return magnitude * mean_reward


__all__ = [
    "FEEDBACK_SCHEMA_VERSION",
    "BiasReport",
    "SimulatedEstimation",
    "SimulationFeedback",
    "compare_estimates",
    "expected_bias_shift",
]
