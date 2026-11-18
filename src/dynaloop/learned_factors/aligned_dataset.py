"""Aligned dataset: features at the triggered entry, label at window end.

The default DatasetH trains on a 1-day label at every daily row. This dataset
reuses the same materialised feature frame but re-samples it so that each
training row is one (window, instrument) decision:

  * features are taken at the triggered entry time inside the window;
  * the label is close[window_end]/close[entry]-1, the same target the
    evaluation grid scores.

Training and evaluation therefore share one target definition. The trigger
rule and window cadence are frozen with the family. Daily-sampled rows whose
window has no trigger are simply absent; nothing is zero-filled.

The public surface matches DatasetH (``prepare``/``fetch``/``feature_names``/
``segments``), so LGBModel works unchanged. All decisions use information
available no later than the entry itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from dynaloop.learned_factors.handler import DK_I, DK_L, DK_R
from dynaloop.learned_factors.label_alignment import (
    TriggerSpec,
    WindowSpec,
    build_windows,
    pick_entry,
    window_target,
)
from dynaloop.learned_factors.provider import QlibBinaryProvider


@dataclass(frozen=True, slots=True)
class AlignedConfig:
    """Configuration of the flexible-decision / fixed-window alignment."""

    window: WindowSpec
    trigger: TriggerSpec
    signal_feature: str | None = None  # feature used by the threshold trigger

    def __post_init__(self) -> None:
        if self.trigger.kind == "threshold" and not self.signal_feature:
            raise ValueError("threshold trigger needs signal_feature")

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window.to_dict(),
            "trigger": self.trigger.to_dict(),
            "signal_feature": self.signal_feature,
        }


class AlignedDataset:
    """A window-aligned view over an already materialised feature frame."""

    def __init__(
        self,
        provider: QlibBinaryProvider,
        feature_frame: pd.DataFrame,
        feature_names: tuple[str, ...],
        segments: Mapping[str, tuple[str, str]],
        config: AlignedConfig,
    ) -> None:
        self.config = config
        self.feature_names = tuple(feature_names)
        self.segments = {k: (str(v[0]), str(v[1])) for k, v in segments.items()}
        self.calendar = provider.calendar
        self.frame = self._build(provider, feature_frame)

    def _build(
        self, provider: QlibBinaryProvider, feature_frame: pd.DataFrame,
    ) -> pd.DataFrame:
        windows = build_windows(self.calendar, self.config.window)
        # Assign each window to its segment by full containment. A window that
        # straddles a split is dropped (grid purging), never partially labelled.
        bounds = {
            name: (int(np.searchsorted(self.calendar, pd.Timestamp(start), side="left")),
                   int(np.searchsorted(self.calendar, pd.Timestamp(end), side="right")) - 1)
            for name, (start, end) in self.segments.items()
        }
        window_segment: dict[int, str] = {}
        for w in windows:
            for name, (lo, hi) in bounds.items():
                if lo <= w.start_pos and w.end_pos <= hi:
                    window_segment[w.start_pos] = name
                    break

        by_symbol: dict[str, pd.DataFrame] = {}
        closes: dict[str, np.ndarray] = {}
        for symbol in feature_frame.index.get_level_values("instrument").unique():
            by_symbol[symbol] = feature_frame.xs(symbol, level="instrument").sort_index()
            closes[symbol] = provider.frame(symbol)["close"].to_numpy(dtype=float)

        signal_col = self.config.signal_feature
        rows: list[dict[str, Any]] = []
        indices: list[tuple[pd.Timestamp, str]] = []
        for w in windows:
            segment = window_segment.get(w.start_pos)
            if segment is None:
                continue
            for symbol, frame in by_symbol.items():
                mask = provider.membership_mask(symbol)
                decision_pos = w.start_pos
                if decision_pos >= len(mask) or not mask[decision_pos]:
                    continue
                # Signal is evaluated over the whole window from a feature that
                # is known at each session (no label, no future).
                if signal_col:
                    signal = frame[signal_col].reindex(self.calendar).to_numpy(dtype=float)
                else:
                    signal = np.zeros(len(self.calendar))
                dec = pick_entry(w, self.calendar, signal,
                                 self.config.trigger, self.config.window)
                if dec is None:
                    continue
                entry_ts = self.calendar[dec.entry_pos]
                if entry_ts not in frame.index:
                    continue
                target = window_target(closes[symbol], dec)
                if target is None:
                    continue
                feature_row = frame.loc[entry_ts, list(self.feature_names)].to_numpy(dtype=float)
                record: dict[str, Any] = {
                    name: float(value) for name, value in zip(self.feature_names, feature_row)
                }
                record["segment"] = segment
                record["label_raw"] = float(target)
                rows.append(record)
                indices.append((self.calendar[decision_pos], symbol))

        if not rows:
            raise ValueError("aligned dataset produced no decisions")
        df = pd.DataFrame(rows, index=pd.MultiIndex.from_tuples(
            indices, names=["datetime", "instrument"]))
        # Cross-sectional z-score of the label per decision date, matching
        # Qlib's learn processor CSZScoreNorm on labels.
        grp = df.groupby(level="datetime")["label_raw"]
        mean = grp.transform("mean").to_numpy(dtype=float)
        std = grp.transform("std").to_numpy(dtype=float)
        std = np.where(np.isfinite(std) & (std > 1e-12), std, np.nan)
        df["label"] = ((df["label_raw"].to_numpy(dtype=float) - mean) / std).astype(np.float32)
        return df.sort_index()

    def prepare(
        self,
        segment: str = "test",
        col_set: str | tuple[str, ...] = "feature",
        data_key: str = DK_I,
    ) -> pd.DataFrame:
        if segment not in self.segments:
            raise KeyError(f"unknown segment: {segment}")
        selected = self.frame[self.frame["segment"] == segment]
        wanted = (col_set,) if isinstance(col_set, str) else tuple(col_set)
        columns: list[str] = []
        for item in wanted:
            if item == "feature":
                columns.extend(self.feature_names)
            elif item == "label":
                columns.append("label" if data_key == DK_L else "label_raw")
            else:
                raise ValueError(f"unknown col_set member: {item}")
        return selected[columns]

    @property
    def handler(self) -> "AlignedDataset":
        """Minimal fetch-compatible view for run_workflow's raw-label read."""
        return self

    def fetch(
        self,
        segment: tuple[str, str] | slice,
        col_set: str | tuple[str, ...] = "feature",
        data_key: str = DK_I,
    ) -> pd.DataFrame:
        start, end = (segment.start, segment.stop) if isinstance(segment, slice) else segment
        dates = self.frame.index.get_level_values("datetime")
        selected = self.frame[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
        wanted = (col_set,) if isinstance(col_set, str) else tuple(col_set)
        columns: list[str] = []
        for item in wanted:
            if item == "feature":
                columns.extend(self.feature_names)
            elif item == "label":
                columns.append("label" if data_key == DK_L else "label_raw")
            else:
                raise ValueError(f"unknown col_set member: {item}")
        return selected[columns].rename(columns={"label_raw": "label_raw"})
