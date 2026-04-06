import json
import logging
import re
import sqlite3

import anthropic

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "about", "above", "after",
    "and", "any", "at", "before", "between", "but", "by", "for", "from",
    "how", "i", "in", "into", "it", "its", "my", "not", "of", "on", "or",
    "our", "out", "over", "so", "some", "than", "that", "then", "there",
    "these", "they", "this", "to", "too", "under", "up", "very", "was",
    "we", "what", "when", "where", "which", "who", "why", "with", "you",
    "seen", "recently", "lately", "have", "ive", "ve",
}

RERANK_SYSTEM_PROMPT = """You are a search assistant for a Platform Engineering research digest at L'Oréal. Given a user query and a list of candidate articles, select and rank the most relevant results.

Context about the reader:
- Role: Sr. Director, Platform Engineering & Developer Experience at L'Oréal
- Toolchain: ServiceNow, GitHub, Kubernetes, Terraform, Spring Boot, SonarQube, Snyk, k6, Grafana
- Priorities: CI/CD standardization, observability, developer experience, AI-augmented development"""

RERANK_USER_PROMPT = """Query: "{query}"

Candidate articles:
{candidates_text}

Select the top {top_k} most relevant articles for this query. Return ONLY valid JSON (no markdown fencing):

[
  {{
    "index": 1,
    "relevance": "One sentence explaining why this article matches the query."
  }}
]

Rules:
- Only include articles genuinely relevant to the query. If fewer than {top_k} are relevant, return fewer.
- Order by relevance, most relevant first.
- Consider semantic meaning, not just keyword matches."""


def build_index(seen: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE articles USING fts5("
        "url, title, summary, tags, category, first_seen, score UNINDEXED"
        ")"
    )
    for url, meta in seen.items():
        conn.execute(
            "INSERT INTO articles(url, title, summary, tags, category, first_seen, score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                url,
                meta.get("title", ""),
                meta.get("summary", ""),
                " ".join(meta.get("tags", [])),
                meta.get("category", ""),
                meta.get("first_seen", ""),
                meta.get("score", 0),
            ),
        )
    conn.commit()
    count = conn.execute("SELECT count(*) FROM articles").fetchone()[0]
    logger.info("Built FTS5 index with %d articles.", count)
    return conn


def _to_fts_query(query: str) -> str:
    words = re.findall(r"\w+", query.lower())
    terms = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    if not terms:
        terms = words[:3]
    return " OR ".join(f'"{t}"' for t in terms)


def search_fts(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    fts_query = _to_fts_query(query)
    logger.info("FTS5 query: %s", fts_query)

    try:
        rows = conn.execute(
            "SELECT url, title, summary, tags, category, first_seen, score, rank "
            "FROM articles WHERE articles MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("FTS5 query failed: %s. Falling back to broad search.", e)
        return []

    results = []
    for row in rows:
        results.append({
            "url": row[0],
            "title": row[1],
            "summary": row[2],
            "tags": row[3].split() if row[3] else [],
            "category": row[4],
            "first_seen": row[5],
            "score": row[6],
            "bm25_rank": row[7],
        })

    logger.info("FTS5 returned %d candidates.", len(results))
    return results


def rerank_with_claude(
    candidates: list[dict], query: str, api_key: str, top_k: int = 10
) -> list[dict]:
    if not candidates:
        return []

    lines = []
    for i, c in enumerate(candidates, 1):
        tags = ", ".join(c.get("tags", [])) or "none"
        lines.append(
            f"{i}. [{c.get('category', '')}] {c.get('title', '')}\n"
            f"   Tags: {tags} | Score: {c.get('score', '?')}/10 | {c.get('first_seen', '')[:10]}\n"
            f"   {c.get('summary', 'No summary')}"
        )
    candidates_text = "\n\n".join(lines)
    prompt = RERANK_USER_PROMPT.format(
        query=query, candidates_text=candidates_text, top_k=top_k
    )

    client = anthropic.Anthropic(api_key=api_key)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=RERANK_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            rankings = json.loads(text)

            results = []
            for r in rankings:
                idx = r.get("index", 0) - 1
                if 0 <= idx < len(candidates):
                    candidate = candidates[idx].copy()
                    candidate["relevance"] = r.get("relevance", "")
                    results.append(candidate)
            logger.info("Claude re-ranked to %d results.", len(results))
            return results

        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 0:
                logger.warning("Re-ranking JSON parse error, retrying: %s", e)
            else:
                logger.error("Re-ranking failed after retry. Returning FTS5 order.")
                return candidates[:top_k]

    return candidates[:top_k]
