from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, case, literal
from sqlalchemy.orm import Session

from ....db import get_db
from ....models import Hit, HitRead, AppSettings, Quote
from ....services.coverage.pipeline import run_due as pipeline_run_due
from ....services.coverage.sheets import upsert_from_sheet
from pydantic import BaseModel
from typing import List
from ....models import Quote
from ....embedding import embed_texts

router = APIRouter(prefix="/coverage", tags=["Coverage"])

# Single-tenant sentinel user ID for read tracking
SENTINEL_USER = "00000000-0000-0000-0000-000000000000"


@router.get("")
def list_coverage(
    db: Session = Depends(get_db),
    new_only: bool = False,
    client: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    if page < 1:
        page = 1
    if limit < 1 or limit > 100:
        limit = 20

    # Subquery to get read status for each hit (single query, no N+1)
    read_subq = (
        db.query(HitRead.hit_id)
        .filter(HitRead.user_id == SENTINEL_USER)
        .subquery()
    )

    # Build base query with LEFT JOIN to read status
    q = db.query(
        Hit,
        case((read_subq.c.hit_id.isnot(None), literal(True)), else_=literal(False)).label("is_read")
    ).outerjoin(read_subq, Hit.id == read_subq.c.hit_id)

    # Apply filters
    if client:
        q = q.filter(Hit.client_name == client)
    if start:
        try:
            dt = datetime.fromisoformat(start)
            q = q.filter(Hit.created_at >= dt)
        except Exception:
            pass
    if end:
        try:
            dt = datetime.fromisoformat(end)
            q = q.filter(Hit.created_at <= dt)
        except Exception:
            pass

    # Apply new_only filter BEFORE pagination (fixes pagination bug)
    if new_only:
        q = q.filter(read_subq.c.hit_id.is_(None))

    # Get total count BEFORE pagination for proper UI
    total_count = q.count()

    # Apply ordering and pagination
    q = q.order_by(Hit.created_at.desc())
    rows = q.offset((page - 1) * limit).limit(limit).all()

    # Build results
    results = []
    for hit, is_read in rows:
        results.append({
            "id": str(hit.id),
            "client_name": hit.client_name,
            "url": hit.url,
            "domain": hit.domain,
            "title": hit.title,
            "snippet": (hit.snippet or "")[:280],
            "match_type": hit.match_type,
            "confidence": float(hit.confidence) if hit.confidence is not None else None,
            "published_at": hit.published_at.isoformat() if hit.published_at else None,
            "created_at": hit.created_at.isoformat() if hit.created_at else None,
            "is_read": is_read,
        })

    return {
        "items": results,
        "page": page,
        "limit": limit,
        "count": len(results),
        "total": total_count,
    }


@router.get("/r/{hit_id}")
def redirect_and_mark_read(hit_id: str, db: Session = Depends(get_db)):
    h = db.get(Hit, hit_id)
    if not h:
        raise HTTPException(status_code=404, detail="Not found")
    if not db.query(HitRead).filter(HitRead.hit_id == h.id, HitRead.user_id == SENTINEL_USER).first():
        db.add(HitRead(hit_id=h.id, user_id=SENTINEL_USER, read_at=datetime.utcnow()))  # type: ignore[arg-type]
        db.commit()
    return RedirectResponse(url=h.url, status_code=307)


@router.get("/{hit_id}/markdown")
async def coverage_markdown(hit_id: str, db: Session = Depends(get_db)):
    h = db.get(Hit, hit_id)
    if not h:
        raise HTTPException(status_code=404, detail="Not found")
    return {"markdown": h.markdown or ""}


@router.post("/mark-all-read")
def mark_all_read(db: Session = Depends(get_db)):
    # Get all hit IDs that are not already marked as read (single query)
    already_read_subq = (
        db.query(HitRead.hit_id)
        .filter(HitRead.user_id == SENTINEL_USER)
        .subquery()
    )
    unread_hits = (
        db.query(Hit.id)
        .outerjoin(already_read_subq, Hit.id == already_read_subq.c.hit_id)
        .filter(already_read_subq.c.hit_id.is_(None))
        .all()
    )

    now = datetime.utcnow()
    created = 0
    for (hid,) in unread_hits:
        db.add(HitRead(hit_id=hid, user_id=SENTINEL_USER, read_at=now))  # type: ignore[arg-type]
        created += 1

    if created:
        db.commit()
    return {"updated": created}


@router.post("/settings/email")
def update_email_settings(emails: str, enabled: bool, db: Session = Depends(get_db)):
    s = db.query(AppSettings).first()
    if not s:
        s = AppSettings(emails=emails, email_enabled=enabled)
        db.add(s)
    else:
        s.emails = emails
        s.email_enabled = enabled
        s.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "email_enabled": s.email_enabled, "emails": s.emails}


@router.post("/scan")
async def coverage_scan(limit: int = 20, db: Session = Depends(get_db)):
    processed = await pipeline_run_due(db, limit=limit)
    return {"processed": processed}


@router.post("/sheets/import")
def coverage_sheets_import(db: Session = Depends(get_db)):
    result = upsert_from_sheet(db)
    return result


@router.get("/quotes")
def list_quotes(
    db: Session = Depends(get_db),
    client: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    if page < 1:
        page = 1
    if limit < 1 or limit > 100:
        limit = 20

    q = db.query(Quote)
    if client:
        q = q.filter(Quote.client_name == client)

    # Get total count BEFORE pagination
    total_count = q.count()

    q = q.order_by(Quote.added_at.desc())
    quotes = q.offset((page - 1) * limit).limit(limit).all()

    items = []
    for qu in quotes:
        items.append(
            {
                "id": str(qu.id),
                "client_name": qu.client_name,
                "quote_text": qu.quote_text,
                "state": qu.state,
                "added_at": qu.added_at.isoformat() if qu.added_at else None,
                "first_hit_at": qu.first_hit_at.isoformat() if qu.first_hit_at else None,
                "last_hit_at": qu.last_hit_at.isoformat() if qu.last_hit_at else None,
                "last_checked_at": qu.last_checked_at.isoformat() if qu.last_checked_at else None,
                "next_run_at": qu.next_run_at.isoformat() if qu.next_run_at else None,
                "hit_count": qu.hit_count,
                "days_without_hit": qu.days_without_hit,
            }
        )
    return {"items": items, "page": page, "limit": limit, "count": len(items), "total": total_count}


@router.delete("/quotes/{quote_id}")
def delete_quote(quote_id: str, db: Session = Depends(get_db)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Not found")

    # Delete dependent hit reads and hits first to satisfy FK constraints
    hits = db.query(Hit).filter(Hit.quote_id == q.id).all()
    deleted_hits = 0
    if hits:
        hit_ids = [h.id for h in hits]
        if hit_ids:
            db.query(HitRead).filter(HitRead.hit_id.in_(hit_ids)).delete(synchronize_session=False)
            db.query(Hit).filter(Hit.id.in_(hit_ids)).delete(synchronize_session=False)
            deleted_hits = len(hit_ids)

    db.delete(q)
    db.commit()
    return {"ok": True, "deleted_hits": deleted_hits}


class PasteItem(BaseModel):
    client_name: str
    quote_text: str


class PasteIn(BaseModel):
    items: List[PasteItem]


@router.post("/ingest/paste")
def coverage_paste_import(payload: PasteIn, db: Session = Depends(get_db)):
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


