"""Run the neural Wake path on an explicit frozen, point-in-time snapshot.

Usage: python -m dynaloop.orchestrator.brain --records bars.json
       --features close volume --symbol TEST --output run.json
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import torch

from dynaloop.infrastructure import fingerprint
from dynaloop.model.brain import BrainConfig
from dynaloop.training_engine.wake import WakeConfig, WakeLearner
from dynaloop.research_engine import FactorFrame
from dynaloop.research_engine.strategies import FactorSignalStrategy
from dynaloop.validation_backtesting_engine import BacktestConfig, StaticFeed, run_backtest
from dynaloop.validation_backtesting_engine.domain.models import ExecutionMode


def run_brain(records: Iterable[Mapping[str, Any]], brain: BrainConfig, wake: WakeConfig, *, symbol: str,
              backtest: BacktestConfig | None = None,
              source_metadata: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], WakeLearner]:
    """Return an auditable report and resumable learner; never fetch market data.

    Source rows must already contain causal factor values. This API cannot infer
    whether an arbitrary supplied column was calculated using future data.
    """
    rows = [dict(row) for row in records]
    if any(row.get("symbol", symbol) != symbol for row in rows):
        raise ValueError("snapshot must contain exactly the requested symbol")
    frame = FactorFrame(rows)
    if not set(brain.features).issubset(frame.columns):
        raise ValueError("snapshot does not contain all configured features")
    if len(rows) < brain.window + wake.horizon:
        raise ValueError("snapshot is too short to mature even one prediction")
    config = backtest or BacktestConfig()
    if config.execution_mode != ExecutionMode.NEXT_BAR:
        raise ValueError("close-based brain signals require next-bar execution")
    feed = StaticFeed.from_records(rows, symbol=symbol)
    learner = WakeLearner(brain, wake, symbol=symbol)
    events = [learner.observe(str(row["date"]), row["close"],
              {f: row[f] for f in brain.features}, symbol=symbol) for row in rows]
    signals = {event.timestamp: event.prediction for event in events}
    result = run_backtest(feed, FactorSignalStrategy(signals, symbol=symbol), config)
    forecast_by_date = {e.timestamp: e.prediction for e in events}
    errors = [forecast_by_date[e.matured_timestamp] - e.realized_return
              for e in events if e.matured_timestamp is not None]
    report = dict(schema_version=1, brain=asdict(brain), wake=asdict(wake), symbol=symbol,
        source=dict(source_metadata or {"kind": "caller_supplied_snapshot", "synthetic": None}),
        data_fingerprint=fingerprint(rows), torch_version=str(torch.__version__),
        parameter_count=sum(p.numel() for p in learner.model.parameters()),
        events=[asdict(e) for e in events], pending_labels=len(learner.pending),
        forecast_mae=sum(abs(e) for e in errors) / len(errors),
        backtest=result.to_dict())
    report["fingerprint"] = fingerprint(report)
    return report, learner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True)
    parser.add_argument("--features", nargs="+", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--window", type=int, default=64)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--loops", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    records = json.loads(Path(args.records).read_text(encoding="utf-8"))
    brain = BrainConfig(tuple(args.features), args.window, args.width, args.heads,
                        args.blocks, args.loops, args.seed)
    report, learner = run_brain(records, brain, WakeConfig(horizon=args.horizon), symbol=args.symbol)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if args.checkpoint:
        learner.save(args.checkpoint)
    print(json.dumps({key: report[key] for key in ("fingerprint", "parameter_count", "forecast_mae", "pending_labels")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
