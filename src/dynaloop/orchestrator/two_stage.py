"""Two-stage orchestration: select (portfolio) then time (selected names).

Final architecture (Anthony 2026-11-17): two blocks in series -- first select
stocks into a portfolio, then time the entries/exits on the selected names.
Within EACH block, research and execution are separated. Authority: Qlib's
nested-decision-execution example (weekly portfolio generation + daily order
execution) and dual-momentum (cross-sectional selection + time-series filter).

The separation is enforced by types, not by convention:

  SelectionResearch  --(produces)--> SelectionRule (frozen, fingerprinted)
  SelectionExecution --(consumes only SelectionRule)--> target weights
  TimingResearch     --(consumes SelectionRule, produces)--> TimingRule
  TimingExecution    --(consumes only TimingRule + weights)--> actions

An execution object can NEVER receive a verdict function, a raw report, or the
research dataset: its constructor signature only accepts the frozen rule. Any
rule change requires a new research round and a new fingerprint. This is the
research/execution split made structural.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from dynaloop.research_engine.portfolio_weights import (
    WeightConfig,
    WeightScheme,
    build_target_weights,
)
from dynaloop.research_engine.timing_learning import TimingCandidate
from dynaloop.research_engine.spec import fingerprint


@dataclass(frozen=True, slots=True)
class SelectionRule:
    """Frozen output of stage-1 research: which names, by what evidence.

    The weight construction is part of the freeze: the exact scheme, top_k,
    temperature and turnover cap are fingerprinted, so execution cannot change
    how scores become weights without a new research round.
    """

    factor_ids: tuple[str, ...]
    top_k: int
    evidence_fingerprints: tuple[str, ...]
    round_id: str
    weight_config: WeightConfig | None = None

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        if not self.factor_ids:
            raise ValueError("a selection rule needs at least one effective factor")
        if len(self.evidence_fingerprints) != len(self.factor_ids):
            raise ValueError("each factor needs its evidence fingerprint")
        if self.weight_config is None:
            object.__setattr__(
                self, "weight_config",
                WeightConfig(scheme=WeightScheme.EQUAL, top_k=self.top_k),
            )
        elif self.weight_config.top_k != self.top_k:
            raise ValueError("weight_config.top_k must equal the rule top_k")

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_ids": list(self.factor_ids),
            "top_k": self.top_k,
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "round_id": self.round_id,
            "weight_config": self.weight_config.to_dict(),
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


class SelectionResearch:
    """Stage-1 research: turn certified evidence into a frozen selection rule."""

    def __init__(
        self,
        effective_factors: Sequence[Any],
        *,
        top_k: int,
        round_id: str,
        weight_config: WeightConfig | None = None,
    ) -> None:
        if int(top_k) < 1:
            raise ValueError("top_k must be >= 1")
        # Accept only entries carrying an evidence fingerprint. Neither the
        # verdict function nor the raw report can reach this object.
        prepared: list[tuple[str, str]] = []
        for item in effective_factors:
            factor_id = getattr(item, "factor_id", None)
            fp = getattr(item, "fingerprint", None)
            status = getattr(item, "status", None)
            is_effective = getattr(item, "effective", None)
            if not factor_id or not fp:
                raise ValueError("effective factors must carry factor_id and fingerprint")
            if status != "effective" or is_effective is False:
                raise ValueError(
                    f"only certified effective factors may enter a selection rule "
                    f"(got status={status!r}, effective={is_effective!r})")
            prepared.append((str(factor_id), str(fp)))
        self._prepared = tuple(prepared)
        self._top_k = int(top_k)
        self._round_id = str(round_id)
        # Freeze the weight construction together with the factor set: a change
        # here must change the rule fingerprint and require a new round.
        self._weight_config = weight_config or WeightConfig(
            scheme=WeightScheme.EQUAL, top_k=int(top_k))

    def freeze(self) -> SelectionRule:
        cfg = self._weight_config
        if cfg.top_k != self._top_k:
            cfg = WeightConfig(
                scheme=cfg.scheme, top_k=self._top_k,
                temperature=cfg.temperature, drop=cfg.drop)
        return SelectionRule(
            factor_ids=tuple(f for f, _ in self._prepared),
            evidence_fingerprints=tuple(fp for _, fp in self._prepared),
            top_k=self._top_k,
            weight_config=cfg,
            round_id=self._round_id,
        )


class SelectionExecution:
    """Stage-1 execution: consume a frozen rule to build target weights.

    The only research artefact it can hold is a SelectionRule. No dataset, no
    verdict function, no raw report is reachable from here.
    """

    def __init__(self, rule: SelectionRule) -> None:
        if not isinstance(rule, SelectionRule):
            raise TypeError("SelectionExecution accepts only a frozen SelectionRule")
        self.rule = rule

    def target_weights(
        self,
        scores: Mapping[str, float],
        *,
        previous: Mapping[str, float] | None = None,
        volatilities: Mapping[str, float] | None = None,
    ) -> dict[str, float]:
        """Build target weights strictly from the frozen weight construction."""
        return build_target_weights(
            scores, config=self.rule.weight_config,
            previous=previous, volatilities=volatilities,
        )


@dataclass(frozen=True, slots=True)
class TimingRule:
    """Frozen output of stage-2 research on the selected names."""

    entry_threshold: float
    exit_threshold: float
    selected_symbols: tuple[str, ...]  # frozen membership, execution enforces it
    selection_rule_fingerprint: str
    round_id: str
    certification_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.selected_symbols:
            raise ValueError("timing rule needs a non-empty selected universe")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "selected_symbols": list(self.selected_symbols),
            "selected_universe_fingerprint": fingerprint(
                {"symbols": list(self.selected_symbols)}),
            "selection_rule_fingerprint": self.selection_rule_fingerprint,
            "round_id": self.round_id,
            "certification_fingerprint": self.certification_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


class TimingResearch:
    """Stage-2 research: learn and freeze an entry/exit rule on selected names."""

    def __init__(self, selection: SelectionRule, *, entry_threshold: float,
                 exit_threshold: float, round_id: str) -> None:
        if not isinstance(selection, SelectionRule):
            raise TypeError("TimingResearch needs a frozen SelectionRule")
        if entry_threshold < exit_threshold:
            raise ValueError("entry_threshold must be >= exit_threshold (hysteresis)")
        self._selection = selection
        self._entry = float(entry_threshold)
        self._exit = float(exit_threshold)
        self._round_id = str(round_id)

    @classmethod
    def from_certified(
        cls,
        selection: SelectionRule,
        candidate: TimingCandidate,
        *,
        round_id: str,
    ) -> "TimingResearch":
        """Freeze a rule from a candidate already certified on held-out data.

        ``TimingCandidate`` is produced only by the search-period learner; the
        caller is responsible for having run certification and for passing only
        candidate ids whose terminal state was ``effective``. Thresholds come
        from the learned candidate, never from hand-tuning here.
        """
        research = cls(
            selection,
            entry_threshold=candidate.entry_threshold,
            exit_threshold=candidate.exit_threshold,
            round_id=round_id,
        )
        research._certified_candidate = candidate
        return research

    def freeze(
        self,
        selected_symbols: Sequence[str],
        *,
        certification_fingerprint: str = "",
    ) -> TimingRule:
        universe = tuple(sorted(str(s) for s in selected_symbols))
        if not universe:
            raise ValueError("timing research needs a non-empty selected universe")
        candidate = getattr(self, "_certified_candidate", None)
        if candidate is not None and self._entry != candidate.entry_threshold:
            raise ValueError("certified candidate thresholds were changed")
        return TimingRule(
            entry_threshold=self._entry,
            exit_threshold=self._exit,
            selected_symbols=universe,
            selection_rule_fingerprint=self._selection.fingerprint,
            round_id=self._round_id,
            certification_fingerprint=str(certification_fingerprint),
        )


class TimingExecution:
    """Stage-2 execution: consume only a frozen TimingRule plus target weights.

    It cannot see SelectionResearch or TimingResearch. It decides hold/enter/
    exit per selected name from the timing signal, and refuses symbols outside
    the frozen selected universe.
    """

    def __init__(self, rule: TimingRule) -> None:
        if not isinstance(rule, TimingRule):
            raise TypeError("TimingExecution accepts only a frozen TimingRule")
        self.rule = rule

    def actions(
        self,
        signals: Mapping[str, float],
        target_weights: Mapping[str, float],
        positions: Mapping[str, float],
    ) -> dict[str, str]:
        # The selected universe is fixed by the research freeze; execution
        # cannot trade a name that research did not select.
        allowed = set(self.rule.selected_symbols)
        out: dict[str, str] = {}
        for name in target_weights:
            if name not in allowed:
                raise ValueError(f"{name!r} is outside the frozen selected universe")
            value = signals.get(name)
            held = float(positions.get(name, 0.0)) > 0
            if value is None or not _finite(float(value)):
                out[name] = "hold"
                continue
            score = float(value)
            if not held and score > self.rule.entry_threshold:
                out[name] = "enter"
            elif held and score < self.rule.exit_threshold:
                out[name] = "exit"
            else:
                out[name] = "hold"
        return out


def _finite(value: float) -> bool:
    import math
    return math.isfinite(value)
