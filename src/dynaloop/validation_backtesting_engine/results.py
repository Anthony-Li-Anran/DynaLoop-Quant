"""JSON persistence for completed backtest runs (mechanical storage only)."""

from __future__ import annotations

from dynaloop.infrastructure import JsonMappingStore

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dynaloop.validation_backtesting_engine.domain.models import BacktestError


class RunResultStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._store = JsonMappingStore(path, error_type=BacktestError, label='Stored backtest results', recover_invalid=False)

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, dict[str, Any]]:
        return self._store.read()

    def save(self, run_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._store.transaction() as entries:
            entry = {
                "run_id": run_id,
                "config_id": payload.get("config_id"),
                "label": payload.get("label"),
                "setup": dict(payload.get("setup") or {}),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "result": dict(payload.get("result") or {}),
            }
            entries[run_id] = entry
        return entry

    def update_setup(self, run_id: str, setup: Mapping[str, Any]) -> dict[str, Any] | None:
        """Replace only the view-side setup, preserving the run's identity.

        Pane visibility is a view concern; it must not rewrite the engine result
        or the original creation timestamp of the run.
        """
        with self._store.transaction() as entries:
            entry = entries.get(run_id)
            if entry is None:
                return None
            entry["setup"] = dict(setup)
        return entry

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._read().get(run_id)

    def list_all(self) -> tuple[dict[str, Any], ...]:
        summaries: list[dict[str, Any]] = []
        for run_id, entry in sorted(self._read().items()):
            result = entry.get("result") or {}
            metrics = result.get("metrics") or {}
            spec = result.get("spec") or {}
            setup = entry.get("setup") or {}
            resolved = result.get("resolved_config") or {}
            metadata = resolved.get("metadata") or {}
            summaries.append(
                {
                    "run_id": run_id,
                    "config_id": entry.get("config_id"),
                    "label": entry.get("label"),
                    "created_at": entry.get("created_at"),
                    "source_key": setup.get("source_key") or metadata.get("source_key"),
                    "symbol": setup.get("symbol") or metadata.get("symbol") or (spec.get("symbols") or [None])[0],
                    "strategy_class": setup.get("strategy_class") or metadata.get("strategy_class"),
                    "window": spec.get("realized_window"),
                    "bar_count": spec.get("bar_count"),
                    "final_equity": metrics.get("final_equity"),
                    "total_return": metrics.get("total_return"),
                    "fill_count": metrics.get("fill_count"),
                }
            )
        return tuple(summaries)
