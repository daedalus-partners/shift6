from __future__ import annotations

import os
import httpx


EXA_API_KEY = os.getenv("EXA_API_KEY", "")


async def fetch_article_via_exa(url: str) -> tuple[str | None, str | None, str | None]:
    if not EXA_API_KEY:
        return None, None, None
    headers = {
        "Authorization": f"Bearer {EXA_API_KEY}",
        "Content-Type": "application/json",
    }
    # Try a generic search+contents call by URL. Exa API versions vary; we handle failures gracefully.
    payload = {
        "query": url,
        "num_results": 1,
        "use_autoprompt": False,
        "include_text": True,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            # Prefer search endpoint that can return text/content
            r = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
            if r.status_code != 200:
                return None, None, None
            j = r.json()
            if not j:
                return None, None, None
            items = j.get("results") or j.get("data") or []
            if not items:
                return None, None, None
            item = items[0]
            title = (item.get("title") or item.get("id") or "").strip() or None
            desc = (item.get("description") or item.get("summary") or "").strip() or None
            body = (item.get("text") or item.get("content") or "").strip() or None
            return title, desc, body
    except Exception:
        return None, None, None


async def exa_search(query: str, num_results: int = 3) -> list[dict]:
    if not EXA_API_KEY:
        return []
    headers = {
        "Authorization": f"Bearer {EXA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": str(query),
        "num_results": int(num_results),
        "use_autoprompt": False,
        "include_text": True,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            r = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
            if r.status_code != 200:
                return []
            j = r.json() or {}
            items = j.get("results") or j.get("data") or []
            out = []
            for it in items:
                out.append({
                    "title": it.get("title"),
                    "url": it.get("url") or it.get("link") or it.get("id"),
                    "text": it.get("text") or it.get("content") or "",
                })
            return out
    except Exception:
        return []


