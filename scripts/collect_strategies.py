"""Daily strategy-library ingestion entrypoint.

The web search and schema-guided LLM extraction are performed by the scheduled
automation (which has web access). This script is the deterministic sink: it
reads that structured candidate JSON and stores it with point-in-time-correct
timestamps. It makes NO network call itself and NEVER fabricates a strategy.
If no input is supplied it reports an explicit unavailable status.

Usage:
  python scripts/collect_strategies.py --input candidates.json --query "A-share trend"
  python scripts/collect_strategies.py --print-schema
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dynaloop.live_strategy import (  # noqa: E402
    LiveStrategyLibrary,
    StructuredCandidateCollector,
)

DEFAULT_STATE_DIR = Path("~/.dynaloop").expanduser()


def candidate_schema() -> dict[str, object]:
    """The exact JSON shape the automation must produce per strategy."""
    return {
        "candidates": [
            {
                "name": "strategy name (required, non-empty)",
                "method": "core method in one line (required, non-empty)",
                "source_url": "https://... (required, for provenance)",
                "summary": "short factual summary (required, non-empty)",
                "author": "author or null",
                "published_at": "YYYY-MM-DD or null",
                "source_name": "site/publication name",
                "regimes": ["applicable market regime tags, e.g. trend, momentum"],
                "raw_excerpt": "source excerpt or null",
            }
        ],
        "query": "the search query used",
        "extractor_version": "schema-extract/1",
        "prompt_version": "optional prompt version id",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest structured strategy candidates.")
    parser.add_argument("--input", type=Path, help="JSON file with a 'candidates' list")
    parser.add_argument("--query", default="", help="search query used by the automation")
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--print-schema", action="store_true")
    args = parser.parse_args(argv)

    if args.print_schema:
        print(json.dumps(candidate_schema(), ensure_ascii=False, indent=2))
        return 0

    state_dir = args.state_dir or Path(
        os.environ.get("DYNALOOP_STATE_DIRECTORY", str(DEFAULT_STATE_DIR))
    ).expanduser()
    library = LiveStrategyLibrary(state_dir / "live_strategy.json")

    if args.input is None or not args.input.is_file():
        # Explicit unavailable: never fabricate strategies when input is missing.
        result = library.refresh(None, query=args.query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") or []
    collector = StructuredCandidateCollector(
        candidates,
        collected_at=datetime.now(timezone.utc).date().isoformat(),
        extractor_version=payload.get("extractor_version") or "schema-extract/1",
        prompt_version=payload.get("prompt_version"),
    )
    result = library.refresh(
        collector, query=payload.get("query") or args.query,
        limit=max(1, len(candidates)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
