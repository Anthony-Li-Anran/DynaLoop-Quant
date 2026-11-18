"""Learned backtest proxy: fast resampled reward + uncertainty estimates.

The proxy is a *calibrated empirical model* of Wake's verdicts. It never
re-runs the backtest, never reads backtest P&L and never touches the frozen
data: the only real values it consumes are ``WakeObservation`` rewards, which
come from ``factor_reward(FactorEvaluation)``.

Uncertainty comes from a real time-series block bootstrap (``arch``), so
short-range serial dependence in the calibration residuals is preserved.
Conformal coverage guarantees and their finite-sample quantile correction are
deliberately not implemented here: those belong to stage 4's Statistical &
Uncertainty Engine, whose tool selection is a deferred decision.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
from arch.bootstrap import CircularBlockBootstrap, StationaryBootstrap

from dynaloop.market_environment.feedback import SimulatedEstimation
from dynaloop.market_environment.observations import WakeObservation, factor_group_key
from dynaloop.research_engine import FactorCandidate
from dynaloop.research_engine.spec import fingerprint, library_versions
from dynaloop.training_engine import RewardSpec

PROXY_SCHEMA_VERSION = 1
BOOTSTRAP_CLASSES = {
    "circular": CircularBlockBootstrap,
    "stationary": StationaryBootstrap,
}


class ProxyError(ValueError):
    """Raised when a proxy configuration or calibration is invalid."""


def proxy_library_versions() -> dict[str, str | None]:
    """Observational metadata: every library that can change the numbers."""
    versions = library_versions()
    try:
        import arch

        versions["arch"] = getattr(arch, "__version__", None)
    except ImportError:
        versions["arch"] = None
    return versions


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """Every free parameter of one Sleep estimation round."""

    reward: RewardSpec = field(default_factory=RewardSpec)
    bootstrap: str = "circular"
    block_size: int = 5
    reps: int = 300
    seed: int = 0
    round_index: int = 0
    interval_size: float = 0.9

    def __post_init__(self) -> None:
        if self.bootstrap not in BOOTSTRAP_CLASSES:
            raise ProxyError(f"bootstrap must be one of {sorted(BOOTSTRAP_CLASSES)}.")
        if not isinstance(self.block_size, int) or self.block_size < 1:
            raise ProxyError("block_size must be a positive integer.")
        if not isinstance(self.reps, int) or self.reps < 10:
            raise ProxyError("reps must be an integer of at least 10.")
        if not isinstance(self.seed, int) or self.seed < 0:
            raise ProxyError("seed must be a non-negative integer.")
        if not isinstance(self.round_index, int) or self.round_index < 0:
            raise ProxyError("round_index must be a non-negative integer.")
        if not 0 < float(self.interval_size) < 1:
            raise ProxyError("interval_size must be in (0, 1).")

    def rng(self) -> np.random.Generator:
        """Independent reproducible stream per (seed, round)."""
        return np.random.default_rng(np.random.SeedSequence([self.seed, self.round_index]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROXY_SCHEMA_VERSION,
            "reward": self.reward.to_dict(),
            "bootstrap": self.bootstrap,
            "block_size": self.block_size,
            "reps": self.reps,
            "seed": self.seed,
            "round_index": self.round_index,
            "interval_size": self.interval_size,
            "rng": "PCG64/SeedSequence([seed, round_index])",
        }


@dataclass(frozen=True, slots=True)
class BiasInjection:
    """Known-magnitude bias injected into the proxy reward (Wrapper style).

    This mirrors Gymnasium's ``RewardWrapper.reward``: only the returned
    reward is transformed, the underlying estimate and the frozen Wake
    verdict are left untouched.
    """

    magnitude: float = 0.0
    mode: str = "additive"

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.magnitude)):
            raise ProxyError("magnitude must be finite.")
        if self.mode not in ("additive", "multiplicative"):
            raise ProxyError("mode must be 'additive' or 'multiplicative'.")

    def apply(self, reward: float) -> float:
        if self.mode == "additive":
            return float(reward + self.magnitude)
        return float(reward * (1.0 + self.magnitude))

    def to_dict(self) -> dict[str, Any]:
        return {"magnitude": self.magnitude, "mode": self.mode}


@dataclass(frozen=True, slots=True)
class ProxyCalibration:
    """Immutable proxy state; every update produces a new version."""

    version: int
    group_rewards: tuple[tuple[str, tuple[float, ...]], ...]
    residuals: tuple[float, ...]
    bias_offset: float
    reward_spec: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or self.version < 1:
            raise ProxyError("calibration version must be a positive integer.")
        if not math.isfinite(float(self.bias_offset)):
            raise ProxyError("bias_offset must be finite.")

    def all_rewards(self) -> tuple[float, ...]:
        return tuple(value for _, values in self.group_rewards for value in values)

    def global_mean(self) -> float:
        rewards = self.all_rewards()
        return float(sum(rewards) / len(rewards)) if rewards else 0.0

    def mean_for(self, group_key: str) -> float:
        """Grouped empirical mean, with the global mean as the cold-start fallback."""
        for key, values in self.group_rewards:
            if key == group_key and values:
                return float(sum(values) / len(values))
        return self.global_mean()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROXY_SCHEMA_VERSION,
            "version": self.version,
            "group_rewards": [
                {"group_key": key, "rewards": list(values)} for key, values in self.group_rewards
            ],
            "residuals": list(self.residuals),
            "bias_offset": self.bias_offset,
            "reward_spec": self.reward_spec,
        }

    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


def _sorted_groups(mapping: Mapping[str, Sequence[float]]) -> tuple[tuple[str, tuple[float, ...]], ...]:
    return tuple(
        (key, tuple(sorted(float(value) for value in values)))
        for key, values in sorted(mapping.items())
    )


def _bootstrap_spread(
    residuals: Sequence[float], config: ProxyConfig
) -> tuple[float, float, float, bool, int]:
    """Block-bootstrap the calibration residual mean with ``arch``."""
    array = np.asarray(list(residuals), dtype=float)
    array = array[np.isfinite(array)]
    if array.size < 2:
        return 0.0, 0.0, 0.0, False, 0
    block_size = min(config.block_size, int(array.size))
    bootstrap_class = BOOTSTRAP_CLASSES[config.bootstrap]
    bootstrap = bootstrap_class(block_size, array, seed=config.rng())
    draws = np.asarray(bootstrap.apply(np.mean, reps=config.reps), dtype=float).reshape(-1)
    uncertainty = float(draws.std(ddof=1)) if draws.size > 1 else 0.0
    lower, upper = np.quantile(
        draws, [(1.0 - config.interval_size) / 2.0, (1.0 + config.interval_size) / 2.0]
    )
    return uncertainty, float(lower), float(upper), True, int(draws.size)


@runtime_checkable
class BacktestProxy(Protocol):
    """Replaceable Sleep proxy: fit calibrates, estimate produces quick values."""

    name: str

    def fit(
        self, observations: Sequence[WakeObservation], config: ProxyConfig
    ) -> ProxyCalibration: ...

    def estimate(
        self,
        candidates: Sequence[FactorCandidate],
        calibration: ProxyCalibration,
        config: ProxyConfig,
        bias: BiasInjection | None = None,
    ) -> tuple[SimulatedEstimation, ...]: ...

    def recalibrate(
        self,
        calibration: ProxyCalibration,
        observations: Sequence[WakeObservation],
        estimations: Sequence[SimulatedEstimation],
        config: ProxyConfig,
    ) -> ProxyCalibration: ...


class ResampledBacktestProxy:
    """First real Sleep proxy: grouped empirical reward + residual bootstrap."""

    name = "resampled"

    def fit(
        self, observations: Sequence[WakeObservation], config: ProxyConfig
    ) -> ProxyCalibration:
        if not observations:
            raise ProxyError("Calibration requires at least one Wake observation.")
        grouped: dict[str, list[float]] = defaultdict(list)
        for observation in observations:
            grouped[observation.group_key].append(observation.reward)
        calibration = ProxyCalibration(
            version=1,
            group_rewards=_sorted_groups(grouped),
            residuals=(),
            bias_offset=0.0,
            reward_spec=config.reward.to_dict(),
        )
        residuals = tuple(
            float(observation.reward - calibration.mean_for(observation.group_key))
            for observation in observations
        )
        return replace(calibration, residuals=residuals)

    def estimate(
        self,
        candidates: Sequence[FactorCandidate],
        calibration: ProxyCalibration,
        config: ProxyConfig,
        bias: BiasInjection | None = None,
    ) -> tuple[SimulatedEstimation, ...]:
        injection = bias or BiasInjection()
        uncertainty, lower, upper, applied, draws = _bootstrap_spread(
            calibration.residuals, config
        )
        estimation_spec = {
            "schema_version": PROXY_SCHEMA_VERSION,
            "proxy": self.name,
            "config": config.to_dict(),
            "bias_injection": injection.to_dict(),
            "calibration_fingerprint": calibration.fingerprint(),
            "calibration_version": calibration.version,
            "bootstrap": {
                "applied": applied,
                "draws": draws,
                "method": "block_bootstrap_mean_of_calibration_residuals",
                "interval": "percentile of the bootstrap mean, descriptive only",
                "residual_lower": lower,
                "residual_upper": upper,
            },
            "library_versions": proxy_library_versions(),
        }
        estimates: list[SimulatedEstimation] = []
        for candidate in candidates:
            group_key = factor_group_key(candidate)
            base = calibration.mean_for(group_key) + calibration.bias_offset
            reward = injection.apply(base)
            estimates.append(
                SimulatedEstimation(
                    factor_id=candidate.factor_id,
                    expression=candidate.expression,
                    group_key=group_key,
                    reward=reward,
                    base_reward=base,
                    uncertainty=uncertainty,
                    interval_lower=reward + lower,
                    interval_upper=reward + upper,
                    calibration_version=calibration.version,
                    bootstrap_applied=applied,
                    spec=dict(estimation_spec),
                )
            )
        return tuple(estimates)

    def recalibrate(
        self,
        calibration: ProxyCalibration,
        observations: Sequence[WakeObservation],
        estimations: Sequence[SimulatedEstimation],
        config: ProxyConfig,
    ) -> ProxyCalibration:
        """Absorb measured bias into a new immutable calibration version."""
        real = {item.factor_id: item.reward for item in observations}
        simulated = {item.factor_id: item.reward for item in estimations}
        if set(real) != set(simulated) or not real:
            raise ProxyError("Recalibration requires matched real and simulated families.")
        measured_bias = float(
            sum(simulated[key] - real[key] for key in real) / len(real)
        )
        merged: dict[str, list[float]] = defaultdict(list)
        for key, values in calibration.group_rewards:
            merged[key].extend(values)
        for observation in observations:
            merged[observation.group_key].append(observation.reward)
        next_calibration = ProxyCalibration(
            version=calibration.version + 1,
            group_rewards=_sorted_groups(merged),
            residuals=(),
            bias_offset=float(calibration.bias_offset - measured_bias),
            reward_spec=config.reward.to_dict(),
        )
        residuals = tuple(
            float(
                observation.reward
                - next_calibration.mean_for(observation.group_key)
                - next_calibration.bias_offset
            )
            for observation in observations
        )
        return replace(next_calibration, residuals=residuals)


__all__ = [
    "BOOTSTRAP_CLASSES",
    "PROXY_SCHEMA_VERSION",
    "BacktestProxy",
    "BiasInjection",
    "ProxyCalibration",
    "ProxyConfig",
    "ProxyError",
    "ResampledBacktestProxy",
    "proxy_library_versions",
]
