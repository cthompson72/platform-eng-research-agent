import logging
from datetime import datetime, timedelta, timezone

from .search import build_index, rerank_with_claude, search_fts

logger = logging.getLogger(__name__)


def _pre_filter(
    seen: dict,
    date_range: int | None = None,
    category: str | None = None,
    min_score: int | None = None,
) -> dict:
    filtered = {}
    cutoff = None
    if date_range:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=date_range)).isoformat()

    for url, meta in seen.items():
        if cutoff and meta.get("first_seen", "") < cutoff:
            continue
        if category and meta.get("category", "").lower() != category.lower():
            continue
        if min_score and meta.get("score", 0) < min_score:
            continue
        filtered[url] = meta

    return filtered


def run_query(
    query: str,
    seen: dict,
    api_key: str,
    date_range: int | None = None,
    category: str | None = None,
    min_score: int | None = None,
    top_k: int = 10,
) -> dict:
    total = len(seen)
    filtered = _pre_filter(seen, date_range=date_range, category=category, min_score=min_score)
    logger.info("Pre-filtered %d -> %d articles.", total, len(filtered))

    if not filtered:
        return {
            "query": query,
            "results": [],
            "total_searched": 0,
            "filters": {"date_range": date_range, "category": category, "min_score": min_score},
        }

    conn = build_index(filtered)
    candidates = search_fts(conn, query, limit=50)
    conn.close()

    if not candidates:
        logger.info("No FTS5 matches for query: %s", query)
        return {
            "query": query,
            "results": [],
            "total_searched": len(filtered),
            "filters": {"date_range": date_range, "category": category, "min_score": min_score},
        }

    results = rerank_with_claude(candidates, query, api_key, top_k=top_k)

    return {
        "query": query,
        "results": results,
        "total_searched": len(filtered),
        "filters": {"date_range": date_range, "category": category, "min_score": min_score},
    }
