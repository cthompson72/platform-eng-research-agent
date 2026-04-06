import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

MAX_ARTICLES = 20
SLACK_PAYLOAD_LIMIT = 39_000  # Leave margin under 40KB limit


def _slack_link(url: str, text: str) -> str:
    """Format a URL as a Slack mrkdwn link, ensuring the scheme is present."""
    if url and not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return f"<{url}|{text}>"


def format_digest(articles: list[dict], stats: dict) -> dict:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Platform Engineering Digest — {today}"},
        }
    ]

    # Group by category, sort by score descending within each
    by_category = defaultdict(list)
    for article in articles[:MAX_ARTICLES]:
        by_category[article.get("category", "Uncategorized")].append(article)

    for category in sorted(by_category.keys()):
        cat_articles = sorted(by_category[category], key=lambda a: a.get("score", 0), reverse=True)

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{category}* ({len(cat_articles)} articles)",
            },
        })

        for article in cat_articles:
            score = article.get("score", "?")
            summary = article.get("summary", "")
            tags = ", ".join(article.get("tags", []))
            tag_line = f"\n_{tags}_" if tags else ""

            link = _slack_link(article["url"], f"*{article['title']}*")
            text = (
                f"{link} (score: {score}/10)\n"
                f"{summary}{tag_line}"
            )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            })

    # Tag summary
    tag_counts = defaultdict(int)
    for article in articles[:MAX_ARTICLES]:
        for tag in article.get("tags", []):
            tag_counts[tag] += 1
    if tag_counts:
        top_tags = sorted(tag_counts.items(), key=lambda t: t[1], reverse=True)
        tag_text = ", ".join(f"{count}\u00d7 {tag}" for tag, count in top_tags)
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Tags:* {tag_text}"}],
        })

    # Footer
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f"{stats.get('feeds_scanned', 0)} feeds scanned | "
                    f"{stats.get('new_articles', 0)} new articles | "
                    f"{stats.get('above_threshold', 0)} above threshold"
                ),
            }
        ],
    })

    payload = {"blocks": blocks}

    # Truncate if payload too large
    payload_str = json.dumps(payload)
    while len(payload_str) > SLACK_PAYLOAD_LIMIT and len(blocks) > 4:
        blocks.pop(-2)  # Remove last article section, keep footer
        payload = {"blocks": blocks}
        payload_str = json.dumps(payload)

    return payload


def format_weekly_trends(trends: dict, article_count: int) -> dict:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Weekly Trends — {today}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_Analysis of {article_count} articles from the past 7 days_",
            },
        },
    ]

    # Executive summary
    exec_summary = trends.get("executive_summary", "")
    if exec_summary:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Executive Summary*\n{exec_summary}"},
        })

    # Themes
    themes = trends.get("themes", [])
    if themes:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Cross-Cutting Themes*"},
        })
        for theme in themes:
            sources = ", ".join(theme.get("sources", []))
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{theme.get('theme', '')}* "
                        f"({theme.get('article_count', 0)} articles from {sources})\n"
                        f"{theme.get('summary', '')}"
                    ),
                },
            })

    # Top 3
    top_3 = trends.get("top_3", [])
    if top_3:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Top 3 Action Items*"},
        })
        for item in top_3:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{_slack_link(item.get('url', ''), '*' + item.get('title', '') + '*')}\n{item.get('why', '')}",
                },
            })

    # Emerging patterns
    emerging = trends.get("emerging", [])
    if emerging:
        blocks.append({"type": "divider"})
        bullets = "\n".join(f"• {e}" for e in emerging)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Emerging Patterns*\n{bullets}"},
        })

    return {"blocks": blocks}


def format_query_results(query_result: dict) -> dict:
    query = query_result.get("query", "")
    results = query_result.get("results", [])
    total = query_result.get("total_searched", 0)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Search: {query[:140]}"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{len(results)} results from {total} articles searched_"}],
        },
    ]

    for i, r in enumerate(results, 1):
        tags = ", ".join(r.get("tags", []))
        tag_line = f"\n_{tags}_" if tags else ""
        date = r.get("first_seen", "")[:10]
        link = _slack_link(r["url"], f"*{r.get('title', '')}*")

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{i}. {link} (score: {r.get('score', '?')}/10, {date})\n"
                    f"{r.get('relevance', '')}{tag_line}"
                ),
            },
        })

    if not results:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No relevant articles found for this query._"},
        })

    return {"blocks": blocks}


def format_competitive_intel(intel: dict, org_count: int) -> dict:
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Competitive Intelligence — Platform Engineering"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{org_count} organizations tracked_"}],
        },
    ]

    # Org profiles
    landscape = intel.get("landscape", [])
    if landscape:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Organization Profiles*"},
        })
        for org_info in landscape:
            tech = ", ".join(org_info.get("key_technologies", []))
            tech_line = f"\n_Tech: {tech}_" if tech else ""
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{org_info.get('org', '')}*\n"
                        f"{org_info.get('summary', '')}\n"
                        f"_For L'Oréal:_ {org_info.get('relevance_to_loreal', '')}{tech_line}"
                    ),
                },
            })

    # Cross-org patterns
    patterns = intel.get("patterns", [])
    if patterns:
        blocks.append({"type": "divider"})
        bullets = "\n".join(f"• {p}" for p in patterns)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Cross-Org Patterns*\n{bullets}"},
        })

    # Recommendations
    recs = intel.get("recommendations", [])
    if recs:
        blocks.append({"type": "divider"})
        bullets = "\n".join(f"• {r}" for r in recs)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Recommendations for L'Oréal*\n{bullets}"},
        })

    return {"blocks": blocks}


def post_to_slack(webhook_url: str, payload: dict) -> bool:
    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 200 and resp.text == "ok":
            logger.info("Digest posted to Slack successfully.")
            return True
        else:
            logger.error("Slack returned status %d: %s", resp.status_code, resp.text)
            return False
    except requests.RequestException as e:
        logger.error("Failed to post to Slack: %s", e)
        return False
