from __future__ import annotations

import os
import hashlib
import re
import httpx
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .scraper import ArticleDocument, get_domain, fetch_article_http
from .exa import fetch_article_via_exa
from .http_safety import ResponseTooLargeError, UnsafeUrlError, safe_get_text, same_source_url
import logging


logger = logging.getLogger("metadata.da_muv")


class SourceVerificationError(ValueError):
    pass


def clean_outlet_description(value: str) -> str:
    """Normalize publisher-authored metadata without inventing new copy."""
    text = " ".join(str(value or "").split()).strip()
    text = re.sub(
        r"([.!?])\s+([a-z])",
        lambda match: f"{match.group(1)} {match.group(2).upper()}",
        text,
    )
    if text and text[-1] not in ".!?":
        text += "."
    return text[:400]

async def lookup_da_via_openpagerank(clean_domain: str) -> str | None:
    """
    Look up a directional site-authority estimate via Open PageRank.
    """
    da: str | None = None
    opr_api_key = os.getenv("OPENPAGERANK_API_KEY", "")
    if not opr_api_key:
        logger.info("OPENPAGERANK_API_KEY is not configured; authority estimate unavailable")
        return None
    logger.info("Attempting Open PageRank lookup for domain=%s", clean_domain)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            # Open PageRank API
            url = "https://openpagerank.com/api/v1.0/getPageRank"
            params = {"domains[]": clean_domain}
            headers = {"API-OPR": opr_api_key}
            logger.debug("Open PageRank request: url=%s params=%s", url, params)
            resp = await client.get(url, params=params, headers=headers)
            logger.info("Open PageRank response: status_code=%s", resp.status_code)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("response") and len(data["response"]) > 0:
                    pr = data["response"][0]
                    # page_rank_decimal is 0-10, convert to 0-100 scale like DA
                    if pr.get("page_rank_decimal") is not None:
                        page_rank_decimal = pr["page_rank_decimal"]
                        da = str(int(float(page_rank_decimal) * 10))
                        logger.info("DA found via Open PageRank: page_rank_decimal=%s da=%s", page_rank_decimal, da)
                    elif pr.get("rank"):
                        # Use rank as fallback indicator
                        rank = pr["rank"]
                        da = f"Rank: {rank}"
                        logger.info("DA found via Open PageRank (rank fallback): rank=%s da=%s", rank, da)
                    else:
                        logger.warning("Open PageRank returned result but no page_rank_decimal or rank: %s", pr)
                else:
                    logger.warning("Open PageRank response missing or empty: response=%s", data.get("response"))
            else:
                logger.error("Open PageRank request failed: status_code=%s", resp.status_code)
    except Exception as e:
        logger.exception("Open PageRank exception for domain=%s: %s", clean_domain, e)
    return da


async def try_fetch_about_description(domain: str) -> str | None:
    """Attempt to fetch a description from the outlet's about page."""
    base = f"https://{domain}"
    candidates = ["/about", "/about-us", "/company/about"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base,
    }
    for path in candidates:
        try:
            candidate_url = urljoin(base, path)
            resp = await safe_get_text(
                candidate_url, headers=headers, timeout_seconds=15, max_bytes=512 * 1024
            )
            # Some publishers redirect missing "about" routes to unrelated pages. Only
            # accept content from the exact candidate route we requested.
            if not same_source_url(candidate_url, resp.final_url):
                logger.info(
                    "Ignoring redirected about-page candidate requested=%s final=%s",
                    candidate_url,
                    resp.final_url,
                )
                continue
            if resp.status_code == 200 and "text/html" in (resp.headers.get("content-type") or ""):
                soup = BeautifulSoup(resp.text, "html.parser")
                og = soup.find("meta", attrs={"property": "og:description"})
                if og and og.get("content"):
                    return clean_outlet_description(str(og["content"]))
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    return clean_outlet_description(str(meta_desc["content"]))
                for paragraph in soup.find_all("p"):
                    text = paragraph.get_text(" ", strip=True)
                    if len(text) > 50:
                        return clean_outlet_description(text)
        except Exception:
            continue
    return None


async def lookup_da_muv(domain: str) -> dict:
    """
    Return publication metrics with explicit provenance and confidence.
    """
    clean_domain = domain.lower().replace("www.", "")
    observed_at = datetime.now(timezone.utc).date().isoformat()
    authority = await lookup_da_via_openpagerank(clean_domain)
    metrics = {
        "site_authority": {
            "label": "Site authority estimate",
            "value": f"{authority}/100" if authority and authority.isdigit() else "Unavailable",
            "source": "Open PageRank" if authority else "No verified authority source",
            "method": "page_rank_decimal × 10; directional estimate, not Moz Domain Authority" if authority else "Not estimated when the configured source is unavailable",
            "confidence": "medium" if authority else "low",
            "estimated": True,
            "observed_at": observed_at,
        },
        "monthly_audience": {
            "label": "Monthly audience estimate",
            "value": "Unavailable",
            "source": "No verified traffic source",
            "method": "Not estimated when visits or unique-visitor evidence cannot be verified",
            "confidence": "low",
            "estimated": False,
            "observed_at": observed_at,
        },
    }
    logger.info("publication metrics prepared for domain=%s authority_available=%s", clean_domain, bool(authority))
    return metrics


async def fetch_or_scrape(url: str) -> ArticleDocument:
    direct_error: Exception | None = None
    try:
        document = await fetch_article_http(url)
        if not same_source_url(url, document.final_url):
            raise SourceVerificationError("Fetched page redirected to a different article URL")
        if document.canonical_url and not (
            same_source_url(url, document.canonical_url)
            or same_source_url(document.final_url, document.canonical_url)
        ):
            raise SourceVerificationError("Fetched page declares a different canonical article URL")
        return document
    except (UnsafeUrlError, ResponseTooLargeError, SourceVerificationError):
        raise
    except Exception as exc:
        direct_error = exc

    exact = await fetch_article_via_exa(url)
    if exact:
        title, desc, body, result_url = exact
        return ArticleDocument(
            requested_url=url,
            final_url=result_url,
            canonical_url=result_url,
            domain=get_domain(result_url),
            publication=None,
            title=title,
            description=desc,
            body=body or "",
            links=[],
            fetched_at=datetime.now(timezone.utc).isoformat(),
            content_sha256=hashlib.sha256((body or "").encode("utf-8")).hexdigest(),
            source_method="exa_exact_url",
        )
    raise ValueError(f"Unable to verify the submitted article source: {type(direct_error).__name__}")
