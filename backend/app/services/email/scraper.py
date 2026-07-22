from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup  # lightweight parser; install via backend requirements if missing
from .polite import is_allowed, rate_limit, cached_get


@dataclass(frozen=True)
class ParsedArticle:
    title: str | None
    publication: str | None
    description: str | None
    body: str
    links: list[dict[str, str]]
    canonical_url: str | None


@dataclass(frozen=True)
class ArticleDocument:
    requested_url: str
    final_url: str
    canonical_url: str | None
    domain: str
    publication: str | None
    title: str | None
    description: str | None
    body: str
    links: list[dict[str, str]]
    fetched_at: str
    content_sha256: str
    source_method: str


def parse_article_html(html: str, base_url: str) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else None
    publication = None
    site_name = soup.find("meta", attrs={"property": "og:site_name"})
    if site_name and site_name.get("content"):
        publication = str(site_name["content"]).strip()[:128]
    if not publication:
        app_name = soup.find("meta", attrs={"name": "application-name"})
        if app_name and app_name.get("content"):
            publication = str(app_name["content"]).strip()[:128]
    desc = None
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        desc = str(og["content"]).strip()
    if not desc:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            desc = str(meta["content"]).strip()

    canonical_url = None
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        canonical_url = urljoin(base_url, str(canonical["href"]).strip())

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        resolved = urljoin(base_url, str(anchor["href"]).strip())
        if not resolved.startswith(("http://", "https://")) or resolved in seen:
            continue
        seen.add(resolved)
        links.append({"text": anchor.get_text(" ", strip=True)[:240], "url": resolved})
        if len(links) >= 100:
            break

    content_tags = ["p", "blockquote", "q", "h1", "h2", "h3", "h4", "li"]
    parts = [node.get_text(" ", strip=True) for node in soup.find_all(content_tags)]
    body_text = "\n".join(part for part in parts if part)
    return ParsedArticle(title, publication, desc, body_text, links, canonical_url)


async def fetch_article_http(url: str) -> ArticleDocument:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }
    # robots and rate limit
    if not await is_allowed(url):
        raise httpx.HTTPStatusError("Disallowed by robots.txt", request=None, response=None)  # type: ignore[arg-type]
    await rate_limit(url)
    status, html, final_url, content_type = await cached_get(url, headers=headers)
    if status != 200:
        raise httpx.HTTPStatusError(f"status={status}", request=None, response=None)  # type: ignore[arg-type]
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("Submitted URL did not return an HTML article")
    
    parsed = parse_article_html(html, final_url)
    if not parsed.body:
        raise ValueError("Article page did not contain extractable text")
    return ArticleDocument(
        requested_url=url,
        final_url=final_url,
        canonical_url=parsed.canonical_url,
        domain=get_domain(final_url),
        publication=parsed.publication,
        title=parsed.title,
        description=parsed.description,
        body=parsed.body,
        links=parsed.links,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        content_sha256=hashlib.sha256(parsed.body.encode("utf-8")).hexdigest(),
        source_method="direct_http",
    )


def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()
