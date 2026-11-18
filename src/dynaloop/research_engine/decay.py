"""Factor signal decay: IC horizon curve and half-life.

Factors do not stay effective. The evaluation window and the rebalancing
frequency must be derived from the measured decay, not assumed.

References (checked 2026-11-16):
* IC time decay: IC(h) = corr(Factor_t, Ret_{t+1+h}); half-life is the horizon
  at which the mean IC falls to half its initial value (sell-side standard,
  e.g. Founder Securities single-factor evaluation framework).
* Exponential fit IC(h) ~ IC0 * exp(-lambda * h), half-life = ln2 / lambda.
* Flint & Vermaak (2023, JPM 49(2)) for exposure half-life and the rule that
  rebalancing frequency should follow the measured half-life.

Everything here is report-only: decay informs window design and monitoring,
it is never a stand-alone acceptance or rejection rule.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import rankdata

DECAY_SOURCES = {
    "curve": "IC(h) = corr(Factor_t, Ret_{t+1+h}); mean over decision dates",
    "half_life": "exponential fit IC0*exp(-lambda*h), half-life = ln2/lambda; "
                 "linear-interpolation fallback reported alongside",
    "usage": "Flint & Vermaak (2023): rebalance frequency follows half-life",
}


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 3:
        return None
    ra, rb = rankdata(a), rankdata(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = float(np.sqrt((ra @ ra) * (rb @ rb)))
    if denom <= 0:
        return None
    return float((ra @ rb) / denom)


def ic_decay_curve(
    score_frames: Sequence[Mapping[str, float]],
    returns_by_horizon: Mapping[int, Sequence[Mapping[str, float]]],
) -> dict[str, Any]:
    """Mean rank IC at each forward horizon.

    ``score_frames[t]`` maps symbol -> score at decision date t.
    ``returns_by_horizon[h][t]`` maps symbol -> forward return over horizon h
    measured from the same decision date. Only symbols present in both are used.
    """
    horizons = sorted(int(h) for h in returns_by_horizon)
    mean_ics: list[float | None] = []
    per_period: dict[str, list[float | None]] = {}
    for h in horizons:
        frames = returns_by_horizon[h]
        ics: list[float | None] = []
        for scores, rets in zip(score_frames, frames):
            common = sorted(set(scores).intersection(rets))
            if len(common) < 3:
                ics.append(None)
                continue
            a = np.asarray([scores[s] for s in common], dtype=float)
            b = np.asarray([rets[s] for s in common], dtype=float)
            valid = np.isfinite(a) & np.isfinite(b)
            ics.append(_spearman(a[valid], b[valid]) if valid.sum() >= 3 else None)
        finite = [v for v in ics if v is not None and math.isfinite(v)]
        mean_ics.append(float(np.mean(finite)) if finite else None)
        per_period[str(h)] = ics
    return {
        "horizons": horizons,
        "mean_ic": mean_ics,
        "per_period_ic": per_period,
        "status": "ok" if any(v is not None for v in mean_ics) else "insufficient_data",
        "promotion_role": "report_only",
        "sources": dict(DECAY_SOURCES),
    }


def ic_half_life(
    horizons: Sequence[int],
    mean_ic: Sequence[float | None],
) -> dict[str, Any]:
    """Half-life from an IC horizon curve.

    Exponential fit uses only strictly positive IC points (log-linear
    regression of IC on horizon). The interpolated estimate locates the first
    crossing of IC0/2. Both are reported; disagreement is itself a warning that
    the decay is not cleanly exponential.
    """
    h = np.asarray(horizons, dtype=float)
    ic = np.asarray([np.nan if v is None else v for v in mean_ic], dtype=float)
    out: dict[str, Any] = {
        "horizons": [int(v) for v in h],
        "half_life_exponential": None,
        "half_life_interpolated": None,
        "decay_rate_lambda": None,
        "fit_r_squared": None,
        "status": "insufficient_positive_ic",
        "promotion_role": "report_only",
        "sources": dict(DECAY_SOURCES),
    }
    valid = np.isfinite(ic) & (ic > 0)
    if valid.sum() >= 2 and np.ptp(h[valid]) > 0:
        x = h[valid]
        y = np.log(ic[valid])
        slope, intercept = np.polyfit(x, y, 1)
        fitted = intercept + slope * x
        ss_res = float(((y - fitted) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        out["fit_r_squared"] = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
        if slope < 0:
            lam = -float(slope)
            out["decay_rate_lambda"] = lam
            out["half_life_exponential"] = float(math.log(2.0) / lam)
            out["status"] = "ok"

    finite = np.isfinite(ic)
    if finite.sum() >= 2 and finite[0] and ic[0] > 0:
        target = ic[0] / 2.0
        for i in range(1, len(h)):
            if not (np.isfinite(ic[i]) and np.isfinite(ic[i - 1])):
                continue
            if ic[i - 1] >= target >= ic[i] and ic[i - 1] > ic[i]:
                frac = (ic[i - 1] - target) / (ic[i - 1] - ic[i])
                out["half_life_interpolated"] = float(h[i - 1] + frac * (h[i] - h[i - 1]))
                break
    if out["status"] != "ok" and out["half_life_interpolated"] is not None:
        out["status"] = "interpolated_only"
    return out
