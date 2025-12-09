from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from ...models import Quote
from ...embedding import embed_texts


def _load_service_account_json() -> dict | None:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        return None


def _open_sheet() -> tuple[object, str] | tuple[None, str]:
    try:
        import gspread  # type: ignore
    except Exception:
        return None, "gspread not installed"
    sa = _load_service_account_json()
    if not sa:
        return None, "missing GOOGLE_SERVICE_ACCOUNT_JSON"
    sheet_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
    if not sheet_id:
        return None, "missing GOOGLE_SHEETS_ID"
    try:
        client = gspread.service_account_from_dict(sa)
        sh = client.open_by_key(sheet_id)
        ws = sh.sheet1  # first worksheet
        return ws, "ok"
    except Exception as e:
        return None, f"gspread error: {e}"


def _read_records_with_rownums(ws: object) -> List[Tuple[int, Dict[str, str]]]:
    # ws is a gspread worksheet. We access via duck typing to avoid strict types.
    values = ws.get_all_values()  # type: ignore[attr-defined]
    if not values:
        return []
    header = [h.strip() for h in (values[0] or [])]
    out: List[Tuple[int, Dict[str, str]]] = []
    for idx, row in enumerate(values[1:], start=2):
        rec = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        out.append((idx, rec))
    return out


def upsert_from_sheet(db: Session) -> Dict[str, int | str]:
    ws, status = _open_sheet()
    if not ws:
        return {"ok": 0, "inserted": 0, "updated": 0, "skipped": 0, "error": status}

    rows = _read_records_with_rownums(ws)
    now = datetime.now(timezone.utc)

    inserted = 0
    updated = 0
    skipped = 0

    # Preload quotes by sheet_row_id for faster upsert
    existing_by_id: Dict[str, Quote] = {
        q.sheet_row_id: q for q in db.query(Quote).all() if q.sheet_row_id
    }

    texts_to_embed: List[Tuple[str, Quote | None]] = []

    sheet_key = os.getenv("GOOGLE_SHEETS_ID", "").strip()

    for rownum, rec in rows:
        client_name = (rec.get("client_name") or rec.get("Client") or rec.get("client") or "").strip()
        quote_text = (rec.get("quote_text") or rec.get("Quote") or rec.get("quote") or "").strip()
        notes = (rec.get("notes") or rec.get("Notes") or "").strip()
        if not client_name or not quote_text:
            skipped += 1
            continue
        sheet_row_id = f"{sheet_key}:{rownum}"
        existing = existing_by_id.get(sheet_row_id)
        if not existing:
            q = Quote(
                sheet_row_id=sheet_row_id,
                client_name=client_name,
                quote_text=quote_text,
                state="ACTIVE_HOURLY",
                added_at=now,
                next_run_at=now,
                hit_count=0,
                days_without_hit=0,
            )
            db.add(q)
            existing_by_id[sheet_row_id] = q
            inserted += 1
            texts_to_embed.append((quote_text, q))
        else:
            changed = False
            if existing.client_name != client_name:
                existing.client_name = client_name
                changed = True
            if existing.quote_text != quote_text:
                existing.quote_text = quote_text
                # re-embed if changed
                texts_to_embed.append((quote_text, existing))
                changed = True
            if changed:
                updated += 1

    # Perform embeddings in batch
    if texts_to_embed:
        texts = [t for t, _ in texts_to_embed]
        vecs = embed_texts(texts)
        for (_, quote_obj), vec in zip(texts_to_embed, vecs):
            quote_obj.quote_emb = vec  # type: ignore[assignment]

    db.commit()

    return {"ok": 1, "inserted": inserted, "updated": updated, "skipped": skipped}

