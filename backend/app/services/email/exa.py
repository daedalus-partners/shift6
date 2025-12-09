from __future__ import annotations

import os
import httpx


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
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            r = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
            if r.status_code != 200:
                return []
            j = r.json() or {}
            items = j.get("results") or []
            out = []
            for it in items:
                out.append({
                    "title": it.get("title"),
                    "url": it.get("url") or it.get("id"),
                    "text": it.get("text") or "",
                })
            return out
    except Exception:
        return []


