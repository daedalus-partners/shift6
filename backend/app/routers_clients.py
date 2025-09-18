from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Client
from .schemas import ClientCreate, ClientOut

router = APIRouter(prefix="/clients", tags=["clients"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    exists = db.query(Client).filter(Client.slug == payload.slug).first()
    if exists:
        raise HTTPException(status_code=409, detail="slug already exists")
    c = Client(slug=payload.slug, name=payload.name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("/", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(Client).order_by(Client.slug.asc()).all()
