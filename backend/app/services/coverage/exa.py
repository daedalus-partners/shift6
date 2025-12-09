from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

EXA_API_KEY = os.getenv("EXA_API_KEY", "")


async def exa_search(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search using Exa AI API and return results with text content.
    """
    if not EXA_API_KEY:
        return []
    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "query": query,
        "numResults": int(num_results),
        "useAutoprompt": False,
        "contents": {
            "text": True,  # Request full text content
        },
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            r = await client.post(
                "https://api.exa.ai/search",
                headers=headers,
                json=payload
            )
            if r.status_code != 200:
                # Log error for debugging
                print(f"[Exa] Search failed: {r.status_code} - {r.text[:200]}")
                return []
            data = r.json() or {}
            items = data.get("results") or []
            results: List[Dict[str, Any]] = []
            for it in items:
                results.append(
                    {
                        "title": it.get("title") or "",
                        "url": it.get("url") or it.get("id") or "",
                        "text": it.get("text") or it.get("content") or "",
                        "description": it.get("summary") or "",
                        "publishedDate": it.get("publishedDate") or "",
                    }
                )
            return results
    except Exception as e:
        print(f"[Exa] Search exception: {e}")
        return []


async def fetch_article_text(url: str) -> Optional[str]:
    """Retrieve article body via Exa contents API."""
    if not EXA_API_KEY:
        return None
    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }
    # Use contents endpoint to get text for a specific URL
    payload: Dict[str, Any] = {
        "ids": [url],
        "text": True,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            r = await client.post(
                "https://api.exa.ai/contents",
                headers=headers,
                json=payload
            )
            if r.status_code != 200:
                return None
            data = r.json() or {}
            results = data.get("results") or []
            if results:
                return (results[0].get("text") or "").strip() or None
    except Exception:
        pass
    return None

