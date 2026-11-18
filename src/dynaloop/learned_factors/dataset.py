"""Local analogue of ``qlib.data.dataset.DatasetH`` (segmented handler view)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from dynaloop.learned_factors.handler import Alpha158Handler, DK_I, HandlerConfig
from dynaloop.learned_factors.provider import QlibBinaryProvider


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    handler: HandlerConfig
    segments: Mapping[str, tuple[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "handler": self.handler.to_dict(),
            "segments": {key: list(value) for key, value in self.segments.items()},
        }


class DatasetH:
    """A handler plus named train/valid/test time segments."""

    def __init__(self, provider: QlibBinaryProvider, config: DatasetConfig) -> None:
        self.config = config
        self.handler = Alpha158Handler(provider, config.handler)
        self.segments: dict[str, tuple[str, str]] = {
            key: (str(value[0]), str(value[1]))
            for key, value in config.segments.items()
        }
        if "train" not in self.segments:
            raise ValueError("a train segment is required")

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self.handler.feature_names

    def prepare(
        self,
        segment: str = "test",
        col_set: str | tuple[str, ...] = "feature",
        data_key: str = DK_I,
    ) -> pd.DataFrame:
        if segment not in self.segments:
            raise KeyError(f"unknown segment: {segment}")
        return self.handler.fetch(self.segments[segment], col_set=col_set, data_key=data_key)
