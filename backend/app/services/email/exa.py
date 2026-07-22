from __future__ import annotations

import os
import httpx
import logging

from .http_safety import same_source_url


logger = logging.getLogger("exa.search")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")


def extract_exact_article_result(
    requested_url: str, results: list[dict]
) -> tuple[str | None, str | None, str | None, str] | None:
    for item in results:
        result_url = str(item.get("url") or item.get("id") or "").strip()
        if not result_url or not same_source_url(requested_url, result_url):
            continue
        title = (item.get("title") or "").strip() or None
        desc = (item.get("summary") or item.get("description") or "").strip() or None
        body = (item.get("text") or "").strip() or None
        if body:
            return title, desc, body, result_url
    return None


async def fetch_article_via_exa(url: str) -> tuple[str | None, str | None, str | None, str] | None:
    """Fetch article content via Exa AI search API."""
    if not EXA_API_KEY:
        return None
    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "query": url,
        "numResults": 1,
        "useAutoprompt": False,
        "contents": {
            "text": True,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            r = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
            if r.status_code != 200:
                return None
            j = r.json()
            if not j:
                return None
            items = j.get("results") or []
            if not items:
                return None
            return extract_exact_article_result(url, items)
    except Exception:
        return None


async def exa_search(query: str, num_results: int = 3) -> list[dict]:
    """Search using Exa AI API."""
    if not EXA_API_KEY:
        logger.warning("Exa API key not set, skipping search")
        return []
    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "query": str(query),
        "numResults": int(num_results),
        "useAutoprompt": False,
        "contents": {
            "text": True,
        },
    }
    logger.info("Exa search request: num_results=%s", num_results)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            r = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
            logger.info("Exa search response: status_code=%s", r.status_code)
            if r.status_code != 200:
                logger.error("Exa search failed: status_code=%s", r.status_code)
                return []
            j = r.json() or {}
            items = j.get("results") or []
            logger.info("Exa search returned %s results", len(items))
            out = []
            for it in items:
                title = it.get("title")
                url = it.get("url") or it.get("id")
                text = it.get("text") or ""
                out.append({
                    "title": title,
                    "url": url,
                    "text": text,
                })
            return out
    except Exception:
        logger.exception("Exa search failed")
        return []
