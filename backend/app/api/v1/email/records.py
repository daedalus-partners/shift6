from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..deps import get_db_dep as get_db
from ....services.email.coverage_records import (
    export_records_csv,
    get_record,
    list_clients,
    list_publications,
    search_records,
    summarize_records,
)


router = APIRouter(prefix="/email/records", tags=["Email Coverage Records"])
DateBasis = Literal["published", "captured", "generated"]


def _filters(
    client_name: str | None,
    publication: str | None,
    start_date: date | None,
    end_date: date | None,
    date_basis: DateBasis,
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date_must_precede_end_date")
    return {
        "client_name": client_name.strip() if client_name else None,
        "publication": publication.strip() if publication else None,
        "start_date": start_date,
        "end_date": end_date,
        "date_basis": date_basis,
    }


@router.get("")
def records(
    client_name: str | None = Query(default=None, max_length=128),
    publication: str | None = Query(default=None, max_length=256),
    start_date: date | None = None,
    end_date: date | None = None,
    date_basis: DateBasis = "published",
    limit: int = Query(100, ge=1, le=250),
    offset: int = Query(0, ge=0, le=100_000),
    db: Session = Depends(get_db),
):
    try:
        return search_records(
            db,
            limit=limit,
            offset=offset,
            **_filters(client_name, publication, start_date, end_date, date_basis),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/clients")
def record_clients(db: Session = Depends(get_db)):
    return {"items": list_clients(db)}


@router.get("/publications")
def record_publications(db: Session = Depends(get_db)):
    return {"items": list_publications(db)}


@router.get("/summary")
def record_summary(
    client_name: str | None = Query(default=None, max_length=128),
    publication: str | None = Query(default=None, max_length=256),
    start_date: date | None = None,
    end_date: date | None = None,
    date_basis: DateBasis = "published",
    db: Session = Depends(get_db),
):
    try:
        return summarize_records(
            db,
            **_filters(client_name, publication, start_date, end_date, date_basis),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/export.csv")
def export_csv(
    client_name: str | None = Query(default=None, max_length=128),
    publication: str | None = Query(default=None, max_length=256),
    start_date: date | None = None,
    end_date: date | None = None,
    date_basis: DateBasis = "published",
    db: Session = Depends(get_db),
):
    try:
        content, count = export_records_csv(
            db,
            **_filters(client_name, publication, start_date, end_date, date_basis),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = f"shift6-coverage-{date.today().isoformat()}.csv"
    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Shift6-Record-Count": str(count),
        },
    )


@router.get("/{summary_id}")
def record_detail(summary_id: int, db: Session = Depends(get_db)):
    item = get_record(db, summary_id)
    if not item:
        raise HTTPException(status_code=404, detail="coverage_record_not_found")
    return item
