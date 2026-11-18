"""End-to-end local workflow: provider -> handler -> dataset -> model -> signal.

The four stages mirror ``qlib/examples/workflow_by_code.py`` (DataHandler,
DatasetH, LGBModel.fit/predict, SignalRecord/SigAnaRecord). Nothing here
decides whether a factor is "effective": that verdict belongs to the separate,
already-frozen certification layer in ``research_engine.cross_section``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from dynaloop.learned_factors.alpha158 import config_fingerprint
from dynaloop.learned_factors.dataset import DatasetConfig, DatasetH
from dynaloop.learned_factors.handler import DK_R
from dynaloop.learned_factors.model import LGBConfig, LGBModel
from dynaloop.learned_factors.provider import QlibBinaryProvider


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    dataset: DatasetConfig
    model: LGBConfig

    def to_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset.to_dict(), "model": self.model.to_dict()}

    @property
    def library_fingerprint(self) -> str:
        handler = self.dataset.handler
        return config_fingerprint(handler.features, handler.labels)


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    predictions: pd.Series
    best_iteration: int
    signal_analysis: dict[str, Any]
    feature_importance: dict[str, int]
    evals_result: dict[str, Any]


def signal_analysis(
    predictions: pd.Series,
    label_raw: pd.Series,
    *,
    quantiles: int = 5,
) -> dict[str, Any]:
    """Descriptive SigAnaRecord-style metrics; no acceptance rule is applied.

    Qlib's ``SignalRecord.generate_label`` uses ``DK_R`` (raw labels), and
    ``SigAnaRecord`` feeds those raw labels to ``calc_ic`` and
    ``calc_long_short_return``. The latter returns a HALF spread
    ``(top - bottom) / 2`` plus the universe mean, which is the definition we
    reproduce here. Quantile *excess* returns are kept as an extra diagnostic.
    """
    joined = pd.concat(
        [predictions.rename("pred"), label_raw.rename("label")], axis=1
    )
    if joined.empty:
        return {"status": "no_overlapping_observations"}
    ic_values: list[float] = []
    rank_ic_values: list[float] = []
    group_returns: list[np.ndarray] = []
    long_short_returns: list[float] = []
    long_average_returns: list[float] = []
    for _date, group in joined.groupby(level="datetime", sort=True):
        # Qlib's per-date correlation drops non-finite PAIRS, not whole days.
        pair = group.replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) < quantiles * 2:
            continue
        pred = pair["pred"].to_numpy(dtype=float)
        label = pair["label"].to_numpy(dtype=float)
        ic_values.append(float(np.corrcoef(pred, label)[0, 1]))
        rank_pred = pd.Series(pred).rank().to_numpy()
        rank_label = pd.Series(label).rank().to_numpy()
        rank_ic_values.append(float(np.corrcoef(rank_pred, rank_label)[0, 1]))

        order = np.argsort(pred)
        size = int(len(order) / quantiles)
        if size < 1:
            continue
        sorted_label = label[order]
        equal_weight = float(label.mean())
        group_returns.append(
            np.asarray(
                [float(sorted_label[i * size:(i + 1) * size].mean() - equal_weight)
                 for i in range(quantiles)],
                dtype=float,
            )
        )
        top = float(sorted_label[-size:].mean())
        bottom = float(sorted_label[:size].mean())
        long_short_returns.append((top - bottom) / 2)
        long_average_returns.append(equal_weight)

    ic = np.asarray(ic_values, dtype=float)
    rank_ic = np.asarray(rank_ic_values, dtype=float)
    groups = np.asarray(group_returns, dtype=float) if group_returns else np.empty((0, quantiles))
    mean_groups = groups.mean(axis=0) if len(groups) else np.zeros(quantiles)
    ls = np.asarray(long_short_returns, dtype=float)
    avg = np.asarray(long_average_returns, dtype=float)
    return {
        "periods": int(len(ic)),
        "ic": float(ic.mean()) if ic.size else None,
        "icir": float(ic.mean() / ic.std(ddof=1)) if ic.size > 1 and ic.std(ddof=1) > 0 else None,
        "rank_ic": float(rank_ic.mean()) if rank_ic.size else None,
        "rank_icir": float(rank_ic.mean() / rank_ic.std(ddof=1))
        if rank_ic.size > 1 and rank_ic.std(ddof=1) > 0 else None,
        "mean_quantile_excess_returns": [float(v) for v in mean_groups],
        "long_short_quantile_spread": float(mean_groups[-1] - mean_groups[0]),
        "long_short_return": float(ls.mean()) if ls.size else None,
        "long_average_return": float(avg.mean()) if avg.size else None,
        "metric_sources": [
            "Qlib qlib.workflow.record_temp.SigAnaRecord (IC, ICIR, Rank IC, Rank ICIR)",
            "Qlib qlib.workflow.record_temp.SignalRecord.generate_label (data_key=DK_R)",
            "Qlib qlib.contrib.eva.alpha.calc_ic / calc_long_short_return",
        ],
        "note": (
            "descriptive only; Qlib applies no significance test or factor acceptance rule. "
            "long_short_return is Qlib's half spread (top-bottom)/2; "
            "long_short_quantile_spread is a separate full-spread diagnostic."
        ),
    }


def run_workflow(
    provider: QlibBinaryProvider,
    config: WorkflowConfig,
    *,
    frozen_model_text: str | None = None,
    dataset: Any | None = None,
) -> tuple[WorkflowResult, LGBModel]:
    """Fit (or restore) the model and produce test-segment predictions.

    ``dataset`` may be supplied by the caller to use an alternative view (e.g.
    ``AlignedDataset`` with flexible entries and fixed-window targets). It must
    expose the DatasetH surface (prepare/fetch/feature_names/segments/handler).
    Omitting it preserves the default daily-sampled DatasetH behaviour.
    """
    if dataset is None:
        dataset = DatasetH(provider, config.dataset)
    if frozen_model_text is None:
        model = LGBModel(config.model).fit(dataset)
    else:
        model = LGBModel.from_string(frozen_model_text, config.model)
    predictions = model.predict(dataset, segment="test")
    labels = dataset.handler.fetch(
        dataset.segments["test"], col_set="label", data_key=DK_R
    )["label_raw"]
    analysis = signal_analysis(predictions, labels)
    result = WorkflowResult(
        predictions=predictions,
        best_iteration=int(model.best_iteration or 0),
        signal_analysis=analysis,
        feature_importance=model.feature_importance(dataset),
        evals_result=model.evals_result,
    )
    return result, model
