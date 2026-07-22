from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ...models import Hit, Quote
from ..email.metadata import fetch_or_scrape
from .emailer import deliver_hit_email
from .exa import exa_search
from .matching import (
    adjudicate_with_claude,
    cosine_similarity,
    embed,
    has_client_name,
    has_normalized_exact_quote,
    jaccard_similarity,
    shingles as make_shingles,
    tokenize_words,
)


def _normalize_domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def _sentences(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _build_queries(client_name: str, quote_text: str) -> List[str]:
    queries = [f'"{quote_text}" AND {client_name}']
    words = tokenize_words(quote_text)
    quote_shingles = make_shingles(words, size=8) or make_shingles(words, size=7)
    queries.extend(f'"{shingle}" AND {client_name}' for shingle in quote_shingles[:3])
    queries.append(client_name)
    return queries


def _coverage_markdown(q: Quote, url: str, title: str, domain: str | None, match_type: str, snippet: str) -> str:
    def escape(value: str) -> str:
        return re.sub(r"([\\`*_{}\[\]()#+|>])", r"\\\1", re.sub(r"\s+", " ", value).strip())

    safe_title = escape(title or "Coverage")
    safe_domain = escape(domain or "Publication")
    safe_client = escape(q.client_name)
    safe_snippet = escape(snippet)[:800]
    return (
        f"{safe_domain} — [{safe_title}]({url})\n\n"
        "## Verified Coverage Match\n\n"
        f"- Client: {safe_client}\n"
        f"- Match type: {match_type}\n"
        "- Source status: Re-fetched and verified before persistence\n\n"
        "## Matched Source Text\n\n"
        f"> {safe_snippet}\n"
    )


async def _evaluate_candidate(
    db: Session,
    q: Quote,
    candidate: dict,
    quote_vec: Optional[object],
) -> Optional[Hit]:
    candidate_url = str(candidate.get("url") or "").strip()
    if not candidate_url:
        return None
    try:
        document = await fetch_or_scrape(candidate_url)
    except Exception:
        return None

    source_text = document.body
    title = document.title or str(candidate.get("title") or "")
    if not source_text or not has_client_name(q.client_name, f"{title}\n{source_text}"):
        return None

    best_sentence = max(_sentences(source_text), key=lambda sentence: jaccard_similarity(q.quote_text, sentence), default="")
    if has_normalized_exact_quote(q.quote_text, source_text):
        match_type = "exact"
        confidence = 1.0
        matched_text = next(
            (sentence for sentence in _sentences(source_text) if has_normalized_exact_quote(q.quote_text, sentence)),
            q.quote_text,
        )
    else:
        best_jaccard = jaccard_similarity(q.quote_text, best_sentence)
        cosine_value = 0.0
        if quote_vec is not None and best_sentence:
            try:
                cosine_value = cosine_similarity(quote_vec, embed(best_sentence))
            except Exception:
                cosine_value = 0.0
        if best_jaccard < 0.6 and cosine_value < 0.78:
            return None
        ok, model_type, model_confidence, _model_text = await adjudicate_with_claude(
            q.client_name, q.quote_text, best_sentence
        )
        if not ok or model_confidence < 0.7 or model_type not in {"partial", "paraphrase"}:
            return None
        match_type = model_type
        confidence = model_confidence
        matched_text = best_sentence

    verified_url = document.final_url
    existing = db.query(Hit).filter(Hit.quote_id == q.id, Hit.url == verified_url).first()
    if existing:
        return None
    domain = document.domain or _normalize_domain(verified_url)
    hit = Hit(
        quote_id=q.id,
        client_name=q.client_name,
        url=verified_url,
        domain=domain,
        title=title,
        snippet=matched_text[:800],
        published_at=None,
        match_type=match_type,
        confidence=confidence,
        markdown=_coverage_markdown(q, verified_url, title, domain, match_type, matched_text),
        source_verified=True,
        source_sha256=document.content_sha256,
        email_delivery_status="pending",
    )
    db.add(hit)
    return hit


def _compute_next(state: str, first_hit_at: Optional[datetime], days_without_hit: int) -> datetime:
    now = datetime.now(timezone.utc)
    if state == "ACTIVE_HOURLY":
        return now + timedelta(hours=1)
    if state == "ACTIVE_DAILY_7D":
        if first_hit_at and (now - first_hit_at).days >= 7:
            return now + timedelta(days=90)
        return now + timedelta(days=1)
    if state == "ACTIVE_QUARTERLY":
        return now + timedelta(days=90)
    if state == "EXPIRED_WEEKLY":
        return now + timedelta(days=7)
    return now + timedelta(hours=6)


async def run_for_quote(db: Session, q: Quote) -> bool:
    try:
        quote_vec = embed(q.quote_text)
    except Exception:
        quote_vec = None
    hit: Hit | None = None
    for query in _build_queries(q.client_name, q.quote_text):
        for candidate in await exa_search(query, num_results=10):
            hit = await _evaluate_candidate(db, q, candidate, quote_vec)
            if hit:
                break
        if hit:
            break

    now = datetime.now(timezone.utc)
    q.last_checked_at = now
    if hit:
        if not q.first_hit_at:
            q.first_hit_at = now
            q.state = "ACTIVE_DAILY_7D"
        q.last_hit_at = now
        q.hit_count = (q.hit_count or 0) + 1
        q.days_without_hit = 0
    else:
        q.days_without_hit = (q.days_without_hit or 0) + 1
        if q.days_without_hit >= 90:
            q.state = "EXPIRED_WEEKLY"
    q.next_run_at = _compute_next(q.state, q.first_hit_at, q.days_without_hit or 0)
    db.commit()

    # The hit and its unique source identity are durable before any external send.
    if hit:
        db.refresh(hit)
        deliver_hit_email(db, hit)
    return hit is not None


async def run_due(db: Session, limit: int = 20) -> int:
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(minutes=15)
    due = (
        db.query(Quote)
        .filter((Quote.next_run_at.is_(None)) | (Quote.next_run_at <= now))
        .order_by(Quote.next_run_at.nullsfirst())
        .with_for_update(skip_locked=True)
        .limit(max(1, min(limit, 50)))
        .all()
    )
    claimed_ids = [quote.id for quote in due]
    for quote in due:
        quote.next_run_at = lease_until
    db.commit()

    processed = 0
    for quote_id in claimed_ids:
        quote = db.get(Quote, quote_id)
        if not quote:
            continue
        try:
            await run_for_quote(db, quote)
            processed += 1
        except Exception:
            db.rollback()
            quote = db.get(Quote, quote_id)
            if quote:
                quote.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=15)
                db.commit()
    return processed
