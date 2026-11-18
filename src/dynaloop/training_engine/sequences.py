"""Causal price features shared by real observations and generated paths."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

FEATURES = ("return_1", "momentum_5", "momentum_20", "volatility_20", "drawdown_20")
CONTEXT = 20


def price_features(close: np.ndarray) -> np.ndarray:
    close = np.asarray(close, dtype=np.float64)
    if close.ndim != 1 or not np.isfinite(close).all() or (close <= 0).any():
        raise ValueError("close must be a finite positive vector")
    series = pd.Series(close)
    returns = np.log(series).diff()
    return np.column_stack((returns * 100, returns.rolling(5).sum() * 100,
        returns.rolling(20).sum() * 100, returns.rolling(20).std(ddof=0) * 100,
        (series / series.rolling(20).max() - 1) * 100)).astype(np.float32)


@dataclass
class SequenceData:
    symbol: str
    records: list[dict]
    features: np.ndarray
    indices: np.ndarray
    x: np.ndarray
    y: np.ndarray
    paths: np.ndarray
    dates: np.ndarray
    maturity: np.ndarray

    def partition(self, start: str, end: str) -> np.ndarray:
        # Purge labels that mature across the upper split boundary.
        return (self.dates >= start) & (self.maturity <= end)


def sequences(records: list[dict], symbol: str, window: int, horizon: int) -> SequenceData:
    if type(window) is not int or window < 1 or type(horizon) is not int or horizon < 1:
        raise ValueError("window and horizon must be positive integers")
    dates = np.array([str(r["date"]) for r in records])
    if list(dates) != sorted(set(dates)):
        raise ValueError("timestamps must be strictly increasing")
    if any(r.get("symbol", symbol) != symbol for r in records):
        raise ValueError("mixed symbols")
    close = np.array([r["close"] for r in records], dtype=np.float64)
    features = price_features(close)
    returns = np.diff(np.log(close), prepend=np.nan) * 100
    indices = np.arange(CONTEXT + window, len(close) - horizon)
    if len(indices) == 0:
        raise ValueError("insufficient history")
    x = np.stack([features[i-window+1:i+1] for i in indices])
    y = np.array([(close[i+horizon] / close[i] - 1) * 100 for i in indices], dtype=np.float32)
    # Each path: 20 conditioning returns, window input returns, horizon labels.
    paths = np.stack([returns[i-window-CONTEXT+1:i+horizon+1] for i in indices]).astype(np.float32)
    if not all(np.isfinite(a).all() for a in (x, y, paths)):
        raise ValueError("nonfinite sequence data")
    return SequenceData(symbol, records, features, indices, x, y, paths,
                        dates[indices], dates[indices+horizon])


def generated_samples(paths: np.ndarray, window: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    paths = np.asarray(paths)
    if paths.ndim != 2 or paths.shape[1] != CONTEXT + window + horizon or not np.isfinite(paths).all():
        raise ValueError("invalid generated path dimensions or values")
    if np.max(np.abs(paths), initial=0) > 50:
        raise ValueError("generated daily log return exceeds safety bound")
    inputs, targets = [], []
    for path in paths:
        close = np.exp(np.r_[0., np.cumsum(path.astype(np.float64) / 100)])
        features = price_features(close)
        decision = CONTEXT + window
        inputs.append(features[decision-window+1:decision+1])
        targets.append((close[-1] / close[decision] - 1) * 100)
    return np.asarray(inputs, dtype=np.float32), np.asarray(targets, dtype=np.float32)


@dataclass
class FeatureScaler:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, x: np.ndarray) -> "FeatureScaler":
        return cls(x.mean(axis=(0, 1)), np.maximum(x.std(axis=(0, 1)), 1e-5))

    def transform(self, x: np.ndarray) -> np.ndarray:
        # Fixed clipping is a numerical bound, not fitted on test extremes.
        return np.clip((x - self.mean) / self.scale, -10, 10).astype(np.float32)

    def to_dict(self):
        return dict(mean=self.mean.tolist(), scale=self.scale.tolist())
