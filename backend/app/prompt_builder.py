from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from typing import List, Tuple

from .models import Client, KnowledgeChunk, KnowledgeEmbedding, StyleSnippet, SampleQuote
import os
import httpx
from .embedding import embed_texts


def retrieve_top_chunks(db: Session, client_id: int, query: str, k: int = 6) -> List[Tuple[int, str, float]]:
    rows = db.execute(
        select(KnowledgeChunk.id, KnowledgeChunk.text, KnowledgeEmbedding.embedding)
        .join(KnowledgeEmbedding, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id)
        .where(KnowledgeChunk.client_id == client_id, KnowledgeEmbedding.client_id == client_id)
    ).all()
    if not rows:
        return []
    import numpy as np
    try:
        qv = embed_texts([query])[0]
    except Exception:
        # If embedding model isn't available yet, skip retrieval
        return []
    embs = np.stack([r[2] for r in rows])
    sims = (embs @ qv) / (np.linalg.norm(embs, axis=1) * (np.linalg.norm(qv) + 1e-9) + 1e-9)
    idx = np.argsort(-sims)[:k]
    return [(int(rows[i][0]), str(rows[i][1]), float(sims[i])) for i in idx]


def _load_system_prompt(slug: str | None, client_name: str) -> str:
    if slug:
        path = os.path.join(os.path.dirname(__file__), "..", "system_prompts", f"{slug}.md")
        path = os.path.abspath(path)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().replace("{{CLIENT_NAME}}", client_name)
            except Exception:
                pass
    # default
    return (
        f"You are a media quote assistant for {client_name}.\n"
        f"Produce one press-ready quote, concise, punchy, on-brand. Length ≤ 250 words (prefer ~200).\n"
        f"Return only the quote text."
    )


async def _get_web_snippets(user_message: str) -> List[str]:
    # Optional Exa integration via HTTP; fail-quiet
    api_key = os.getenv("EXA_API_KEY", "")
    if not api_key:
        return []
    try:
        headers = {"x-api-key": api_key, "content-type": "application/json"}
        payload = {"query": user_message, "numResults": 3}
        # attempt generic Exa endpoint; ignore failures
        async with httpx.AsyncClient(timeout=10) as client:
            # endpoint may vary; try a common path
            url = os.getenv("EXA_API_URL", "https://api.exa.ai/search")
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                return []
            data = r.json()
            items = data.get("results") or data.get("documents") or []
            snippets: List[str] = []
            for it in items[:3]:
                text = it.get("text") or it.get("snippet") or it.get("title")
                if text:
                    snippets.append(str(text))
            return snippets[:3]
    except Exception:
        return []


def build_prompt(
    db: Session,
    client_id: int,
    user_message: str,
    include_web: bool = False,
    web_snippets: List[str] | None = None,
    use_retrieval: bool = False,
) -> Tuple[str, List[dict]]:
    client = db.get(Client, client_id)
    client_name = client.name if client else "Client"
    client_slug = client.slug if client else None

    # Random selection per user preference: Style N=10, Samples M=3
    styles = (
        db.query(StyleSnippet)
        .filter(StyleSnippet.client_id == client_id)
        .order_by(func.random())
        .limit(10)
        .all()
    )
    samples = (
        db.query(SampleQuote)
        .filter(SampleQuote.client_id == client_id)
        .order_by(func.random())
        .limit(3)
        .all()
    )
    top_chunks: List[Tuple[int, str, float]] = []
    if use_retrieval:
        try:
            top_chunks = retrieve_top_chunks(db, client_id, user_message, k=6)
        except Exception:
            top_chunks = []

    style_text = "\n".join([f"- {s.text}" for s in styles]) if styles else ""
    sample_text = "\n\n".join([f"Sample: {s.text}" for s in samples]) if samples else ""
    knowledge_text = "\n\n".join([f"[Context {i+1}]\n{t}" for i, (_, t, _) in enumerate(top_chunks)]) if top_chunks else ""

    web_text = ""
    if include_web:
        if web_snippets is not None:
            web_text = "\n\n".join(web_snippets)
        else:
            # budget always present; try to fetch a few snippets about the user_message
            # note: this is async-capable helper; call synchronously via anyio if desired
            try:
                import anyio

                web_text = "\n\n".join(anyio.run(_get_web_snippets, user_message))
            except Exception:
                web_text = ""

    system_prompt = _load_system_prompt(client_slug, client_name)

    context_block = "\n\n".join([p for p in [knowledge_text, sample_text, web_text] if p])

    messages: List[dict] = [
        {"role": "system", "content": system_prompt},
    ]
    if context_block:
        messages.append({"role": "system", "content": f"Context:\n{context_block}"})
    messages.append({"role": "user", "content": user_message})

    return system_prompt, messages
