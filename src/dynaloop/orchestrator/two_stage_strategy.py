"""Backtest adapter: drive the engine with the two frozen rules only.

The strategy is a dumb consumer. It holds a frozen ``SelectionRule`` and a
frozen ``TimingRule`` and receives decision-time scores/signals from a caller
supplied provider. It cannot see a research verdict, a raw report or any data
after the current bar -- the engine hands it a truncated BarView and enforces
NEXT_BAR execution. All allocation logic lives in the two frozen rules; the
adapter only translates their output into signed order quantities.

Data flow per decision bar t:
  scores_t, timing_t = provider(t, truncated_view)      # caller guarantees no look-ahead
  target = SelectionExecution(rule).target_weights(scores_t, previous=positions)
  actions = TimingExecution(rule).actions(timing_t, target, positions)
  orders  = rebalance(target, actions, positions, prices_t)
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping

from dynaloop.orchestrator.two_stage import (
    SelectionExecution,
    SelectionRule,
    TimingExecution,
    TimingRule,
)
from dynaloop.research_engine.portfolio_weights import WeightConfig
from dynaloop.validation_backtesting_engine.domain.models import BacktestError
from dynaloop.validation_backtesting_engine.strategies import BaseStrategy

# Decision-time (timestamp, truncated view) -> (selection scores, timing signals).
SignalProvider = Callable[[str, Any], tuple[Mapping[str, float], Mapping[str, float]]]


class TwoStageStrategy(BaseStrategy):
    """Execute the select-then-time cascade inside the deterministic engine."""

    def __init__(
        self,
        selection_rule: SelectionRule,
        timing_rule: TimingRule,
        signal_provider: SignalProvider,
        *,
        allocation: float = 0.95,
        reset_every: int = 1,
    ) -> None:
        if not isinstance(selection_rule, SelectionRule):
            raise TypeError("TwoStageStrategy needs a frozen SelectionRule")
        if not isinstance(timing_rule, TimingRule):
            raise TypeError("TwoStageStrategy needs a frozen TimingRule")
        if timing_rule.selection_rule_fingerprint != selection_rule.fingerprint:
            raise ValueError("timing rule was not frozen on this selection rule")
        if not 0 < allocation <= 1:
            raise ValueError("allocation must be in (0, 1]")
        if type(reset_every) is not int or reset_every < 1:
            raise ValueError("reset_every must be an integer >= 1")
        self.selection = SelectionExecution(selection_rule)
        self.timing = TimingExecution(timing_rule)
        self.provider = signal_provider
        self.allocation = float(allocation)
        self.reset_every = reset_every
        self._bar = 0
        self.last_target: dict[str, float] = {}
        self.last_actions: dict[str, str] = {}
        self.actions_seen: set[str] = set()

    def on_start(self, config: Any) -> None:
        self._bar = 0
        self.last_target = {}
        self.last_actions = {}
        self.actions_seen = set()

    def on_data(self, timestamp: str, data: Any, context: Any, broker: Any) -> None:
        self._bar += 1
        # Signals are supplied by the caller for the decision timestamp only.
        # An empty score map means "no decision on this bar" -- the strategy
        # HOLDS its book. Treating it as an empty target would liquidate the
        # portfolio on every non-decision bar and fabricate enormous turnover.
        scores, timing_signals = self.provider(timestamp, data)
        if not scores:
            return
        positions = {k: float(v) for k, v in broker.positions.items() if float(v) > 0}
        target = self.selection.target_weights(scores, previous=positions)
        actions = self.timing.actions(timing_signals, target, positions)
        self.last_target = dict(target)
        self.last_actions = dict(actions)
        self.actions_seen.update(actions.values())

        if self._bar % self.reset_every != 0:
            return  # rebalance only on the frozen decision cadence

        equity = float(broker.cash) + sum(
            qty * data.bar(sym).close for sym, qty in positions.items()
            if data.bar(sym) is not None
        )
        investable = equity * self.allocation

        # Desired value per name: flat when the timing rule says exit, otherwise
        # the frozen target weight. A name held but outside the new target is sold.
        desired: dict[str, float] = {}
        for name, weight in target.items():
            if actions.get(name) == "exit":
                desired[name] = 0.0
            elif actions.get(name) == "enter" or name in positions:
                desired[name] = float(weight) * investable
        for name in positions:
            if name not in target:
                desired[name] = 0.0  # dropped from the frozen selection

        for name, want_value in sorted(desired.items()):
            bar = data.bar(name)
            if bar is None or bar.close <= 0:
                continue
            current_qty = positions.get(name, 0.0)
            want_qty = want_value / float(bar.close)
            delta = want_qty - current_qty
            if abs(delta) < 1e-12:
                continue
            try:
                broker.submit_order(name, delta)
            except BacktestError:
                # An unfillable order is a rejected order in the audit ledger;
                # we never invent cash or bypass the engine's cash constraint.
                continue


def constant_scores_provider(
    scores: Mapping[str, float], timing: Mapping[str, float]
) -> SignalProvider:
    """A deterministic provider for control runs and tests (no time variation)."""
    def _provider(timestamp: str, view: Any) -> tuple[Mapping[str, float], Mapping[str, float]]:
        return dict(scores), dict(timing)
    return _provider
