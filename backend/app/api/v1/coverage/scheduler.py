from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ....db import get_db
from ....models import Quote
from ....services.coverage.pipeline import run_due as pipeline_run_due

router = APIRouter(prefix="/search", tags=["Search/Scheduler"])


@router.post("/run-due")
async def run_due(db: Session = Depends(get_db)):
    processed = await pipeline_run_due(db, limit=20)
    return {"processed": processed}
