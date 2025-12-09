from __future__ import annotations

import os
import httpx
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .scraper import get_domain, fetch_article_http
from .exa import fetch_article_via_exa, exa_search
import re


async def try_fetch_about_description(domain: str) -> str | None:
    """Attempt to fetch a description from the outlet's about page."""
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
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Try og:description first
                    og = soup.find("meta", attrs={"property": "og:description"})
                    if og and og.get("content"):
                        return og["content"].strip()[:400]
                    # Try meta description
                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    if meta_desc and meta_desc.get("content"):
                        return meta_desc["content"].strip()[:400]
                    # Fall back to first substantial paragraph
                    for p in soup.find_all("p"):
                        text = p.get_text(" ", strip=True)
                        if len(text) > 50:  # Skip tiny paragraphs
                            return text[:400]
            except Exception:
                continue
    return None


async def lookup_da_muv(domain: str) -> tuple[str | None, str | None]:
    """
    Look up Domain Authority and Monthly Unique Visitors for a domain.
    Uses Open PageRank API for DA (free) and falls back to Exa search for MUV.
    """
    da: str | None = None
    muv: str | None = None
    
    # Clean domain (remove www. prefix for consistency)
    clean_domain = domain.lower().replace("www.", "")
    
    # DA via Open PageRank API (free, no key required for basic lookups)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            # Open PageRank API
            resp = await client.get(
                f"https://openpagerank.com/api/v1.0/getPageRank",
                params={"domains[]": clean_domain},
                headers={"API-OPR": os.getenv("OPENPAGERANK_API_KEY", "")}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("response") and len(data["response"]) > 0:
                    pr = data["response"][0]
                    # page_rank_decimal is 0-10, convert to 0-100 scale like DA
                    if pr.get("page_rank_decimal") is not None:
                        da = str(int(float(pr["page_rank_decimal"]) * 10))
                    elif pr.get("rank"):
                        # Use rank as fallback indicator
                        da = f"Rank: {pr['rank']}"
    except Exception:
        pass
    
    # Fallback: Try Exa search for DA from Moz
    if not da:
        moz_q = f"site:moz.com Domain Authority {clean_domain}"
        for item in await exa_search(moz_q, num_results=3):
            u = (item.get("url") or "").lower()
            if not u or "moz.com" not in u:
                continue
            text = (item.get("text") or "")
            m = re.search(r"Domain Authority\s*[:\s]*(\d{1,3})", text, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                if 0 <= val <= 100:
                    da = str(val)
                    break
    
    # MUV via Exa search for SimilarWeb data
    sw_q = f"site:similarweb.com {clean_domain} traffic"
    for item in await exa_search(sw_q, num_results=3):
        u = (item.get("url") or "").lower()
        if not u or "similarweb.com" not in u:
            continue
        text = (item.get("text") or "")
        # Look for various traffic indicators
        patterns = [
            r"(\d[\d,.]*\s*[KkMm]?)\s*(?:monthly\s+)?(?:unique\s+)?visitors",
            r"visits[:\s]*(\d[\d,.]*\s*[KkMm]?)",
            r"traffic[:\s]*(\d[\d,.]*\s*[KkMm]?)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                muv = m.group(1).strip()
                break
        if muv:
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


