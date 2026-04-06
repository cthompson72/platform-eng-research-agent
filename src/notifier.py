import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

MAX_ARTICLES = 20
SLACK_PAYLOAD_LIMIT = 39_000  # Leave margin under 40KB limit


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

            text = (
                f"<{article['url']}|*{article['title']}*> (score: {score}/10)\n"
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
                    "text": f"<{item.get('url', '')}|*{item.get('title', '')}*>\n{item.get('why', '')}",
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
