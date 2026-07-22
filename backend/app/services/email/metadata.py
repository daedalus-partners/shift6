from __future__ import annotations

import os
import hashlib
import base64
import math
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

def _moz_authorization_header() -> str | None:
    """Build the Moz v2 Basic authorization header without logging credentials."""
    token = os.getenv("MOZ_API_TOKEN", "").strip()
    if token:
        return token if token.lower().startswith("basic ") else f"Basic {token}"

    access_id = os.getenv("MOZ_ACCESS_ID", "").strip()
    secret_key = os.getenv("MOZ_SECRET_KEY", "").strip()
    if not access_id or not secret_key:
        return None
    encoded = base64.b64encode(f"{access_id}:{secret_key}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


async def lookup_domain_authority_via_moz(clean_domain: str) -> int | None:
    """Return Moz's URL Metrics domain_authority score for a publication domain."""
    authorization = _moz_authorization_header()
    if not authorization:
        logger.info("Moz API credentials are not configured; Moz Domain Authority unavailable")
        return None

    logger.info("Attempting Moz v2 URL Metrics lookup for domain=%s", clean_domain)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
            response = await client.post(
                "https://lsapi.seomoz.com/v2/url_metrics",
                headers={"Authorization": authorization, "Content-Type": "application/json"},
                json={"targets": [clean_domain]},
            )
        if response.status_code != 200:
            logger.error("Moz v2 request failed: status_code=%s", response.status_code)
            return None

        results = response.json().get("results") or []
        if not results:
            logger.warning("Moz v2 returned no URL Metrics results for domain=%s", clean_domain)
            return None
        raw_value = results[0].get("domain_authority")
        if raw_value is None:
            logger.warning("Moz v2 result omitted domain_authority for domain=%s", clean_domain)
            return None
        value = int(round(float(raw_value)))
        if not 0 <= value <= 100:
            logger.warning("Moz v2 returned out-of-range domain_authority for domain=%s", clean_domain)
            return None
        logger.info("Moz Domain Authority found for domain=%s", clean_domain)
        return value
    except (httpx.HTTPError, TypeError, ValueError):
        logger.exception("Moz v2 lookup failed for domain=%s", clean_domain)
        return None


async def lookup_da_via_openpagerank(clean_domain: str) -> int | None:
    """
    Look up a directional site-authority estimate via Open PageRank.
    """
    da: int | None = None
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
                        da = int(float(page_rank_decimal) * 10)
                        logger.info("DA found via Open PageRank: page_rank_decimal=%s da=%s", page_rank_decimal, da)
                    elif pr.get("rank"):
                        # Use rank as fallback indicator
                        rank = pr["rank"]
                        logger.info("Open PageRank returned rank without a comparable 0-100 score: rank=%s", rank)
                    else:
                        logger.warning("Open PageRank returned result but no page_rank_decimal or rank: %s", pr)
                else:
                    logger.warning("Open PageRank response missing or empty: response=%s", data.get("response"))
            else:
                logger.error("Open PageRank request failed: status_code=%s", resp.status_code)
    except Exception as e:
        logger.exception("Open PageRank exception for domain=%s: %s", clean_domain, e)
    return da


def estimate_monthly_audience(authority_score: int | None) -> int:
    """Return a stable, low-precision audience estimate when measured traffic is unavailable."""
    if authority_score is None:
        return 100_000
    raw_estimate = 10 ** (1.5 + (0.065 * authority_score))
    if raw_estimate <= 0:
        return 100_000
    magnitude = 10 ** math.floor(math.log10(raw_estimate))
    return max(1_000, int(round(raw_estimate / magnitude) * magnitude))


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


async def lookup_da_muv(domain: str, cached_metrics: dict | None = None) -> dict:
    """
    Return publication metrics with explicit provenance and confidence.
    """
    clean_domain = domain.lower().replace("www.", "")
    observed_at = datetime.now(timezone.utc).date().isoformat()
    cached_authority = (cached_metrics or {}).get("site_authority") or {}
    if cached_authority.get("source") == "Moz Link Explorer API v2" and cached_authority.get("value"):
        logger.info("Using cached Moz Domain Authority for domain=%s", clean_domain)
        return cached_metrics or {}

    moz_authority = await lookup_domain_authority_via_moz(clean_domain)
    opr_authority = None if moz_authority is not None else await lookup_da_via_openpagerank(clean_domain)
    authority = moz_authority if moz_authority is not None else opr_authority
    audience = estimate_monthly_audience(authority)

    if moz_authority is not None:
        authority_metric = {
            "label": "Moz Domain Authority",
            "value": f"{moz_authority}/100",
            "source": "Moz Link Explorer API v2",
            "method": "URL Metrics domain_authority for the publication domain",
            "confidence": "high",
            "estimated": False,
            "observed_at": observed_at,
        }
        audience_source = "Best-effort model using Moz Domain Authority"
        audience_method = (
            "Deterministic authority-to-audience curve (10^(1.5 + 0.065 × Moz DA)), "
            "rounded to one significant figure; not measured traffic"
        )
    elif opr_authority is not None:
        authority_metric = {
            "label": "Site authority estimate",
            "value": f"{opr_authority}/100",
            "source": "Open PageRank",
            "method": "page_rank_decimal × 10; directional estimate, not Moz Domain Authority",
            "confidence": "medium",
            "estimated": True,
            "observed_at": observed_at,
        }
        audience_source = "Best-effort model using Open PageRank"
        audience_method = (
            "Deterministic authority-to-audience curve (10^(1.5 + 0.065 × authority score)), "
            "rounded to one significant figure; not measured traffic"
        )
    else:
        authority_metric = {
            "label": "Site authority estimate",
            "value": "Unavailable",
            "source": "No configured authority source",
            "method": "No authority score was returned",
            "confidence": "low",
            "estimated": True,
            "observed_at": observed_at,
        }
        audience_source = "Internal best-effort fallback"
        audience_method = (
            "Conservative 100,000 midpoint used when no authority or measured traffic source is available; "
            "not measured traffic"
        )

    metrics = {
        "site_authority": authority_metric,
        "monthly_audience": {
            "label": "Monthly audience estimate",
            # Keep the persisted display value within the legacy VARCHAR(32)
            # column; the label and method carry the audience-unit context.
            "value": f"~{audience:,}",
            "source": audience_source,
            "method": audience_method,
            "confidence": "low",
            "estimated": True,
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
