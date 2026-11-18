"""Read-only catalog of completed, explicitly configured research artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON: {value}")


class ResearchCatalog:
    """Expose recorded evidence without promoting exploratory factors."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def list_runs(self) -> list[dict]:
        if not self.root.exists():
            return []
        runs = []
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir() and directory.resolve().parent == self.root:
                panel = directory / "panel_discovery.json"
                if panel.is_file():
                    try:
                        data = self._read_panel(panel)
                        runs.append(dict(run_id=directory.name, factors=len(data["summary"]["candidates"]),
                                         status="exploratory", kind="panel_discovery"))
                    except (ValueError, OSError):
                        runs.append(dict(run_id=directory.name, factors=None, status="unreadable",
                                         kind="panel_discovery"))
                    continue
                library = directory / "factor_library.json"
                if library.is_file():
                    try:
                        rows = self._read(library)
                        if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("expression"), str) for r in rows):
                            raise ValueError("Invalid factor library")
                        runs.append(dict(run_id=directory.name, factors=len(rows), status="exploratory"))
                    except (ValueError, OSError):
                        runs.append(dict(run_id=directory.name, factors=None, status="unreadable"))
        return runs

    def _read(self, path: Path):
        if path.resolve().parent.parent != self.root:
            raise ValueError("Artifact is outside the configured research directory")
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)

    def _read_panel(self, path: Path) -> dict:
        data = self._read(path)
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or not isinstance(data.get("summary"), dict)
                or not isinstance(data["summary"].get("candidates"), list)
                or not isinstance(data.get("decisions"), list)):
            raise ValueError("Invalid panel discovery artifact")
        return data

    def _forward_decisions(self, directory: Path) -> list[dict]:
        path = directory / "forward_ledger.json"
        if not path.is_file():
            return []
        ledger = self._read(path)
        if (not isinstance(ledger, dict) or ledger.get("schema_version") != 1
                or not isinstance(ledger.get("decisions"), dict)):
            raise ValueError("Invalid forward decision ledger")
        rows = []
        for month, record in sorted(ledger["decisions"].items(), reverse=True):
            if (not isinstance(record, dict) or not isinstance(record.get("signals"), list)
                    or any(not isinstance(record.get(key), str) for key in
                           ("decision", "committed_at", "data_through", "source_sha256"))):
                raise ValueError(f"Invalid forward decision for {month}")
            rows.append(dict(month=month, decision=record["decision"], committed_at=record["committed_at"],
                             data_through=record["data_through"], source_sha256=record["source_sha256"],
                             candidate=record.get("candidate"), ranked=len(record["signals"]),
                             settlement=record.get("settlement")))
        return rows

    def detail(self, run_id: str) -> dict:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
            raise ValueError("Invalid research run identifier")
        directory = self.root / run_id
        panel = directory / "panel_discovery.json"
        if panel.is_file():
            return dict(run_id=run_id, status="exploratory", factors=[], artifacts={},
                        panel_discovery={**self._read_panel(panel), "forward_decisions": self._forward_decisions(directory)},
                        limitation="Historical replay. Rank IC uses observed labels and excludes execution costs.")
        library = directory / "factor_library.json"
        rows = self._read(library)
        if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("expression"), str) for r in rows):
            raise ValueError("Invalid factor library")
        artifacts = {}
        for name in ("factor_library.json", "manifest.json", "summary.json", "factor_followup.json"):
            path = directory / name
            if path.is_file():
                # Read through the same boundary check before exposing content.
                value = self._read(path)
                artifacts[name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), content=value)
        followup = artifacts.get("factor_followup.json", {}).get("content")
        if followup is not None and (not isinstance(followup, dict) or not isinstance(followup.get("cards"), list)):
            raise ValueError("Invalid factor follow-up")
        return dict(run_id=run_id, status="exploratory", factors=rows, artifacts=artifacts, followup=followup,
                    limitation="Recorded exploratory candidates. Selection-window scores do not establish independent effectiveness.")
