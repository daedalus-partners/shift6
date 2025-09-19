from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import List, Tuple

from .models import Client, KnowledgeChunk, KnowledgeEmbedding, StyleSnippet, SampleQuote
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

    styles = (
        db.query(StyleSnippet)
        .filter(StyleSnippet.client_id == client_id)
        .order_by(StyleSnippet.created_at.desc())
        .limit(5)
        .all()
    )
    samples = (
        db.query(SampleQuote)
        .filter(SampleQuote.client_id == client_id)
        .order_by(SampleQuote.created_at.desc())
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

    web_text = "\n\n".join(web_snippets or []) if include_web and web_snippets else ""

    system_prompt = (
        f"You are a media quote assistant for {client_name}.\n"
        f"Write a concise, punchy, on-brand quote under 70 words unless told otherwise.\n"
        f"Use the client's factual Knowledge; avoid hallucinations.\n"
        f"Voice/style guidance (may be empty):\n{style_text}\n"
    )

    context_block = "\n\n".join([p for p in [knowledge_text, sample_text, web_text] if p])

    messages: List[dict] = [
        {"role": "system", "content": system_prompt},
    ]
    if context_block:
        messages.append({"role": "system", "content": f"Context:\n{context_block}"})
    messages.append({"role": "user", "content": user_message})

    return system_prompt, messages
