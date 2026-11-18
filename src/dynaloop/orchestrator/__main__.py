"""One-command entry point: python -m dynaloop.orchestrator [options].

Uses explicitly labelled synthetic demo bars by default, or a frozen JSON bar
snapshot via ``--records``. ``--database`` enables experiment-run tracing.
``--output`` writes the complete reproducible spec; stdout always prints a
short summary including the run fingerprint.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from dynaloop.experiment_management.facade import ExperimentManagementFacade
from dynaloop.orchestrator import (
    SYNTHETIC_SOURCE_METADATA,
    LoopConfig,
    LoopOrchestrator,
    synthetic_demo_records,
)
from dynaloop.research_engine import FactorFrame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the DynaLoop six-stage loop.")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--group-size", type=int, default=6)
    parser.add_argument("--symbol", default="TEST")
    parser.add_argument("--start", help="inclusive lower timestamp; defaults to first input bar")
    parser.add_argument("--end", help="inclusive upper timestamp; defaults to last input bar")
    parser.add_argument("--features", nargs="+", help="factor columns; defaults to numeric input columns")
    parser.add_argument("--bias", type=float, default=0.0,
                        help="known-magnitude additive bias injected into Sleep")
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--reps", type=int, default=120,
                        help="resampling replicates for proxy and statistics")
    parser.add_argument("--records", type=str, default=None,
                        help="path to a frozen JSON array of bar records")
    parser.add_argument("--database", type=str, default=None,
                        help="SQLite path for experiment run tracing")
    parser.add_argument("--output", type=str, default=None,
                        help="write the full reproducible spec to this path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.records:
        path = Path(args.records)
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise SystemExit("--records must point to a non-empty JSON array of bar records.")
        source_metadata: dict[str, Any] = {
            "source": "json_snapshot",
            "path": str(path),
            "synthetic_demo": False,
        }
    else:
        rows = synthetic_demo_records()
        source_metadata = dict(SYNTHETIC_SOURCE_METADATA)

    facade = (
        ExperimentManagementFacade.open_local(args.database)
        if args.database else None
    )
    frame = FactorFrame(rows)
    config = LoopConfig(
        symbol=args.symbol,
        start=args.start or frame.timestamps[0],
        end=args.end or frame.timestamps[-1],
        features=tuple(args.features or frame.columns),
        seed=args.seed,
        rounds=args.rounds,
        group_size=args.group_size,
        bias_magnitude=args.bias,
        alpha=args.alpha,
        proxy_reps=args.reps,
        statistical_reps=args.reps,
    )
    result = LoopOrchestrator(config, experiment_facade=facade).run(
        rows, source_metadata=source_metadata
    )
    if args.output:
        Path(args.output).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
    print(json.dumps({
        "fingerprint": result.fingerprint(),
        "rounds": len(result.rounds),
        "run_ids": list(result.run_ids),
        "final_reliability": result.final_reliability,
        "final_policy_version": result.final_policy.version,
        "final_calibration_version": result.final_calibration.version,
        "source": source_metadata,
        "spec_output": args.output,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
