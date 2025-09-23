from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session
from ..deps import get_db_dep as get_db  # fix import path; provide Session
from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
from ....models import Article, ArticleSummary, ArticleEmbedding
from ....embedding import embed_texts
from sqlalchemy import text as sql_text
from ....services.email.metadata import fetch_or_scrape, try_fetch_about_description, lookup_da_muv
from ....services.email.nlp import extract_mentions_and_links, find_best_quote, classify_sentiment, extract_client_links, approximate_substring
from ....services.email.summarizer import summarize_to_markdown

router = APIRouter(prefix="/email", tags=["Email"])


class SummarizeIn(BaseModel):
    client_name: str
    article_url: HttpUrl


@router.get("/health")
def email_health():
    return {"status": "ok"}


@router.post("/summarize")
async def summarize(input: SummarizeIn, db: Session = Depends(get_db)):
    try:
        title, desc, body, domain = await fetch_or_scrape(str(input.article_url))
        outlet_desc = await try_fetch_about_description(domain) if domain else None
        da, muv = await lookup_da_muv(domain) if domain else (None, None)
        mentions, links = extract_mentions_and_links(input.client_name, body or "")
        client_links = extract_client_links(links, input.client_name)
        best_quote = find_best_quote(body or "", input.client_name)
        # If quote not found but the article contains attributed speech without quotes, attempt approximate match using LLM output
        if not best_quote:
            # Ask the LLM to propose a short candidate sentence, then align approximately to body
            candidate_prompt = {
                "client_name": input.client_name,
                "body_excerpt": (body or "")[:1500],
            }
            # cheap heuristic: pick sentence with attribution verbs mentioning client tokens
            best_quote = None
            try:
                # try to find a plausible sentence using regex heuristics
                tokens = [t for t in (input.client_name or "").split() if len(t) > 2]
                pattern = r"([^\.!?]{10,300}?(?:said|stated|told|according to|noted|explained)[^\.!?]{0,200})"
                for m in re.finditer(pattern, body or "", flags=re.IGNORECASE):
                    sent = m.group(1)
                    if any(t.lower() in sent.lower() for t in tokens):
                        best_quote = sent.strip()
                        break
            except Exception:
                best_quote = None

        data = {
            "client_name": input.client_name,
            "url": str(input.article_url),
            "domain": domain,
            "title": title,
            "outlet_description": outlet_desc or desc,
            "da": da,
            "muv": muv,
            "mentions": mentions,
            "links": links,
            "client_links": client_links,
            "body": body,
            "best_quote": best_quote,
        }
        md = await summarize_to_markdown(data)

        # persist (get-or-create by URL)
        url_str = str(input.article_url)
        article = db.query(Article).filter(Article.url == url_str).first()
        if article is None:
            article = Article(
                client_name=input.client_name,
                url=url_str,
                domain=domain,
                title=title,
                description=desc,
                body=body,
            )
            db.add(article)
            db.commit()
            db.refresh(article)
        else:
            # update basic fields if newly available
            if not article.title and title:
                article.title = title
            if not article.description and desc:
                article.description = desc
            if not article.body and body:
                article.body = body
            if not article.domain and domain:
                article.domain = domain
            db.add(article)
            db.commit()

        sentiment = classify_sentiment((body or "") + "\n" + (md or ""))
        summary = ArticleSummary(article_id=article.id, markdown=md, sentiment=sentiment, da=da or None, muv=muv or None)
        db.add(summary)
        db.commit()

        # embed body if available
        if body:
            try:
                vec = embed_texts([body])[0]
                existing = db.query(ArticleEmbedding).filter(ArticleEmbedding.article_id == article.id).first()
                if existing is None:
                    db.add(ArticleEmbedding(article_id=article.id, embedding=vec))
                    db.commit()
            except Exception:
                pass

        return {"markdown": md, "article_id": article.id, "summary_id": summary.id}
    except Exception as e:
        # Always return JSON so the frontend can parse errors
        raise HTTPException(status_code=502, detail=f"summarize_failed: {type(e).__name__}: {str(e)[:180]}")


@router.get("/history")
def history(limit: int = 5, offset: int = 0, db: Session = Depends(get_db)):
    # Latest-first list of articles with optional attached summary id
    # cap to last 5 items
    limit = max(1, min(limit, 5))
    q = (
        db.query(Article, ArticleSummary.id.label("summary_id"))
        .outerjoin(ArticleSummary, ArticleSummary.article_id == Article.id)
        .order_by(desc(Article.created_at))
        .offset(offset)
        .limit(limit)
    )
    items = []
    for a, sid in q.all():
        items.append({
            "id": a.id,
            "url": a.url,
            "title": a.title,
            "domain": a.domain,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "summary_id": sid,
        })
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/summary/{summary_id}")
def get_summary(summary_id: int, db: Session = Depends(get_db)):
    s = db.query(ArticleSummary).filter(ArticleSummary.id == summary_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="summary_not_found")
    return {"markdown": s.markdown, "article_id": s.article_id, "summary_id": s.id}


@router.get("/history/search")
def search_history(q: str, limit: int = 10, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 50))
    q = (q or "").strip()
    if not q:
        return {"items": []}
    try:
        vec = embed_texts([q])[0].tolist()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"embed_failed: {type(e).__name__}")
    # Use pgvector cosine distance operator <#>
    sql = sql_text(
        """
        SELECT a.id, a.url, a.title, a.domain, s.id AS summary_id
        FROM article_embeddings e
        JOIN articles a ON a.id = e.article_id
        LEFT JOIN article_summaries s ON s.article_id = a.id
        ORDER BY e.embedding <#> :v
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"v": vec, "lim": limit}).mappings().all()
    return {"items": [dict(r) for r in rows], "limit": limit}


