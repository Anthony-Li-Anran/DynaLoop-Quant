"""Rule-based A-share sentiment-cycle state machine.

Faithful port of 314405571-star/a-share-sentiment-cycle (MIT, docs/算法总结.md):
L1 global 0-10, L2 main-line 0-13, L3 leader signal, two-day ebb confirmation,
and position tiers T0-T5. No training, no fitted parameters, no return claim.

The output is a bounded, auditable regime classification plus a position-size
ceiling -- NOT a price target, NOT a factor verdict. Per the source's own
honest limitation, thresholds come from trading practice and have no
statistical significance test; this engine is report-only and must never be
wired to an order router or treated as validated evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from dynaloop.alternative_data.indicators import (
    is_break_up,
    is_high_face,
    is_limit_down,
    is_limit_up,
    is_sky_floor,
)


@dataclass(frozen=True, slots=True)
class Config:
    systemic_drop: float = -0.025
    drop_ratio: float = 1.2
    high_face_soft: int = 8
    high_face_hard: int = 15
    sector_min_count: int = 3
    sector_hold_ratio: float = 0.5
    leader_break_warn: int = 1
    leader_break_confirm: int = 2
    sky_floor_warn: int = 1
    sky_floor_confirm: int = 2
    ebb_l2: int = 6
    ebb_prev_l2: int = 7
    baseline_window: int = 20
    sequence_cap: int = 60
    position_tiers: tuple[int, int, int, int] = (11, 8, 5, 2)  # L2 cut points


@dataclass(slots=True)
class DailyMarket:
    """One day's already-classified market facts (fed by a data adapter)."""

    date: str
    hs300_return: float | None = None
    limit_up_seals: int = 0                       # non-broken seals, market-wide
    limit_down_count: int = 0
    high_face_count: int = 0                      # market-wide
    sky_floor_count: int = 0
    sector_counts: Mapping[str, int] = field(default_factory=dict)  # hot stocks per sector
    sector_high_counts: Mapping[str, int] = field(default_factory=dict)  # boards>=3
    sector_fry_counts: Mapping[str, int] = field(default_factory=dict)  # boards>=3 broken
    sector_promotions: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    # sector -> (yesterday sealed count, still sealed today count)
    board_leaders: Sequence[tuple[str, int, float, bool]] = ()
    # (code, boards, turnover, is_broken) for main-line candidate leaders


@dataclass(slots=True)
class State:
    prev_main_sector: str | None = None
    prev_leader: str | None = None
    break_days: int = 0
    prev_l2: int = 0
    prev_ratio_trigger: bool = False
    fry_rate_seq: list[float] = field(default_factory=list)
    promote_rate_seq: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prev_main_sector": self.prev_main_sector,
            "prev_leader": self.prev_leader,
            "break_days": self.break_days,
            "prev_l2": self.prev_l2,
            "prev_ratio_trigger": self.prev_ratio_trigger,
            "fry_rate_seq": list(self.fry_rate_seq),
            "promote_rate_seq": list(self.promote_rate_seq),
        }


@dataclass(frozen=True, slots=True)
class Snapshot:
    date: str
    l1: float
    l2: float
    l3: str                    # none | warning | confirm
    main_sector: str | None
    sector_sticky: bool
    ebb: bool
    position_tier: str         # T0..T5
    position_single: float
    position_total: float
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date, "l1": self.l1, "l2": self.l2, "l3": self.l3,
            "main_sector": self.main_sector, "sector_sticky": self.sector_sticky,
            "ebb": self.ebb, "position_tier": self.position_tier,
            "position_single": self.position_single,
            "position_total": self.position_total,
            "diagnostics": dict(self.diagnostics),
        }


def _mean(values: Sequence[float], default: float) -> float:
    return sum(values) / len(values) if values else default


def _score_l1(day: DailyMarket, cfg: Config, state: State) -> tuple[float, bool]:
    score = 10.0
    if day.hs300_return is not None and day.hs300_return <= cfg.systemic_drop:
        score -= 4.0
    ratio_trigger = (
        day.limit_up_seals > 0
        and day.limit_down_count / day.limit_up_seals > cfg.drop_ratio
    )
    if ratio_trigger and state.prev_ratio_trigger:
        score -= 3.0
    if day.high_face_count >= cfg.high_face_hard:
        score -= 3.0
    elif day.high_face_count >= cfg.high_face_soft:
        score -= 1.0
    return max(0.0, min(10.0, score)), ratio_trigger


def _pick_main_sector(day: DailyMarket, cfg: Config, state: State) -> tuple[str | None, bool]:
    if not day.sector_counts:
        return None, False
    challenger = max(day.sector_counts, key=lambda k: day.sector_counts[k])
    top_n = day.sector_counts[challenger]
    if top_n < cfg.sector_min_count:
        return None, False
    floor = max(cfg.sector_min_count, cfg.sector_hold_ratio * top_n)
    if (state.prev_main_sector is not None
            and day.sector_counts.get(state.prev_main_sector, 0) >= floor):
        return state.prev_main_sector, True
    return challenger, False


def _score_l2(day: DailyMarket, cfg: Config, state: State, sector: str | None) -> tuple[int, float, float]:
    if sector is None:
        return 0, 0.0, 0.0
    # tier completeness
    boards = [b for _, b, _, broken in day.board_leaders if not broken]
    n_high_boards = sum(1 for b in boards if b >= 4)
    s_tier = 4 if n_high_boards >= 3 else (2 if n_high_boards >= 1 else 0)
    # fry-rate deviation vs rolling baseline (baseline BEFORE appending today)
    high_total = day.sector_high_counts.get(sector, 0)
    fry_today = (
        day.sector_fry_counts.get(sector, 0) / high_total if high_total > 0 else 0.0
    )
    fry_base = _mean(state.fry_rate_seq[-cfg.baseline_window:], 0.3)
    if high_total < 2:
        s_fry = 2  # small-sample neutral
    elif fry_today < fry_base:
        s_fry = 4
    elif fry_today - fry_base <= 0.15:
        s_fry = 2
    else:
        s_fry = 0
    # promotion-rate deviation
    sealed, still = day.sector_promotions.get(sector, (0, 0))
    promote_today = still / sealed if sealed > 0 else 0.0
    promote_base = _mean(state.promote_rate_seq[-cfg.baseline_window:], 0.3)
    if sealed == 0:
        s_promote = 0
    elif promote_today >= promote_base:
        s_promote = 2
    elif promote_today - promote_base >= -0.20:
        s_promote = 1
    else:
        s_promote = 0
    # high-face penalty (market-wide, per source semantics)
    if day.high_face_count == 0:
        s_face = 3
    elif day.high_face_count <= 5:
        s_face = 1
    elif day.high_face_count >= 6 and day.sky_floor_count >= 1:
        s_face = -1
    else:
        s_face = 0
    score = min(13, s_tier + s_fry + s_promote + s_face)
    return score, fry_today, promote_today


def _leader_signal(day: DailyMarket, cfg: Config, state: State,
                   sector: str | None) -> tuple[str, int, str | None]:
    candidates = [c for c in day.board_leaders if not c[3]]  # not broken
    if candidates:
        code = max(candidates, key=lambda c: (c[1], c[2]))[0]
    else:
        code = state.prev_leader  # no new leader: keep watching yesterday's
    if code is None:
        return "none", 0, None
    if code != state.prev_leader and state.prev_leader is not None:
        break_days = 0  # leader change resets
    else:
        break_days = state.break_days
    sealed_codes = {c[0] for c in day.board_leaders if not c[3]}
    new_break = 0 if code in sealed_codes else break_days + 1
    sf = day.sky_floor_count
    if new_break >= cfg.leader_break_confirm or sf >= cfg.sky_floor_confirm:
        signal = "confirm"
    elif new_break >= cfg.leader_break_warn or sf >= cfg.sky_floor_warn:
        signal = "warning"
    else:
        signal = "none"
    return signal, new_break, code


def _tier(l2: int, cfg: Config) -> tuple[str, float, float]:
    t5, t4, t3, t2 = cfg.position_tiers
    if l2 >= t5:
        return "T5", 0.25, 0.90
    if l2 >= t4:
        return "T4", 0.20, 0.70
    if l2 >= t3:
        return "T3", 0.10, 0.30
    if l2 >= t2:
        return "T2", 0.05, 0.10
    return "T1", 0.0, 0.0


class EmotionEngine:
    """Advances sentiment state one trading day at a time."""

    def __init__(self, cfg: Config | None = None, state: State | None = None) -> None:
        self.cfg = cfg or Config()
        self.state = state or State()

    def update(self, day: DailyMarket) -> Snapshot:
        cfg, st = self.cfg, self.state
        l1, ratio_trigger = _score_l1(day, cfg, st)
        sector, sticky = _pick_main_sector(day, cfg, st)
        l2, fry_today, promote_today = _score_l2(day, cfg, st, sector)
        l3, break_days, leader = _leader_signal(day, cfg, st, sector)
        ebb = (
            l2 <= cfg.ebb_l2 and st.prev_l2 <= cfg.ebb_prev_l2
            and l3 in ("warning", "confirm")
        )
        if ebb:
            regime_tier = "T0"
            single, total = 0.0, 0.0
        else:
            regime_tier, single, total = _tier(int(l2), cfg)

        st.fry_rate_seq = (st.fry_rate_seq + [fry_today])[-cfg.sequence_cap:]
        st.promote_rate_seq = (st.promote_rate_seq + [promote_today])[-cfg.sequence_cap:]
        st.prev_main_sector = sector
        st.prev_leader = leader
        st.break_days = break_days
        st.prev_l2 = int(l2)
        st.prev_ratio_trigger = ratio_trigger

        return Snapshot(
            date=day.date, l1=l1, l2=float(l2), l3=l3,
            main_sector=sector, sector_sticky=sticky, ebb=ebb,
            position_tier=regime_tier, position_single=single, position_total=total,
            diagnostics={
                "fry_today": fry_today, "promote_today": promote_today,
                "leader": leader, "break_days": break_days,
                "ratio_trigger": ratio_trigger,
            },
        )


__all__ = [
    "Config", "DailyMarket", "State", "Snapshot", "EmotionEngine",
]
