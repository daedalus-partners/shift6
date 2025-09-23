from __future__ import annotations

import os
import httpx
from urllib.parse import urljoin
from .scraper import get_domain, fetch_article_http


async def try_fetch_about_description(domain: string) -> str | None:  # type: ignore[name-defined]
    # Attempt a couple common about paths and return first paragraph
    base = f"https://{domain}"
    candidates = ["/about", "/about-us", "/company/about"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
        for path in candidates:
            try:
                resp = await client.get(urljoin(base, path), headers=headers, follow_redirects=True)
                if resp.status_code == 200 and "text/html" in (resp.headers.get("content-type") or ""):
                    # Quick-and-dirty first <p>
                    text = resp.text
                    start = text.lower().find("<p")
                    if start != -1:
                        seg = text[start: start + 2000]
                        # remove tags roughly
                        cleaned = " ".join(seg.replace("<p", " ").replace("</p>", " ").split())
                        return cleaned[:400]
            except Exception:
                continue
    return None


async def lookup_da_muv(domain: str) -> tuple[str | None, str | None]:
    # Minimal placeholder; if API keys exist, wire simple GETs
    # Returning None keeps output clean without fake data
    return None, None


async def fetch_or_scrape(url: str) -> tuple[str | None, str | None, str | None, str]:
    domain = get_domain(url)
    try:
        title, desc, body = await fetch_article_http(url)
    except Exception:
        title, desc, body = None, None, None
    return title, desc, body, domain


