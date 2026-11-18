"""Living strategy library: harvested candidate practices with report-only
experience stars. Nothing here is a validated factor, verdict or return claim,
and nothing here enters any freeze fingerprint or statistical gate.
"""

from dynaloop.live_strategy.contracts import (
    ExperienceEvent,
    ProviderReport,
    StrategyEntry,
    LIVE_STRATEGY_SCHEMA_VERSION,
)
from dynaloop.live_strategy.collector import (
    NullStrategyCollector,
    StructuredCandidateCollector,
    StrategyCollector,
    normalize_candidate,
)
from dynaloop.live_strategy.experience import (
    DEFAULT_HALF_LIFE_DAYS,
    decayed_tally,
    experience_report,
    wilson_lower_bound,
)
from dynaloop.live_strategy.index import retrieve_relevant
from dynaloop.live_strategy.service import LiveStrategyLibrary
from dynaloop.live_strategy.store import StrategyLibraryStore

__all__ = [
    "LIVE_STRATEGY_SCHEMA_VERSION",
    "StrategyEntry", "ExperienceEvent", "ProviderReport",
    "StrategyCollector", "NullStrategyCollector", "StructuredCandidateCollector",
    "normalize_candidate",
    "decayed_tally", "wilson_lower_bound", "experience_report",
    "DEFAULT_HALF_LIFE_DAYS",
    "retrieve_relevant",
    "StrategyLibraryStore", "LiveStrategyLibrary",
]
