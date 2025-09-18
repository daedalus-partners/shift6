from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import KnowledgeFile, KnowledgeChunk
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


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 100) -> List[str]:
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + max_chars)
        chunk = text[start:end]
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


@router.post("/{client_id}/upload", response_model=KnowledgeFileOut)
def upload_file(client_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = file.file.read()
    sha256 = hashlib.sha256(content).hexdigest()
    fname = f"{sha256[:16]}_{file.filename}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(content)

    text = content.decode(errors="ignore") if file.content_type.startswith("text/") else ""

    kf = KnowledgeFile(
        client_id=client_id,
        source_type="file",
        filename=file.filename,
        mime=file.content_type,
        bytes_size=len(content),
        sha256=sha256,
        uploaded_at=datetime.utcnow(),
        text=text or None,
    )
    db.add(kf)
    db.commit()
    db.refresh(kf)

    if text:
        for idx, chunk in enumerate(_chunk_text(text)):
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
    # delete chunks
    db.query(KnowledgeChunk).filter(KnowledgeChunk.file_id == file_id).delete()
    db.delete(kf)
    db.commit()
    return {"ok": True}
