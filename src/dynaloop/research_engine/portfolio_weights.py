"""Portfolio weight construction: the qlib ``WeightStrategyBase`` analogue.

qlib separates target-position construction from order generation: a strategy
implements ``generate_target_weight_position`` and the framework turns that
into orders. We follow the same contract. A frozen, fingerprinted ``WeightConfig``
maps decision-time scores to target weights; cash is not part of the output and
weights are normalised to sum to one. Turnover control uses qlib's topk-dropout
idea: held names whose rank stays inside ``top_k + drop`` are preferred, and at
most ``drop`` names change per rebalance.

This module is pure and side-effect free. It never sees a research verdict or a
raw report -- only scores (and optional volatilities) supplied by the caller.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class WeightScheme(str, Enum):
    EQUAL = "equal"
    SCORE = "score"
    INVERSE_VOLATILITY = "inverse_volatility"


@dataclass(frozen=True, slots=True)
class WeightConfig:
    """Frozen parameters of one target-weight construction."""

    scheme: WeightScheme = WeightScheme.EQUAL
    top_k: int = 1
    temperature: float = 1.0
    drop: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, WeightScheme):
            object.__setattr__(self, "scheme", WeightScheme(str(self.scheme)))
        if type(self.top_k) is not int or self.top_k < 1:
            raise ValueError("top_k must be an integer >= 1")
        if not math.isfinite(float(self.temperature)) or float(self.temperature) <= 0:
            raise ValueError("temperature must be finite and positive")
        if self.drop is not None and (type(self.drop) is not int or self.drop < 0):
            raise ValueError("drop must be None or an integer >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme.value,
            "top_k": self.top_k,
            "temperature": float(self.temperature),
            "drop": self.drop,
        }


def _usable(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _rank(usable: Mapping[str, float]) -> list[str]:
    # Deterministic tie-break by name so the same input always yields the same book.
    return sorted(usable, key=lambda name: (-usable[name], name))


def _select_names(
    ranked: Sequence[str],
    usable: Mapping[str, float],
    config: WeightConfig,
    previous: Mapping[str, float] | None,
) -> list[str]:
    top_k = config.top_k
    if not previous or config.drop is None:
        return list(ranked[:top_k])

    prev = set(previous)
    rank_index = {name: i for i, name in enumerate(ranked)}
    # Keep held names that remain near the top of the book (qlib topk-dropout).
    held_in_range = [n for n in ranked[: top_k + config.drop] if n in prev]
    kept = held_in_range[:top_k]
    for name in ranked:
        if len(kept) >= top_k:
            break
        if name not in kept:
            kept.append(name)

    # Enforce the turnover cap: at most `drop` held names may leave.
    dropped = [n for n in prev if n not in kept and n in usable]
    if len(dropped) > config.drop:
        excess = len(dropped) - config.drop
        best_dropped = sorted(dropped, key=lambda n: rank_index.get(n, 10**9))[:excess]
        newly_added = [n for n in kept if n not in prev]
        newly_added.sort(key=lambda n: rank_index.get(n, 10**9))
        for name in newly_added[:excess]:
            kept.remove(name)
        kept.extend(best_dropped)

    return sorted(kept, key=lambda n: rank_index.get(n, 10**9))


def build_target_weights(
    scores: Mapping[str, Any],
    *,
    config: WeightConfig,
    previous: Mapping[str, float] | None = None,
    volatilities: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Map decision-time scores to normalised target weights.

    ``scores`` higher-is-better. ``volatilities`` are required only by the
    inverse-volatility scheme; when missing (or non-positive) that scheme falls
    back to equal weight on the selected names rather than inventing a number.
    """
    usable: dict[str, float] = {}
    for name, value in scores.items():
        number = _usable(value)
        if number is not None:
            usable[str(name)] = number
    if not usable:
        return {}

    ranked = _rank(usable)
    chosen = _select_names(ranked, usable, config, previous)
    if not chosen:
        return {}

    if config.scheme is WeightScheme.EQUAL:
        raw = {name: 1.0 for name in chosen}
    elif config.scheme is WeightScheme.SCORE:
        # Softmax is shift-invariant and keeps negative scores usable. Fall back
        # to equal weight when the temperature computation cannot be trusted.
        peak = max(usable[n] for n in chosen)
        scaled = [(usable[n] - peak) / config.temperature for n in chosen]
        try:
            exp = [math.exp(min(max(s, -700.0), 700.0)) for s in scaled]
            total = math.fsum(exp)
            raw = {name: e for name, e in zip(chosen, exp)} if total > 0 else {n: 1.0 for n in chosen}
        except (OverflowError, ValueError):
            raw = {n: 1.0 for n in chosen}
    elif config.scheme is WeightScheme.INVERSE_VOLATILITY:
        raw = {}
        for name in chosen:
            vol = _usable((volatilities or {}).get(name))
            raw[name] = (1.0 / vol) if (vol is not None and vol > 0) else None
        if all(value is None for value in raw.values()):
            raw = {n: 1.0 for n in chosen}
        else:
            raw = {n: (value if value is not None else 0.0) for n, value in raw.items()}
    else:  # pragma: no cover - enum is exhaustive
        raise ValueError(f"unsupported weight scheme: {config.scheme}")

    total = math.fsum(raw.values())
    if not math.isfinite(total) or total <= 0:
        return {name: 1.0 / len(chosen) for name in chosen}
    return {name: float(raw[name]) / total for name in chosen}
