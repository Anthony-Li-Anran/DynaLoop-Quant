"""Shared resampling MATH for the two Part A verdicts. Nothing else.

Deliberately free of any verdict, null hypothesis, baseline, family or channel
concept. Both channels use the same two algorithms -- one shared block-bootstrap
time-index path per replicate across the whole family, and max-statistic
step-down -- because those are the correct tools for serially dependent,
cross-correlated candidate statistics.

Each channel defines its OWN family, statistic, null hypothesis and baseline in
its own module. Distinct path salts keep the two channels' random draws
independent as well. NEVER pass candidates from both channels to one call.
"""
from __future__ import annotations

import numpy as np
from arch.bootstrap import CircularBlockBootstrap, StationaryBootstrap

TIMING_PATH_SALT = 0xC0FFEE
CROSS_SECTION_PATH_SALT = 0xC5C5EC


def shared_time_paths(
    n: int,
    *,
    reps: int,
    block_size: int,
    seed: int,
    bootstrap: str = "stationary",
    salt: int = TIMING_PATH_SALT,
) -> np.ndarray:
    """One shared resampled time-index path per replicate, shape ``(reps, n)``.

    Sharing the path is essential: independent per-candidate resampling would
    destroy cross-candidate dependence and invalidate the joint max statistic.
    """
    if bootstrap not in ("stationary", "circular"):
        raise ValueError("bootstrap must be 'stationary' or 'circular'")
    cls = StationaryBootstrap if bootstrap == "stationary" else CircularBlockBootstrap
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), int(salt)]))
    boot = cls(int(block_size), np.arange(int(n)), seed=rng)
    paths = np.empty((int(reps), int(n)), dtype=int)
    for b, (positional, _keywords) in enumerate(boot.bootstrap(reps=int(reps))):
        paths[b] = np.asarray(positional[0], dtype=int)
    if paths.shape != (int(reps), int(n)):
        raise RuntimeError("bootstrap produced an unexpected index shape")
    return paths


def studentized_statistics(
    differentials: np.ndarray, paths: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Observed statistics and recentred bootstrap statistics, ``T x K`` input.

    Returns ``(observed, t_star, mean, scale)``. Each column is recentred by its
    own sample mean, building a least-favourable / no-superiority null. The
    studentising scale is fixed at its observed value and NOT re-estimated per
    replicate: this is the conservative Reality-Check style variant, not a full
    SPA test.
    """
    matrix = np.asarray(differentials, dtype=float)
    n, k = matrix.shape
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0, ddof=1)
    scale = np.where(std > 1e-12, std, 1.0)
    observed = np.sqrt(n) * mean / scale
    t_star = np.empty((paths.shape[0], k), dtype=float)
    for b in range(paths.shape[0]):
        resampled_mean = matrix[paths[b]].mean(axis=0)
        t_star[b] = np.sqrt(n) * (resampled_mean - mean) / scale
    return observed, t_star, mean, scale


def stepdown(
    observed: np.ndarray, t_star: np.ndarray
) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Romano-Wolf / Westfall-Young max-statistic step-down.

    Returns ``(adjusted_p_values, family_p_value, descending_order, max_star)``.
    Monotone adjusted p-values come from the running maximum of the raw tail
    frequencies over the remaining (harder) family.
    """
    reps = t_star.shape[0]
    max_star = t_star.max(axis=1)
    family_p = float((1 + np.count_nonzero(max_star >= observed.max())) / (reps + 1))
    order = np.argsort(-observed)
    adjusted = np.ones(observed.shape[0], dtype=float)
    previous = 0.0
    for rank, position in enumerate(order):
        remaining_max = t_star[:, order[rank:]].max(axis=1)
        raw = (1 + np.count_nonzero(remaining_max >= observed[position])) / (reps + 1)
        previous = max(previous, raw)
        adjusted[position] = previous
    return adjusted, family_p, order, max_star
