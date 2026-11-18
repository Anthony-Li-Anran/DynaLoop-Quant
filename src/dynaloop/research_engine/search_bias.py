"""Search-bias-aware uncertainty quantification for factor research.

A factor's significance is a joint property of the factor AND the search that
produced it. This module implements the two standard instruments that fold the
recorded search intensity into the conclusion:

* Probabilistic / Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014,
  "The Deflated Sharpe Ratio", JPM 40(5):94-107); formulas cross-checked
  against the mlfinlab ``backtest_statistics.statistics`` documentation.
* Probability of Backtest Overfitting via Combinatorially Symmetric
  Cross-Validation (Bailey, Borwein, Lopez de Prado & Zhu, 2014/2017).

Every result is a REPORT-ONLY diagnostic: it quantifies how much of an apparent
edge is explained by having tried many configurations. It does not prove
profitability, causality or future persistence, and it never replaces the
frozen-family certification verdict.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Sequence

import numpy as np
from scipy.stats import norm

EULER_GAMMA = float(np.euler_gamma)

DSR_SOURCES = {
    "psr": "Bailey & Lopez de Prado (2014); mlfinlab probabilistic_sharpe_ratio",
    "dsr": "Bailey & Lopez de Prado (2014); mlfinlab deflated_sharpe_ratio",
    "benchmark": "SR0 = sqrt(V) * [(1-gamma)*Phi^-1(1-1/N) + "
                 "gamma*Phi^-1(1-1/(N*e))]; gamma = Euler-Mascheroni",
}
PBO_SOURCES = {
    "cscv": "Bailey, Borwein, Lopez de Prado & Zhu (2014/2017) CSCV",
    "partition": "S contiguous blocks, all C(S, S/2) IS/OOS combinations",
    "logit": "omega = OOS average rank / (N+1); lambda = ln(omega/(1-omega))",
}


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def probabilistic_sharpe_ratio(
    sr: float,
    benchmark: float,
    n_obs: int,
    skew: float,
    kurtosis: float,
) -> dict[str, Any]:
    """PSR: probability the true Sharpe exceeds ``benchmark``.

    ``kurtosis`` is the raw (non-excess) kurtosis, so a normal distribution
    uses 3.0. Returns ``None`` fields when the denominator degenerates.
    """
    out: dict[str, Any] = {
        "sr": _finite_or_none(sr),
        "benchmark": _finite_or_none(benchmark),
        "n_obs": int(n_obs),
        "skew": _finite_or_none(skew),
        "kurtosis": _finite_or_none(kurtosis),
        "psr": None,
        "status": "degenerate_denominator",
        "promotion_role": "report_only",
        "sources": dict(DSR_SOURCES),
    }
    denominator_sq = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    if n_obs < 2 or denominator_sq <= 0 or not math.isfinite(denominator_sq):
        return out
    z = (sr - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denominator_sq)
    out["psr"] = float(norm.cdf(z))
    out["status"] = "ok"
    return out


def deflated_sharpe_ratio(
    sr: float,
    n_obs: int,
    skew: float,
    kurtosis: float,
    n_trials: int | None = None,
    trial_sharpes: Sequence[float] | np.ndarray | None = None,
    trial_sharpe_variance: float | None = None,
) -> dict[str, Any]:
    """DSR: PSR against the expected maximum Sharpe of N noise trials.

    The trial count N and the cross-trial Sharpe variance V must come from the
    trial ledger (every configuration ever evaluated, including failures).
    Supply either ``trial_sharpes`` or both ``n_trials`` and
    ``trial_sharpe_variance``.
    """
    if trial_sharpes is not None:
        values = np.asarray(trial_sharpes, dtype=float)
        values = values[np.isfinite(values)]
        if values.size < 2:
            raise ValueError("need at least two finite trial Sharpe estimates")
        n_trials = int(values.size)
        # ddof=0 matches the population variance used by the reference formula.
        trial_sharpe_variance = float(values.var())
    if not n_trials or n_trials < 2:
        raise ValueError("DSR requires the recorded number of independent trials")
    if trial_sharpe_variance is None or not math.isfinite(trial_sharpe_variance):
        raise ValueError("DSR requires the cross-trial Sharpe variance")
    variance = max(float(trial_sharpe_variance), 0.0)
    n = int(n_trials)
    benchmark = math.sqrt(variance) * (
        (1.0 - EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n)
        + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n * math.e))
    )
    result = probabilistic_sharpe_ratio(sr, float(benchmark), n_obs, skew, kurtosis)
    result.update({
        "dsr": result["psr"],
        "n_trials": n,
        "trial_sharpe_variance": variance,
        "benchmark_rule": "expected max Sharpe of N noise trials (DSR)",
        "note": "N and V must come from the full trial ledger, not an estimate.",
    })
    return result


def _block_sums(matrix: np.ndarray, n_slices: int) -> tuple[np.ndarray, ...]:
    """Per-block sufficient statistics so combinations need no re-slicing."""
    rows = matrix.shape[0] // n_slices
    blocks = matrix[: rows * n_slices].reshape(n_slices, rows, matrix.shape[1])
    count = np.full((n_slices, 1), float(rows))
    total = blocks.sum(axis=1)
    total_sq = (blocks ** 2).sum(axis=1)
    return count, total, total_sq


def _metric_from_sums(
    count: np.ndarray, total: np.ndarray, total_sq: np.ndarray, metric: str,
) -> np.ndarray:
    n = np.maximum(count, 1.0)
    mean = total / n
    if metric == "mean":
        return mean
    # Sample variance (ddof=1) per candidate; Sharpe is scale-free here.
    var = (total_sq - n * mean ** 2) / np.maximum(n - 1.0, 1.0)
    sd = np.sqrt(np.clip(var, 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 1e-15, mean / np.where(sd > 1e-15, sd, 1.0), 0.0)


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Average ranks for ties, 1 = worst ... N = best (per CSCV convention)."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    sorted_values = values[order]
    i = 0
    while i < values.size:
        j = i
        while j + 1 < values.size and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def backtest_overfitting_probability(
    returns: np.ndarray,
    n_slices: int = 16,
    metric: str = "sharpe",
    max_combinations: int | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """CSCV Probability of Backtest Overfitting for a matrix of trial returns.

    ``returns`` is T x N: synchronous per-period returns of EVERY configuration
    that was evaluated. PBO is the probability that the in-sample winner ranks
    at or below the out-of-sample median. It evaluates the selection process,
    never a single strategy.
    """
    if metric not in ("sharpe", "mean"):
        raise ValueError("metric must be 'sharpe' or 'mean'")
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("returns must be a T x N matrix")
    n_trials = int(matrix.shape[1])
    if n_trials < 2:
        raise ValueError("CSCV needs at least two candidate columns")
    if n_slices % 2 or n_slices < 2:
        raise ValueError("n_slices must be even and >= 2")

    finite_rows = np.isfinite(matrix).all(axis=1)
    dropped = int((~finite_rows).sum())
    matrix = matrix[finite_rows]
    if matrix.shape[0] < n_slices:
        raise ValueError("not enough synchronous rows for the requested slices")
    remainder = matrix.shape[0] % n_slices
    # Drop leading rows so the blocks are contiguous and equal-length.
    matrix = matrix[remainder:]
    n_obs = int(matrix.shape[0])

    count, total, total_sq = _block_sums(matrix, n_slices)
    half = n_slices // 2
    all_combos = list(combinations(range(n_slices), half))
    if max_combinations is not None and max_combinations < len(all_combos):
        rng = np.random.default_rng(seed)
        picked = rng.choice(len(all_combos), size=max_combinations, replace=False)
        all_combos = [all_combos[i] for i in sorted(picked)]

    logits: list[float] = []
    is_scores: list[float] = []
    oos_scores: list[float] = []
    oos_losses = 0
    full = np.arange(n_slices)
    for combo in all_combos:
        train_idx = np.asarray(combo)
        test_idx = np.setdiff1d(full, train_idx)
        train_metric = _metric_from_sums(
            count[train_idx].sum(axis=0), total[train_idx].sum(axis=0),
            total_sq[train_idx].sum(axis=0), metric,
        )
        test_metric = _metric_from_sums(
            count[test_idx].sum(axis=0), total[test_idx].sum(axis=0),
            total_sq[test_idx].sum(axis=0), metric,
        )
        winner = int(np.argmax(train_metric))
        ranks = _average_ranks(test_metric)
        omega = float(ranks[winner]) / (n_trials + 1.0)
        omega = min(max(omega, 1e-12), 1.0 - 1e-12)
        logits.append(math.log(omega / (1.0 - omega)))
        is_scores.append(float(train_metric[winner]))
        oos_scores.append(float(test_metric[winner]))
        # Mean out-of-sample return sign of the selected configuration.
        oos_mean = float(total[test_idx].sum(axis=0)[winner]
                         / max(count[test_idx].sum(), 1.0))
        if oos_mean <= 0:
            oos_losses += 1

    logit_arr = np.asarray(logits)
    is_arr = np.asarray(is_scores)
    oos_arr = np.asarray(oos_scores)
    slope = None
    if is_arr.size > 1 and float(is_arr.var()) > 0:
        slope = float(np.polyfit(is_arr, oos_arr, 1)[0])
    return {
        "pbo": float(np.mean(logit_arr <= 0.0)),
        "n_combinations": int(logit_arr.size),
        "n_trials": n_trials,
        "n_obs": n_obs,
        "n_slices": n_slices,
        "metric": metric,
        "dropped_rows": dropped,
        "median_logit": _finite_or_none(float(np.median(logit_arr))),
        "degradation_slope": slope,
        "prob_oos_loss": float(oos_losses / logit_arr.size),
        "mean_is_metric": _finite_or_none(float(is_arr.mean())),
        "mean_oos_metric": _finite_or_none(float(oos_arr.mean())),
        "status": "ok",
        "promotion_role": "report_only",
        "sources": dict(PBO_SOURCES),
        "note": "PBO measures the selection process over the supplied candidate "
                "matrix; it is not the probability that a strategy has no edge.",
    }
