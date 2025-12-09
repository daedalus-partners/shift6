from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ...models import Quote, Hit
from .exa import exa_search, fetch_article_text
from .matching import (
    tokenize_words,
    shingles as make_shingles,
    jaccard_similarity,
    embed,
    cosine_similarity,
    adjudicate_with_claude,
)
from ...services.email.summarizer import summarize_to_markdown
from .emailer import send_hit_email


def _normalize_domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def _sentences(text: str) -> List[str]:
    out: List[str] = []
    buf: List[str] = []
    for ch in text:
        buf.append(ch)
        if ch in ".!?\n":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    if buf:
        s = "".join(buf).strip()
        if s:
            out.append(s)
    return out


def _build_queries(client_name: str, quote_text: str) -> List[str]:
    queries: List[str] = []
    # 1) exact quote
    exact = f'"{quote_text}" AND {client_name}'
    queries.append(exact)
    # 2) shingles (two of them)
    words = tokenize_words(quote_text)
    sh = make_shingles(words, size=8) or make_shingles(words, size=7)
    for s in sh[:3]:
        queries.append(f'"{s}" AND {client_name}')
    # 3) client only (fresh)
    queries.append(client_name)
    return queries


async def _evaluate_candidate(
    db: Session,
    q: Quote,
    candidate: dict,
    quote_vec: Optional[object],
) -> Optional[Hit]:
    url = candidate.get("url") or ""
    title = candidate.get("title") or ""
    text = candidate.get("text") or candidate.get("description") or ""
    domain = _normalize_domain(url) or None

    if not url or not text:
        return None

    # must contain client_name
    if q.client_name.lower() not in (text.lower() + " " + title.lower()):
        return None

    # exact substring
    match_type = None
    confidence = 1.0 if q.quote_text in text else None
    if confidence:
        match_type = "exact"
    else:
        # compute best sentence similarity
        best_sentence = None
        best_jaccard = 0.0
        for s in _sentences(text):
            jac = jaccard_similarity(q.quote_text, s)
            if jac > best_jaccard:
                best_jaccard = jac
                best_sentence = s
        cosine_val = 0.0
        if quote_vec is not None and best_sentence:
            try:
                s_vec = embed(best_sentence)
                cosine_val = cosine_similarity(quote_vec, s_vec)
            except Exception:
                cosine_val = 0.0
        tentative = best_jaccard >= 0.6 or cosine_val >= 0.78
        if tentative:
            # Adjudicate with Claude
            ok, typ, conf, matched = await adjudicate_with_claude(
                q.client_name, q.quote_text, best_sentence or text[:800]
            )
            if ok and conf >= 0.7:
                match_type = typ
                confidence = conf
        else:
            return None

    if not match_type:
        return None

    # Check duplicate URL
    existing = db.query(Hit).filter(Hit.url == url).first()
    if existing:
        return None

    # Summarize markdown (best effort)
    md = await summarize_to_markdown(
        {
            "client_name": q.client_name,
            "url": url,
            "domain": domain,
            "title": title,
            "body": text[:4000],
            "best_quote": q.quote_text if match_type == "exact" else None,
        }
    )

    hit = Hit(
        quote_id=q.id,
        client_name=q.client_name,
        url=url,
        domain=domain,
        title=title,
        snippet=text[:400],
        published_at=None,
        match_type=match_type,
        confidence=confidence,
        markdown=md,
    )
    db.add(hit)
    # Attempt email (settings-driven); mark emailed_at only if sent
    if send_hit_email(db, hit):
        hit.emailed_at = datetime.now(timezone.utc)
    return hit


def _compute_next(state: str, first_hit_at: Optional[datetime], days_without_hit: int) -> datetime:
    now = datetime.now(timezone.utc)
    if state == "ACTIVE_HOURLY":
        return now + timedelta(hours=1)
    if state == "ACTIVE_DAILY_7D":
        # after 7 days since first_hit -> quarterly
        if first_hit_at and (now - first_hit_at).days >= 7:
            return now + timedelta(days=90)
        return now + timedelta(days=1)
    if state == "ACTIVE_QUARTERLY":
        return now + timedelta(days=90)
    if state == "EXPIRED_WEEKLY":
        return now + timedelta(days=7)
    return now + timedelta(hours=6)


async def run_for_quote(db: Session, q: Quote) -> bool:
    # ensure embedding
    quote_vec = None
    try:
        quote_vec = embed(q.quote_text)
    except Exception:
        quote_vec = None

    queries = _build_queries(q.client_name, q.quote_text)
    found = False

    for query in queries:
        results = await exa_search(query, num_results=5)
        for cand in results:
            hit = await _evaluate_candidate(db, q, cand, quote_vec)
            if hit:
                # finalize hit and update quote
                now = datetime.now(timezone.utc)
                if not q.first_hit_at:
                    q.first_hit_at = now
                    q.state = "ACTIVE_DAILY_7D"
                q.last_hit_at = now
                q.hit_count = (q.hit_count or 0) + 1
                q.days_without_hit = 0
                found = True
                break
        if found:
            break

    if not found:
        # bump days_without_hit; consider expiry after 90 days without hits
        q.days_without_hit = (q.days_without_hit or 0) + 1
        if (q.days_without_hit or 0) >= 90:
            q.state = "EXPIRED_WEEKLY"

    # schedule next run
    q.next_run_at = _compute_next(q.state, q.first_hit_at, q.days_without_hit or 0)
    return found


async def run_due(db: Session, limit: int = 20) -> int:
    now = datetime.now(timezone.utc)
    due: List[Quote] = (
        db.query(Quote)
        .filter((Quote.next_run_at == None) | (Quote.next_run_at <= now))  # noqa: E711
        .order_by(Quote.next_run_at.nullsfirst())
        .limit(limit)
        .all()
    )
    processed = 0
    for q in due:
        processed += 1
        await run_for_quote(db, q)
        db.commit()
    return processed
