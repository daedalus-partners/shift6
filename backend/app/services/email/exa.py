from __future__ import annotations

import os
import httpx
import logging


logger = logging.getLogger("exa.search")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")


async def fetch_article_via_exa(url: str) -> tuple[str | None, str | None, str | None]:
    """Fetch article content via Exa AI search API."""
    if not EXA_API_KEY:
        return None, None, None
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
                return None, None, None
            j = r.json()
            if not j:
                return None, None, None
            items = j.get("results") or []
            if not items:
                return None, None, None
            item = items[0]
            title = (item.get("title") or "").strip() or None
            desc = (item.get("summary") or "").strip() or None
            body = (item.get("text") or "").strip() or None
            return title, desc, body
    except Exception:
        return None, None, None


async def exa_search(query: str, num_results: int = 3) -> list[dict]:
    """Search using Exa AI API."""
    if not EXA_API_KEY:
        logger.warning("Exa API key not set, skipping search for query: %s", query)
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
    logger.info("Exa search request: query=%s num_results=%s", query, num_results)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            r = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
            logger.info("Exa search response: status_code=%s", r.status_code)
            if r.status_code != 200:
                logger.error("Exa search failed: status_code=%s response=%s", r.status_code, r.text[:500])
                return []
            j = r.json() or {}
            items = j.get("results") or []
            logger.info("Exa search returned %s results", len(items))
            out = []
            for idx, it in enumerate(items):
                title = it.get("title")
                url = it.get("url") or it.get("id")
                text = it.get("text") or ""
                text_preview = text[:200] if text else "(no text)"
                logger.debug("Exa result[%s]: url=%s title=%s text_preview=%s", idx, url, title, text_preview)
                out.append({
                    "title": title,
                    "url": url,
                    "text": text,
                })
            return out
    except Exception as e:
        logger.exception("Exa search exception for query=%s: %s", query, e)
        return []


