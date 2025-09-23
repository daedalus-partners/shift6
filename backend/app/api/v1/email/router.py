from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session
from ..deps import get_db_dep as get_db  # fix import path; provide Session
from fastapi import Depends
from sqlalchemy.orm import Session
from ....models import Article, ArticleSummary
from ....services.email.metadata import fetch_or_scrape, try_fetch_about_description, lookup_da_muv
from ....services.email.nlp import extract_mentions_and_links
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
            "body": body,
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

        summary = ArticleSummary(article_id=article.id, markdown=md, sentiment=None, da=da or None, muv=muv or None)
        db.add(summary)
        db.commit()

        return {"markdown": md, "article_id": article.id, "summary_id": summary.id}
    except Exception as e:
        # Always return JSON so the frontend can parse errors
        raise HTTPException(status_code=502, detail=f"summarize_failed: {type(e).__name__}: {str(e)[:180]}")


@router.get("/history")
def history(q: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    # TODO: implement pgvector similarity search; return latest for now
    return {"items": [], "query": q or ""}


