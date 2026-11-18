"""The Alpha158 standard feature library, reproduced locally from Qlib.

``qlib/contrib/data/loader.py::Alpha158DL.get_feature_config`` and
``qlib/contrib/data/handler.py::Alpha158`` are the authority for every string
below. This module copies the *configuration structure* (kbar / price /
volume / rolling, windows, include/exclude) rather than importing qlib, so the
feature library can be edited later without touching the evaluator.

Default handlers: 9 kbar + 4 price + 29 rolling operators x 5 windows = 158.
"""

from __future__ import annotations

from typing import Any, Mapping

from dynaloop.learned_factors.expression import assert_no_future_reference

DEFAULT_WINDOWS = (5, 10, 20, 30, 60)

DEFAULT_CONFIG: dict[str, Any] = {
    "kbar": {},
    "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
    "rolling": {},
}

KBAR_FIELDS = (
    "($close-$open)/$open",
    "($high-$low)/$open",
    "($close-$open)/($high-$low+1e-12)",
    "($high-Greater($open, $close))/$open",
    "($high-Greater($open, $close))/($high-$low+1e-12)",
    "(Less($open, $close)-$low)/$open",
    "(Less($open, $close)-$low)/($high-$low+1e-12)",
    "(2*$close-$high-$low)/$open",
    "(2*$close-$high-$low)/($high-$low+1e-12)",
)
KBAR_NAMES = ("KMID", "KLEN", "KMID2", "KUP", "KUP2", "KLOW", "KLOW2", "KSFT", "KSFT2")

LABEL_EXPRESSION = "Ref($close, -2)/Ref($close, -1) - 1"
LABEL_NAME = "LABEL0"


def feature_config(config: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Return ``{feature_name: expression}`` with Qlib's exact field order."""
    conf = dict(DEFAULT_CONFIG if config is None else config)
    fields: list[str] = []
    names: list[str] = []

    if "kbar" in conf:
        fields += list(KBAR_FIELDS)
        names += list(KBAR_NAMES)

    if "price" in conf:
        windows = conf["price"].get("windows", range(5))
        feature = conf["price"].get("feature", ["OPEN", "HIGH", "LOW", "CLOSE", "VWAP"])
        for item in feature:
            field = item.lower()
            fields += [
                "Ref($%s, %d)/$close" % (field, d) if d != 0 else "$%s/$close" % field
                for d in windows
            ]
            names += [field.upper() + str(d) for d in windows]

    if "volume" in conf:
        windows = conf["volume"].get("windows", range(5))
        fields += [
            "Ref($volume, %d)/($volume+1e-12)" % d if d != 0 else "$volume/($volume+1e-12)"
            for d in windows
        ]
        names += ["VOLUME" + str(d) for d in windows]

    if "rolling" in conf:
        windows = conf["rolling"].get("windows", list(DEFAULT_WINDOWS))
        include = conf["rolling"].get("include", None)
        exclude = conf["rolling"].get("exclude", [])
        include_set = set(include) if include is not None else None

        def use(op: str) -> bool:
            return op not in exclude and (include_set is None or op in include_set)

        def add(op: str, pattern, name_pattern: str) -> None:
            if use(op):
                fields.extend(pattern(d) for d in windows)
                names.extend(name_pattern % d for d in windows)

        add("ROC", lambda d: "Ref($close, %d)/$close" % d, "ROC%d")
        add("MA", lambda d: "Mean($close, %d)/$close" % d, "MA%d")
        add("STD", lambda d: "Std($close, %d)/$close" % d, "STD%d")
        add("BETA", lambda d: "Slope($close, %d)/$close" % d, "BETA%d")
        add("RSQR", lambda d: "Rsquare($close, %d)" % d, "RSQR%d")
        add("RESI", lambda d: "Resi($close, %d)/$close" % d, "RESI%d")
        add("MAX", lambda d: "Max($high, %d)/$close" % d, "MAX%d")
        add("LOW", lambda d: "Min($low, %d)/$close" % d, "MIN%d")
        add("QTLU", lambda d: "Quantile($close, %d, 0.8)/$close" % d, "QTLU%d")
        add("QTLD", lambda d: "Quantile($close, %d, 0.2)/$close" % d, "QTLD%d")
        add("RANK", lambda d: "Rank($close, %d)" % d, "RANK%d")
        add("RSV", lambda d: "($close-Min($low, %d))/(Max($high, %d)-Min($low, %d)+1e-12)" % (d, d, d), "RSV%d")
        add("IMAX", lambda d: "IdxMax($high, %d)/%d" % (d, d), "IMAX%d")
        add("IMIN", lambda d: "IdxMin($low, %d)/%d" % (d, d), "IMIN%d")
        add("IMXD", lambda d: "(IdxMax($high, %d)-IdxMin($low, %d))/%d" % (d, d, d), "IMXD%d")
        add("CORR", lambda d: "Corr($close, Log($volume+1), %d)" % d, "CORR%d")
        add("CORD", lambda d: "Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), %d)" % d, "CORD%d")
        add("CNTP", lambda d: "Mean($close>Ref($close, 1), %d)" % d, "CNTP%d")
        add("CNTN", lambda d: "Mean($close<Ref($close, 1), %d)" % d, "CNTN%d")
        add("CNTD", lambda d: "Mean($close>Ref($close, 1), %d)-Mean($close<Ref($close, 1), %d)" % (d, d), "CNTD%d")
        add("SUMP", lambda d: "Sum(Greater($close-Ref($close, 1), 0), %d)/(Sum(Abs($close-Ref($close, 1)), %d)+1e-12)" % (d, d), "SUMP%d")
        add("SUMN", lambda d: "Sum(Greater(Ref($close, 1)-$close, 0), %d)/(Sum(Abs($close-Ref($close, 1)), %d)+1e-12)" % (d, d), "SUMN%d")
        add("SUMD", lambda d: "(Sum(Greater($close-Ref($close, 1), 0), %d)-Sum(Greater(Ref($close, 1)-$close, 0), %d))/(Sum(Abs($close-Ref($close, 1)), %d)+1e-12)" % (d, d, d), "SUMD%d")
        add("VMA", lambda d: "Mean($volume, %d)/($volume+1e-12)" % d, "VMA%d")
        add("VSTD", lambda d: "Std($volume, %d)/($volume+1e-12)" % d, "VSTD%d")
        add("WVMA", lambda d: "Std(Abs($close/Ref($close, 1)-1)*$volume, %d)/(Mean(Abs($close/Ref($close, 1)-1)*$volume, %d)+1e-12)" % (d, d), "WVMA%d")
        add("VSUMP", lambda d: "Sum(Greater($volume-Ref($volume, 1), 0), %d)/(Sum(Abs($volume-Ref($volume, 1)), %d)+1e-12)" % (d, d), "VSUMP%d")
        add("VSUMN", lambda d: "Sum(Greater(Ref($volume, 1)-$volume, 0), %d)/(Sum(Abs($volume-Ref($volume, 1)), %d)+1e-12)" % (d, d), "VSUMN%d")
        add("VSUMD", lambda d: "(Sum(Greater($volume-Ref($volume, 1), 0), %d)-Sum(Greater(Ref($volume, 1)-$volume, 0), %d))/(Sum(Abs($volume-Ref($volume, 1)), %d)+1e-12)" % (d, d, d), "VSUMD%d")

    if len(names) != len(set(names)):
        raise ValueError("duplicate Alpha158 feature names")
    result = dict(zip(names, fields))
    assert_no_future_reference(result)
    return result


def label_config() -> dict[str, str]:
    """Qlib Alpha158.get_label_config: next-day buy, day-after sell return."""
    return {LABEL_NAME: LABEL_EXPRESSION}


def config_fingerprint(features: Mapping[str, str], labels: Mapping[str, str]) -> str:
    """Deterministic digest used by the preregistration freeze."""
    import hashlib
    import json

    body = {"features": dict(features), "labels": dict(labels)}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
