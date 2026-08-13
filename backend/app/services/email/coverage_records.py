from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ...models import (
    Article,
    ArticleSourceRevision,
    ArticleSummary,
    CoverageScoreSnapshot,
    EvidenceArtifact,
    Publication,
)


DateBasis = Literal["published", "captured", "generated"]
VALID_DATE_BASES: tuple[DateBasis, ...] = ("published", "captured", "generated")
DEFAULT_EXPORT_LIMIT = 10_000


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_expression(date_basis: DateBasis):
    if date_basis == "published":
        return func.coalesce(ArticleSourceRevision.published_at, Article.published_at_utc)
    if date_basis == "captured":
        # Screenshot capture time is distinct from the HTTP source-fetch time.
        # Correlating on the summary revision keeps repeated generations of the
        # same article from borrowing evidence captured for a different report.
        return (
            select(func.max(EvidenceArtifact.captured_at))
            .where(
                EvidenceArtifact.article_id == Article.id,
                EvidenceArtifact.kind.in_(("screenshot_full", "screenshot_thumbnail")),
                EvidenceArtifact.status == "ready",
                or_(
                    and_(
                        ArticleSummary.source_revision_id.is_not(None),
                        EvidenceArtifact.source_revision_id
                        == ArticleSummary.source_revision_id,
                    ),
                    and_(
                        ArticleSummary.source_revision_id.is_(None),
                        EvidenceArtifact.source_revision_id.is_(None),
                    ),
                ),
            )
            .correlate(Article, ArticleSummary)
            .scalar_subquery()
        )
    if date_basis == "generated":
        return ArticleSummary.created_at
    raise ValueError(f"Unsupported date basis: {date_basis}")


def _base_query(
    db: Session,
    *,
    client_name: str | None = None,
    publication: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    date_basis: DateBasis = "published",
):
    if date_basis not in VALID_DATE_BASES:
        raise ValueError(f"date_basis must be one of {', '.join(VALID_DATE_BASES)}")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    query = (
        db.query(ArticleSummary, Article, ArticleSourceRevision, Publication)
        .join(Article, Article.id == ArticleSummary.article_id)
        .outerjoin(
            ArticleSourceRevision,
            ArticleSourceRevision.id == ArticleSummary.source_revision_id,
        )
        .outerjoin(Publication, Publication.id == Article.publication_id)
    )
    if client_name and client_name.strip():
        query = query.filter(func.lower(Article.client_name) == client_name.strip().lower())
    if publication and publication.strip():
        normalized = publication.strip().lower().removeprefix("www.")
        query = query.filter(
            or_(
                func.lower(func.coalesce(Publication.domain, "")) == normalized,
                func.lower(func.coalesce(Publication.name, "")) == normalized,
                func.lower(func.coalesce(Article.domain, "")) == normalized,
                func.lower(func.coalesce(Article.publication, "")) == normalized,
                func.lower(func.coalesce(ArticleSourceRevision.domain, "")) == normalized,
                func.lower(func.coalesce(ArticleSourceRevision.publication, ""))
                == normalized,
            )
        )

    date_expression = _date_expression(date_basis)
    if start_date:
        query = query.filter(func.date(date_expression) >= start_date)
    if end_date:
        query = query.filter(func.date(date_expression) <= end_date)
    return query, date_expression


def _score_for(
    db: Session,
    *,
    article_id: int,
    source_revision_id: int | None,
) -> CoverageScoreSnapshot | None:
    query = db.query(CoverageScoreSnapshot).filter(
        CoverageScoreSnapshot.article_id == article_id
    )
    if source_revision_id is not None:
        query = query.filter(CoverageScoreSnapshot.source_revision_id == source_revision_id)
    return query.order_by(
        CoverageScoreSnapshot.calculated_at.desc(),
        CoverageScoreSnapshot.id.desc(),
    ).first()


def _evidence_for(
    db: Session,
    *,
    article_id: int,
    source_revision_id: int | None,
) -> list[EvidenceArtifact]:
    query = db.query(EvidenceArtifact).filter(EvidenceArtifact.article_id == article_id)
    if source_revision_id is not None:
        query = query.filter(EvidenceArtifact.source_revision_id == source_revision_id)
    return query.order_by(EvidenceArtifact.created_at.desc(), EvidenceArtifact.id.desc()).all()


def _evidence_public_url(artifact_id: int) -> str:
    base = os.getenv("EVIDENCE_PUBLIC_BASE_PATH", "/api/v1/evidence").rstrip("/")
    return f"{base}/{artifact_id}/content"


def serialize_record(
    db: Session,
    summary: ArticleSummary,
    article: Article,
    revision: ArticleSourceRevision | None,
    publication: Publication | None,
) -> dict[str, Any]:
    revision_id = revision.id if revision else summary.source_revision_id
    score = _score_for(db, article_id=article.id, source_revision_id=revision_id)
    artifacts = _evidence_for(db, article_id=article.id, source_revision_id=revision_id)

    evidence = [
        {
            "id": artifact.id,
            "kind": artifact.kind,
            "status": artifact.status,
            "url": _evidence_public_url(artifact.id) if artifact.status == "ready" else None,
            "storage_key": artifact.storage_key,
            "sha256": artifact.sha256,
            "mime_type": artifact.mime_type,
            "byte_size": artifact.byte_size,
            "captured_at": _iso(artifact.captured_at),
            "source_url": artifact.source_url,
            "final_url": artifact.final_url,
            "viewport": artifact.viewport,
            "error": artifact.error,
        }
        for artifact in artifacts
    ]
    thumbnail = next(
        (
            item
            for item in evidence
            if item["kind"] == "screenshot_thumbnail" and item["status"] == "ready"
        ),
        None,
    )
    screenshot = next(
        (
            item
            for item in evidence
            if item["kind"] == "screenshot_full" and item["status"] == "ready"
        ),
        None,
    )

    published_at = revision.published_at if revision else article.published_at_utc
    source_fetched_at = revision.fetched_at if revision else article.source_fetched_at
    published_date_raw = (
        revision.published_date_raw if revision else article.published_date_raw
    )
    published_date_source = (
        revision.published_date_source if revision else article.published_date_source
    )
    published_date_confidence = (
        revision.published_date_confidence
        if revision
        else article.published_date_confidence
    )
    date_candidates = (
        revision.published_date_candidates
        if revision
        else article.published_date_candidates
    )

    return {
        "summary_id": summary.id,
        "article_id": article.id,
        "source_revision_id": revision_id,
        "client_id": article.client_id,
        "client_name": article.client_name,
        "publication_id": article.publication_id,
        "publication": (
            (revision.publication if revision else None)
            or article.publication
            or (publication.name if publication else None)
        ),
        "domain": (
            (revision.domain if revision else None)
            or (publication.domain if publication else None)
            or article.domain
        ),
        "url": article.url,
        "final_url": (revision.final_url if revision else None) or article.final_url,
        "canonical_url": (
            (revision.canonical_url if revision else None) or article.canonical_url
        ),
        "title": (revision.title if revision else None) or article.title,
        "author": (revision.author if revision else None) or article.author,
        "published_at": _iso(published_at),
        "published_date_raw": published_date_raw,
        "published_date_source": published_date_source,
        "published_date_confidence": published_date_confidence,
        "published_date_candidates": date_candidates or [],
        "source_fetched_at": _iso(source_fetched_at),
        "captured_at": screenshot.get("captured_at") if screenshot else None,
        "generated_at": _iso(summary.created_at),
        "source_method": (
            (revision.source_method if revision else None) or article.source_method
        ),
        "source_sha256": (
            (revision.source_sha256 if revision else None) or article.source_sha256
        ),
        "subject": summary.subject,
        "sentiment": summary.sentiment,
        "validation_status": summary.validation_status,
        "metrics": summary.metrics or {},
        "score": (
            {
                "id": score.id,
                "methodology_version": score.methodology_version,
                "formula_hash": score.formula_hash,
                "status": score.status,
                "total": _number(score.total_score),
                "components": score.components or {},
                "inputs": score.inputs or {},
                "calculated_at": _iso(score.calculated_at),
            }
            if score
            else {
                "status": "legacy_unscored",
                "total": None,
                "methodology_version": None,
                "components": {},
                "inputs": {},
            }
        ),
        "evidence": evidence,
        "thumbnail": thumbnail,
        "screenshot": screenshot,
    }


def search_records(
    db: Session,
    *,
    client_name: str | None = None,
    publication: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    date_basis: DateBasis = "published",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if not 1 <= limit <= DEFAULT_EXPORT_LIMIT:
        raise ValueError(f"limit must be between 1 and {DEFAULT_EXPORT_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    query, date_expression = _base_query(
        db,
        client_name=client_name,
        publication=publication,
        start_date=start_date,
        end_date=end_date,
        date_basis=date_basis,
    )
    total = query.count()
    rows = (
        query.order_by(date_expression.desc().nullslast(), ArticleSummary.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_record(db, *row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {
            "client_name": client_name,
            "publication": publication,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "date_basis": date_basis,
        },
    }


def get_record(db: Session, summary_id: int) -> dict[str, Any] | None:
    row = (
        db.query(ArticleSummary, Article, ArticleSourceRevision, Publication)
        .join(Article, Article.id == ArticleSummary.article_id)
        .outerjoin(
            ArticleSourceRevision,
            ArticleSourceRevision.id == ArticleSummary.source_revision_id,
        )
        .outerjoin(Publication, Publication.id == Article.publication_id)
        .filter(ArticleSummary.id == summary_id)
        .first()
    )
    return serialize_record(db, *row) if row else None


def list_clients(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(Article.client_id, Article.client_name, func.count(ArticleSummary.id))
        .join(ArticleSummary, ArticleSummary.article_id == Article.id)
        .group_by(Article.client_id, Article.client_name)
        .order_by(func.lower(Article.client_name))
        .all()
    )
    return [
        {"id": client_id, "name": name, "record_count": count}
        for client_id, name, count in rows
    ]


def list_publications(db: Session) -> list[dict[str, Any]]:
    domain_expression = func.coalesce(Publication.domain, Article.domain)
    name_expression = func.coalesce(Publication.name, Article.publication)
    rows = (
        db.query(domain_expression, name_expression, func.count(ArticleSummary.id))
        .join(ArticleSummary, ArticleSummary.article_id == Article.id)
        .outerjoin(Publication, Publication.id == Article.publication_id)
        .filter(domain_expression.isnot(None))
        .group_by(domain_expression, name_expression)
        .order_by(func.lower(domain_expression))
        .all()
    )
    return [
        {"domain": domain, "name": name, "record_count": count}
        for domain, name, count in rows
    ]


def summarize_records(
    db: Session,
    **filters: Any,
) -> dict[str, Any]:
    result = search_records(db, limit=DEFAULT_EXPORT_LIMIT, offset=0, **filters)
    items = result["items"]
    numeric_scores = [
        item["score"]["total"]
        for item in items
        if item.get("score", {}).get("total") is not None
    ]
    clients = sorted({item["client_name"] for item in items if item.get("client_name")})
    publications = sorted({item["domain"] for item in items if item.get("domain")})
    return {
        "record_count": result["total"],
        "client_count": len(clients),
        "publication_count": len(publications),
        "scored_record_count": len(numeric_scores),
        "pending_score_count": len(items) - len(numeric_scores),
        "average_shift6_score": (
            round(sum(numeric_scores) / len(numeric_scores), 2) if numeric_scores else None
        ),
        "filters": result["filters"],
    }


CSV_COLUMNS = (
    "summary_id",
    "article_id",
    "source_revision_id",
    "client_id",
    "client_name",
    "publication_id",
    "publication",
    "domain",
    "title",
    "author",
    "url",
    "final_url",
    "canonical_url",
    "published_at",
    "published_date_raw",
    "published_date_source",
    "published_date_confidence",
    "source_fetched_at",
    "captured_at",
    "generated_at",
    "source_method",
    "source_sha256",
    "subject",
    "sentiment",
    "validation_status",
    "site_authority_value",
    "site_authority_source",
    "site_authority_method",
    "site_authority_confidence",
    "site_authority_observed_at",
    "monthly_audience_value",
    "monthly_audience_source",
    "monthly_audience_method",
    "monthly_audience_confidence",
    "monthly_audience_observed_at",
    "shift6_score",
    "shift6_score_status",
    "shift6_methodology_version",
    "shift6_formula_hash",
    "shift6_components_json",
    "shift6_inputs_json",
    "screenshot_ids",
    "screenshot_urls",
    "screenshot_hashes",
    "screenshot_captured_at",
)


def csv_safe(value: Any) -> str:
    """Neutralize spreadsheet formula execution while preserving visible data."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def records_to_csv(items: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        authority = metrics.get("site_authority") or {}
        audience = metrics.get("monthly_audience") or {}
        score = item.get("score") or {}
        evidence = [
            artifact
            for artifact in item.get("evidence") or []
            if str(artifact.get("kind", "")).startswith("screenshot")
        ]
        row = {
            **{column: item.get(column) for column in CSV_COLUMNS},
            "site_authority_value": authority.get("value"),
            "site_authority_source": authority.get("source"),
            "site_authority_method": authority.get("method"),
            "site_authority_confidence": authority.get("confidence"),
            "site_authority_observed_at": authority.get("observed_at"),
            "monthly_audience_value": audience.get("value"),
            "monthly_audience_source": audience.get("source"),
            "monthly_audience_method": audience.get("method"),
            "monthly_audience_confidence": audience.get("confidence"),
            "monthly_audience_observed_at": audience.get("observed_at"),
            "shift6_score": score.get("total"),
            "shift6_score_status": score.get("status"),
            "shift6_methodology_version": score.get("methodology_version"),
            "shift6_formula_hash": score.get("formula_hash"),
            "shift6_components_json": score.get("components") or {},
            "shift6_inputs_json": score.get("inputs") or {},
            "screenshot_ids": ";".join(str(value["id"]) for value in evidence),
            "screenshot_urls": ";".join(
                str(value["url"]) for value in evidence if value.get("url")
            ),
            "screenshot_hashes": ";".join(
                str(value["sha256"]) for value in evidence if value.get("sha256")
            ),
            "screenshot_captured_at": ";".join(
                str(value["captured_at"])
                for value in evidence
                if value.get("captured_at")
            ),
        }
        writer.writerow({key: csv_safe(value) for key, value in row.items()})
    return output.getvalue()


def export_records_csv(db: Session, **filters: Any) -> tuple[str, int]:
    result = search_records(db, limit=DEFAULT_EXPORT_LIMIT, offset=0, **filters)
    if result["total"] > DEFAULT_EXPORT_LIMIT:
        raise ValueError(
            f"Export exceeds {DEFAULT_EXPORT_LIMIT} rows; narrow the client, publication, or date range"
        )
    return records_to_csv(result["items"]), result["total"]
