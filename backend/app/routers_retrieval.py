from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import KnowledgeChunk, KnowledgeEmbedding
from .embedding import embed_texts

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/{client_id}/reindex")
def reindex(client_id: int, db: Session = Depends(get_db)):
    db.execute(delete(KnowledgeEmbedding).where(KnowledgeEmbedding.client_id == client_id))
    db.commit()

    chunks = db.execute(
        select(KnowledgeChunk.id, KnowledgeChunk.text).where(KnowledgeChunk.client_id == client_id).order_by(KnowledgeChunk.id.asc())
    ).all()
    if not chunks:
        return {"indexed": 0}

    embeddings = embed_texts([t for _, t in chunks])
    for (chunk_id, _), vec in zip(chunks, embeddings):
        db.add(
            KnowledgeEmbedding(
                chunk_id=chunk_id,
                client_id=client_id,
                embedding=vec.tolist(),
            )
        )
    db.commit()
    return {"indexed": len(chunks)}


@router.get("/{client_id}/search")
def search(client_id: int, q: str, k: int = 5, db: Session = Depends(get_db)):
    # Simple CPU cosine similarity
    chunks = db.execute(
        select(KnowledgeChunk.id, KnowledgeChunk.text, KnowledgeEmbedding.embedding)
        .join(KnowledgeEmbedding, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id)
        .where(KnowledgeChunk.client_id == client_id, KnowledgeEmbedding.client_id == client_id)
    ).all()
    if not chunks:
        return []

    import numpy as np

    query_vec = embed_texts([q])[0]
    embs = np.stack([row[2] for row in chunks])
    sims = (embs @ query_vec) / (np.linalg.norm(embs, axis=1) * (np.linalg.norm(query_vec) + 1e-9) + 1e-9)
    top_idx = np.argsort(-sims)[:k]
    results = []
    for idx in top_idx:
        chunk_id, text, _ = chunks[int(idx)]
        results.append({"chunk_id": int(chunk_id), "text": text, "score": float(sims[int(idx)])})
    return results
