from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Awaitable, Callable, Sequence
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ...db import SessionLocal
from ...models import Article, ArticleSourceRevision, EvidenceArtifact
from ..email.http_safety import UnsafeUrlError, same_source_url, validate_public_url


logger = logging.getLogger(__name__)
ARTIFACT_FULL = "screenshot_full"
ARTIFACT_THUMBNAIL = "screenshot_thumbnail"
SCREENSHOT_ARTIFACT_KINDS = (ARTIFACT_FULL, ARTIFACT_THUMBNAIL)
PENDING = "pending"
PROCESSING = "processing"
READY = "ready"
FAILED = "failed"
DEFAULT_VIEWPORT = {"width": 1440, "height": 1000, "device_scale_factor": 1}
DEFAULT_THUMBNAIL_WIDTH = 480
DEFAULT_TIMEOUT_MS = 30_000
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_CAPTURE_HEIGHT = 30_000
_SAFE_SEGMENT = re.compile(r"^[a-zA-Z0-9._-]+$")
_capture_slots = asyncio.Semaphore(max(1, int(os.getenv("SCREENSHOT_CAPTURE_CONCURRENCY", "1"))))


class ScreenshotCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapturedScreenshot:
    full_png: bytes
    thumbnail_png: bytes
    final_url: str
    viewport: dict[str, int | float]


@dataclass(frozen=True)
class StoredArtifact:
    storage_key: str
    sha256: str
    byte_size: int


CaptureFunction = Callable[[str], Awaitable[CapturedScreenshot]]


def evidence_root() -> Path:
    return Path(os.getenv("EVIDENCE_DIR", "/data/evidence")).expanduser().resolve()


def validate_storage_key(storage_key: str) -> PurePosixPath:
    """Validate a DB storage key before resolving it under EVIDENCE_DIR."""
    raw_key = str(storage_key or "")
    if not raw_key or "//" in raw_key or raw_key.startswith("./") or "/./" in raw_key:
        raise ValueError("invalid_evidence_storage_key")
    key = PurePosixPath(raw_key)
    if key.is_absolute() or not key.parts or any(
        part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part) for part in key.parts
    ):
        raise ValueError("invalid_evidence_storage_key")
    return key


def storage_path(storage_key: str, root: Path | None = None) -> Path:
    base = (root or evidence_root()).resolve()
    relative = validate_storage_key(storage_key)
    resolved = base.joinpath(*relative.parts).resolve()
    if resolved == base or base not in resolved.parents:
        raise ValueError("evidence_path_outside_root")
    return resolved


def artifact_storage_key(
    article_id: int,
    source_revision_id: int | None,
    kind: str,
    sha256: str,
) -> str:
    if kind not in SCREENSHOT_ARTIFACT_KINDS:
        raise ValueError("unsupported_evidence_artifact_kind")
    revision = str(source_revision_id) if source_revision_id is not None else "latest"
    suffix = "full.png" if kind == ARTIFACT_FULL else "thumbnail.png"
    return f"articles/{int(article_id)}/revisions/{revision}/{sha256}-{suffix}"


def manifest_storage_key(article_id: int, source_revision_id: int | None) -> str:
    revision = str(source_revision_id) if source_revision_id is not None else "latest"
    return f"articles/{int(article_id)}/revisions/{revision}/manifest.json"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _store_png(
    *,
    article_id: int,
    source_revision_id: int | None,
    kind: str,
    png: bytes,
    root: Path | None = None,
) -> StoredArtifact:
    if not png or len(png) > MAX_IMAGE_BYTES:
        raise ScreenshotCaptureError("screenshot_size_out_of_bounds")
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ScreenshotCaptureError("browser_returned_invalid_png")
    digest = hashlib.sha256(png).hexdigest()
    key = artifact_storage_key(article_id, source_revision_id, kind, digest)
    path = storage_path(key, root=root)
    if path.exists():
        existing = path.read_bytes()
        if hashlib.sha256(existing).hexdigest() != digest:
            raise ScreenshotCaptureError("immutable_artifact_hash_mismatch")
    else:
        _atomic_write(path, png)
    return StoredArtifact(storage_key=key, sha256=digest, byte_size=len(png))


def _write_manifest(
    *,
    article_id: int,
    source_revision_id: int | None,
    source_url: str,
    final_url: str,
    captured_at: datetime,
    viewport: dict[str, int | float],
    artifacts: Sequence[tuple[str, StoredArtifact]],
    root: Path | None = None,
) -> str:
    key = manifest_storage_key(article_id, source_revision_id)
    payload = {
        "schema_version": 1,
        "article_id": article_id,
        "source_revision_id": source_revision_id,
        "source_url": source_url,
        "final_url": final_url,
        "captured_at": captured_at.isoformat(),
        "viewport": viewport,
        "artifacts": [
            {
                "kind": kind,
                "storage_key": stored.storage_key,
                "sha256": stored.sha256,
                "byte_size": stored.byte_size,
                "mime_type": "image/png",
            }
            for kind, stored in artifacts
        ],
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = storage_path(key, root=root)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ScreenshotCaptureError("invalid_existing_evidence_manifest") from exc
        if existing != payload:
            raise ScreenshotCaptureError("immutable_evidence_manifest_exists")
    else:
        _atomic_write(path, encoded)
    return key


def _source_identity(db: Session, article: Article, source_revision_id: int | None) -> str:
    if source_revision_id is None:
        return str(article.canonical_url or article.final_url or article.url)
    revision = db.get(ArticleSourceRevision, source_revision_id)
    if revision is None or revision.article_id != article.id:
        raise ValueError("source_revision_not_found")
    return str(revision.canonical_url or revision.final_url or revision.requested_url)


def queue_screenshot_capture(
    db: Session,
    *,
    article_id: int,
    source_revision_id: int | None,
    source_url: str | None = None,
) -> tuple[EvidenceArtifact, EvidenceArtifact]:
    """Create or reuse one durable pending artifact row for each screenshot kind."""
    article = db.get(Article, article_id)
    if article is None:
        raise ValueError("article_not_found")
    durable_source_url = _source_identity(db, article, source_revision_id)
    if source_url is not None and not same_source_url(source_url, durable_source_url):
        raise ValueError("source_url_does_not_match_article")

    rows: list[EvidenceArtifact] = []
    for kind in SCREENSHOT_ARTIFACT_KINDS:
        query = db.query(EvidenceArtifact).filter(
            EvidenceArtifact.article_id == article.id,
            EvidenceArtifact.kind == kind,
        )
        if source_revision_id is None:
            query = query.filter(EvidenceArtifact.source_revision_id.is_(None))
        else:
            query = query.filter(EvidenceArtifact.source_revision_id == source_revision_id)
        artifact = query.order_by(EvidenceArtifact.id.desc()).first()
        if artifact is None or artifact.status == FAILED:
            artifact = EvidenceArtifact(
                article_id=article.id,
                source_revision_id=source_revision_id,
                kind=kind,
                status=PENDING,
                mime_type="image/png",
                source_url=durable_source_url,
                viewport=dict(DEFAULT_VIEWPORT),
            )
            db.add(artifact)
        rows.append(artifact)
    db.flush()
    return rows[0], rows[1]


async def capture_page_with_playwright(url: str) -> CapturedScreenshot:
    """Capture one verified public page without retaining browser state."""
    validated_url = await validate_public_url(url)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - deployment configuration failure
        raise ScreenshotCaptureError("playwright_not_installed") from exc

    timeout_ms = int(os.getenv("SCREENSHOT_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)))
    viewport = dict(DEFAULT_VIEWPORT)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu", "--no-sandbox"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": viewport["width"], "height": viewport["height"]},
                device_scale_factor=viewport["device_scale_factor"],
                java_script_enabled=True,
                ignore_https_errors=False,
            )
            page = await context.new_page()

            async def guard_request(route, request) -> None:
                if request.url.startswith(("data:", "blob:", "about:")):
                    await route.continue_()
                    return
                try:
                    await validate_public_url(request.url)
                except (UnsafeUrlError, ValueError):
                    await route.abort("blockedbyclient")
                    return
                await route.continue_()

            await page.route("**/*", guard_request)
            response = await page.goto(
                validated_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if response is None:
                raise ScreenshotCaptureError("browser_navigation_returned_no_response")
            if response.status >= 400:
                raise ScreenshotCaptureError(f"browser_navigation_status_{response.status}")
            final_url = await validate_public_url(page.url)
            if not same_source_url(validated_url, final_url):
                raise ScreenshotCaptureError("browser_redirected_to_different_article_url")
            try:
                await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8_000))
            except Exception:
                # Many publisher pages keep analytics connections open. DOM
                # readiness is sufficient; network-idle is best effort.
                pass
            document_height = await page.evaluate(
                "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            )
            if not isinstance(document_height, (int, float)) or document_height < 1:
                raise ScreenshotCaptureError("invalid_document_height")
            if document_height > MAX_CAPTURE_HEIGHT:
                raise ScreenshotCaptureError("document_too_tall_to_capture_safely")
            full_png = await page.screenshot(
                full_page=True,
                type="png",
                animations="disabled",
                timeout=timeout_ms,
            )
            thumbnail_png = await page.screenshot(
                type="png",
                animations="disabled",
                clip={
                    "x": 0,
                    "y": 0,
                    "width": viewport["width"],
                    "height": min(viewport["height"], int(document_height)),
                },
                scale="css",
                timeout=timeout_ms,
            )
        finally:
            await browser.close()

    # Render the bounded viewport preview at a stable small width. Pillow only
    # transforms trusted bytes returned by Chromium; it never fetches a URL.
    try:
        from PIL import Image

        from io import BytesIO

        source = Image.open(BytesIO(thumbnail_png))
        source.load()
        ratio = min(1.0, DEFAULT_THUMBNAIL_WIDTH / source.width)
        resized = source.resize(
            (max(1, round(source.width * ratio)), max(1, round(source.height * ratio))),
            Image.Resampling.LANCZOS,
        )
        output = BytesIO()
        resized.save(output, format="PNG", optimize=True)
        thumbnail_png = output.getvalue()
    except Exception as exc:
        raise ScreenshotCaptureError("thumbnail_generation_failed") from exc

    return CapturedScreenshot(full_png, thumbnail_png, final_url, viewport)


def _mark_rows_failed(db: Session, rows: Sequence[EvidenceArtifact], error: str) -> None:
    safe_error = " ".join(str(error or "screenshot_capture_failed").split())[:2_000]
    for row in rows:
        row.status = FAILED
        row.error = safe_error
    db.commit()


async def run_screenshot_capture_job(
    *,
    article_id: int,
    source_revision_id: int | None,
    capture: CaptureFunction | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
    root: Path | None = None,
) -> bool:
    """Run one nonfatal durable capture job and return whether it succeeded."""
    capture_function = capture or capture_page_with_playwright
    async with _capture_slots:
        db = session_factory()
        rows: tuple[EvidenceArtifact, EvidenceArtifact] | None = None
        try:
            rows = queue_screenshot_capture(
                db,
                article_id=article_id,
                source_revision_id=source_revision_id,
            )
            if all(row.status == READY for row in rows):
                db.rollback()
                return True
            if any(row.status == PROCESSING for row in rows):
                db.rollback()
                return False
            source_url = rows[0].source_url
            for row in rows:
                row.status = PROCESSING
                row.error = None
            db.commit()

            captured = await capture_function(source_url)
            if not same_source_url(source_url, captured.final_url):
                raise ScreenshotCaptureError("captured_page_does_not_match_source_url")
            captured_at = datetime.now(timezone.utc)
            stored_full = _store_png(
                article_id=article_id,
                source_revision_id=source_revision_id,
                kind=ARTIFACT_FULL,
                png=captured.full_png,
                root=root,
            )
            stored_thumbnail = _store_png(
                article_id=article_id,
                source_revision_id=source_revision_id,
                kind=ARTIFACT_THUMBNAIL,
                png=captured.thumbnail_png,
                root=root,
            )
            stored_by_kind = {
                ARTIFACT_FULL: stored_full,
                ARTIFACT_THUMBNAIL: stored_thumbnail,
            }
            _write_manifest(
                article_id=article_id,
                source_revision_id=source_revision_id,
                source_url=source_url,
                final_url=captured.final_url,
                captured_at=captured_at,
                viewport=captured.viewport,
                artifacts=[
                    (ARTIFACT_FULL, stored_full),
                    (ARTIFACT_THUMBNAIL, stored_thumbnail),
                ],
                root=root,
            )
            for row in rows:
                stored = stored_by_kind[row.kind]
                row.status = READY
                row.storage_key = stored.storage_key
                row.sha256 = stored.sha256
                row.byte_size = stored.byte_size
                row.captured_at = captured_at
                row.final_url = captured.final_url
                row.viewport = dict(captured.viewport)
                row.error = None
            db.commit()
            return True
        except Exception as exc:
            db.rollback()
            if rows is None:
                try:
                    rows = queue_screenshot_capture(
                        db,
                        article_id=article_id,
                        source_revision_id=source_revision_id,
                    )
                except Exception:
                    db.rollback()
            if rows is not None:
                _mark_rows_failed(db, rows, f"{type(exc).__name__}: {exc}")
            logger.exception(
                "Screenshot evidence capture failed article_id=%s source_revision_id=%s",
                article_id,
                source_revision_id,
            )
            return False
        finally:
            db.close()


def schedule_screenshot_capture(
    *,
    article_id: int,
    source_revision_id: int | None,
) -> asyncio.Task[bool]:
    """Schedule a best-effort job in the active API process."""
    task = asyncio.create_task(
        run_screenshot_capture_job(
            article_id=article_id,
            source_revision_id=source_revision_id,
        ),
        name=f"screenshot-evidence-{article_id}-{source_revision_id or 'latest'}",
    )

    def log_failure(completed: asyncio.Task[bool]) -> None:
        try:
            completed.result()
        except Exception:
            logger.exception("Unhandled screenshot evidence background-job failure")

    task.add_done_callback(log_failure)
    return task
