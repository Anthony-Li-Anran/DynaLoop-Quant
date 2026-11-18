"""Local analogue of ``qlib.contrib.model.gbdt.LGBModel``.

Qlib wraps ``lightgbm.train`` with ``objective=mse``, ``verbosity=-1``,
``early_stopping_rounds=50`` and ``num_boost_round=1000``. We keep those
defaults and add only the explicit seed / single-thread flags needed for a
reproducible preregistration (Qlib itself leaves the RNG implicit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from dynaloop.learned_factors.dataset import DatasetH
from dynaloop.learned_factors.handler import DK_L


@dataclass(frozen=True, slots=True)
class LGBConfig:
    loss: str = "mse"
    early_stopping_rounds: int = 50
    num_boost_round: int = 1000
    seed: int = 0
    num_threads: int = 1

    def __post_init__(self) -> None:
        if self.loss not in ("mse", "binary"):
            raise ValueError("loss must be 'mse' or 'binary'")
        if self.early_stopping_rounds < 1 or self.num_boost_round < 1:
            raise ValueError("boosting rounds must be positive")

    @property
    def params(self) -> dict[str, Any]:
        return {
            "objective": self.loss,
            "verbosity": -1,
            "seed": self.seed,
            "deterministic": True,
            "force_col_wise": True,
            "num_threads": self.num_threads,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "loss": self.loss,
            "early_stopping_rounds": self.early_stopping_rounds,
            "num_boost_round": self.num_boost_round,
            "seed": self.seed,
            "num_threads": self.num_threads,
            "params": self.params,
        }


class LGBModel:
    """Train on ``train`` (early-stopped on ``valid``), predict any segment."""

    def __init__(self, config: LGBConfig = LGBConfig()) -> None:
        self.config = config
        self.model: lgb.Booster | None = None
        self.evals_result: dict[str, Any] = {}
        self.best_iteration: int | None = None

    def fit(self, dataset: DatasetH) -> "LGBModel":
        train = dataset.prepare("train", col_set=("feature", "label"), data_key=DK_L)
        if train.empty:
            raise ValueError("empty train segment")
        x_train = train[list(dataset.feature_names)]
        y_train = np.asarray(train["label"], dtype=float)
        dtrain = lgb.Dataset(x_train.to_numpy(), label=y_train, free_raw_data=False)

        valid_sets = [dtrain]
        valid_names = ["train"]
        if "valid" in dataset.segments:
            valid = dataset.prepare("valid", col_set=("feature", "label"), data_key=DK_L)
            if valid.empty:
                raise ValueError("empty valid segment")
            dvalid = lgb.Dataset(
                valid[list(dataset.feature_names)].to_numpy(),
                label=np.asarray(valid["label"], dtype=float),
                free_raw_data=False,
                reference=dtrain,
            )
            valid_sets.append(dvalid)
            valid_names.append("valid")

        callbacks = [lgb.log_evaluation(period=0), lgb.record_evaluation(self.evals_result)]
        callbacks.append(lgb.early_stopping(self.config.early_stopping_rounds, verbose=False))
        self.model = lgb.train(
            self.config.params,
            dtrain,
            num_boost_round=self.config.num_boost_round,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
        )
        self.best_iteration = int(self.model.best_iteration or self.model.current_iteration())
        return self

    def predict(self, dataset: DatasetH, segment: str = "test") -> pd.Series:
        if self.model is None:
            raise ValueError("model is not fitted yet")
        features = dataset.prepare(segment, col_set="feature")
        values = self.model.predict(
            features[list(dataset.feature_names)].to_numpy(),
            num_iteration=self.best_iteration,
        )
        return pd.Series(values, index=features.index, name="prediction", dtype=float)

    def model_to_string(self) -> str:
        if self.model is None:
            raise ValueError("model is not fitted yet")
        return self.model.model_to_string(num_iteration=self.best_iteration)

    @classmethod
    def from_string(cls, text: str, config: LGBConfig) -> "LGBModel":
        instance = cls(config)
        instance.model = lgb.Booster(model_str=text)
        instance.best_iteration = instance.model.num_trees()
        return instance

    def feature_importance(self, dataset: DatasetH) -> dict[str, float]:
        """Split gain as LightGBM reports it (a float, never truncated)."""
        if self.model is None:
            raise ValueError("model is not fitted yet")
        gain = self.model.feature_importance(importance_type="gain")
        return {
            name: float(value)
            for name, value in zip(dataset.feature_names, gain)
        }
