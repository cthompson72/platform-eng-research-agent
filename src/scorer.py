import json
import logging
import time

import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a relevance scoring assistant for a Platform Engineering research digest at L'Oréal.

Score each article's relevance on a 1-10 scale and provide a 2-sentence summary.

Context about the reader:
- Role: Sr. Director, Platform Engineering & Developer Experience at L'Oréal
- DevOps maturity: Early-stage; foundational improvements are HIGHLY relevant
- Active toolchain: ServiceNow, GitHub, Kubernetes, Terraform, Spring Boot, SonarQube, Snyk, k6, Grafana
- Strategic priorities: CI/CD standardization, observability, developer experience, AI-augmented development, platform engineering org design

Scoring rubric:
- Security advisories for any tool in the stack: ALWAYS score 9-10
- Vendor updates for stack tools: score 7-9 depending on impact
- Platform engineering patterns and IDP design: score 7-9
- CI/CD, observability, developer experience best practices: score 6-8
- General thought leadership: score 4-6 unless directly about platform eng org design
- Content about unrelated tools/stacks: score 1-3"""

USER_PROMPT_TEMPLATE = """Score the following articles for relevance. Return ONLY valid JSON, no markdown fencing.

Articles:
{articles_text}

Response format (JSON array):
[
  {{
    "index": 1,
    "score": 8,
    "summary": "Two sentence summary of why this matters.",
    "tags": ["ci-cd", "github"]
  }}
]

Valid tags: security-advisory, vendor-update, ci-cd, observability, developer-experience, platform-engineering, ai-augmented-dev, testing, performance, org-design, kubernetes, servicenow, devsecops"""


def _format_articles_for_prompt(articles: list[dict]) -> str:
    lines = []
    for i, article in enumerate(articles, 1):
        lines.append(
            f"{i}. [{article.get('category', 'Unknown')}] "
            f"{article['title']}\n"
            f"   {article.get('description', 'No description available.')[:500]}"
        )
    return "\n\n".join(lines)


def _call_api(client: anthropic.Anthropic, articles: list[dict]) -> list[dict]:
    articles_text = _format_articles_for_prompt(articles)
    prompt = USER_PROMPT_TEMPLATE.format(articles_text=articles_text)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    return json.loads(text)


def _score_batch(client: anthropic.Anthropic, articles: list[dict]) -> list[dict]:
    for attempt in range(2):
        try:
            results = _call_api(client, articles)
            if not isinstance(results, list):
                raise ValueError("Expected JSON array")

            for result in results:
                idx = result.get("index", 0) - 1
                if 0 <= idx < len(articles):
                    articles[idx]["score"] = result.get("score", 5)
                    articles[idx]["summary"] = result.get("summary", "")
                    articles[idx]["tags"] = result.get("tags", [])
            return articles

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if attempt == 0:
                logger.warning("JSON parse error on scoring batch, retrying: %s", e)
                time.sleep(2)
            else:
                logger.error("Scoring batch failed after retry: %s. Assigning default scores.", e)
                for article in articles:
                    article.setdefault("score", 5)
                    article.setdefault("summary", "")
                    article.setdefault("tags", [])
                return articles

        except anthropic.RateLimitError:
            if attempt == 0:
                logger.warning("Rate limited, waiting 8s before retry.")
                time.sleep(8)
            else:
                logger.error("Rate limited after retry. Assigning default scores.")
                for article in articles:
                    article.setdefault("score", 5)
                    article.setdefault("summary", "")
                    article.setdefault("tags", [])
                return articles

    return articles


def score_articles(articles: list[dict], api_key: str, batch_size: int = 6) -> list[dict]:
    if not articles:
        return articles

    client = anthropic.Anthropic(api_key=api_key)
    scored = []

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        logger.info("Scoring batch %d-%d of %d articles", i + 1, i + len(batch), len(articles))
        scored_batch = _score_batch(client, batch)
        scored.extend(scored_batch)

    return scored
