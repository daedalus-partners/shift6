from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


sys.path.insert(0, "backend")

from app.models import Article, ArticleSourceRevision, EvidenceArtifact  # noqa: E402
from app.services.evidence import screenshots  # noqa: E402


PNG_FULL = b"\x89PNG\r\n\x1a\nfull-image"
PNG_THUMBNAIL = b"\x89PNG\r\n\x1a\nthumbnail-image"


class FakeQuery:
    def __init__(self, session, rows):
        self.session = session
        self.rows = list(rows)

    def filter(self, *criteria):
        filtered = list(self.rows)
        for criterion in criteria:
            left = getattr(criterion, "left", None)
            column = getattr(left, "name", None)
            operator = getattr(criterion, "operator", None)
            right = getattr(criterion, "right", None)
            value = getattr(right, "value", None)
            if column and operator is not None:
                rendered = str(operator)
                if "is_" in rendered and value is None:
                    filtered = [row for row in filtered if getattr(row, column) is None]
                elif value is not None:
                    filtered = [row for row in filtered if getattr(row, column) == value]
        return FakeQuery(self.session, filtered)

    def order_by(self, *_criteria):
        return self

    def first(self):
        return self.rows[-1] if self.rows else None


class FakeSession:
    def __init__(self, article, revision=None):
        self.article = article
        self.revision = revision
        self.artifacts: list[EvidenceArtifact] = []
        self.closed = False

    def get(self, model, object_id):
        if model is Article and self.article.id == object_id:
            return self.article
        if model is ArticleSourceRevision and self.revision and self.revision.id == object_id:
            return self.revision
        if model is EvidenceArtifact:
            return next((row for row in self.artifacts if row.id == object_id), None)
        return None

    def query(self, model):
        assert model is EvidenceArtifact
        return FakeQuery(self, self.artifacts)

    def add(self, row):
        if row.id is None:
            row.id = len(self.artifacts) + 1
        self.artifacts.append(row)

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def article_fixture() -> Article:
    article = Article(
        client_name="Acme",
        url="https://publisher.example/story",
        final_url="https://publisher.example/story",
    )
    article.id = 42
    return article


def revision_fixture() -> ArticleSourceRevision:
    revision = ArticleSourceRevision(
        article_id=42,
        requested_url="https://publisher.example/story",
        final_url="https://publisher.example/story",
        source_method="direct_http",
    )
    revision.id = 7
    return revision


def test_storage_key_is_hash_addressed_and_cannot_escape_evidence_root(tmp_path):
    stored = screenshots._store_png(
        article_id=42,
        source_revision_id=7,
        kind=screenshots.ARTIFACT_FULL,
        png=PNG_FULL,
        root=tmp_path,
    )

    path = screenshots.storage_path(stored.storage_key, root=tmp_path)
    assert path.read_bytes() == PNG_FULL
    assert path.name.endswith("-full.png")
    assert stored.sha256 in path.name
    assert path.stat().st_mode & 0o777 == 0o640
    for unsafe in ("../secret.png", "/tmp/secret.png", "articles//secret.png", "a/./b"):
        with pytest.raises(ValueError):
            screenshots.storage_path(unsafe, root=tmp_path)


def test_store_rejects_non_png_and_oversized_data(tmp_path, monkeypatch):
    with pytest.raises(screenshots.ScreenshotCaptureError, match="invalid_png"):
        screenshots._store_png(
            article_id=42,
            source_revision_id=7,
            kind=screenshots.ARTIFACT_FULL,
            png=b"not a png",
            root=tmp_path,
        )
    monkeypatch.setattr(screenshots, "MAX_IMAGE_BYTES", 8)
    with pytest.raises(screenshots.ScreenshotCaptureError, match="size_out_of_bounds"):
        screenshots._store_png(
            article_id=42,
            source_revision_id=7,
            kind=screenshots.ARTIFACT_FULL,
            png=PNG_FULL,
            root=tmp_path,
        )


def test_queue_is_idempotent_and_uses_revision_identity():
    session = FakeSession(article_fixture(), revision_fixture())

    first = screenshots.queue_screenshot_capture(
        session,
        article_id=42,
        source_revision_id=7,
    )
    second = screenshots.queue_screenshot_capture(
        session,
        article_id=42,
        source_revision_id=7,
    )

    assert first == second
    assert len(session.artifacts) == 2
    assert {row.kind for row in first} == set(screenshots.SCREENSHOT_ARTIFACT_KINDS)
    assert all(row.source_url == "https://publisher.example/story" for row in first)
    assert all(row.status == "pending" for row in first)


def test_queue_rejects_cross_article_revision_and_source_override():
    session = FakeSession(article_fixture(), revision_fixture())
    session.revision.article_id = 99
    with pytest.raises(ValueError, match="source_revision_not_found"):
        screenshots.queue_screenshot_capture(session, article_id=42, source_revision_id=7)

    session.revision.article_id = 42
    with pytest.raises(ValueError, match="source_url_does_not_match_article"):
        screenshots.queue_screenshot_capture(
            session,
            article_id=42,
            source_revision_id=7,
            source_url="https://evil.example/story",
        )


@pytest.mark.asyncio
async def test_capture_job_persists_both_files_manifest_and_ready_rows(tmp_path):
    session = FakeSession(article_fixture(), revision_fixture())

    async def capture(_url: str):
        return screenshots.CapturedScreenshot(
            full_png=PNG_FULL,
            thumbnail_png=PNG_THUMBNAIL,
            final_url="https://publisher.example/story",
            viewport=dict(screenshots.DEFAULT_VIEWPORT),
        )

    ok = await screenshots.run_screenshot_capture_job(
        article_id=42,
        source_revision_id=7,
        capture=capture,
        session_factory=lambda: session,
        root=tmp_path,
    )

    assert ok is True
    assert session.closed is True
    assert {row.status for row in session.artifacts} == {"ready"}
    assert {row.kind for row in session.artifacts} == set(screenshots.SCREENSHOT_ARTIFACT_KINDS)
    for row in session.artifacts:
        assert row.captured_at.tzinfo == timezone.utc
        assert screenshots.storage_path(row.storage_key, root=tmp_path).is_file()
        assert row.sha256
        assert row.byte_size > 0
    manifest_path = screenshots.storage_path(
        screenshots.manifest_storage_key(42, 7), root=tmp_path
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["source_revision_id"] == 7
    assert {item["kind"] for item in manifest["artifacts"]} == set(
        screenshots.SCREENSHOT_ARTIFACT_KINDS
    )


@pytest.mark.asyncio
async def test_capture_failure_is_durable_and_nonfatal(tmp_path):
    session = FakeSession(article_fixture(), revision_fixture())

    async def capture(_url: str):
        raise screenshots.ScreenshotCaptureError("publisher_timeout")

    ok = await screenshots.run_screenshot_capture_job(
        article_id=42,
        source_revision_id=7,
        capture=capture,
        session_factory=lambda: session,
        root=tmp_path,
    )

    assert ok is False
    assert session.closed is True
    assert {row.status for row in session.artifacts} == {"failed"}
    assert all("publisher_timeout" in row.error for row in session.artifacts)
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.asyncio
async def test_browser_capture_rejects_private_url_before_importing_playwright(monkeypatch):
    async def reject(_url: str):
        raise screenshots.UnsafeUrlError("private destination")

    monkeypatch.setattr(screenshots, "validate_public_url", reject)
    with pytest.raises(screenshots.UnsafeUrlError, match="private destination"):
        await screenshots.capture_page_with_playwright("http://127.0.0.1/internal")
