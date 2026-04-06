import logging
import re
from datetime import datetime, timezone
from time import mktime

import feedparser

from .dedup import is_new

logger = logging.getLogger(__name__)


def strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_date(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime.fromtimestamp(
                mktime(entry.published_parsed), tz=timezone.utc
            ).isoformat()
        except (ValueError, OverflowError):
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime.fromtimestamp(
                mktime(entry.updated_parsed), tz=timezone.utc
            ).isoformat()
        except (ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc).isoformat()


def fetch_feed(url: str, timeout: int = 30) -> list[dict]:
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "PlatformEngResearchAgent/1.0"})
        if feed.bozo and not feed.entries:
            logger.warning("Feed error for %s: %s", url, feed.bozo_exception)
            return []

        articles = []
        for entry in feed.entries:
            link = entry.get("link", "")
            if not link:
                continue
            articles.append({
                "title": entry.get("title", "Untitled"),
                "url": link,
                "published": _parse_date(entry),
                "description": strip_html(
                    entry.get("summary", entry.get("description", ""))
                ),
            })
        return articles
    except Exception as e:
        logger.warning("Failed to fetch feed %s: %s", url, e)
        return []


def fetch_all_feeds(feeds_config: list[dict], seen: dict) -> list[dict]:
    new_articles = []
    for feed_cfg in feeds_config:
        url = feed_cfg["url"]
        category = feed_cfg.get("category", "Uncategorized")
        priority = feed_cfg.get("priority", "medium")

        articles = fetch_feed(url)
        logger.info("Fetched %d articles from %s", len(articles), url)

        for article in articles:
            if is_new(article["url"], seen):
                article["category"] = category
                article["priority"] = priority
                new_articles.append(article)

    logger.info("Total new articles across all feeds: %d", len(new_articles))
    return new_articles
