"""Public facade: expression -> frozen frame -> values -> strategy -> result.

Cross-module links follow the system contract's "direct composition" rule:
Data's public ``fetch_bar_records`` supplies raw records, and the Validation &
Backtesting Engine's public ``build_strategy`` / ``backtest_from_records``
supply the deterministic verdict. Neither module is changed or bypassed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from dynaloop.data import fetch_bar_records
from dynaloop.research_engine.candidates import (
    EvaluationPolicy,
    FactorCandidate,
    CompiledFactor,
    compile_factor,
)
from dynaloop.research_engine.evaluation import (
    FactorEvaluation,
    build_evaluation_spec,
    information_coefficient,
)
from dynaloop.research_engine.expressions import (
    FactorError,
    Node,
    normalize_expression,
    parse_expression,
)
from dynaloop.research_engine.frame import FactorFrame, window_records
from dynaloop.validation_backtesting_engine import (
    BacktestConfig,
    backtest_from_records,
    build_strategy,
)
from dynaloop.validation_backtesting_engine.strategies import BaseStrategy


class FactorResearch:
    """Stage 1 entry point; stateless apart from the timestamp column name."""

    def __init__(self, *, timestamp_col: str = "date") -> None:
        if not timestamp_col:
            raise FactorError("timestamp_col must be a non-empty string.")
        self.timestamp_col = timestamp_col

    @staticmethod
    def parse(expression: str | Node) -> Node:
        return parse_expression(expression)

    @staticmethod
    def normalize(expression: str | Node) -> str:
        return normalize_expression(expression)

    @staticmethod
    def candidate(expression: str) -> FactorCandidate:
        return FactorCandidate.from_expression(expression)

    @staticmethod
    def fetch_records(
        registries: Any,
        *,
        source_key: str,
        symbol: str,
        start: str | None,
        end: str | None,
        frequency: str = "1d",
        adjust: str = "qfq",
        capability_store: Any = None,
        store: Any = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Directly call Data's public source-driven fetch (no adapter code)."""
        return fetch_bar_records(
            registries,
            source_key=source_key,
            symbol=symbol,
            start=start,
            end=end,
            frequency=frequency,
            adjust=adjust,
            capability_store=capability_store,
            store=store,
        )

    @staticmethod
    def strategy(compiled: CompiledFactor) -> BaseStrategy:
        """Resolve through the engine's public module.Class path."""
        return build_strategy(compiled.strategy_class, compiled.strategy_kwargs)

    def evaluate(
        self,
        expression: str | FactorCandidate,
        records: Iterable[Mapping[str, Any]],
        *,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        config: BacktestConfig | Mapping[str, Any] | None = None,
        policy: EvaluationPolicy | Mapping[str, Any] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
        columns: Sequence[Any] | None = None,
    ) -> FactorEvaluation:
        """Evaluate one candidate over one frozen window, end to end."""
        candidate = self._as_candidate(expression)
        resolved_policy = self._as_policy(policy)
        windowed, frame, declared_metadata = self._prepare(
            records, start=start, end=end, source_metadata=source_metadata, columns=columns
        )
        return self._run(
            candidate,
            frame,
            windowed,
            symbol=symbol,
            start=start,
            end=end,
            raw_config=config,
            policy=resolved_policy,
            source_metadata=declared_metadata,
        )

    def evaluate_batch(
        self,
        expressions: Iterable[str | FactorCandidate],
        records: Iterable[Mapping[str, Any]],
        *,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        config: BacktestConfig | Mapping[str, Any] | None = None,
        policy: EvaluationPolicy | Mapping[str, Any] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
        columns: Sequence[Any] | None = None,
    ) -> tuple[FactorEvaluation, ...]:
        """A test family: all candidates share one frozen frame and one policy."""
        resolved_policy = self._as_policy(policy)
        windowed, frame, declared_metadata = self._prepare(
            records, start=start, end=end, source_metadata=source_metadata, columns=columns
        )
        return tuple(
            self._run(
                self._as_candidate(expression),
                frame,
                windowed,
                symbol=symbol,
                start=start,
                end=end,
                raw_config=config,
                policy=resolved_policy,
                source_metadata=declared_metadata,
            )
            for expression in expressions
        )

    @staticmethod
    def _as_candidate(expression: str | FactorCandidate) -> FactorCandidate:
        if isinstance(expression, FactorCandidate):
            return expression
        return FactorCandidate.from_expression(str(expression))

    @staticmethod
    def _as_policy(policy: EvaluationPolicy | Mapping[str, Any] | None) -> EvaluationPolicy:
        if isinstance(policy, EvaluationPolicy):
            return policy
        return EvaluationPolicy(**dict(policy or {}))

    def _prepare(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        start: str | None,
        end: str | None,
        source_metadata: Mapping[str, Any] | None,
        columns: Sequence[Any] | None,
    ) -> tuple[list[dict[str, Any]], FactorFrame, dict[str, Any]]:
        metadata = dict(source_metadata or {})
        windowed = window_records(
            records, start=start, end=end, timestamp_col=self.timestamp_col
        )
        declared = columns if columns is not None else metadata.get("columns")
        frame = FactorFrame(
            windowed, timestamp_col=self.timestamp_col, columns=declared
        )
        return windowed, frame, metadata

    def _run(
        self,
        candidate: FactorCandidate,
        frame: FactorFrame,
        windowed: list[dict[str, Any]],
        *,
        symbol: str,
        start: str | None,
        end: str | None,
        raw_config: BacktestConfig | Mapping[str, Any] | None,
        policy: EvaluationPolicy,
        source_metadata: Mapping[str, Any],
    ) -> FactorEvaluation:
        if not isinstance(symbol, str) or not symbol.strip():
            raise FactorError("A symbol is required to evaluate a factor.")
        node = parse_expression(candidate.expression)
        values = frame.evaluate(node, min_periods=policy.min_periods)
        compiled = compile_factor(candidate, values, policy=policy, symbol=symbol.strip())

        if raw_config is None:
            engine_config = BacktestConfig()
        elif isinstance(raw_config, BacktestConfig):
            engine_config = raw_config
        elif isinstance(raw_config, Mapping):
            engine_config = BacktestConfig.from_dict(raw_config)
        else:
            raise FactorError("config must be BacktestConfig, a mapping, or None.")
        engine_config = replace(
            engine_config,
            metadata={
                **engine_config.metadata,
                "factor_id": candidate.factor_id,
                "factor_expression": candidate.expression,
            },
        )

        strategy = build_strategy(compiled.strategy_class, compiled.strategy_kwargs)
        result = backtest_from_records(
            windowed,
            symbol=symbol.strip(),
            strategy=strategy,
            config=engine_config,
            start=start,
            end=end,
            timestamp_col=frame.timestamp_col,
        )
        statistics = information_coefficient(values, frame, horizon=policy.ic_horizon)
        spec = build_evaluation_spec(
            candidate=candidate,
            policy=policy,
            frame=frame,
            values=values,
            compiled=compiled,
            statistics=statistics,
            result=result,
            start=start,
            end=end,
            source_metadata=source_metadata,
        )
        return FactorEvaluation(
            candidate=candidate,
            policy=policy,
            values=values,
            compiled=compiled,
            statistics=statistics,
            backtest=result.to_dict(),
            backtest_fingerprint=result.fingerprint(),
            spec=spec,
        )
