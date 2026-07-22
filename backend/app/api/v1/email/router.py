from __future__ import annotations

import logging
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import desc, text as sql_text
from sqlalchemy.orm import Session

from ..deps import get_db_dep as get_db
from ....embedding import embed_texts
from ....models import Article, ArticleEmbedding, ArticleSummary
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


@router.post("/summarize")
async def summarize(input: SummarizeIn, db: Session = Depends(get_db)):
    client_name = input.client_name.strip()
    requested_url = str(input.article_url)
    try:
        document = await fetch_or_scrape(requested_url)
        if document.domain:
            outlet_desc, metrics = await asyncio.gather(
                try_fetch_about_description(document.domain), lookup_da_muv(document.domain)
            )
        else:
            outlet_desc, metrics = None, {}
        mentions, _ = extract_mentions_and_links(client_name, document.body)
        client_links = extract_client_links(document.links, client_name)
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
        subject = coverage_subject(requested_url, document.domain, document.title, document.publication)

        article = (
            db.query(Article)
            .filter(Article.client_name == client_name, Article.url == requested_url)
            .first()
        )
        if article is None:
            article = Article(client_name=client_name, url=requested_url)
            db.add(article)
        article.domain = document.domain
        article.publication = document.publication
        article.title = document.title
        article.description = document.description
        article.body = document.body
        article.final_url = document.final_url
        article.canonical_url = document.canonical_url
        article.source_sha256 = document.content_sha256
        article.source_fetched_at = _source_timestamp(document.fetched_at)
        article.source_method = document.source_method
        db.flush()

        sentiment = classify_sentiment(document.body)
        summary = ArticleSummary(
            article_id=article.id,
            markdown=markdown,
            sentiment=sentiment,
            da=(metrics.get("site_authority") or {}).get("value"),
            muv=(metrics.get("monthly_audience") or {}).get("value"),
            subject=subject,
            metrics=metrics,
            validation_status="source_verified",
        )
        db.add(summary)
        db.commit()
        db.refresh(article)
        db.refresh(summary)

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
            "validation_status": summary.validation_status,
            "metrics": metrics,
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
                "subject": summary.subject,
                "validation_status": summary.validation_status,
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
        "validation_status": summary.validation_status,
        "metrics": summary.metrics or {},
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
