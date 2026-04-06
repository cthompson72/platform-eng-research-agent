import json
import logging
from collections import defaultdict

import anthropic

logger = logging.getLogger(__name__)

COMPETITIVE_SYSTEM_PROMPT = """You are a competitive intelligence analyst for Platform Engineering at L'Oréal.

Context:
- L'Oréal is early-stage in platform engineering maturity
- Toolchain: ServiceNow, GitHub, Kubernetes, Terraform, Spring Boot, SonarQube, Snyk, k6, Grafana
- Goal: understand what other large enterprises are doing with platform engineering to inform strategy"""

COMPETITIVE_USER_PROMPT = """Analyze these articles grouped by organization. Each group contains articles that mention a specific company's platform engineering activities.

{org_text}

Return ONLY valid JSON (no markdown fencing):

{{
  "landscape": [
    {{
      "org": "Company Name",
      "summary": "2-3 sentences on their platform engineering approach and maturity.",
      "relevance_to_loreal": "One sentence on what L'Oréal can learn from this org.",
      "key_technologies": ["tech1", "tech2"]
    }}
  ],
  "patterns": ["Cross-org pattern 1", "Cross-org pattern 2"],
  "recommendations": ["Actionable recommendation for L'Oréal based on this landscape"]
}}

Rules:
- landscape: one entry per org, sorted by relevance to L'Oréal.
- patterns: common themes across orgs (max 5).
- recommendations: max 3, specific and actionable."""


def get_competitive_articles(seen: dict) -> dict[str, list[dict]]:
    by_org = defaultdict(list)
    for url, meta in seen.items():
        orgs = meta.get("orgs_mentioned", [])
        for org in orgs:
            by_org[org].append({"url": url, **meta})

    # Sort orgs by article count descending
    return dict(sorted(by_org.items(), key=lambda x: len(x[1]), reverse=True))


def _format_orgs_for_prompt(by_org: dict[str, list[dict]]) -> str:
    sections = []
    for org, articles in by_org.items():
        lines = [f"=== {org} ({len(articles)} articles) ==="]
        for a in articles[:5]:  # Cap per org to control token usage
            tags = ", ".join(a.get("tags", []))
            lines.append(
                f"- {a.get('title', '')}\n"
                f"  {a.get('summary', '')}\n"
                f"  Tags: {tags}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def analyze_competitive_landscape(
    by_org: dict[str, list[dict]], api_key: str
) -> dict:
    if not by_org:
        return {
            "landscape": [],
            "patterns": [],
            "recommendations": ["Not enough competitive intelligence data yet. The scorer will begin extracting organization mentions from new articles."],
        }

    client = anthropic.Anthropic(api_key=api_key)
    org_text = _format_orgs_for_prompt(by_org)
    prompt = COMPETITIVE_USER_PROMPT.format(org_text=org_text)

    logger.info("Analyzing competitive landscape for %d organizations...", len(by_org))

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=COMPETITIVE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            result = json.loads(text)
            logger.info("Competitive analysis complete: %d orgs profiled.", len(result.get("landscape", [])))
            return result
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 0:
                logger.warning("Competitive analysis JSON parse error, retrying: %s", e)
            else:
                logger.error("Competitive analysis failed after retry: %s", e)
                return {"landscape": [], "patterns": [], "recommendations": []}

    return {"landscape": [], "patterns": [], "recommendations": []}
