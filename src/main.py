import argparse
import json
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

from .dedup import load_seen, mark_seen, save_seen
from .feed_parser import fetch_all_feeds, fetch_feed
from .notifier import format_digest, post_to_slack
from .scorer import score_articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_digest(articles: list[dict], stats: dict) -> None:
    print(f"\n{'='*60}")
    print(f"Platform Engineering Digest — {stats.get('above_threshold', 0)} articles above threshold")
    print(f"{'='*60}\n")

    from collections import defaultdict
    by_category = defaultdict(list)
    for article in articles:
        by_category[article.get("category", "Uncategorized")].append(article)

    for category in sorted(by_category.keys()):
        print(f"\n--- {category} ---")
        for article in sorted(by_category[category], key=lambda a: a.get("score", 0), reverse=True):
            score = article.get("score", "?")
            print(f"  [{score}/10] {article['title']}")
            print(f"          {article['url']}")
            if article.get("summary"):
                print(f"          {article['summary']}")
            if article.get("tags"):
                print(f"          Tags: {', '.join(article['tags'])}")
            print()

    print(f"{'='*60}")
    print(
        f"Feeds scanned: {stats.get('feeds_scanned', 0)} | "
        f"New articles: {stats.get('new_articles', 0)} | "
        f"Above threshold: {stats.get('above_threshold', 0)}"
    )
    print(f"{'='*60}\n")


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Platform Engineering Research Digest")
    parser.add_argument("--dry-run", action="store_true", help="Print digest to stdout, skip Slack")
    parser.add_argument("--weekly-trends", action="store_true", help="Run weekly trend synthesis instead of daily digest")
    parser.add_argument("--no-score", action="store_true", help="Skip Claude API scoring")
    parser.add_argument("--full-text", action="store_true", help="Fetch full article text for richer scoring")
    parser.add_argument("--single-feed", type=str, default=None, help="Fetch only this feed URL (for debugging)")
    parser.add_argument("--no-scrape", action="store_true", help="Skip web scraping sources")
    parser.add_argument("--single-scraper", type=str, default=None, help="Run only this scraper ID (for debugging)")
    parser.add_argument("--max-articles", type=int, default=50, help="Max articles sent to scorer (default 50)")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--seen-file", default="data/seen_articles.json", help="Path to seen articles JSON")
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    settings = config.get("settings", {})
    threshold = settings.get("relevance_threshold", 6)
    max_articles = settings.get("max_articles_per_digest", 25)
    batch_size = settings.get("batch_size", 6)

    # Load dedup store
    seen = load_seen(args.seen_file)

    # Weekly trends mode — separate pipeline
    if args.weekly_trends:
        from .trends import get_weekly_articles, synthesize_trends
        from .notifier import format_weekly_trends

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not set. Required for weekly trends.")
            sys.exit(1)

        weekly_articles = get_weekly_articles(seen)
        logger.info("Found %d articles from the past 7 days for trend synthesis.", len(weekly_articles))

        if not weekly_articles:
            logger.info("No articles in the past 7 days. Skipping trends.")
            return

        trends = synthesize_trends(weekly_articles, api_key)

        if args.dry_run:
            print(f"\n{'='*60}")
            print("Weekly Trends")
            print(f"{'='*60}")
            print(f"\nExecutive Summary:\n{trends.get('executive_summary', '')}\n")
            for theme in trends.get("themes", []):
                print(f"Theme: {theme.get('theme', '')} ({theme.get('article_count', 0)} articles)")
                print(f"  Sources: {', '.join(theme.get('sources', []))}")
                print(f"  {theme.get('summary', '')}\n")
            print("Top 3 Action Items:")
            for item in trends.get("top_3", []):
                print(f"  - {item.get('title', '')}")
                print(f"    {item.get('why', '')}")
            if trends.get("emerging"):
                print("\nEmerging Patterns:")
                for e in trends["emerging"]:
                    print(f"  - {e}")
            print(f"\n{'='*60}\n")
        else:
            webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
            if not webhook_url:
                logger.error("SLACK_WEBHOOK_URL not set.")
                sys.exit(1)
            payload = format_weekly_trends(trends, len(weekly_articles))
            if not post_to_slack(webhook_url, payload):
                logger.error("Slack delivery of weekly trends failed.")
        return

    # Fetch feeds
    if args.single_feed:
        feeds_config = [{"url": args.single_feed, "category": "Debug", "priority": "high"}]
    else:
        feeds_config = config.get("feeds", [])

    max_per_feed = settings.get("max_per_feed", 20)
    new_articles = fetch_all_feeds(feeds_config, seen, max_per_feed=max_per_feed)
    feeds_scanned = len(feeds_config)

    # Scrape web sources
    if (not args.no_scrape or args.single_scraper) and not args.single_feed:
        from .scraper import scrape_all_sources
        if args.single_scraper:
            scrape_configs = [{"id": args.single_scraper, "category": "Debug", "priority": "high"}]
        else:
            scrape_configs = config.get("scrape_sources", [])
        if scrape_configs:
            scraped = scrape_all_sources(scrape_configs, seen, max_per_source=max_per_feed)
            new_articles.extend(scraped)
            feeds_scanned += len(scrape_configs)

    # Sort by priority and truncate to --max-articles before scoring
    priority_order = {"high": 0, "medium": 1, "low": 2}
    new_articles.sort(key=lambda a: priority_order.get(a.get("priority", "medium"), 1))
    if len(new_articles) > args.max_articles:
        total = len(new_articles)
        new_articles = new_articles[:args.max_articles]
        logger.warning(
            "Truncated %d articles to %d (use --max-articles to adjust).",
            total, args.max_articles,
        )

    if not new_articles:
        logger.info("No new articles found. Nothing to do.")
        save_seen(args.seen_file, seen)
        return

    # Fetch full article text if requested
    if args.full_text:
        from .content_fetcher import fetch_full_texts
        logger.info("Fetching full text for %d articles...", len(new_articles))
        new_articles = fetch_full_texts(new_articles)

    # Score articles
    if args.no_score:
        logger.info("Skipping scoring (--no-score). Assigning default score of 5.")
        for article in new_articles:
            article["score"] = 5
            article["summary"] = ""
            article["tags"] = []
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not set. Use --no-score to skip scoring.")
            sys.exit(1)
        try:
            new_articles = score_articles(new_articles, api_key, batch_size=batch_size)
        except Exception as e:
            logger.error("Scoring failed entirely: %s. Falling back to unscored.", e)
            for article in new_articles:
                article.setdefault("score", 5)
                article.setdefault("summary", "")
                article.setdefault("tags", [])

    # Apply tag-based score adjustments
    tag_filters = settings.get("tag_filters", {})
    boost_tags = set(tag_filters.get("boost", []))
    suppress_tags = set(tag_filters.get("suppress", []))
    for article in new_articles:
        tags = set(article.get("tags", []))
        if tags & boost_tags:
            article["score"] = article.get("score", 0) + 1
        if tags & suppress_tags:
            article["score"] = article.get("score", 0) - 2

    # Filter and sort
    above_threshold = [a for a in new_articles if a.get("score", 0) >= threshold]
    above_threshold.sort(key=lambda a: a.get("score", 0), reverse=True)
    above_threshold = above_threshold[:max_articles]

    stats = {
        "feeds_scanned": feeds_scanned,
        "new_articles": len(new_articles),
        "above_threshold": len(above_threshold),
    }

    logger.info(
        "Stats: %d feeds scanned, %d new articles, %d above threshold (%d).",
        feeds_scanned, len(new_articles), len(above_threshold), threshold,
    )

    # Deliver digest
    if above_threshold:
        if args.dry_run:
            print_digest(above_threshold, stats)
        else:
            webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
            if not webhook_url:
                logger.error("SLACK_WEBHOOK_URL not set. Use --dry-run to print to stdout.")
                sys.exit(1)
            payload = format_digest(above_threshold, stats)
            if not post_to_slack(webhook_url, payload):
                logger.error("Slack delivery failed. Printing to stdout as fallback.")
                print_digest(above_threshold, stats)
    else:
        logger.info("No articles above threshold. Skipping digest delivery.")

    # Mark all fetched articles as seen (including below-threshold)
    for article in new_articles:
        mark_seen(article["url"], article, seen)

    save_seen(args.seen_file, seen)
    logger.info("Done. Seen articles store updated.")


if __name__ == "__main__":
    main()
