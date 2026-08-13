from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....models import Article, EvidenceArtifact
from ....services.evidence.screenshots import (
    SCREENSHOT_ARTIFACT_KINDS,
    queue_screenshot_capture,
    run_screenshot_capture_job,
    storage_path,
)
from ..deps import get_db_dep as get_db


router = APIRouter(prefix="/api/v1/evidence", tags=["Evidence"])


class ScreenshotCaptureIn(BaseModel):
    article_id: int = Field(ge=1)
    source_revision_id: int | None = Field(default=None, ge=1)


def artifact_json(artifact: EvidenceArtifact) -> dict:
    return {
        "id": artifact.id,
        "article_id": artifact.article_id,
        "source_revision_id": artifact.source_revision_id,
        "kind": artifact.kind,
        "status": artifact.status,
        "storage_key": artifact.storage_key,
        "sha256": artifact.sha256,
        "mime_type": artifact.mime_type,
        "byte_size": artifact.byte_size,
        "captured_at": artifact.captured_at.isoformat() if artifact.captured_at else None,
        "source_url": artifact.source_url,
        "final_url": artifact.final_url,
        "viewport": artifact.viewport,
        "error": artifact.error,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


async def _capture_after_response(article_id: int, source_revision_id: int | None) -> None:
    await run_screenshot_capture_job(
        article_id=article_id,
        source_revision_id=source_revision_id,
    )


@router.post("/screenshots", status_code=202)
def capture_screenshots(
    payload: ScreenshotCaptureIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        rows = queue_screenshot_capture(
            db,
            article_id=payload.article_id,
            source_revision_id=payload.source_revision_id,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        detail = str(exc)
        status_code = 404 if detail in {"article_not_found", "source_revision_not_found"} else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if any(row.status not in {"ready", "processing"} for row in rows):
        background_tasks.add_task(
            _capture_after_response,
            payload.article_id,
            payload.source_revision_id,
        )
    return {
        "status": "accepted",
        "artifacts": [artifact_json(row) for row in rows],
    }


@router.get("")
def list_evidence(
    article_id: int = Query(ge=1),
    source_revision_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    if db.get(Article, article_id) is None:
        raise HTTPException(status_code=404, detail="article_not_found")
    query = db.query(EvidenceArtifact).filter(
        EvidenceArtifact.article_id == article_id,
        EvidenceArtifact.kind.in_(SCREENSHOT_ARTIFACT_KINDS),
    )
    if source_revision_id is not None:
        query = query.filter(EvidenceArtifact.source_revision_id == source_revision_id)
    rows = query.order_by(EvidenceArtifact.created_at.desc(), EvidenceArtifact.id.desc()).all()
    return {"items": [artifact_json(row) for row in rows]}


@router.get("/{artifact_id}")
def get_evidence(artifact_id: int, db: Session = Depends(get_db)):
    artifact = db.get(EvidenceArtifact, artifact_id)
    if artifact is None or artifact.kind not in SCREENSHOT_ARTIFACT_KINDS:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    return artifact_json(artifact)


@router.get("/{artifact_id}/content")
def evidence_content(artifact_id: int, db: Session = Depends(get_db)):
    artifact = db.get(EvidenceArtifact, artifact_id)
    if artifact is None or artifact.kind not in SCREENSHOT_ARTIFACT_KINDS:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    if artifact.status != "ready" or not artifact.storage_key:
        raise HTTPException(status_code=409, detail="evidence_not_ready")
    try:
        path = storage_path(artifact.storage_key)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="invalid_evidence_storage_key") from exc
    if not path.is_file():
        raise HTTPException(status_code=410, detail="evidence_content_missing")
    return FileResponse(
        path=Path(path),
        media_type=artifact.mime_type or "image/png",
        filename=f"shift6-{artifact.article_id}-{artifact.kind}.png",
        headers={"ETag": f'"{artifact.sha256}"'} if artifact.sha256 else None,
    )
