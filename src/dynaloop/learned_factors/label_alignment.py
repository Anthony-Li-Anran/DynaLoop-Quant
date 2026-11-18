"""Flexible decisions, fixed evaluation windows.

Design (Anthony 2026-11-16): trading is opportunistic -- enter when conditions
are right, not on an institution-style fixed cadence. But effectiveness is
always measured over fixed calendar windows (a week, a month), which are the
"periods" of the family-wise test. Two decoupled layers:

1. Evaluation window -- fixed cadence (weekly/monthly). Each window is one
   scoring period. The number of windows fixes the test's period count.
2. Decision trigger -- a rule that picks WHEN inside a window to enter, from
   information available no later than the entry itself. A window with no
   trigger simply does not trade. The rule is frozen in the preregistration,
   so the entry time is not chosen with hindsight.

The label is close[window_end]/close[entry]-1: hold from the triggered entry
to the end of the fixed evaluation window. Because each label lives strictly
inside one window, windows are non-overlapping and no label can straddle a
train/valid/test boundary (the grid analogue of purging, by construction).

Authority: Qlib's 1-day label is a replaceable default (A-share T+1);
FactorBench uses one fixed forward-return target for fair comparison; Lopez de
Prado (2018) requires that label windows not overlap split boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

WINDOW_FREQUENCIES = ("weekly", "monthly")
TRIGGER_KINDS = ("window_start", "threshold")


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """Fixed evaluation-window cadence -- the unit of statistical scoring."""

    frequency: str = "monthly"   # weekly / monthly
    execution_lag: int = 1       # earliest entry: T+1 close (A-share T+1)

    def __post_init__(self) -> None:
        if self.frequency not in WINDOW_FREQUENCIES:
            raise ValueError(f"frequency must be one of {WINDOW_FREQUENCIES}")
        if self.execution_lag < 1:
            raise ValueError("execution_lag must be >= 1 (T+1 rule)")

    def to_dict(self) -> dict[str, Any]:
        return {"frequency": self.frequency, "execution_lag": self.execution_lag}


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    """The entry rule, frozen with the family before any evaluation period."""

    kind: str = "window_start"
    threshold: float | None = None  # required for the threshold trigger

    def __post_init__(self) -> None:
        if self.kind not in TRIGGER_KINDS:
            raise ValueError(f"trigger kind must be one of {TRIGGER_KINDS}")
        if self.kind == "threshold" and self.threshold is None:
            raise ValueError("threshold trigger requires a threshold")

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"kind": self.kind}
        if self.threshold is not None:
            body["threshold"] = self.threshold
        return body


@dataclass(frozen=True, slots=True)
class EvaluationWindow:
    """One fixed scoring window on the trading calendar."""

    start_pos: int
    end_pos: int
    start_date: str
    end_date: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_pos": self.start_pos, "end_pos": self.end_pos,
            "start_date": self.start_date, "end_date": self.end_date,
        }


def build_windows(
    calendar: pd.DatetimeIndex, spec: WindowSpec | None = None,
) -> tuple[EvaluationWindow, ...]:
    """Contiguous, non-overlapping weekly/monthly windows over the calendar."""
    spec = spec or WindowSpec()
    key = calendar.to_period("W" if spec.frequency == "weekly" else "M")
    groups: dict[Any, list[int]] = {}
    for pos, period in enumerate(key):
        groups.setdefault(period, []).append(pos)
    out = []
    for positions in groups.values():
        lo, hi = int(positions[0]), int(positions[-1])
        if hi <= lo:
            continue
        out.append(EvaluationWindow(
            start_pos=lo, end_pos=hi,
            start_date=calendar[lo].date().isoformat(),
            end_date=calendar[hi].date().isoformat(),
        ))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Decision:
    """One triggered entry inside a window, with its fixed-window target."""

    window: EvaluationWindow
    entry_pos: int
    entry_date: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window.to_dict(),
            "entry_pos": self.entry_pos,
            "entry_date": self.entry_date,
        }


def pick_entry(
    window: EvaluationWindow,
    calendar: pd.DatetimeIndex,
    signal: Sequence[float],
    spec: TriggerSpec,
    window_spec: WindowSpec,
) -> Decision | None:
    """Choose the entry position inside a window from information at entry.

    ``window_start`` enters at the first tradable session (T+1 within the
    window). ``threshold`` enters at the first session whose signal (known at
    that session) exceeds the frozen threshold; if none does, the window is
    skipped. No rule may look at the window end or beyond.
    """
    lo = window.start_pos + window_spec.execution_lag
    hi = window.end_pos - 1  # need at least one bar between entry and window end
    if lo > hi:
        return None
    sig = np.asarray(signal, dtype=float)
    if spec.kind == "window_start":
        entry = lo
    else:
        entry = None
        for pos in range(lo, hi + 1):
            value = sig[pos] if pos < len(sig) else np.nan
            if np.isfinite(value) and value > float(spec.threshold):
                entry = pos
                break
        if entry is None:
            return None
    return Decision(
        window=window,
        entry_pos=entry,
        entry_date=calendar[entry].date().isoformat(),
    )


def window_target(close: Sequence[float], decision: Decision) -> float | None:
    """close[window_end]/close[entry]-1, the fixed-window scoring target."""
    arr = np.asarray(close, dtype=float)
    entry = float(arr[decision.entry_pos])
    end = float(arr[decision.window.end_pos])
    if not (np.isfinite(entry) and np.isfinite(end) and entry > 0):
        return None
    value = end / entry - 1.0
    return float(value) if np.isfinite(value) else None


def assign_windows(
    windows: Sequence[EvaluationWindow],
    segments: Mapping[str, tuple[str, str]],
    calendar: pd.DatetimeIndex,
) -> dict[str, int]:
    """Map each window to its segment by start date; reject boundary straddles.

    A window belongs to a segment only if its entire [start,end] lies inside
    that segment. Windows straddling a split are dropped from scoring (grid
    purging), and the dropped count is returned as evidence.
    """
    bounds = {
        name: (int(np.searchsorted(calendar, pd.Timestamp(start), side="left")),
               int(np.searchsorted(calendar, pd.Timestamp(end), side="right")) - 1)
        for name, (start, end) in segments.items()
    }
    assignment: dict[str, int] = {}
    for window in windows:
        for name, (lo, hi) in bounds.items():
            if lo <= window.start_pos and window.end_pos <= hi:
                assignment[name] = assignment.get(name, 0) + 1
                break
    return assignment
