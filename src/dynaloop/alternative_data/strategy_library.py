"""Read-only registry of external strategy-library candidates.

Sourced from the upstream survey done on 2026-11-18. Entries are metadata for
the subjective-analysis input context ONLY. No returns, no backtest numbers,
no "effective" label is carried over: those upstream claims are not validated
by this project and must not be laundered into an evidence claim here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    name: str
    url: str
    family: str
    license_note: str
    relevance: str
    caveat: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "url": self.url, "family": self.family,
            "license_note": self.license_note, "relevance": self.relevance,
            "caveat": self.caveat,
        }


_CANDIDATES = (
    StrategyCandidate(
        name="QuantsPlaybook",
        url="https://github.com/shirunxian/QuantsPlaybook",
        family="broker-report reproductions: timing / factor / value / portfolio",
        license_note="see repository",
        relevance="Broad A-share strategy taxonomy for candidate naming and lineage.",
        caveat="Upstream return claims are unverified; metadata only.",
    ),
    StrategyCandidate(
        name="cross-sectional-multi-factor-model",
        url="https://github.com/100868871/cross-sectional-multi-factor-model-",
        family="LightGBM cross-sectional multi-factor, walk-forward, PIT alignment",
        license_note="see repository",
        relevance="Methodologically aligned with this project's learned-factor + PIT path.",
        caveat="Reported IC/returns are upstream claims, not reproduced here.",
    ),
    StrategyCandidate(
        name="a-share-sentiment-cycle",
        url="https://github.com/314405571-star/a-share-sentiment-cycle",
        family="rule-based sentiment regime (L1/L2/L3), no training",
        license_note="MIT",
        relevance="Ported as the report-only sentiment-cycle engine in this layer.",
        caveat="No backtest/parameter validation upstream; report-only.",
    ),
    StrategyCandidate(
        name="a-share-quant-v9",
        url="https://github.com/nyc1013/a-share-quant-v9",
        family="weekly multi-factor + breadth timing",
        license_note="see repository",
        relevance="Breadth-timing idea comparable to the sentiment regime output.",
        caveat="Headline returns are upstream claims; not verified or reproduced.",
    ),
)


def list_candidates() -> list[dict[str, Any]]:
    return [c.to_dict() for c in _CANDIDATES]


__all__ = ["StrategyCandidate", "list_candidates"]
