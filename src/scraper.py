import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .dedup import is_new

logger = logging.getLogger(__name__)

USER_AGENT = "PlatformEngResearchAgent/1.0"
REQUEST_TIMEOUT = 15


def _get_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


def _parse_relative_date(text: str) -> str:
    """Best-effort date parsing from visible text. Returns ISO string or now()."""
    text = text.strip()
    # Try common date formats
    for fmt in ["%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%d %b %Y", "%b %d %Y"]:
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()


# --- Per-source scrapers ---


def scrape_tldrsec(config: dict) -> list[dict]:
    """Scrape tldrsec.com Substack newsletter archive."""
    soup = _get_soup("https://tldrsec.com/t/Newsletter")
    if not soup:
        return []

    articles = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not href.startswith("/p/tldr-sec-") or len(text) < 10:
            continue

        # Extract date and title from text like "Apr 02, 2026[tl;dr sec] #322 - ..."
        date_match = re.match(r"([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4})", text)
        date_str = _parse_relative_date(date_match.group(1)) if date_match else datetime.now(timezone.utc).isoformat()

        title_match = re.search(r"(\[tl;dr sec\].+)", text)
        title = title_match.group(1) if title_match else text

        articles.append({
            "title": title[:200],
            "url": f"https://tldrsec.com{href}",
            "published": date_str,
            "description": f"tl;dr sec newsletter issue: {title[:200]}",
        })

    return articles


def scrape_k6(config: dict) -> list[dict]:
    """Scrape Grafana k6 tag page (k6.io/blog redirects here)."""
    soup = _get_soup("https://grafana.com/tags/k6/")
    if not soup:
        return []

    articles = []
    for art in soup.find_all("article"):
        a = art.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if not href.startswith("/blog/"):
            continue

        # Title is the first meaningful text in the article
        text_parts = [t for t in art.stripped_strings if len(t) > 10]
        title = text_parts[0] if text_parts else "Untitled"

        articles.append({
            "title": title[:200],
            "url": f"https://grafana.com{href}",
            "published": datetime.now(timezone.utc).isoformat(),
            "description": " ".join(text_parts[1:3])[:300] if len(text_parts) > 1 else "",
        })

    return articles


def scrape_ministryoftesting(config: dict) -> list[dict]:
    """Scrape Ministry of Testing articles page."""
    soup = _get_soup("https://www.ministryoftesting.com/articles")
    if not soup:
        return []

    articles = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        # Only internal article links, skip list/tag pages
        if "/articles/" not in href or len(text) < 20:
            continue
        if "list" in href or "tag" in href:
            continue
        # Normalize
        if href.startswith("/"):
            href = f"https://www.ministryoftesting.com{href}"
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        articles.append({
            "title": text[:200],
            "url": href,
            "published": datetime.now(timezone.utc).isoformat(),
            "description": "",
        })

    return articles


def scrape_gatling(config: dict) -> list[dict]:
    """Scrape Gatling blog page."""
    soup = _get_soup("https://gatling.io/blog")
    if not soup:
        return []

    articles = []
    seen_hrefs = set()
    for h3 in soup.find_all("h3"):
        # Find link either in h3 or parent
        a = h3.find("a", href=True)
        if not a:
            parent_a = h3.find_parent("a", href=True)
            if parent_a:
                a = parent_a
        if not a:
            continue

        href = a["href"]
        title = h3.get_text(strip=True)

        if "/blog/" not in href or len(title) < 10:
            continue
        if not href.startswith("http"):
            href = f"https://gatling.io{href}"
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        articles.append({
            "title": title[:200],
            "url": href,
            "published": datetime.now(timezone.utc).isoformat(),
            "description": "",
        })

    return articles


def scrape_cncf_casestudies(config: dict) -> list[dict]:
    """Scrape CNCF case studies page."""
    soup = _get_soup("https://www.cncf.io/case-studies/")
    if not soup:
        return []

    articles = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        if "/case-studies/" not in href or len(text) < 10:
            continue
        if href.rstrip("/") in ("https://www.cncf.io/case-studies", "/case-studies"):
            continue
        if not href.startswith("http"):
            href = f"https://www.cncf.io{href}"
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # Fetch title, description, and date from case study page
        description = ""
        published = datetime.now(timezone.utc).isoformat()
        title = text
        case_soup = _get_soup(href)
        if case_soup:
            og_title = case_soup.find("meta", attrs={"property": "og:title"})
            if og_title and og_title.get("content"):
                title = og_title["content"]
            desc_meta = case_soup.find("meta", attrs={"name": "description"})
            if desc_meta:
                description = desc_meta.get("content", "")[:500]
            date_meta = case_soup.find("meta", attrs={"property": "article:published_time"})
            if date_meta:
                published = date_meta.get("content", published)

        articles.append({
            "title": f"CNCF Case Study: {title[:180]}",
            "url": href,
            "published": published,
            "description": description,
        })

    return articles


# --- Dispatcher ---

SCRAPERS = {
    "tldrsec": scrape_tldrsec,
    "k6": scrape_k6,
    "ministryoftesting": scrape_ministryoftesting,
    "gatling": scrape_gatling,
    "cncf_casestudies": scrape_cncf_casestudies,
}


def scrape_source(source_id: str, config: dict) -> list[dict]:
    scraper_fn = SCRAPERS.get(source_id)
    if not scraper_fn:
        logger.warning("No scraper found for source '%s'. Skipping.", source_id)
        return []
    try:
        return scraper_fn(config)
    except Exception as e:
        logger.warning("Scraper '%s' failed: %s. Skipping.", source_id, e)
        return []


def scrape_all_sources(
    scrape_configs: list[dict], seen: dict, max_per_source: int = 20
) -> list[dict]:
    new_articles = []
    for cfg in scrape_configs:
        source_id = cfg["id"]
        category = cfg.get("category", "Uncategorized")
        priority = cfg.get("priority", "medium")
        limit = cfg.get("max_per_source", max_per_source)

        articles = scrape_source(source_id, cfg)
        logger.info("Scraped %d articles from %s", len(articles), source_id)

        # Sort by published date and cap
        articles.sort(key=lambda a: a.get("published", ""), reverse=True)
        if len(articles) > limit:
            articles = articles[:limit]

        for article in articles:
            if is_new(article["url"], seen):
                article["category"] = category
                article["priority"] = priority
                new_articles.append(article)

    logger.info("Total new scraped articles: %d", len(new_articles))
    return new_articles
