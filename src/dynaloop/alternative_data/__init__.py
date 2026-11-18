"""Shared alternative-data layer for subjective and quantitative branches.

All content here is report-only engineering capability: point-in-time news
records and a rule-based sentiment regime. Nothing in this package is a
validated factor, a verdict, or an investment claim.
"""

from dynaloop.alternative_data.contracts import (
    NewsRecord,
    ProviderStatus,
    SentimentRecord,
)
from dynaloop.alternative_data.providers import (
    NewsProvider,
    NullNewsProvider,
    StaticNewsProvider,
    align_to_available_time,
)
from dynaloop.alternative_data.akshare_news import AkshareNewsProvider
from dynaloop.alternative_data.indicators import (
    Bar,
    attempted_board_number,
    is_break_up,
    is_high_face,
    is_limit_down,
    is_limit_up,
    is_sky_floor,
)
from dynaloop.alternative_data.sentiment_cycle import (
    Config,
    DailyMarket,
    EmotionEngine,
    Snapshot,
    State,
)
from dynaloop.alternative_data.subjective_input import build_subjective_input
from dynaloop.alternative_data.strategy_library import list_candidates

__all__ = [
    "NewsRecord", "ProviderStatus", "SentimentRecord",
    "NewsProvider", "NullNewsProvider", "StaticNewsProvider", "AkshareNewsProvider",
    "align_to_available_time",
    "Bar", "attempted_board_number", "is_break_up", "is_high_face",
    "is_limit_down", "is_limit_up", "is_sky_floor",
    "Config", "DailyMarket", "EmotionEngine", "Snapshot", "State",
    "build_subjective_input", "list_candidates",
]
