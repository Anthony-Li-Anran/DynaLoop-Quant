"""Best-effort real news provider backed by akshare (Eastmoney feed).

Network access is optional and never required for the rest of the system. When
the feed is reachable, real headlines with their genuine publish time are
returned. ``available_at`` is set to the fetch time: a headline is treated as
usable only from the moment this system obtained it, never back-dated to its
publish time (``docs/brain.md`` alignment rule). When the feed is down or the
dependency is absent, the provider reports ``available=False`` with a reason
and returns no rows -- it does not fabricate news.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from dynaloop.alternative_data.contracts import NewsRecord, ProviderStatus

_MODEL_VERSION = "akshare-stock-news-em/1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_publish_time(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class AkshareNewsProvider:
    """Real A-share news via ``ak.stock_news_em``; degrades explicitly."""

    def __init__(self, *, model_version: str = _MODEL_VERSION) -> None:
        self._model_version = model_version
        self._last_error: str | None = None

    @property
    def name(self) -> str:
        return "akshare.stock_news_em"

    def status(self) -> ProviderStatus:
        try:
            import akshare  # noqa: F401
        except Exception as exc:  # dependency absent
            return ProviderStatus(
                name=self.name, available=False,
                reason=f"akshare unavailable: {type(exc).__name__}",
            )
        return ProviderStatus(
            name=self.name,
            available=self._last_error is None,
            reason=self._last_error,
        )

    def fetch(self, *, symbols: Sequence[str] = (), limit: int = 50) -> list[NewsRecord]:
        import akshare as ak

        symbols = tuple(symbols)
        if not symbols:
            self._last_error = "no symbols supplied"
            return []

        fetched_at = _utc_now()
        available_at = fetched_at  # usable only from the moment we obtained it
        out: list[NewsRecord] = []
        errors: list[str] = []
        for symbol in symbols:
            try:
                frame = ak.stock_news_em(symbol=str(symbol))
            except Exception as exc:  # network / upstream failure
                errors.append(f"{symbol}: {type(exc).__name__}")
                continue
            for _, row in frame.head(max(0, limit)).iterrows():
                headline = str(row.get("新闻标题", "")).strip()
                if not headline:
                    continue
                out.append(NewsRecord(
                    headline=headline,
                    source=str(row.get("文章来源", "eastmoney")).strip() or "eastmoney",
                    published_at=_normalise_publish_time(row.get("发布时间")),
                    fetched_at=fetched_at,
                    available_at=available_at,
                    symbols=(str(symbol),),
                    model_version=self._model_version,
                    raw_excerpt=(str(row.get("新闻内容", ""))[:500]
                                 if "新闻内容" in row else None),
                    meta={"link": str(row.get("新闻链接", "")) or None},
                ))

        self._last_error = "; ".join(errors) if (errors and not out) else None
        return out


__all__ = ["AkshareNewsProvider"]
