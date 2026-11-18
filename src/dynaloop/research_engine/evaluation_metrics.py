"""Report-only factor evaluation metrics aligned with upstream practice.

Nothing in this module participates in a promotion decision. Every returned
mapping carries ``promotion_role = "report_only"`` so callers cannot silently
turn a descriptive number into a veto.

Upstream references (checked 2026-11-15 against repository sources):

* Qlib ``qlib/contrib/eva/alpha.py::pred_autocorr`` -- per-period Pearson
  correlation between the current prediction cross-section and the lagged one.
* alphalens ``performance.factor_rank_autocorrelation`` -- the same idea on
  factor ranks rather than raw values, used as a turnover / signal-decay proxy.
* Newey & West (1987, Econometrica) HAC with a Bartlett kernel; qweave's
  ``t_nw`` and the ``strategy-tail`` HAC specification use it for IC series
  whose overlapping forward returns induce serial correlation.
* Newey & West (1994) automatic bandwidth ``floor(4 * (n/100)^(2/9))`` as used
  by open-source factor frameworks (e.g. FactorTest) and matching statsmodels'
  HAC lag-selection convention.

The long-run variance may be non-positive in finite samples. In that case the
HAC t statistic is returned as ``None`` with an explicit status; it is NEVER
silently replaced by the naive t statistic.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import rankdata

HAC_LAG_RULE = "Newey-West (1994) automatic bandwidth: floor(4 * (n/100)^(2/9))"
HAC_SOURCES = {
    "hac_t_stat": "Newey & West (1987) Bartlett-kernel HAC; qweave t_nw; "
                  "strategy-tail HAC specification",
    "hac_lag": HAC_LAG_RULE,
    "long_run_variance": "gamma_0 + 2 * sum_{l=1..L} (1 - l/(L+1)) * gamma_l",
}
AUTOCORR_SOURCES = {
    "value_autocorr_lag1": "Qlib qlib.contrib.eva.alpha.pred_autocorr (lag=1, "
                           "per-period cross-sectional Pearson correlation)",
    "rank_autocorr_lag1": "alphalens.performance.factor_rank_autocorrelation "
                          "(same-period rank vectors, Spearman)",
    "turnover_proxy": "open-source factor frameworks: (1 - mean rank autocorr) / 2",
}


def _pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    """Pearson correlation, or None when either vector is degenerate."""
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.size < 2 or x.size != y.size:
        return None
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        return None
    centred_x = x - x.mean()
    centred_y = y - y.mean()
    denom = float(math.sqrt(float(centred_x @ centred_x) * float(centred_y @ centred_y)))
    if denom <= 0 or not math.isfinite(denom):
        return None
    value = float(centred_x @ centred_y) / denom
    return value if math.isfinite(value) else None


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman correlation via average ranks for ties."""
    return _pearson(rankdata(a), rankdata(b))


def hac_t_statistic(
    series: Sequence[float] | np.ndarray, lag: int | None = None,
) -> dict[str, Any]:
    """Naive and HAC (Bartlett kernel) t statistics for the mean of a series.

    ``lag=None`` selects the Newey-West (1994) automatic bandwidth. An explicit
    lag is allowed for sensitivity analysis but is recorded in the output.
    """
    raw = np.asarray(series, dtype=float)
    values = raw[np.isfinite(raw)]
    n = int(values.size)
    out: dict[str, Any] = {
        "periods": n,
        "mean": None,
        "naive_t_stat": None,
        "hac_t_stat": None,
        "hac_lag": None,
        "hac_lag_rule": HAC_LAG_RULE,
        "long_run_variance": None,
        "status": "insufficient_periods",
        "promotion_role": "report_only",
        "sources": dict(HAC_SOURCES),
        "note": "Descriptive only. A non-positive long-run variance yields null "
                "rather than falling back to the naive t statistic.",
    }
    if n < 3:
        return out
    mean = float(values.mean())
    centred = values - mean
    denominator = n - 1  # ddof=1 keeps lag=0 identical to the conventional t
    variance = float(centred @ centred) / denominator
    out["mean"] = mean
    if not (math.isfinite(variance) and variance > 0):
        out["status"] = "zero_variance"
        return out
    out["naive_t_stat"] = float(mean / math.sqrt(variance / n))

    automatic = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    selected = automatic if lag is None else int(lag)
    if selected < 0:
        raise ValueError("lag must be non-negative")
    lags = int(min(selected, n - 2))
    out["hac_lag"] = lags

    long_run_variance = variance
    for order in range(1, lags + 1):
        gamma = float(centred[order:] @ centred[:-order]) / denominator
        long_run_variance += 2.0 * (1.0 - order / (lags + 1)) * gamma
    out["long_run_variance"] = (float(long_run_variance)
                                if math.isfinite(long_run_variance) else None)
    if not (math.isfinite(long_run_variance) and long_run_variance > 0):
        out["status"] = "non_positive_long_run_variance"
        return out
    out["hac_t_stat"] = float(mean / math.sqrt(long_run_variance / n))
    out["status"] = "ok"
    return out


def factor_autocorrelation(
    frames: Sequence[Mapping[str, float]], min_pairs: int = 2,
) -> dict[str, Any]:
    """Lag-1 cross-sectional autocorrelation of factor values and factor ranks.

    ``frames[t]`` maps a symbol to that period's factor score. Only symbols
    present in both adjacent periods are compared, so a changing point-in-time
    universe never fabricates an observation.
    """
    if min_pairs < 2:
        raise ValueError("min_pairs must be at least 2")
    value_series: list[float | None] = []
    rank_series: list[float | None] = []
    pair_counts: list[int] = []
    for t in range(1, len(frames)):
        current, previous = frames[t], frames[t - 1]
        common = sorted(set(current).intersection(previous))
        pair_counts.append(len(common))
        if len(common) < min_pairs:
            value_series.append(None)
            rank_series.append(None)
            continue
        a = np.asarray([current[key] for key in common], dtype=float)
        b = np.asarray([previous[key] for key in common], dtype=float)
        usable = np.isfinite(a) & np.isfinite(b)
        if int(usable.sum()) < min_pairs:
            value_series.append(None)
            rank_series.append(None)
            continue
        value_series.append(_pearson(a[usable], b[usable]))
        rank_series.append(_spearman(a[usable], b[usable]))

    def _mean(values: list[float | None]) -> float | None:
        finite = [v for v in values if v is not None and math.isfinite(v)]
        return float(np.mean(finite)) if finite else None

    mean_value = _mean(value_series)
    mean_rank = _mean(rank_series)
    out: dict[str, Any] = {
        "lag": 1,
        "comparable_periods": len(value_series),
        "valid_periods": sum(v is not None for v in rank_series),
        "min_pairs": min_pairs,
        "mean_common_symbols": (float(np.mean(pair_counts)) if pair_counts else None),
        "value_autocorr_lag1": mean_value,
        "rank_autocorr_lag1": mean_rank,
        "turnover_proxy_from_rank_autocorr": ((1.0 - mean_rank) / 2.0
                                              if mean_rank is not None else None),
        "per_period_value_autocorr": value_series,
        "per_period_rank_autocorr": rank_series,
        "status": "ok" if mean_rank is not None else "insufficient_overlap",
        "promotion_role": "report_only",
        "sources": dict(AUTOCORR_SOURCES),
        "note": "Qlib uses raw prediction values; alphalens uses factor ranks. "
                "Both are reported. The turnover proxy is NOT the realised "
                "portfolio turnover reported by the cost model.",
    }
    return out


def series_lag1_autocorrelation(
    values: Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    """Lag-1 autocorrelation of a single time series (timing-channel analogue)."""
    raw = np.asarray(values, dtype=float)
    pairs = [(float(a), float(b)) for a, b in zip(raw[:-1], raw[1:])
             if math.isfinite(float(a)) and math.isfinite(float(b))]
    a = np.asarray([p[0] for p in pairs], dtype=float)
    b = np.asarray([p[1] for p in pairs], dtype=float)
    value = _pearson(a, b)
    rank = _spearman(a, b)
    return {
        "lag": 1,
        "valid_pairs": len(pairs),
        "value_autocorr_lag1": value,
        "rank_autocorr_lag1": rank,
        "status": "ok" if value is not None else "insufficient_or_degenerate",
        "promotion_role": "report_only",
        "sources": {
            "value_autocorr_lag1": "Qlib pred_autocorr (lag=1) applied to the "
                                  "single-instrument prediction series",
            "rank_autocorr_lag1": "alphalens factor_rank_autocorrelation applied "
                                  "to the same series",
        },
        "note": "Descriptive serial-dependence diagnostic; it motivates the HAC "
                "correction but is not an acceptance test.",
    }
