from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import SampleQuote
from .schemas import SampleQuoteCreate, SampleQuoteOut

router = APIRouter(prefix="/samples", tags=["samples"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/{client_id}", response_model=SampleQuoteOut)
def create_sample(client_id: int, payload: SampleQuoteCreate, db: Session = Depends(get_db)):
    s = SampleQuote(client_id=client_id, source=payload.source, text=payload.text)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

@router.get("/{client_id}", response_model=list[SampleQuoteOut])
def list_samples(client_id: int, db: Session = Depends(get_db)):
    return (
        db.query(SampleQuote)
        .filter(SampleQuote.client_id == client_id)
        .order_by(SampleQuote.created_at.desc())
        .all()
    )

@router.delete("/{client_id}/{sample_id}")
def delete_sample(client_id: int, sample_id: int, db: Session = Depends(get_db)):
    s = (
        db.query(SampleQuote)
        .filter(SampleQuote.id == sample_id, SampleQuote.client_id == client_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(s)
    db.commit()
    return {"ok": True}
