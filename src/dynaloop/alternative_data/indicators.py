"""Pure micro-structure indicators for the A-share sentiment cycle.

Faithful port of the rule definitions in 314405571-star/a-share-sentiment-cycle
(docs/算法总结.md, MIT). No network, no training, no labels. Every threshold is
a fixed, documented trading-practice value, not a fitted parameter; the engine
carrying these signals is report-only and makes no return claim.

Known scope limit inherited from the source: a uniform 9.5% price-limit test is
used; ChiNext/STAR (20%), ST (5%) and BSE (30%) boards are NOT modelled. This
is surfaced, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

LIMIT_UP = 0.095
LIMIT_DOWN = -0.095
LIMIT_EPS = 1e-9
SKY_FLOOR_UP = 0.09
SKY_FLOOR_DOWN = -0.09
BREAK_BURST_MIN = 5
BREAK_FACE = 0.08
ONE_WORD_TURNOVER = 0.01


@dataclass(frozen=True, slots=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    preclose: float
    turnover: float | None = None  # 0..1 fraction; None disables one-word filter


def change(bar: Bar) -> float:
    return bar.close / bar.preclose - 1.0 if bar.preclose > 0 else 0.0


def is_limit_up(bar: Bar) -> bool:
    if bar.preclose <= 0:
        return False
    if (bar.open == bar.high == bar.close
            and bar.turnover is not None and bar.turnover < ONE_WORD_TURNOVER):
        return False  # one-word / suspended-like print: not a meaningful seal
    return change(bar) >= LIMIT_UP - LIMIT_EPS


def is_break_up(bar: Bar) -> bool:
    if bar.preclose <= 0:
        return False
    return (bar.high / bar.preclose - 1.0 >= LIMIT_UP - LIMIT_EPS
            and bar.close < bar.high)


def is_limit_down(bar: Bar) -> bool:
    return bar.preclose > 0 and change(bar) <= LIMIT_DOWN + LIMIT_EPS


def attempted_board_number(history: list[Bar], bar: Bar) -> int:
    """Boards this bar attempts: consecutive seals before today, plus one.

    Fixes the source's headline bug: a break-up bar must count the *attempted*
    board, otherwise its board number is 0 and the fry rate is always 0.
    """
    if not (is_limit_up(bar) or is_break_up(bar)):
        return 0
    count = 0
    for past in reversed(history):
        if is_limit_up(past):
            count += 1
        else:
            break
    return count + 1


def burst_count(history: list[Bar], window: int = 20) -> int:
    """Number of limit-up seals in the trailing window (excluding today)."""
    return sum(1 for bar in history[-window:] if is_limit_up(bar))


def is_high_face(bar: Bar, history: list[Bar]) -> bool:
    """A recognised high board giving back >=8% intraday from its high."""
    return (burst_count(history) >= BREAK_BURST_MIN
            and (bar.high - bar.close) / bar.preclose >= BREAK_FACE
            if bar.preclose > 0 else False)


def is_sky_floor(bar: Bar, history: list[Bar]) -> bool:
    """Same-day limit-up to limit-down on a recognised high board."""
    if bar.preclose <= 0 or not is_high_face(bar, history):
        return False
    return change(bar) <= SKY_FLOOR_DOWN + LIMIT_EPS and (
        bar.high / bar.preclose - 1.0 >= SKY_FLOOR_UP - LIMIT_EPS
    )


__all__ = [
    "Bar", "change", "is_limit_up", "is_break_up", "is_limit_down",
    "attempted_board_number", "burst_count", "is_high_face", "is_sky_floor",
]
