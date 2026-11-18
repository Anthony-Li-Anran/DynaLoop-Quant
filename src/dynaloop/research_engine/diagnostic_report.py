"""Report-only diagnostic bundle for a factor-research round.

Collects search-intensity and decay diagnostics into one mapping that can be
attached to a certification artifact WITHOUT changing the verdict. Every field
is descriptive. In particular this module never touches the family p-value,
the frozen fingerprint, the promotion status or the effective-factor list.

Inputs come from the frozen round's own trial ledger and per-period series;
nothing is recomputed on a window that has already been inspected.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from dynaloop.research_engine.search_bias import (
    backtest_overfitting_probability,
    deflated_sharpe_ratio,
)
from dynaloop.research_engine.trial_ledger import TrialLedger
from dynaloop.research_engine.decay import ic_decay_curve, ic_half_life


def build_diagnostic_report(
    ledger: TrialLedger,
    *,
    evaluation_returns: np.ndarray | None = None,
    ic_horizons: Sequence[int] | None = None,
    mean_ic_by_horizon: Sequence[float | None] | None = None,
    n_slices: int = 16,
) -> dict[str, Any]:
    """Assemble the descriptive diagnostics for one research round.

    ``ledger`` must contain every evaluated configuration (including failures).
    ``evaluation_returns`` is a T x N matrix of the trials' per-period returns
    on the evaluation grid; without it the PBO field is marked unavailable.
    IC-horizon inputs are optional; without them decay fields are unavailable.
    """
    report: dict[str, Any] = {
        "promotion_role": "report_only",
        "note": "Descriptive search-intensity and decay diagnostics. Cannot "
                "change the family p-value, fingerprint, status or effective list.",
    }
    n = ledger.n_trials
    report["search_intensity"] = {
        "n_independent_trials": n,
        "n_records": len(ledger),
    }
    sharpes = ledger.trial_sharpes()
    if sharpes.size >= 2:
        report["deflated_sharpe"] = deflated_sharpe_ratio(
            sr=float(sharpes.max()),
            n_obs=int(max(len(sharpes), 2)),
            skew=0.0,
            kurtosis=3.0,
            trial_sharpes=sharpes,
        )
        report["deflated_sharpe"]["note"] += (
            " Des illustrative (skew/kurtosis defaulted); supply observed moments "
            "from the ledger metrics for a final figure."
        )
    else:
        report["deflated_sharpe"] = {"status": "insufficient_trials", "dsr": None}

    if evaluation_returns is not None:
        report["backtest_overfitting"] = backtest_overfitting_probability(
            evaluation_returns, n_slices=n_slices)
    else:
        report["backtest_overfitting"] = {
            "status": "no_trial_return_matrix", "pbo": None}

    if ic_horizons is not None and mean_ic_by_horizon is not None:
        report["decay"] = ic_half_life(ic_horizons, mean_ic_by_horizon)
    else:
        report["decay"] = {"status": "no_ic_horizon_curve", "half_life_exponential": None}
    return report


def attach_report(
    certification: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    *,
    key: str = "search_diagnostics",
) -> dict[str, Any]:
    """Return a copy of ``certification`` with diagnostics attached.

    Asserts that all verdict-bearing fields are byte-identical afterwards, so
    attaching a report can never silently alter a frozen conclusion.
    """
    protected = (
        "family_p_value", "adjusted_p_value", "freeze_fingerprint",
        "fingerprint", "status", "effective_factor_ids",
    )
    out = dict(certification)
    out[key] = dict(diagnostics)
    for field in protected:
        if field in certification:
            if out.get(field) != certification[field]:
                raise AssertionError(f"diagnostic attachment changed {field}")
    return out
