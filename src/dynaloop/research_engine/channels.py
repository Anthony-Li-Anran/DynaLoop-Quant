"""Part A channel identity, labelled evidence, and the mixed-family guard.

The two channels (cross-sectional stock selection and single-instrument timing)
are both legitimate research objects, but their null hypotheses, baselines and
sample structures differ. They must never enter the same judgement family.

This module owns the vocabulary, the Chinese evidence labels and the guard. It
deliberately implements NEITHER verdict. Judgement lives in ``cross_section.py``
and ``effectiveness.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from dynaloop.research_engine.spec import fingerprint

CHANNEL_CROSS_SECTION = "cross_section"
CHANNEL_TIMING = "timing"

CHANNEL_LABELS: dict[str, str] = {
    CHANNEL_CROSS_SECTION: "横截面有效因子",
    CHANNEL_TIMING: "择时有效因子",
}

CHANNEL_ASSERTIONS: dict[str, str] = {
    CHANNEL_CROSS_SECTION: "同一时点标的池内的相对排序能力，在冻结后的独立窗口上稳定可重复",
    CHANNEL_TIMING: "单只标的的时序方向 / 关系，在冻结后的独立窗口上稳定可重复",
}

CHANNEL_SCOPE_LIMITS: dict[str, str] = {
    CHANNEL_CROSS_SECTION: (
        "不认证任何单只标的的进出时点、市场方向、盈利能力或未来持续；"
        "静态 / 近似成分股名单下幸存者偏差未消除；结论不得外推到其它标的池"
    ),
    CHANNEL_TIMING: (
        "不认证任何标的池的相对排序、市场方向、盈利能力或未来持续；"
        "结论只对冻结候选绑定的那一只标的与验证窗口有效"
    ),
}

NOT_CLAIMED: tuple[str, ...] = (
    "跨轮自适应 / 序贯错误率",
    "共形覆盖保证",
    "盈利能力与可交易性",
    "因果关系",
    "关系在未来持续",
    "跨通道外推",
)


class ChannelIsolationError(ValueError):
    """A candidate from the other channel entered this family. Never merge."""


def require_channel(channel: str) -> str:
    if channel not in CHANNEL_LABELS:
        raise ValueError(f"unknown Part A channel: {channel!r}")
    return channel


def channel_fields(channel: str) -> dict[str, Any]:
    """Channel identity fields written into every report, verdict and spec."""
    require_channel(channel)
    return {
        "channel": channel,
        "channel_label": CHANNEL_LABELS[channel],
        "assertion": CHANNEL_ASSERTIONS[channel],
        "scope_limit": CHANNEL_SCOPE_LIMITS[channel],
        "not_claimed": list(NOT_CLAIMED),
    }


def enforce_channel(channel: str, candidates: Iterable[Any]) -> None:
    """Reject candidates declared for the other channel, or a mixed family.

    Candidates that carry no ``metadata["channel"]`` are accepted: the family
    is always defined by the verdict function being called. A declared channel
    is evidence that must agree with that call.
    """
    require_channel(channel)
    declared: set[str] = set()
    for candidate in candidates:
        metadata = getattr(candidate, "metadata", None)
        value = metadata.get("channel") if isinstance(metadata, Mapping) else None
        if value is None:
            continue
        if value not in CHANNEL_LABELS:
            raise ChannelIsolationError(f"candidate declares unknown channel {value!r}")
        declared.add(value)
    if len(declared) > 1:
        raise ChannelIsolationError(
            "candidates from both channels were placed in one judgement family"
        )
    if declared and channel not in declared:
        raise ChannelIsolationError(
            f"candidates declared for {sorted(declared)} cannot be judged as {channel}"
        )


@dataclass(frozen=True, slots=True)
class FactorEvidence:
    """One labelled, fingerprinted evidence entry: the Part A delivery unit."""

    channel: str
    channel_label: str
    factor_id: str
    expression: str
    status: str
    claim: str
    assertion: str
    scope_limit: str
    not_claimed: tuple[str, ...]
    effective: bool
    adjusted_p_value: float | None
    periods: int
    report_fingerprint: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "channel_label": self.channel_label,
            "factor_id": self.factor_id,
            "expression": self.expression,
            "status": self.status,
            "claim": self.claim,
            "assertion": self.assertion,
            "scope_limit": self.scope_limit,
            "not_claimed": list(self.not_claimed),
            "effective": self.effective,
            "adjusted_p_value": self.adjusted_p_value,
            "periods": self.periods,
            "report_fingerprint": self.report_fingerprint,
            "fingerprint": self.fingerprint,
        }


def evidence_from_report(report: Any, *, channel: str) -> tuple[FactorEvidence, ...]:
    """Normalise one channel's report into labelled evidence entries.

    Both channel reports expose ``candidates`` (with ``factor_id``,
    ``expression``, ``status``, ``adjusted_p_value``, ``periods``) and a
    ``fingerprint``. Duck typing keeps the two verdict modules independent.
    """
    require_channel(channel)
    declared = getattr(report, "channel", None)
    if declared is not None and declared != channel:
        raise ChannelIsolationError(
            f"report declares channel {declared!r}, cannot be read as {channel!r}"
        )
    label = CHANNEL_LABELS[channel]
    entries: list[FactorEvidence] = []
    for verdict in report.candidates:
        effective = bool(verdict.status == "effective")
        claim = (
            f"{label}：{verdict.factor_id} 在冻结窗口上通过全部判定，状态 effective"
            if effective else
            f"{label}（本次未获认证）：{verdict.factor_id} 状态 {verdict.status}"
        )
        digest = fingerprint({
            "channel": channel,
            "factor_id": verdict.factor_id,
            "status": verdict.status,
            "report_fingerprint": report.fingerprint,
        })
        entries.append(FactorEvidence(
            channel=channel,
            channel_label=label,
            factor_id=verdict.factor_id,
            expression=getattr(verdict, "expression", ""),
            status=verdict.status,
            claim=claim,
            assertion=CHANNEL_ASSERTIONS[channel],
            scope_limit=CHANNEL_SCOPE_LIMITS[channel],
            not_claimed=NOT_CLAIMED,
            effective=effective,
            adjusted_p_value=float(verdict.adjusted_p_value),
            periods=int(verdict.periods),
            report_fingerprint=report.fingerprint,
            fingerprint=digest,
        ))
    return tuple(entries)
