from __future__ import annotations

import logging
import asyncio
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import desc, text as sql_text
from sqlalchemy.orm import Session

from ..deps import get_db_dep as get_db
from ....embedding import embed_texts
from ....models import (
    Article,
    ArticleEmbedding,
    ArticleSourceRevision,
    ArticleSummary,
    CoverageScoreSnapshot,
    Publication,
    PublicationMetricSnapshot,
)
from ....services.email.http_safety import ResponseTooLargeError, UnsafeUrlError
from ....services.email.metadata import fetch_or_scrape, lookup_da_muv, try_fetch_about_description
from ....services.email.nlp import (
    classify_sentiment,
    extract_client_links,
    extract_mentions_and_links,
    find_best_quote,
)
from ....services.email.subject import coverage_subject, markdown_with_subject, markdown_without_subject
from ....services.email.summarizer import SummaryGenerationError, summarize_to_markdown
from ....services.email.scoring import (
    Shift6Score,
    calculate_shift6_score,
    render_shift6_score_markdown,
)
from ....services.evidence.screenshots import (
    queue_screenshot_capture,
    schedule_screenshot_capture,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/email", tags=["Email"])


class SummarizeIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=128)
    article_url: HttpUrl


@router.get("/health")
def email_health():
    return {"status": "ok"}


def _source_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cached_publication_metrics(db: Session, domain: str, max_age_days: int = 30) -> dict | None:
    """Reuse recent Moz metrics so repeated coverage does not consume another API row."""
    rows = (
        db.query(ArticleSummary)
        .join(Article, Article.id == ArticleSummary.article_id)
        .filter(Article.domain == domain)
        .order_by(desc(ArticleSummary.created_at), desc(ArticleSummary.id))
        .limit(20)
        .all()
    )
    oldest_allowed = date.today() - timedelta(days=max_age_days)
    for summary in rows:
        metrics = summary.metrics if isinstance(summary.metrics, dict) else {}
        authority = metrics.get("site_authority") if isinstance(metrics, dict) else None
        if not isinstance(authority, dict) or authority.get("source") != "Moz Link Explorer API v2":
            continue
        try:
            observed_at = date.fromisoformat(str(authority.get("observed_at")))
        except ValueError:
            continue
        if observed_at >= oldest_allowed:
            return metrics
    return None


def _normalized_domain(domain: str | None) -> str | None:
    value = str(domain or "").strip().lower()
    value = re.sub(r"^www\.", "", value)
    return value or None


def _get_or_create_publication(
    db: Session,
    domain: str | None,
    publication_name: str | None,
) -> Publication | None:
    normalized = _normalized_domain(domain)
    if not normalized:
        return None
    publication = db.query(Publication).filter(Publication.domain == normalized).first()
    if publication is None:
        publication = Publication(
            domain=normalized,
            name=(publication_name or normalized)[:128],
        )
        db.add(publication)
        db.flush()
    elif publication_name and not publication.name:
        publication.name = publication_name[:128]
        publication.updated_at = datetime.now(timezone.utc)
    return publication


def _metric_numeric_value(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    normalized = str(value or "").strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return Decimal(match.group())
    except ArithmeticError:
        return None


def _metric_observed_at(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(raw), time.min)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metric_unit(metric_key: str) -> str | None:
    if metric_key == "site_authority":
        return "score_0_100"
    if metric_key == "monthly_audience":
        return "monthly_visits"
    return None


def _persist_metric_snapshots(
    db: Session,
    *,
    metrics: Mapping[str, Any],
    publication: Publication | None,
    article: Article,
    revision: ArticleSourceRevision,
) -> list[PublicationMetricSnapshot]:
    if publication is None:
        return []
    snapshots: list[PublicationMetricSnapshot] = []
    for metric_key, raw_metric in metrics.items():
        if not isinstance(raw_metric, Mapping):
            continue
        snapshot = PublicationMetricSnapshot(
            publication_id=publication.id,
            article_id=article.id,
            source_revision_id=revision.id,
            metric_key=str(metric_key)[:64],
            label=str(raw_metric.get("label") or "")[:128] or None,
            value_text=str(raw_metric.get("value") or "")[:128] or None,
            value_numeric=_metric_numeric_value(raw_metric.get("value")),
            unit=_metric_unit(str(metric_key)),
            provider=str(raw_metric.get("source") or "Unknown")[:128],
            method=str(raw_metric.get("method") or "") or None,
            confidence=str(raw_metric.get("confidence") or "")[:16] or None,
            estimated=bool(raw_metric.get("estimated", False)),
            observed_at=_metric_observed_at(raw_metric.get("observed_at")),
            raw=dict(raw_metric),
        )
        db.add(snapshot)
        snapshots.append(snapshot)
    return snapshots


def _score_payload(snapshot: CoverageScoreSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "methodology_version": snapshot.methodology_version,
        "methodology_status": (
            snapshot.inputs.get("methodology", {}).get("status")
            if isinstance(snapshot.inputs, dict)
            else None
        ),
        "formula_hash": snapshot.formula_hash,
        "status": snapshot.status,
        "total_score": float(snapshot.total_score) if snapshot.total_score is not None else None,
        "components": snapshot.components or {},
    }


def _score_for_summary(db: Session, summary: ArticleSummary) -> CoverageScoreSnapshot | None:
    query = db.query(CoverageScoreSnapshot)
    if summary.source_revision_id is not None:
        query = query.filter(CoverageScoreSnapshot.source_revision_id == summary.source_revision_id)
    else:
        query = query.filter(CoverageScoreSnapshot.article_id == summary.article_id)
    return query.order_by(
        desc(CoverageScoreSnapshot.calculated_at),
        desc(CoverageScoreSnapshot.id),
    ).first()


def _append_score_note(markdown: str, score: Shift6Score) -> str:
    note = render_shift6_score_markdown(score)
    if not note:
        return markdown
    return f"{markdown.rstrip()}\n\n{note}"


@router.post("/summarize")
async def summarize(input: SummarizeIn, db: Session = Depends(get_db)):
    client_name = input.client_name.strip()
    requested_url = str(input.article_url)
    try:
        document = await fetch_or_scrape(requested_url)
        if document.domain:
            cached_metrics = _cached_publication_metrics(db, document.domain)
            outlet_desc, metrics = await asyncio.gather(
                try_fetch_about_description(document.domain),
                lookup_da_muv(document.domain, cached_metrics=cached_metrics),
            )
        else:
            outlet_desc, metrics = None, {}
        mentions, _ = extract_mentions_and_links(client_name, document.body, document.title)
        client_links = extract_client_links(document.links, client_name, requested_url)
        best_quote = find_best_quote(document.body, client_name)

        data = {
            "client_name": client_name,
            "url": requested_url,
            "domain": document.domain,
            "publication": document.publication,
            "title": document.title,
            # Article metadata describes this story, not necessarily the outlet.
            # Keep the publication snapshot explicit when no verified About page exists.
            "outlet_description": outlet_desc,
            "metrics": metrics,
            "mentions": mentions,
            "client_links": client_links,
            "body": document.body,
            "best_quote": best_quote,
        }
        markdown = await summarize_to_markdown(data)
        shift6_score = calculate_shift6_score(metrics)
        markdown = _append_score_note(markdown, shift6_score)
        subject = coverage_subject(requested_url, document.domain, document.title, document.publication)

        article = (
            db.query(Article)
            .filter(Article.client_name == client_name, Article.url == requested_url)
            .first()
        )
        if article is None:
            article = Article(client_name=client_name, url=requested_url)
            db.add(article)
        publication = _get_or_create_publication(
            db,
            document.domain,
            document.publication,
        )
        article.publication_id = publication.id if publication else None
        article.domain = _normalized_domain(document.domain)
        article.publication = document.publication
        article.title = document.title
        article.author = document.author
        article.description = document.description
        article.body = document.body
        article.final_url = document.final_url
        article.canonical_url = document.canonical_url
        article.source_sha256 = document.content_sha256
        article.source_fetched_at = _source_timestamp(document.fetched_at)
        article.source_method = document.source_method
        article.published_at = document.published_date_raw
        article.published_at_utc = document.published_at
        article.published_date_raw = document.published_date_raw
        article.published_date_source = document.published_date_source
        article.published_date_confidence = document.published_date_confidence
        article.published_date_candidates = document.published_date_candidates or []
        db.flush()

        revision = ArticleSourceRevision(
            article_id=article.id,
            requested_url=requested_url,
            final_url=document.final_url,
            canonical_url=document.canonical_url,
            domain=_normalized_domain(document.domain),
            publication=document.publication,
            title=document.title,
            author=document.author,
            description=document.description,
            body=document.body,
            source_sha256=document.content_sha256,
            fetched_at=_source_timestamp(document.fetched_at),
            source_method=document.source_method,
            published_at=document.published_at,
            published_date_raw=document.published_date_raw,
            published_date_source=document.published_date_source,
            published_date_confidence=document.published_date_confidence,
            published_date_candidates=document.published_date_candidates or [],
            links=document.links,
        )
        db.add(revision)
        db.flush()

        _persist_metric_snapshots(
            db,
            metrics=metrics,
            publication=publication,
            article=article,
            revision=revision,
        )

        sentiment = classify_sentiment(document.body)
        summary = ArticleSummary(
            article_id=article.id,
            source_revision_id=revision.id,
            markdown=markdown,
            sentiment=sentiment,
            da=(metrics.get("site_authority") or {}).get("value"),
            muv=(metrics.get("monthly_audience") or {}).get("value"),
            subject=subject,
            metrics=metrics,
            validation_status="source_verified",
        )
        db.add(summary)

        score_inputs = dict(shift6_score.inputs)
        score_inputs["source_revision"] = {
            "id": revision.id,
            "source_sha256": document.content_sha256,
            "fetched_at": document.fetched_at,
            "source_method": document.source_method,
            "requested_url": requested_url,
            "final_url": document.final_url,
        }
        score_snapshot = CoverageScoreSnapshot(
            article_id=article.id,
            source_revision_id=revision.id,
            methodology_version=shift6_score.methodology_version,
            formula_hash=shift6_score.formula_hash,
            status=shift6_score.status,
            total_score=shift6_score.total_score,
            components=shift6_score.components,
            inputs=score_inputs,
        )
        db.add(score_snapshot)
        db.commit()
        db.refresh(article)
        db.refresh(summary)
        db.refresh(score_snapshot)

        # Evidence capture is intentionally nonfatal: the verified report and
        # its immutable source revision remain usable even when a publisher
        # blocks Chromium or a capture times out. Persist pending rows first so
        # the UI and exports can show an honest state while the job runs.
        evidence_payload: dict[str, Any] = {"status": "unavailable", "artifacts": []}
        try:
            evidence_rows = queue_screenshot_capture(
                db,
                article_id=article.id,
                source_revision_id=revision.id,
            )
            db.commit()
            evidence_payload = {
                "status": (
                    "ready"
                    if all(row.status == "ready" for row in evidence_rows)
                    else "pending"
                ),
                "artifacts": [
                    {"id": row.id, "kind": row.kind, "status": row.status}
                    for row in evidence_rows
                ],
            }
            if evidence_payload["status"] != "ready":
                schedule_screenshot_capture(
                    article_id=article.id,
                    source_revision_id=revision.id,
                )
        except Exception:
            db.rollback()
            logger.exception(
                "Screenshot evidence scheduling failed article_id=%s source_revision_id=%s",
                article.id,
                revision.id,
            )

        if document.body:
            try:
                vector = embed_texts([document.body])[0]
                existing = (
                    db.query(ArticleEmbedding)
                    .filter(ArticleEmbedding.article_id == article.id)
                    .first()
                )
                if existing is None:
                    db.add(ArticleEmbedding(article_id=article.id, embedding=vector))
                else:
                    existing.embedding = vector
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Article embedding failed for article_id=%s", article.id)

        return {
            "subject": subject,
            # Keep the email self-contained for browser tabs running an older
            # frontend bundle that does not render the separate subject field.
            "markdown": markdown_with_subject(markdown, subject),
            # Current clients render a dedicated subject row and should not
            # have to parse compatibility content out of the body.
            "body_markdown": markdown_without_subject(markdown),
            "article_id": article.id,
            "summary_id": summary.id,
            "source_revision_id": revision.id,
            "publication_id": publication.id if publication else None,
            "validation_status": summary.validation_status,
            "metrics": metrics,
            "shift6_score": shift6_score.as_dict(),
            "evidence": evidence_payload,
        }
    except (UnsafeUrlError, ResponseTooLargeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SummaryGenerationError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Email summary generation failed")
        raise HTTPException(status_code=502, detail="Unable to generate a verified coverage email") from exc


@router.get("/history")
def history(
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10_000),
    client_name: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    query = (
        db.query(ArticleSummary, Article)
        .join(Article, Article.id == ArticleSummary.article_id)
        .order_by(desc(ArticleSummary.created_at), desc(ArticleSummary.id))
    )
    query = query.filter(Article.client_name == client_name.strip())
    items = []
    for summary, article in query.offset(offset).limit(limit).all():
        score_snapshot = _score_for_summary(db, summary)
        items.append(
            {
                "id": summary.id,
                "article_id": article.id,
                "url": article.url,
                "title": article.title,
                "domain": article.domain,
                "client_name": article.client_name,
                "created_at": summary.created_at.isoformat() if summary.created_at else None,
                "summary_id": summary.id,
                "source_revision_id": summary.source_revision_id,
                "subject": summary.subject,
                "validation_status": summary.validation_status,
                "shift6_score": _score_payload(score_snapshot),
            }
        )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/summary/{summary_id}")
def get_summary(
    summary_id: int,
    client_name: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    row = (
        db.query(ArticleSummary, Article)
        .join(Article, Article.id == ArticleSummary.article_id)
        .filter(ArticleSummary.id == summary_id, Article.client_name == client_name.strip())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="summary_not_found")
    summary, article = row
    score_snapshot = _score_for_summary(db, summary)
    subject = (
        summary.subject or coverage_subject(article.url, article.domain, article.title, article.publication)
        if article
        else "Coverage Live: Publication"
    )
    return {
        "subject": subject,
        "markdown": markdown_with_subject(summary.markdown, subject),
        "body_markdown": markdown_without_subject(summary.markdown),
        "article_id": summary.article_id,
        "summary_id": summary.id,
        "source_revision_id": summary.source_revision_id,
        "validation_status": summary.validation_status,
        "metrics": summary.metrics or {},
        "shift6_score": _score_payload(score_snapshot),
    }


@router.get("/history/search")
def search_history(
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=50),
    client_name: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    query_text = q.strip()
    if not query_text:
        return {"items": []}
    try:
        vector = embed_texts([query_text])[0].tolist()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="embed_failed") from exc

    sql = sql_text(
        """
        SELECT a.id, a.url, a.title, a.domain, a.client_name, s.id AS summary_id,
               s.subject, s.validation_status, s.created_at
        FROM article_embeddings e
        JOIN articles a ON a.id = e.article_id
        JOIN LATERAL (
            SELECT article_summaries.*
            FROM article_summaries
            WHERE article_summaries.article_id = a.id
            ORDER BY article_summaries.created_at DESC, article_summaries.id DESC
            LIMIT 1
        ) s ON TRUE
        WHERE a.client_name = :client_name
        ORDER BY e.embedding <#> :vector
        LIMIT :limit
        """
    )
    params = {"vector": vector, "limit": limit, "client_name": client_name.strip()}
    rows = db.execute(sql, params).mappings().all()
    return {"items": [dict(row) for row in rows], "limit": limit}
