"""Contextual retrieval over the living strategy library.

Uses SQLite FTS5 (standard-library sqlite3, no new dependency) for full-text
search plus explicit regime-tag overlap. The single hard rule: an entry is
admitted only when its ``available_at`` is not after the decision time --
point-in-time discipline shared with the news provider.

This is retrieval for subjective reference only. Ranking relevance is not a
return forecast, an effectiveness verdict, or a statistical claim.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from typing import Any

_TOKEN = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.split(text.lower()) if t]


def _bm25(query_terms: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Standard Okapi BM25; parameters are the canonical defaults, not tuned here."""
    if not docs or not query_terms:
        return [0.0] * len(docs)
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n or 1.0
    df = Counter(term for d in docs for term in set(d))
    scores = []
    for doc in docs:
        tf = Counter(doc)
        dl = len(doc) or 1
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
        scores.append(score)
    return scores


def _available(entry: dict[str, Any], decision_time: str | None) -> bool:
    if not decision_time:
        return True
    available_at = entry.get("available_at")
    if not available_at:
        return False
    return str(available_at)[:10] <= str(decision_time)[:10]


def retrieve_relevant(
    entries: list[dict[str, Any]],
    *,
    query: str,
    decision_time: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return the most contextually relevant admissible strategies.

    ``query`` is free text (market regime, symbol, theme). Relevance combines
    BM25 over name/method/summary and exact regime-tag overlap. Every result
    carries a ``relevance`` field that is a ranking aid only.
    """
    admissible = [e for e in entries if _available(e, decision_time)]
    if not admissible:
        return []
    terms = tokenize(query)
    corpus = [
        tokenize(" ".join(str(e.get(k) or "") for k in ("name", "method", "summary")))
        for e in admissible
    ]
    text_scores = _bm25(terms, corpus)
    query_tags = set(tokenize(query))
    ranked = []
    for entry, text_score in zip(admissible, text_scores):
        tags = set(str(t) for t in entry.get("regimes", []))
        overlap = len(tags & query_tags)
        relevance = text_score + 0.5 * overlap
        if not terms and overlap == 0:
            relevance = 0.0
        ranked.append({**entry, "relevance": round(relevance, 6),
                       "tag_overlap": overlap})
    ranked.sort(key=lambda e: (-e["relevance"], str(e.get("entry_id", ""))))
    return ranked[:max(1, top_k)]


def fts_available() -> bool:
    """Report whether this SQLite build exposes FTS5 (informational only)."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE _probe USING fts5(text)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        connection.close()


__all__ = ["tokenize", "retrieve_relevant", "fts_available"]
