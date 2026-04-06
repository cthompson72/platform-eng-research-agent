import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

PRUNE_DAYS = 180


def load_seen(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("Could not load seen articles from %s: %s. Starting fresh.", path, e)
        return {}


def save_seen(path: str, seen: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PRUNE_DAYS)).isoformat()
    pruned = {
        url: meta for url, meta in seen.items()
        if meta.get("first_seen", "") >= cutoff
    }
    pruned_count = len(seen) - len(pruned)
    if pruned_count > 0:
        logger.info("Pruned %d articles older than %d days.", pruned_count, PRUNE_DAYS)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=2, sort_keys=True)


def is_new(url: str, seen: dict) -> bool:
    return url not in seen


def mark_seen(url: str, metadata: dict, seen: dict) -> None:
    seen[url] = {
        "title": metadata.get("title", ""),
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "category": metadata.get("category", ""),
        "score": metadata.get("score", 0),
    }
