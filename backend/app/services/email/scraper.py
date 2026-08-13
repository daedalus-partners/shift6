from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
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
    author: str | None = None
    published_at: datetime | None = None
    published_date_raw: str | None = None
    published_date_source: str | None = None
    published_date_confidence: str | None = None
    published_date_candidates: list[dict[str, str | None]] | None = None


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
    author: str | None = None
    published_at: datetime | None = None
    published_date_raw: str | None = None
    published_date_source: str | None = None
    published_date_confidence: str | None = None
    published_date_candidates: list[dict[str, str | None]] | None = None


ARTICLE_SCHEMA_TYPES = {
    "article",
    "advertisercontentarticle",
    "analysisnewsarticle",
    "askpublicnewsarticle",
    "backgroundnewsarticle",
    "blogposting",
    "newsarticle",
    "opinionnewsarticle",
    "report",
    "reportagenewsarticle",
    "reviewnewsarticle",
    "scholarlyarticle",
    "satiricalarticle",
    "techarticle",
    "webpage",
}
ARTICLE_CONTENT_SCHEMA_TYPES = ARTICLE_SCHEMA_TYPES - {"webpage"}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def parse_publication_datetime(raw: object) -> tuple[datetime | None, str]:
    """Parse a publication timestamp without discarding timezone uncertainty."""
    value = " ".join(str(raw or "").split()).strip()
    if not value:
        return None, "low"

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return None, "low"
        return datetime.combine(day, time.min, tzinfo=timezone.utc), "medium"

    normalized = re.sub(r"\s+UTC$", "+00:00", value, flags=re.IGNORECASE)
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None, "low"

    confidence = "high"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        # Preserve the raw source value and explicitly lower confidence rather
        # than pretending a publisher-local timestamp carried a timezone.
        parsed = parsed.replace(tzinfo=timezone.utc)
        confidence = "medium"
    return parsed.astimezone(timezone.utc), confidence


def publication_date_candidate(
    raw: object,
    source: str,
    source_confidence: str,
) -> dict[str, str | None] | None:
    raw_text = " ".join(str(raw or "").split()).strip()
    if not raw_text:
        return None
    published_at, parse_confidence = parse_publication_datetime(raw_text)
    confidence = min(
        (source_confidence, parse_confidence),
        key=lambda value: CONFIDENCE_ORDER.get(value, 0),
    )
    return {
        "raw": raw_text[:256],
        "source": source,
        "confidence": confidence,
        "published_at": published_at.isoformat() if published_at else None,
    }


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


def _schema_types(node: dict[str, Any]) -> set[str]:
    raw_types = node.get("@type")
    if not isinstance(raw_types, list):
        raw_types = [raw_types]
    return {str(value).rsplit("/", 1)[-1].lower() for value in raw_types if value}


def _json_ld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        content_type = str(script.get("type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/ld+json":
            continue
        raw = script.string or script.get_text("", strip=True)
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        nodes.extend(_walk_json(payload))
    return nodes


def _iter_date_values(value: Any) -> Iterable[object]:
    if isinstance(value, list):
        yield from value
    elif value is not None:
        yield value


def _author_names(value: Any) -> list[str]:
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_author_names(item))
        return names
    if isinstance(value, dict):
        return _author_names(value.get("name"))
    if isinstance(value, str):
        name = " ".join(value.split()).strip()
        return [name] if name and not name.startswith(("http://", "https://")) else []
    return []


def _extract_author(soup: BeautifulSoup, json_nodes: list[dict[str, Any]]) -> str | None:
    content_nodes = [
        node for node in json_nodes if _schema_types(node) & ARTICLE_CONTENT_SCHEMA_TYPES
    ]
    page_nodes = [node for node in json_nodes if "webpage" in _schema_types(node)]
    remaining_nodes = [
        node for node in json_nodes if node not in content_nodes and node not in page_nodes
    ]
    for node in [*content_nodes, *page_nodes, *remaining_nodes]:
        names = list(dict.fromkeys(_author_names(node.get("author"))))
        if names:
            return ", ".join(names)[:256]

    for meta in soup.find_all("meta"):
        key = str(meta.get("name") or meta.get("property") or "").strip().lower()
        if key not in {"author", "article:author", "byl"}:
            continue
        value = " ".join(str(meta.get("content") or "").split()).strip()
        if value and not value.startswith(("http://", "https://")):
            return value[:256]
    return None


def _article_time_rank(tag: Any) -> int | None:
    markers = " ".join(
        [
            str(tag.get("itemprop") or ""),
            str(tag.get("class") or ""),
            str(tag.get("id") or ""),
            str(tag.get("data-testid") or ""),
        ]
    ).replace("-", "").replace("_", "").lower()
    if "datepublished" in markers or "publish" in markers:
        return 0
    if "datemodified" in markers or "modified" in markers or "updated" in markers:
        return None
    return 1


def _extract_publication_dates(
    soup: BeautifulSoup,
    json_nodes: list[dict[str, Any]],
) -> tuple[
    datetime | None,
    str | None,
    str | None,
    str | None,
    list[dict[str, str | None]],
]:
    candidates: list[dict[str, str | None]] = []
    content_nodes = [
        node for node in json_nodes if _schema_types(node) & ARTICLE_CONTENT_SCHEMA_TYPES
    ]
    page_nodes = [node for node in json_nodes if "webpage" in _schema_types(node)]
    dated_fallbacks = [
        node
        for node in json_nodes
        if node not in content_nodes
        and node not in page_nodes
        and node.get("datePublished") is not None
    ]
    for node in [*content_nodes, *page_nodes, *dated_fallbacks]:
        for value in _iter_date_values(node.get("datePublished")):
            candidate = publication_date_candidate(value, "json_ld.datePublished", "high")
            if candidate:
                candidates.append(candidate)

    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").strip().lower()
        if key != "article:published_time":
            continue
        candidate = publication_date_candidate(
            meta.get("content"),
            "meta.article:published_time",
            "high",
        )
        if candidate:
            candidates.append(candidate)

    article = soup.find("article")
    if article:
        ranked_time_tags = [
            (rank, index, tag)
            for index, tag in enumerate(article.find_all("time"))
            if (rank := _article_time_rank(tag)) is not None
        ]
        time_tags = [tag for _rank, _index, tag in sorted(ranked_time_tags)]
        for tag in time_tags:
            raw = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
            candidate = publication_date_candidate(raw, "article.time", "medium")
            if candidate:
                candidates.append(candidate)

    deduplicated: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for candidate in candidates:
        key = (candidate.get("source"), candidate.get("raw"))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)

    selected = next(
        (candidate for candidate in deduplicated if candidate.get("published_at")),
        None,
    )
    if not selected:
        return None, None, None, None, deduplicated
    parsed, _ = parse_publication_datetime(selected["published_at"])
    return (
        parsed,
        selected.get("raw"),
        selected.get("source"),
        selected.get("confidence"),
        deduplicated,
    )


def parse_article_html(html: str, base_url: str) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")
    json_nodes = _json_ld_nodes(soup)
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
    published_at, date_raw, date_source, date_confidence, date_candidates = (
        _extract_publication_dates(soup, json_nodes)
    )
    return ParsedArticle(
        title=title,
        publication=publication,
        description=desc,
        body=body_text,
        links=links,
        canonical_url=canonical_url,
        author=_extract_author(soup, json_nodes),
        published_at=published_at,
        published_date_raw=date_raw,
        published_date_source=date_source,
        published_date_confidence=date_confidence,
        published_date_candidates=date_candidates,
    )


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
        author=parsed.author,
        published_at=parsed.published_at,
        published_date_raw=parsed.published_date_raw,
        published_date_source=parsed.published_date_source,
        published_date_confidence=parsed.published_date_confidence,
        published_date_candidates=parsed.published_date_candidates,
    )


def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()
