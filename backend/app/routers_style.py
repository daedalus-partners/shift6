from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import StyleSnippet
from .schemas import StyleCreate, StyleOut

router = APIRouter(prefix="/styles", tags=["styles"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/{client_id}", response_model=StyleOut)
def create_style(client_id: int, payload: StyleCreate, db: Session = Depends(get_db)):
    s = StyleSnippet(client_id=client_id, label=payload.label, text=payload.text)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

@router.get("/{client_id}", response_model=list[StyleOut])
def list_styles(client_id: int, db: Session = Depends(get_db)):
    return (
        db.query(StyleSnippet)
        .filter(StyleSnippet.client_id == client_id)
        .order_by(StyleSnippet.created_at.desc())
        .all()
    )

@router.delete("/{client_id}/{style_id}")
def delete_style(client_id: int, style_id: int, db: Session = Depends(get_db)):
    s = (
        db.query(StyleSnippet)
        .filter(StyleSnippet.id == style_id, StyleSnippet.client_id == client_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(s)
    db.commit()
    return {"ok": True}
