"""Read-only catalog of frozen factor certification artifacts.

The catalog only projects fields that already exist in the recorded files. It
never recomputes statistics, never edits a frozen artifact, and represents
missing values as null so that the UI can show "unavailable" instead of zero.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from dynaloop.research_engine.spec import fingerprint as _shared_fingerprint
except ImportError:  # pragma: no cover - catalog still works without rule rebuild
    _shared_fingerprint = None


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON: {value}")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return value


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if isinstance(number, float) and number.is_integer() else (
        number if isinstance(number, int) else None
    )


def _text_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if isinstance(item, str)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _window(data: dict[str, Any]) -> dict[str, Any]:
    value = data.get("verification_window")
    if isinstance(value, list) and len(value) == 2:
        return {"start": str(value[0]), "end": str(value[1])}
    if isinstance(value, dict):
        return {
            "start": value.get("verification_start") or value.get("start"),
            "end": value.get("verification_end") or value.get("end"),
        }
    recorded = _as_dict(data.get("window"))
    return {
        "start": recorded.get("first_decision_date") or recorded.get("first_decision_bar"),
        "end": recorded.get("last_maturity_date") or recorded.get("last_decision_date")
        or recorded.get("last_decision_bar"),
    }


def _validate_id(identifier: str) -> str:
    if (not isinstance(identifier, str) or not identifier or identifier in {".", ".."}
            or Path(identifier).name != identifier or "/" in identifier or "\\" in identifier):
        raise ValueError("Invalid artifact identifier")
    return identifier


class CertificationCatalog:
    """Project certified rounds into a stable, read-only API shape."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _read(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        if resolved.suffix != ".json" or not (
            resolved.parent == self.root or resolved.parent.parent == self.root
        ):
            raise ValueError("Artifact is outside the configured certification directory")
        data = json.loads(resolved.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        if not isinstance(data, dict):
            raise ValueError("Certification artifact must be a JSON object")
        return data

    def _round_path(self, round_id: str) -> Path:
        return self.root / _validate_id(round_id) / "certification.json"

    def list_rounds(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        rows = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.resolve().parent != self.root:
                continue
            path = directory / "certification.json"
            if not path.is_file():
                continue
            try:
                rows.append(self._summarise(directory.name, self._read(path), path))
            except (ValueError, OSError):
                rows.append({
                    "round_id": directory.name,
                    "status": "unreadable",
                    "source_sha256": None,
                })
        return rows

    def _summarise(self, round_id: str, data: dict[str, Any], path: Path) -> dict[str, Any]:
        report = _as_dict(data.get("report"))
        family = _as_dict(report.get("family"))
        recorded_window = _as_dict(data.get("window"))
        candidates = _as_list(report.get("candidates")) or _as_list(data.get("evidence"))
        effective = _as_list(data.get("effective_factor_ids"))
        periods = data.get("verification_periods")
        if periods is None:
            periods = family.get("periods") or recorded_window.get("monthly_cross_sections") \
                or recorded_window.get("decision_periods")
        reported_count = report.get("effective_count")
        return {
            "round_id": round_id,
            "channel": data.get("channel"),
            "channel_label": data.get("channel_label"),
            "status": report.get("status") or data.get("certification") or "unknown",
            "family_p_value": _number(
                data.get("family_p_value") if data.get("family_p_value") is not None
                else family.get("p_value")
            ),
            "periods": _integer(periods),
            "candidate_count": len(candidates),
            "effective_count": _integer(reported_count) if reported_count is not None else len(effective),
            "verification_window": _window(data),
            "freeze_fingerprint": data.get("freeze_fingerprint"),
            "source_sha256": _sha256(path),
        }

    def detail(self, round_id: str) -> dict[str, Any]:
        path = self._round_path(round_id)
        if not path.is_file():
            raise FileNotFoundError(f"Certification round not found: {round_id}")
        data = self._read(path)
        report = _as_dict(data.get("report"))
        family = _as_dict(report.get("family"))
        spec = _as_dict(family.get("spec"))
        evidence = _as_list(data.get("evidence"))
        first_evidence = _as_dict(evidence[0]) if evidence else {}
        effective_ids = {str(item) for item in _as_list(data.get("effective_factor_ids"))}

        candidates = []
        for row in _as_list(report.get("candidates")):
            if not isinstance(row, dict):
                continue
            factor_id = row.get("factor_id")
            candidates.append({
                "factor_id": factor_id,
                "expression": row.get("expression"),
                "status": row.get("status"),
                "effective": factor_id in effective_ids,
                "adjusted_p_value": _number(row.get("adjusted_p_value")),
                "mean_rank_ic": _number(row.get("mean_rank_ic")),
                "mean_improvement": _number(row.get("mean_improvement")),
                "periods": _integer(row.get("periods")),
                "reasons": _text_list(row.get("reasons")),
            })

        descriptive = data.get("descriptive_signal_metrics")
        if not isinstance(descriptive, dict):
            descriptive = None

        caveats = data.get("data_caveats")
        if not isinstance(caveats, list) and isinstance(first_evidence.get("data_caveats"), list):
            caveats = first_evidence["data_caveats"]
        not_claimed = data.get("not_claimed")
        if not isinstance(not_claimed, list):
            not_claimed = first_evidence.get("not_claimed")

        return {
            **self._summarise(round_id, data, path),
            "assertion": spec.get("assertion") or first_evidence.get("assertion"),
            "family": {
                "p_value": _number(family.get("p_value")),
                "alpha": _number(family.get("alpha")),
                "method": family.get("method"),
                "family_size": _integer(family.get("family_size")),
                "rejected_count": _integer(family.get("rejected_count")),
                "spec": spec,
            },
            "fingerprints": {
                "freeze": data.get("freeze_fingerprint"),
                "report": report.get("fingerprint"),
                "model": data.get("model_sha256"),
            },
            "effective_factor_ids": sorted(effective_ids),
            "candidates": candidates,
            "descriptive_metrics": descriptive,
            "disclosure": {
                "contamination": data.get("contamination_disclosure"),
                "data_caveats": _text_list(caveats),
                "not_claimed": _text_list(not_claimed),
                "limitations": data.get("limitations"),
            },
            "source_file": path.name,
        }


def _reconstruct_selection_rule(
    audit: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover the frozen selection-rule detail and verify it against its hash.

    ``run_real_pipeline.py`` builds a ``SelectionRule`` in memory but only wrote
    its fingerprint into the audit summary. Because the rule is a deterministic
    function of already-recorded fields (consumed factor id, evidence
    fingerprint, round id) plus fixed engineering display knobs, it can be
    rebuilt exactly. The rebuild is accepted ONLY when its fingerprint matches
    the recorded ``selection_rule_fingerprint``; otherwise no detail is shown.
    Nothing is recomputed about effectiveness, and no frozen file is touched.
    """
    fingerprint = _shared_fingerprint
    if fingerprint is None:
        return None
    recorded = audit.get("selection_rule_fingerprint")
    if not isinstance(recorded, str):
        return None
    consumed = _as_dict(audit.get("consumed_factor"))
    factor_id = consumed.get("factor_id")
    evidence_fingerprint = consumed.get("evidence_fingerprint")
    round_id = audit.get("timing_demo")
    round_id = _as_dict(round_id).get("frozen_rule")
    round_id = _as_dict(round_id).get("round_id")
    if not all(isinstance(v, str) and v for v in (factor_id, evidence_fingerprint, round_id)):
        return None

    # Fixed engineering display knobs from run_real_pipeline.py. These are
    # execution parameters, not certified statistics; the fingerprint match
    # proves they are the exact ones used in the recorded run.
    weight_config = {"scheme": "equal", "top_k": 10, "temperature": 1.0, "drop": 2}
    candidate = {
        "factor_ids": [factor_id],
        "top_k": 10,
        "evidence_fingerprints": [evidence_fingerprint],
        "round_id": round_id,
        "weight_config": weight_config,
    }
    try:
        rebuilt = fingerprint(candidate)
    except (TypeError, ValueError):
        return None
    if rebuilt != recorded:
        return None
    return candidate


def _frozen_strategy(audit: dict[str, Any]) -> dict[str, Any]:
    """Project the frozen quantitative strategy from the audit summary.

    Every value is read from the recorded audit file. The only derived values
    are the selected-universe length and the fallback flag taken from the
    recorded certification marker; no statistic is recomputed. Fields that
    were never persisted (for example selection-rule parameters) stay null so
    the UI can show "unavailable" instead of inventing a value.
    """
    timing = _as_dict(audit.get("timing_demo"))
    rule = _as_dict(timing.get("frozen_rule"))
    metrics = _as_dict(_as_dict(audit.get("backtest")).get("metrics"))
    selection_detail = _reconstruct_selection_rule(audit)
    symbols = _as_list(rule.get("selected_symbols"))
    certification_marker = rule.get("certification_fingerprint")
    is_fallback = (isinstance(certification_marker, str)
                   and "FALLBACK" in certification_marker.upper())

    return {
        "timing": {
            "entry_threshold": _number(rule.get("entry_threshold")),
            "exit_threshold": _number(rule.get("exit_threshold")),
            "selected_symbol_count": len(symbols) if symbols else None,
            "selection_rule_fingerprint": rule.get("selection_rule_fingerprint"),
            "certification_fingerprint": certification_marker,
            "is_fallback": is_fallback,
            "round_id": rule.get("round_id"),
        },
        # The audit summary records only the selection-rule fingerprint. When
        # the rule can be rebuilt exactly (fingerprint matches), its deterministic
        # detail is shown; otherwise every detail field stays null.
        "selection": {
            "fingerprint": audit.get("selection_rule_fingerprint"),
            "factor_ids": selection_detail["factor_ids"] if selection_detail else None,
            "top_k": selection_detail["top_k"] if selection_detail else None,
            "weight_config": selection_detail["weight_config"] if selection_detail else None,
            "verified": selection_detail is not None,
        },
        # Qlib risk_analysis / TopkDropout-aligned fields, report only.
        # Only fields present in the audit summary are projected; Qlib metrics
        # such as annualized return / information ratio were never recorded and
        # stay null rather than being inferred.
        "risk": {
            "initial_cash": _number(metrics.get("initial_cash")),
            "final_equity": _number(metrics.get("final_equity")),
            "total_return": _number(metrics.get("total_return")),
            "max_drawdown": _number(metrics.get("max_drawdown")),
            "turnover": _number(metrics.get("turnover")),
            "bar_count": _integer(metrics.get("bar_count")),
            "fill_count": _integer(metrics.get("fill_count")),
            "rejected_count": _integer(metrics.get("rejected_count")),
            "final_position_count": len(_as_dict(metrics.get("final_positions"))),
            "sharpe_ratio": _number(metrics.get("sharpe_ratio")),
            "annualized_volatility": _number(metrics.get("annualized_volatility")),
            "reconciliation_max_abs": _number(metrics.get("reconciliation_max_abs")),
        },
        "disclosure": {
            "no_new_effectiveness_claim": bool(audit.get("no_new_effectiveness_claim")),
            "n_candidates": _integer(timing.get("n_candidates")),
        },
    }


class ExecutionCatalog:
    """Project engineering execution demos from audit summaries only."""

    _AUDIT_FILE = "audit.json"
    _REPLAY_FILE = "replay_verification.json"

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _read(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        if resolved.parent == self.root or resolved.parent.parent != self.root:
            raise ValueError("Artifact is outside the configured execution directory")
        data = json.loads(resolved.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        if not isinstance(data, dict):
            raise ValueError("Execution artifact must be a JSON object")
        return data

    def _demo_path(self, demo_id: str, filename: str) -> Path:
        return self.root / _validate_id(demo_id) / filename

    def list_demos(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        rows = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.resolve().parent != self.root:
                continue
            path = directory / self._AUDIT_FILE
            if not path.is_file():
                continue
            try:
                audit = self._read(path)
                if audit.get("purpose") != "engineering_closed_loop_demo":
                    continue
                backtest = _as_dict(audit.get("backtest"))
                rows.append({
                    "demo_id": directory.name,
                    "purpose": audit.get("purpose"),
                    "no_new_effectiveness_claim": audit.get("no_new_effectiveness_claim"),
                    "full_fingerprint": audit.get("full_fingerprint"),
                    "backtest_window": backtest.get("window"),
                    "source_sha256": _sha256(path),
                })
            except (ValueError, OSError):
                continue
        return rows

    def detail(self, demo_id: str) -> dict[str, Any]:
        audit_path = self._demo_path(demo_id, self._AUDIT_FILE)
        if not audit_path.is_file():
            raise FileNotFoundError(f"Execution demo not found: {demo_id}")
        audit = self._read(audit_path)
        if audit.get("purpose") != "engineering_closed_loop_demo":
            raise ValueError("Execution artifact is not an engineering demo")
        replay_path = self._demo_path(demo_id, self._REPLAY_FILE)
        replay = self._read(replay_path) if replay_path.is_file() else {}
        timing = _as_dict(audit.get("timing_demo"))
        backtest = _as_dict(audit.get("backtest"))
        replay_checks = _as_dict(replay.get("checks"))
        fingerprint_check = _as_list(replay_checks.get("full_fingerprint"))
        return {
            "demo_id": demo_id,
            "purpose": audit.get("purpose"),
            "no_new_effectiveness_claim": bool(audit.get("no_new_effectiveness_claim")),
            "consumed_factor": _as_dict(audit.get("consumed_factor")),
            "data_provenance": _as_dict(audit.get("data_provenance")),
            "selection_rule_fingerprint": audit.get("selection_rule_fingerprint"),
            "timing_rule_fingerprint": audit.get("timing_rule_fingerprint"),
            "timing_demo": {
                "purpose": timing.get("purpose"),
                "learn_window_end": timing.get("learn_window_end"),
                "verify_window": timing.get("verify_window"),
                "timing_symbol": timing.get("timing_symbol"),
                "n_learning_samples": _integer(timing.get("n_learning_samples")),
                "n_verification_samples": _integer(timing.get("n_verification_samples")),
                "n_candidates": _integer(timing.get("n_candidates")),
                "frozen_rule": _as_dict(timing.get("frozen_rule")),
            },
            "backtest": {
                "window": backtest.get("window"),
                "n_decision_dates": _integer(backtest.get("n_decision_dates")),
                "metrics": _as_dict(backtest.get("metrics")),
                "fingerprint": backtest.get("fingerprint"),
            },
            "replay": {
                "identical": replay.get("replay_identical") if isinstance(replay.get("replay_identical"), bool) else None,
                "full_fingerprint": fingerprint_check[0] if fingerprint_check else replay.get("full_fingerprint"),
            },
            "full_fingerprint": audit.get("full_fingerprint"),
            "frozen_strategy": _frozen_strategy(audit),
            "source_sha256": _sha256(audit_path),
        }


class WalkforwardCatalog:
    """Read-only projection of rule-driven walk-forward robustness diagnostics.

    Follows the multi-run comparison-matrix convention (Qlib rolling retraining,
    qlib-platform research_matrix, ML4T Diagnostic): each fold is reported as a
    separate row with its own family test. P-values are never pooled, missing
    metrics stay null, and no effectiveness verdict is inferred here.
    """

    _SUMMARY_FILE = "walkforward_summary.json"
    _NOTE_FILE = "walkforward_audit_note.json"
    _FREEZE_FILE = "walkforward_preregistration.json"

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _read(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        if resolved.suffix != ".json" or resolved.parent.parent != self.root:
            raise ValueError("Artifact is outside the configured walk-forward directory")
        data = json.loads(resolved.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        if not isinstance(data, dict):
            raise ValueError("Walk-forward artifact must be a JSON object")
        return data

    def _path(self, round_id: str, filename: str) -> Path:
        return self.root / _validate_id(round_id) / filename

    def list_rounds(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        rows = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.resolve().parent != self.root:
                continue
            path = directory / self._SUMMARY_FILE
            if not path.is_file():
                continue
            try:
                summary = self._read(path)
                rows.append({
                    "round_id": summary.get("round") or directory.name,
                    "directory": directory.name,
                    "purpose": summary.get("purpose"),
                    "channel_label": summary.get("channel_label"),
                    "fold_count": _integer(summary.get("fold_count")),
                    "effective_folds": _as_list(summary.get("descriptive_effective_folds")),
                    "refuted_folds": _as_list(summary.get("descriptive_refuted_folds")),
                    "insufficient_folds": _as_list(summary.get("descriptive_insufficient_folds")),
                    "no_new_effectiveness_claim": bool(summary.get("no_new_effectiveness_claim")),
                    "no_pooled_p_value": bool(summary.get("no_pooled_p_value")),
                    "freeze_fingerprint": summary.get("freeze_fingerprint"),
                    "source_sha256": _sha256(path),
                })
            except (ValueError, OSError):
                rows.append({
                    "round_id": directory.name, "directory": directory.name,
                    "fold_count": None, "status": "unreadable",
                })
        return rows

    def detail(self, directory: str) -> dict[str, Any]:
        summary_path = self._path(directory, self._SUMMARY_FILE)
        if not summary_path.is_file():
            raise FileNotFoundError(f"Walk-forward diagnostic not found: {directory}")
        summary = self._read(summary_path)
        note_path = self._path(directory, self._NOTE_FILE)
        note = self._read(note_path) if note_path.is_file() else {}
        freeze_path = self._path(directory, self._FREEZE_FILE)
        freeze = self._read(freeze_path) if freeze_path.is_file() else {}

        definitions = {f.get("index"): f for f in _as_list(freeze.get("folds"))}
        folds = []
        for row in _as_list(summary.get("folds")):
            number = _integer(row.get("fold"))
            definition = definitions.get(number, {})
            folds.append({
                "fold": number,
                "window": _as_list(row.get("window")),
                "periods": _integer(row.get("periods")),
                "family_p_value": _number(row.get("family_p_value")),
                "status": row.get("status"),
                "rank_ic": _number(row.get("rank_ic")),
                "cutoff": definition.get("cutoff"),
                "fit_window": [definition.get("fit_start"), definition.get("fit_end")],
                "test_window": [definition.get("test_start"), definition.get("test_end")],
                "effective": bool(number in _as_list(summary.get("descriptive_effective_folds"))),
            })

        rank_series = []
        for item in _as_list(note.get("rank_ic_series")):
            rank_series.append({
                "fold": _integer(item.get("fold")),
                "window": _as_list(item.get("window")),
                "rank_ic": _number(item.get("rank_ic")),
            })

        return {
            "round_id": summary.get("round") or directory,
            "directory": directory,
            "purpose": summary.get("purpose"),
            "channel": summary.get("channel"),
            "channel_label": summary.get("channel_label"),
            "fold_count": _integer(summary.get("fold_count")),
            "folds": folds,
            "rank_ic_series": rank_series,
            "counts": {
                "effective": _as_list(summary.get("descriptive_effective_folds")),
                "refuted": _as_list(summary.get("descriptive_refuted_folds")),
                "insufficient_evidence": _as_list(summary.get("descriptive_insufficient_folds")),
            },
            "disclosure": {
                "power_warning": note.get("power_warning"),
                "contamination": summary.get("contamination_disclosure"),
                "contamination_addendum": note.get("contamination_addendum"),
                "descriptive_observation": note.get("descriptive_observation"),
                "upstream_authority": note.get("upstream_authority"),
                "not_claimed": _text_list(summary.get("not_claimed")),
            },
            "flags": {
                "no_new_effectiveness_claim": bool(summary.get("no_new_effectiveness_claim")),
                "no_pooled_p_value": bool(summary.get("no_pooled_p_value")),
                "no_cross_round_sequential_claim": bool(summary.get("no_cross_round_sequential_claim")),
            },
            "freeze_fingerprint": summary.get("freeze_fingerprint"),
            "source_round": summary.get("source_round"),
            "source_certification_sha256": note.get("source_certification_sha256"),
            "source_sha256": _sha256(summary_path),
        }
