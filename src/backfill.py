import json
import logging
import time

import anthropic

logger = logging.getLogger(__name__)

BACKFILL_SYSTEM_PROMPT = """Extract organization names from article titles and summaries. Only list specific companies, government agencies, or named organizations whose platform engineering, DevOps, or infrastructure approach is described. Do not list tool/product vendors unless the article is specifically about that vendor's own internal engineering practices."""

BACKFILL_USER_PROMPT = """For each article, list the organizations mentioned. Return ONLY valid JSON (no markdown fencing).

Articles:
{articles_text}

Response format:
[
  {{"index": 1, "orgs_mentioned": ["Spotify", "Netflix"]}},
  {{"index": 2, "orgs_mentioned": []}}
]

If no specific organization's engineering practices are described, return an empty list for that article."""


def _format_batch(articles: list[tuple[str, dict]]) -> str:
    lines = []
    for i, (url, meta) in enumerate(articles, 1):
        lines.append(
            f"{i}. {meta.get('title', 'Untitled')}\n"
            f"   {meta.get('summary', '')}"
        )
    return "\n\n".join(lines)


def _extract_orgs_batch(
    client: anthropic.Anthropic, batch: list[tuple[str, dict]]
) -> list[list[str]]:
    articles_text = _format_batch(batch)
    prompt = BACKFILL_USER_PROMPT.format(articles_text=articles_text)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=BACKFILL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            results = json.loads(text)
            orgs_by_index = {}
            for r in results:
                orgs_by_index[r.get("index", 0) - 1] = r.get("orgs_mentioned", [])
            return [orgs_by_index.get(i, []) for i in range(len(batch))]
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 0:
                logger.warning("Backfill JSON parse error, retrying: %s", e)
                time.sleep(2)
            else:
                logger.error("Backfill batch failed after retry: %s", e)
                return [[] for _ in batch]
        except anthropic.RateLimitError:
            if attempt == 0:
                logger.warning("Rate limited on backfill, waiting 8s.")
                time.sleep(8)
            else:
                logger.error("Rate limited on backfill after retry.")
                return [[] for _ in batch]

    return [[] for _ in batch]


def backfill_orgs(
    seen: dict, api_key: str, batch_size: int = 6, dry_run: bool = False
) -> dict:
    # Find articles missing orgs_mentioned
    to_backfill = [
        (url, meta) for url, meta in seen.items()
        if "orgs_mentioned" not in meta and meta.get("summary")
    ]

    if not to_backfill:
        logger.info("No articles need org backfill.")
        return seen

    logger.info("Backfilling orgs for %d articles.", len(to_backfill))
    client = anthropic.Anthropic(api_key=api_key)
    total_orgs = 0

    for i in range(0, len(to_backfill), batch_size):
        batch = to_backfill[i:i + batch_size]
        logger.info(
            "Backfill batch %d-%d of %d",
            i + 1, i + len(batch), len(to_backfill),
        )
        orgs_list = _extract_orgs_batch(client, batch)

        for (url, _meta), orgs in zip(batch, orgs_list):
            if dry_run:
                if orgs:
                    logger.info("  [dry-run] %s -> %s", seen[url].get("title", "")[:50], orgs)
            else:
                seen[url]["orgs_mentioned"] = orgs
            if orgs:
                total_orgs += 1

    logger.info(
        "Backfill done. %d/%d articles had orgs extracted.",
        total_orgs, len(to_backfill),
    )
    return seen
