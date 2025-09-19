from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import List

import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from .db import SessionLocal
from .models import KnowledgeFile, KnowledgeChunk, KnowledgeEmbedding
from .schemas import KnowledgeNoteCreate, KnowledgeFileOut

UPLOAD_DIR = "/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _chunk_text(text_src: str, max_chars: int = 1200, overlap: int = 100) -> List[str]:
    chunks: List[str] = []
    start = 0
    n = len(text_src)
    while start < n:
        end = min(n, start + max_chars)
        chunk = text_src[start:end]
        chunks.append(chunk)
        if end == n:
            break
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


@router.post("/{client_id}/notes", response_model=KnowledgeFileOut)
def create_note(client_id: int, payload: KnowledgeNoteCreate, db: Session = Depends(get_db)):
    kf = KnowledgeFile(
        client_id=client_id,
        source_type="note",
        text=payload.text,
        uploaded_at=datetime.utcnow(),
    )
    db.add(kf)
    db.commit()
    db.refresh(kf)

    # create chunks
    for idx, chunk in enumerate(_chunk_text(payload.text)):
        db.add(
            KnowledgeChunk(
                file_id=kf.id,
                client_id=client_id,
                chunk_index=idx,
                text=chunk,
                token_count=len(chunk.split()),
            )
        )
    db.commit()
    return kf


logger = logging.getLogger("knowledge.upload")


@router.post("/{client_id}/upload", response_model=KnowledgeFileOut, status_code=201)
def upload_file(client_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = file.file.read()
    if not content:
        logger.warning("empty upload: client_id=%s filename=%s content_type=%s", client_id, file.filename, file.content_type)
        raise HTTPException(status_code=400, detail="empty file")
    sha256 = hashlib.sha256(content).hexdigest()

    # duplicate detection per client by file content hash
    exists = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.client_id == client_id, KnowledgeFile.sha256 == sha256)
        .first()
    )
    if exists:
        logger.info("duplicate upload: client_id=%s filename=%s sha256=%s", client_id, file.filename, sha256[:12])
        raise HTTPException(status_code=409, detail="duplicate file")

    fname = f"{sha256[:16]}_{file.filename}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(content)

    text_content = content.decode(errors="ignore") if (file.content_type or "").startswith("text/") else ""

    logger.info(
        "uploaded: client_id=%s filename=%s bytes=%s mime=%s sha256=%s user_agent=%s",
        client_id,
        file.filename,
        len(content),
        file.content_type,
        sha256[:12],
        request.headers.get("user-agent", "-")[:80],
    )

    kf = KnowledgeFile(
        client_id=client_id,
        source_type="file",
        filename=file.filename,
        mime=file.content_type,
        bytes_size=len(content),
        sha256=sha256,
        uploaded_at=datetime.utcnow(),
        text=text_content or None,
    )
    db.add(kf)
    db.commit()
    db.refresh(kf)

    if text_content:
        for idx, chunk in enumerate(_chunk_text(text_content)):
            db.add(
                KnowledgeChunk(
                    file_id=kf.id,
                    client_id=client_id,
                    chunk_index=idx,
                    text=chunk,
                    token_count=len(chunk.split()),
                )
            )
        db.commit()

    return kf


@router.get("/{client_id}", response_model=list[KnowledgeFileOut])
def list_knowledge(client_id: int, db: Session = Depends(get_db)):
    q = db.query(KnowledgeFile).filter(KnowledgeFile.client_id == client_id).order_by(KnowledgeFile.uploaded_at.desc())
    return q.all()


@router.delete("/{client_id}/{file_id}")
def delete_knowledge(client_id: int, file_id: int, db: Session = Depends(get_db)):
    kf = db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id, KnowledgeFile.client_id == client_id).first()
    if not kf:
        raise HTTPException(status_code=404, detail="not found")
    # delete embeddings tied to chunks for this file (join delete)
    db.execute(
        text(
            "DELETE FROM knowledge_embeddings USING knowledge_chunks "
            "WHERE knowledge_embeddings.chunk_id = knowledge_chunks.id "
            "AND knowledge_chunks.file_id = :fid"
        ),
        {"fid": file_id},
    )
    db.commit()
    # delete chunks then file
    db.query(KnowledgeChunk).filter(KnowledgeChunk.file_id == file_id).delete(synchronize_session=False)
    db.commit()
    db.delete(kf)
    db.commit()
    return {"ok": True}
