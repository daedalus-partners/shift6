from __future__ import annotations

import os
import httpx


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "anthropic/claude-3.7-sonnet")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shift6.local/",
        "X-Title": "Shift6 Coverage",
    }


async def summarize_to_markdown(data: dict) -> str:
    # If no key, return a deterministic offline placeholder
    if not OPENROUTER_API_KEY:
        return _offline_template(data)

    system = (
        "You are a PR analyst. Generate a concise, well-structured PR coverage email in Markdown with the following sections: "
        "Headline & Outlet, Outlet Snapshot (description, DA, MUV), Links & Mentions, Sentiment & Message Pull-Through, "
        "Quote Highlight, Audience / Strategic Value, Performance / Reach. Keep it actionable and under ~250 words."
    )
    user = (
        f"client_name: {data.get('client_name')}\n"
        f"article_url: {data.get('url')}\n"
        f"domain: {data.get('domain')}\n"
        f"title: {data.get('title') or ''}\n"
        f"outlet_description: {data.get('outlet_description') or ''}\n"
        f"DA: {data.get('da') or ''}\n"
        f"MUV: {data.get('muv') or ''}\n"
        f"mentions: {', '.join(data.get('mentions') or [])}\n"
        f"links: {', '.join(data.get('links') or [])}\n"
        f"article_excerpt: {(data.get('body') or '')[:1200]}\n"
        "Return only Markdown."
    )
    payload = {
        "model": OPENROUTER_MODEL_ID,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=_headers(), json=payload)
            if r.status_code == 200:
                j = r.json()
                msg = (j.get("choices") or [{}])[0].get("message") or {}
                content = msg.get("content") or (j.get("choices") or [{}])[0].get("text")
                if content:
                    return str(content)
    except Exception:
        pass
    return _offline_template(data)


def _offline_template(d: dict) -> str:
    title = d.get("title") or "(Title)"
    domain = d.get("domain") or "(Outlet)"
    da = d.get("da") or "—"
    muv = d.get("muv") or "—"
    desc = d.get("outlet_description") or "—"
    links = d.get("links") or []
    mentions = d.get("mentions") or []
    return (
        f"{title} – {domain}\n\n"
        f"Outlet Snapshot\n\n- DA {da}, MUV {muv}\n- {desc}\n\n"
        f"Links & Mentions\n\n- Links: {', '.join(links) or '—'}\n- Mentions: {', '.join(mentions) or '—'}\n\n"
        f"Sentiment & Message Pull-Through\n\n- (placeholder)\n\n"
        f"Quote Highlight\n\n- (placeholder)\n\n"
        f"Audience / Strategic Value\n\n- (placeholder)\n\n"
        f"Performance / Reach\n\n- (placeholder)\n"
    )


