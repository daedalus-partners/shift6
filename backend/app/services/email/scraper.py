from __future__ import annotations

import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup  # lightweight parser; install via backend requirements if missing
from .polite import is_allowed, rate_limit, cached_get


async def fetch_article_http(url: str) -> tuple[str | None, str | None, str | None]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }
    # robots and rate limit
    if not await is_allowed(url):
        raise httpx.HTTPStatusError("Disallowed by robots.txt", request=None, response=None)  # type: ignore[arg-type]
    await rate_limit(url)
    status, html = await cached_get(url, headers=headers)
    if status != 200:
        raise httpx.HTTPStatusError(f"status={status}", request=None, response=None)  # type: ignore[arg-type]
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string or "").strip() if soup.title else None
        desc = None
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            desc = og["content"].strip()
        # Gather text from common content tags to better capture quoted text
        content_tags = ["p", "blockquote", "q", "h1", "h2", "h3", "h4", "li"]
        parts = []
        for node in soup.find_all(content_tags):
            t = node.get_text(" ", strip=True)
            if t:
                parts.append(t)
        body_text = "\n".join(parts)
        return title, desc, body_text or None


def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


