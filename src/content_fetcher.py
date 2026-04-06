import logging
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 3000
RATE_LIMIT_SECONDS = 1
REQUEST_TIMEOUT = 15
USER_AGENT = "PlatformEngResearchAgent/1.0"


def extract_main_content(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()

    # Try semantic tags in priority order
    for selector in ["article", "main", "[role='main']"]:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 200:
            return el.get_text(separator=" ", strip=True)

    # Fallback: find the largest cluster of <p> tags
    containers = soup.find_all(["div", "section"])
    best = None
    best_len = 0
    for container in containers:
        paragraphs = container.find_all("p")
        text = " ".join(p.get_text(strip=True) for p in paragraphs)
        if len(text) > best_len:
            best = text
            best_len = len(text)

    if best and best_len > 200:
        return best

    return None


def fetch_full_text(url: str, timeout: int = REQUEST_TIMEOUT) -> str | None:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()

        content = extract_main_content(resp.text)
        if content:
            return content[:MAX_CONTENT_LENGTH]
        return None

    except requests.RequestException as e:
        logger.debug("Failed to fetch full text from %s: %s", url, e)
        return None


def fetch_full_texts(articles: list[dict], rate_limit: float = RATE_LIMIT_SECONDS) -> list[dict]:
    for i, article in enumerate(articles):
        url = article.get("url", "")
        if not url:
            continue

        full_text = fetch_full_text(url)
        if full_text:
            article["full_text"] = full_text
            logger.debug("Extracted %d chars from %s", len(full_text), url)
        else:
            logger.debug("No full text extracted from %s", url)

        if i < len(articles) - 1:
            time.sleep(rate_limit)

    fetched = sum(1 for a in articles if "full_text" in a)
    logger.info("Full text extracted for %d/%d articles.", fetched, len(articles))
    return articles
