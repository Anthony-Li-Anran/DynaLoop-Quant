"""Local analogue of ``qlib.data.dataset.handler.DataHandlerLP``.

Alpha158 uses ``infer_processors=[]`` (features are handed to the model as-is,
LightGBM handles NaN) and ``learn_processors=[DropnaLabel, CSZScoreNorm(label)]``.
The raw label is retained separately because the certification layer needs
realised returns, not the cross-sectionally normalised training target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd

from dynaloop.learned_factors.alpha158 import feature_config, label_config
from dynaloop.learned_factors.expression import ExpressionEvaluator
from dynaloop.learned_factors.provider import QlibBinaryProvider

DK_R = "raw"
DK_I = "infer"
DK_L = "learn"

DEFAULT_LEARN_PROCESSORS = ("DropnaLabel", "CSZScoreNorm")


@dataclass(frozen=True, slots=True)
class HandlerConfig:
    universe: str = "csi300"
    start_time: str = "2008-01-01"
    end_time: str = "2020-08-01"
    fit_start_time: str | None = None
    fit_end_time: str | None = None
    infer_processors: tuple[str, ...] = ()
    learn_processors: tuple[str, ...] = DEFAULT_LEARN_PROCESSORS
    features: Mapping[str, str] = field(default_factory=feature_config)
    labels: Mapping[str, str] = field(default_factory=label_config)
    # Runtime information barrier: during the search stage nothing later than
    # this date is materialised. It is NOT a change to the frozen data config.
    materialise_until: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe": self.universe,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "fit_start_time": self.fit_start_time,
            "fit_end_time": self.fit_end_time,
            "infer_processors": list(self.infer_processors),
            "learn_processors": list(self.learn_processors),
            "features": dict(self.features),
            "labels": dict(self.labels),
            "materialise_until": self.materialise_until,
        }


class Alpha158Handler:
    """Materialise the standard feature library and labels for one universe."""

    def __init__(self, provider: QlibBinaryProvider, config: HandlerConfig) -> None:
        self.provider = provider
        self.config = config
        self.feature_names = tuple(config.features)
        self.label_names = tuple(config.labels)
        if len(self.label_names) != 1:
            raise ValueError("Alpha158 declares exactly one label")
        self.frame = self._build()

    def _build(self) -> pd.DataFrame:
        cfg = self.config
        start = pd.Timestamp(cfg.start_time)
        end = pd.Timestamp(cfg.materialise_until or cfg.end_time)
        if end < start:
            raise ValueError("materialise_until is earlier than start_time")

        blocks: list[np.ndarray] = []
        indices: list[pd.MultiIndex] = []
        label_raw: list[np.ndarray] = []
        label_expression = cfg.labels[self.label_names[0]]

        # Qlib materialises the full calendar per instrument. Rows outside the
        # membership intervals are discarded anyway, so we keep only each
        # instrument's active span plus a warm-up for the 60-day rolling window.
        # This is a compute optimisation; it does not change any feature value.
        warmup = pd.Timedelta(days=120)
        for symbol in self.provider.symbols:
            full = self.provider.frame(symbol)
            spans = [
                (lo, hi) for lo, hi in self.provider.membership.get(symbol, ())
                if hi >= start and lo <= end
            ]
            if not spans:
                continue
            left = min(lo for lo, _ in spans) - warmup
            right = min(max(hi for _, hi in spans), end)
            frame = full.loc[left:right]
            if frame.empty:
                continue
            evaluator = ExpressionEvaluator(frame)
            columns = np.empty((len(frame), len(self.feature_names)), dtype=np.float32)
            for j, name in enumerate(self.feature_names):
                columns[:, j] = np.asarray(
                    evaluator.evaluate(cfg.features[name]), dtype=np.float32
                )
            raw_label = np.asarray(evaluator.evaluate(label_expression), dtype=np.float64)

            mask = np.zeros(len(frame), dtype=bool)
            for lo, hi in spans:
                mask |= (np.asarray(frame.index >= lo) & np.asarray(frame.index <= hi))
            mask &= np.asarray(frame.index >= start)
            mask &= np.asarray(frame.index <= end)
            if not mask.any():
                continue
            dates = frame.index[mask]
            blocks.append(columns[mask])
            label_raw.append(raw_label[mask])
            indices.append(pd.MultiIndex.from_product(
                [dates, [symbol]], names=["datetime", "instrument"]
            ))

        if not blocks:
            raise ValueError("empty handler: no in-universe observations")
        values = np.vstack(blocks)
        labels = np.concatenate(label_raw)
        index = indices[0].append(indices[1:]) if len(indices) > 1 else indices[0]
        df = pd.DataFrame(values, index=index, columns=list(self.feature_names), dtype=np.float32)
        df["label_raw"] = labels.astype(np.float32)

        if "DropnaLabel" in cfg.learn_processors:
            df = df[np.isfinite(df["label_raw"].to_numpy())].copy()
        if "CSZScoreNorm" in cfg.learn_processors:
            grouped = df.groupby(level="datetime")["label_raw"]
            mean = grouped.transform("mean").to_numpy(dtype=np.float64)
            std = grouped.transform("std").to_numpy(dtype=np.float64)
            std = np.where(np.isfinite(std) & (std > 1e-12), std, np.nan)
            df["label"] = ((df["label_raw"].to_numpy(dtype=np.float64) - mean) / std).astype(np.float32)
        else:
            df["label"] = df["label_raw"]
        if cfg.infer_processors:
            raise ValueError("custom infer_processors are not part of the Alpha158 default")
        return df.sort_index()

    def fetch(
        self,
        segment: tuple[str, str] | slice,
        col_set: str | tuple[str, ...] = "feature",
        data_key: str = DK_I,
    ) -> pd.DataFrame:
        """Qlib ``DataHandlerLP.fetch``-style selector over a time segment."""
        if isinstance(segment, slice):
            start, end = segment.start, segment.stop
        else:
            start, end = segment
        left, right = pd.Timestamp(start), pd.Timestamp(end)
        dates = self.frame.index.get_level_values("datetime")
        selected = self.frame[(dates >= left) & (dates <= right)]
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
