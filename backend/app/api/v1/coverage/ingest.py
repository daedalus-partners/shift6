from __future__ import annotations

import base64
import json
import os
from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ....db import get_db
from ....models import Quote
from ....embedding import embed_texts
from ....services.coverage.sheets import upsert_from_sheet

router = APIRouter(prefix="/ingest", tags=["Ingest"])


def _get_service_json() -> dict | None:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        # else assume base64-encoded JSON
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        return None


@router.post("/sheets/sync")
def sheets_sync(db: Session = Depends(get_db)):
    result = upsert_from_sheet(db)
    return result


class PasteItem(BaseModel):
    client_name: str
    quote_text: str


class PasteIn(BaseModel):
    items: List[PasteItem]


@router.post("/paste")
def paste_import(payload: PasteIn, db: Session = Depends(get_db)):
    inserted = 0
    updated = 0
    skipped = 0

    existing = {(q.client_name.lower().strip(), q.quote_text.strip()): q for q in db.query(Quote).all()}
    to_embed: List[Quote] = []
    for item in payload.items:
        client = (item.client_name or "").strip()
        quote = (item.quote_text or "").strip()
        if not client or not quote:
            skipped += 1
            continue
        key = (client.lower(), quote)
        q = existing.get(key)
        if not q:
            q = Quote(client_name=client, quote_text=quote, state="ACTIVE_HOURLY")
            db.add(q)
            existing[key] = q
            inserted += 1
            to_embed.append(q)
        else:
            if q.client_name != client:
                q.client_name = client
                updated += 1

    if to_embed:
        vecs = embed_texts([q.quote_text for q in to_embed])
        for q, v in zip(to_embed, vecs):
            q.quote_emb = v  # type: ignore[assignment]

    db.commit()
    return {"ok": 1, "inserted": inserted, "updated": updated, "skipped": skipped}
