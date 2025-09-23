from __future__ import annotations

import os
import httpx
from urllib.parse import urljoin
from .scraper import get_domain, fetch_article_http
from .exa import fetch_article_via_exa, exa_search
import re


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
    da: str | None = None
    muv: str | None = None
    # DA via Moz only
    moz_q = f"site:moz.com Domain Authority {domain}"
    for item in await exa_search(moz_q, num_results=3):
        u = (item.get("url") or "").lower()
        if not u or "moz.com" not in u:
            continue
        text = (item.get("text") or "")
        m = re.search(r"Domain Authority\s*(\d{1,3})", text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                da = str(val)
                break
    # MUV via SimilarWeb only (look for 'Monthly Unique Visitors')
    sw_q = f"site:similarweb.com {domain} monthly unique visitors"
    for item in await exa_search(sw_q, num_results=3):
        u = (item.get("url") or "").lower()
        if not u or "similarweb.com" not in u:
            continue
        text = (item.get("text") or "")
        m = re.search(r"monthly\s+unique\s+visitors[^\d]*(\d[\d,.]*\s*[KkMm]?)", text, re.IGNORECASE)
        if m:
            muv = m.group(1).strip()
            break
    return da, muv


async def fetch_or_scrape(url: str) -> tuple[str | None, str | None, str | None, str]:
    domain = get_domain(url)
    # Try Exa first
    title, desc, body = await fetch_article_via_exa(url)
    if not body:
        try:
            title, desc, body = await fetch_article_http(url)
        except Exception:
            title, desc, body = None, None, None
    return title, desc, body, domain


