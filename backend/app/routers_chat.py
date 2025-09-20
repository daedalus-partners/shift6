from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from .db import SessionLocal
from .models import Chat, ChatMessage

router = APIRouter(prefix="/chat", tags=["chat"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{client_id}/last")
def last_messages(client_id: int, limit: int = 30, db: Session = Depends(get_db)):
    # return latest messages (across chats) for this client, most recent first, capped
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.client_id == client_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
        .all()
    )
    # serialize minimally
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]


