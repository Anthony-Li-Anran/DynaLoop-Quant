"""Report-only experience reputation for harvested strategies.

A strategy's "star level" is accumulated from simulated-execution outcomes that
were attributed to it. The score is a Wilson lower bound on the success rate
with exponential half-life decay on evidence:

* a single early success never produces a perfect score (cold-start caution);
* old outcomes fade so the belief tracks the current market regime;
* a strategy with little evidence ranks below one with much evidence.

Sources: Evan Miller, "How Not To Sort By Average Rating" (2009) for the Wilson
lower bound; Josang & Ismail's Beta reputation model for the success/failure
tally; the half-life decay is the standard exponentially-weighted evidence
weight. These are established ranking heuristics, NOT statistical significance
tests. The score is descriptive: it is never a factor, a verdict, an
effectiveness claim, a return forecast, or an input to any freeze fingerprint.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

Z_95 = 1.96  # canonical 95% normal quantile, a stated constant, not tuned
DEFAULT_HALF_LIFE_DAYS = 30.0  # documented default; callers may override explicitly


def _parse_day(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def decayed_tally(
    events: list[dict[str, Any]],
    strategy_id: str,
    *,
    as_of: str,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> tuple[float, float]:
    """Return (success_weight, failure_weight) for one strategy at ``as_of``."""
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    now = _parse_day(as_of)
    successes = 0.0
    failures = 0.0
    for event in events:
        if strategy_id not in event.get("strategy_ids", []):
            continue
        outcome = event.get("outcome")
        if outcome not in ("success", "failure"):
            continue
        weight = 1.0
        if now is not None:
            when = _parse_day(event.get("recorded_at"))
            if when is not None:
                age_days = max(0.0, (now - when).total_seconds() / 86400.0)
                weight = 0.5 ** (age_days / half_life_days)
        if outcome == "success":
            successes += weight
        else:
            failures += weight
    return successes, failures


def wilson_lower_bound(successes: float, failures: float, z: float = Z_95) -> float:
    """Pessimistic success-rate bound; 0.0 when there is no evidence."""
    n = successes + failures
    if n <= 0:
        return 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - margin) / denom)


def experience_report(
    events: list[dict[str, Any]],
    *,
    as_of: str,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> dict[str, dict[str, Any]]:
    """Map each referenced strategy to its report-only reputation record."""
    strategy_ids = {
        sid for event in events for sid in event.get("strategy_ids", [])
    }
    report: dict[str, dict[str, Any]] = {}
    for sid in sorted(strategy_ids):
        successes, failures = decayed_tally(
            events, sid, as_of=as_of, half_life_days=half_life_days
        )
        n = successes + failures
        report[sid] = {
            "strategy_id": sid,
            "success_weight": round(successes, 6),
            "failure_weight": round(failures, 6),
            "evidence_weight": round(n, 6),
            "wilson_lower": round(wilson_lower_bound(successes, failures), 6),
            "stars": round(5.0 * wilson_lower_bound(successes, failures), 3),
            "has_evidence": n > 0,
            "report_only": True,
        }
    return report


__all__ = [
    "Z_95",
    "DEFAULT_HALF_LIFE_DAYS",
    "decayed_tally",
    "wilson_lower_bound",
    "experience_report",
]
