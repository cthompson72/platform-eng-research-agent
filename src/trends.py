import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import anthropic

logger = logging.getLogger(__name__)

TRENDS_SYSTEM_PROMPT = """You are analyzing a week's worth of platform engineering articles for a Sr. Director of Platform Engineering at L'Oréal.

Context:
- DevOps maturity: Early-stage; foundational improvements are highly relevant
- Toolchain: ServiceNow, GitHub, Kubernetes, Terraform, Spring Boot, SonarQube, Snyk, k6, Grafana
- Priorities: CI/CD standardization, observability, developer experience, AI-augmented development, platform engineering org design"""

TRENDS_USER_PROMPT = """Here are {count} articles from this week's platform engineering digest, with their scores, tags, and summaries:

{articles_text}

Analyze these articles and return ONLY valid JSON (no markdown fencing):

{{
  "themes": [
    {{
      "theme": "Short theme name",
      "article_count": 3,
      "sources": ["source1.com", "source2.com"],
      "summary": "One sentence on why this theme matters for L'Oréal's platform engineering."
    }}
  ],
  "top_3": [
    {{
      "title": "Article title",
      "url": "https://...",
      "why": "One sentence on why this requires attention."
    }}
  ],
  "emerging": ["One sentence per emerging pattern not seen in previous weeks"],
  "executive_summary": "3-4 sentences a Sr. Director could share with their VP summarizing this week's key developments."
}}

Rules:
- themes: topics that appeared in 2+ different sources. Max 5 themes.
- top_3: the 3 articles most likely to require action or awareness.
- emerging: new patterns, max 3. If nothing is clearly new, return empty list.
- executive_summary: concise, action-oriented, no jargon."""


def get_weekly_articles(seen: dict, days: int = 7) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    articles = []
    for url, meta in seen.items():
        if meta.get("first_seen", "") >= cutoff:
            articles.append({"url": url, **meta})
    articles.sort(key=lambda a: a.get("score", 0), reverse=True)
    return articles


def _format_articles_for_trends(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        tags = ", ".join(a.get("tags", [])) or "none"
        summary = a.get("summary", "No summary")
        source = a.get("url", "").split("/")[2] if "/" in a.get("url", "") else "unknown"
        lines.append(
            f"{i}. [{a.get('category', 'Unknown')}] {a.get('title', 'Untitled')} "
            f"(score: {a.get('score', '?')}/10, source: {source})\n"
            f"   Tags: {tags}\n"
            f"   {summary}"
        )
    return "\n\n".join(lines)


def synthesize_trends(articles: list[dict], api_key: str) -> dict:
    if not articles:
        return {
            "themes": [],
            "top_3": [],
            "emerging": [],
            "executive_summary": "No articles collected this week.",
        }

    client = anthropic.Anthropic(api_key=api_key)
    articles_text = _format_articles_for_trends(articles)
    prompt = TRENDS_USER_PROMPT.format(count=len(articles), articles_text=articles_text)

    logger.info("Sending %d articles to Claude for trend synthesis...", len(articles))

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=TRENDS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            result = json.loads(text)
            logger.info(
                "Trend synthesis complete: %d themes, %d top articles.",
                len(result.get("themes", [])),
                len(result.get("top_3", [])),
            )
            return result
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 0:
                logger.warning("JSON parse error on trend synthesis, retrying: %s", e)
            else:
                logger.error("Trend synthesis JSON parsing failed after retry: %s", e)
                return {
                    "themes": [],
                    "top_3": [],
                    "emerging": [],
                    "executive_summary": "Trend synthesis failed due to a parsing error.",
                }
        except anthropic.RateLimitError:
            if attempt == 0:
                logger.warning("Rate limited on trend synthesis, waiting 8s.")
                import time
                time.sleep(8)
            else:
                logger.error("Rate limited on trend synthesis after retry.")
                return {
                    "themes": [],
                    "top_3": [],
                    "emerging": [],
                    "executive_summary": "Trend synthesis failed due to rate limiting.",
                }

    return {"themes": [], "top_3": [], "emerging": [], "executive_summary": ""}
