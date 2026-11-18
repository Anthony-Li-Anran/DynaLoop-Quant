"""Cross-sectional preprocessing: winsorisation, standardisation, neutralisation.

Upstream practice (checked 2026-11-16):

* Qlib ``RobustZScoreNorm`` -- median / (MAD * 1.4826) with optional clipping
  to [-3, 3]; ``CSZScoreNorm`` / ``CSRankNorm`` -- per-datetime cross-sectional
  standardisation.
* Industry / size neutralisation -- per-date cross-sectional OLS of the raw
  factor on industry dummies and log market cap; the residual is the
  neutralised factor, then re-standardised. This is the standard sell-side and
  FactorBench-style construction.

Neutralisation is a research constraint, not a fixed template: which variables
to control is decided by the hypothesis. Both the raw and the neutralised
version must be reported side by side. All outputs are report-only.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

NEUTRALISATION_SOURCES = {
    "winsorise": "Qlib RobustZScoreNorm: median / (MAD*1.4826), clip outliers",
    "neutralise": "cross-sectional OLS on industry dummies + log market cap; "
                  "residual re-standardised (FactorBench-style residual signal)",
}


def robust_winsorise(values: Sequence[float], clip: float = 3.0) -> np.ndarray:
    """Median/MAD winsorisation: clip to median +/- clip * 1.4826 * MAD."""
    x = np.asarray(values, dtype=float)
    out = x.copy()
    finite = np.isfinite(x)
    if finite.sum() < 2:
        return out
    median = float(np.median(x[finite]))
    mad = float(np.median(np.abs(x[finite] - median)))
    scale = 1.4826 * mad
    if scale <= 1e-15:
        return out
    out[finite] = np.clip(x[finite], median - clip * scale, median + clip * scale)
    return out


def cross_sectional_zscore(values: Sequence[float], robust: bool = False) -> np.ndarray:
    """Per-cross-section z-score; robust variant uses median/MAD (Qlib)."""
    x = np.asarray(values, dtype=float)
    out = np.full(x.shape, np.nan)
    finite = np.isfinite(x)
    if finite.sum() < 2:
        return out
    v = x[finite]
    if robust:
        centre = float(np.median(v))
        scale = 1.4826 * float(np.median(np.abs(v - centre)))
    else:
        centre = float(v.mean())
        scale = float(v.std(ddof=1))
    # A near-zero scale means the cross-section carries no dispersion. Using
    # an absolute floor alone would amplify floating-point residue (e.g. a
    # 1e-14 residual from a perfectly neutralised factor) into a spurious
    # O(1) signal. The relative test follows Qlib's "skip zero-variance
    # columns" intent while staying safe at large magnitudes.
    if (not np.isfinite(scale)
            or scale <= 1e-12 * max(1.0, abs(centre))):
        out[finite] = 0.0
        return out
    out[finite] = (v - centre) / scale
    return out


def neutralise_cross_section(
    scores: Sequence[float],
    industries: Sequence[Any] | None = None,
    market_caps: Sequence[float] | None = None,
    min_industry_size: int = 5,
    standardise: bool = True,
) -> dict[str, Any]:
    """Residual of the factor after removing industry and log-size exposure.

    Industries with fewer than ``min_industry_size`` usable members are merged
    into a single group so the regression does not fit noise. Rows with missing
    scores are returned as NaN and excluded from the regression.
    """
    x = np.asarray(scores, dtype=float)
    n = x.size
    usable = np.isfinite(x)
    if industries is not None:
        usable &= np.asarray([v is not None for v in industries])
    if market_caps is not None:
        caps = np.asarray(market_caps, dtype=float)
        usable &= np.isfinite(caps) & (caps > 0)
    if usable.sum() < 5:
        return {
            "residual": np.full(n, np.nan),
            "n_used": int(usable.sum()),
            "r_squared": None,
            "status": "insufficient_cross_section",
            "promotion_role": "report_only",
            "sources": dict(NEUTRALISATION_SOURCES),
        }

    columns: list[np.ndarray] = [np.ones(int(usable.sum()))]
    if industries is not None:
        labels = np.asarray(industries, dtype=object)[usable]
        uniq, counts = np.unique(labels, return_counts=True)
        # Merge tiny industries into one bucket for a stable regression.
        small = set(uniq[counts < min_industry_size])
        if small:
            labels = np.asarray(["__SMALL__" if v in small else v for v in labels],
                                dtype=object)
        levels = sorted(set(labels.tolist()))
        for level in levels[1:]:  # drop one level to avoid perfect collinearity
            columns.append((labels == level).astype(float))
    if market_caps is not None:
        log_cap = np.log(caps[usable])
        columns.append((log_cap - log_cap.mean()) / max(log_cap.std(), 1e-12))

    design = np.column_stack(columns)
    y = x[usable]
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ beta
    resid = y - fitted
    total_ss = float(((y - y.mean()) ** 2).sum())
    r_squared = (1.0 - float((resid ** 2).sum()) / total_ss) if total_ss > 0 else None

    residual = np.full(n, np.nan)
    residual[usable] = resid
    if standardise:
        residual = cross_sectional_zscore(residual)
    return {
        "residual": residual,
        "n_used": int(usable.sum()),
        "r_squared": r_squared,
        "status": "ok",
        "promotion_role": "report_only",
        "sources": dict(NEUTRALISATION_SOURCES),
        "note": "Report the raw and neutralised versions side by side; a drop "
                "after neutralisation means the raw edge was largely exposure.",
    }


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    from scipy.stats import rankdata
    if a.size < 3:
        return None
    ra, rb = rankdata(a), rankdata(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = float(np.sqrt((ra @ ra) * (rb @ rb)))
    if denom <= 0:
        return None
    return float((ra @ rb) / denom)


def residual_information_coefficient(
    scores: Sequence[float],
    forward_returns: Sequence[float],
    industries: Sequence[Any] | None = None,
    market_caps: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Rank IC of the factor residual after style removal.

    This answers "does the factor carry information BEYOND industry/size",
    which is the test that collapses most mined factors in FactorBench.
    """
    neutral = neutralise_cross_section(scores, industries, market_caps)
    resid = neutral["residual"]
    ret = np.asarray(forward_returns, dtype=float)
    valid = np.isfinite(resid) & np.isfinite(ret)
    ic = None
    if valid.sum() >= 3:
        ic = _spearman(resid[valid], ret[valid])
    return {
        "residual_rank_ic": ic,
        "n_pairs": int(valid.sum()),
        "neutralisation_r_squared": neutral["r_squared"],
        "status": neutral["status"] if ic is not None else "insufficient_pairs",
        "promotion_role": "report_only",
        "sources": dict(NEUTRALISATION_SOURCES),
    }
