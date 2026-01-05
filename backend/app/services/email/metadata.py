from __future__ import annotations

import os
import httpx
import json
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .scraper import get_domain, fetch_article_http
from .exa import fetch_article_via_exa, exa_search
import re
import logging


logger = logging.getLogger("metadata.da_muv")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "anthropic/claude-3.7-sonnet")


async def lookup_da_via_openpagerank(clean_domain: str) -> str | None:
    """
    Look up Domain Authority (DA) for a domain via Open PageRank API.
    """
    da: str | None = None
    opr_api_key = os.getenv("OPENPAGERANK_API_KEY", "gcgcg0sssc0gkw0sok48o48480kws8040wookgko")
    # Log API key info (masked for security)
    if opr_api_key:
        api_key_preview = f"{opr_api_key[:4]}...{opr_api_key[-4:]}" if len(opr_api_key) > 8 else "***"
        logger.info("Attempting Open PageRank lookup for DA: domain=%s api_key=%s (length=%s)", 
                   clean_domain, api_key_preview, len(opr_api_key))
    else:
        logger.info("Attempting Open PageRank lookup for DA: domain=%s api_key=(not set)", clean_domain)
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
                logger.debug("Open PageRank response data: %s", data)
                if data.get("response") and len(data["response"]) > 0:
                    pr = data["response"][0]
                    logger.debug("Open PageRank result: %s", pr)
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
                logger.error("Open PageRank request failed: status_code=%s response=%s", resp.status_code, resp.text[:500])
    except Exception as e:
        logger.exception("Open PageRank exception for domain=%s: %s", clean_domain, e)
    return da


async def lookup_da_via_exa(clean_domain: str) -> str | None:
    """
    Look up Domain Authority (DA) for a domain via Exa search for Moz data.
    """
    da: str | None = None
    moz_q = f"site:moz.com Domain Authority {clean_domain}"
    logger.info("Attempting Exa search for DA: query=%s domain=%s", moz_q, clean_domain)
    results = await exa_search(moz_q, num_results=3)
    logger.info("Exa DA search returned %s results", len(results))
    for idx, item in enumerate(results):
        u = (item.get("url") or "").lower()
        text = (item.get("text") or "")
        logger.debug("DA result[%s]: url=%s text_length=%s", idx, u, len(text))
        if not u or "moz.com" not in u:
            logger.debug("DA result[%s]: skipping - url doesn't contain moz.com", idx)
            continue
        # Log a sample of the text to see what we're searching
        text_sample = text[:500] if text else "(empty)"
        logger.info("DA result[%s]: searching text sample: %s", idx, text_sample)
        m = re.search(r"Domain Authority\s*[:\s]*(\d{1,3})", text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                da = str(val)
                logger.info("DA found: %s from url=%s", da, u)
                break
        else:
            logger.debug("DA result[%s]: regex pattern did not match", idx)
    if not da:
        logger.warning("DA not found after searching %s Exa results for domain=%s", len(results), clean_domain)
    return da


async def lookup_muv_via_exa(clean_domain: str) -> str | None:
    """
    Look up Monthly Unique Visitors (MUV) for a domain via Exa search for SimilarWeb data.
    """
    muv: str | None = None
    sw_q = f"site:similarweb.com {clean_domain} traffic"
    logger.info("Attempting Exa search for MUV: query=%s domain=%s", sw_q, clean_domain)
    results = await exa_search(sw_q, num_results=3)
    logger.info("Exa MUV search returned %s results", len(results))
    for idx, item in enumerate(results):
        u = (item.get("url") or "").lower()
        text = (item.get("text") or "")
        logger.debug("MUV result[%s]: url=%s text_length=%s", idx, u, len(text))
        if not u or "similarweb.com" not in u:
            logger.debug("MUV result[%s]: skipping - url doesn't contain similarweb.com", idx)
            continue
        # Log a sample of the text to see what we're searching
        text_sample = text[:500] if text else "(empty)"
        logger.info("MUV result[%s]: searching text sample: %s", idx, text_sample)
        # Look for various traffic indicators
        patterns = [
            r"(\d[\d,.]*\s*[KkMm]?)\s*(?:monthly\s+)?(?:unique\s+)?visitors",
            r"visits[:\s]*(\d[\d,.]*\s*[KkMm]?)",
            r"traffic[:\s]*(\d[\d,.]*\s*[KkMm]?)",
        ]
        matched = False
        for pat_idx, pat in enumerate(patterns):
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                muv = m.group(1).strip()
                logger.info("MUV found: %s using pattern[%s] from url=%s", muv, pat_idx, u)
                matched = True
                break
        if matched:
            break
        else:
            logger.debug("MUV result[%s]: none of the regex patterns matched", idx)
    if not muv:
        logger.warning("MUV not found after searching %s Exa results for domain=%s", len(results), clean_domain)
    return muv


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
    async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
        for path in candidates:
            try:
                resp = await client.get(urljoin(base, path), headers=headers, follow_redirects=True)
                if resp.status_code == 200 and "text/html" in (resp.headers.get("content-type") or ""):
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Try og:description first
                    og = soup.find("meta", attrs={"property": "og:description"})
                    if og and og.get("content"):
                        return og["content"].strip()[:400]
                    # Try meta description
                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    if meta_desc and meta_desc.get("content"):
                        return meta_desc["content"].strip()[:400]
                    # Fall back to first substantial paragraph
                    for p in soup.find_all("p"):
                        text = p.get_text(" ", strip=True)
                        if len(text) > 50:  # Skip tiny paragraphs
                            return text[:400]
            except Exception:
                continue
    return None


async def lookup_da_muv(domain: str) -> tuple[str | None, str | None]:
    """
    Look up Domain Authority and Monthly Unique Visitors for a domain.
    Uses Open PageRank API for DA (free) and falls back to Exa search for MUV.
    """
    da: str | None = None
    muv: str | None = None
    
    # Clean domain (remove www. prefix for consistency)
    clean_domain = domain.lower().replace("www.", "")
    
    # DA via Open PageRank API (free, no key required for basic lookups)
    da = await lookup_da_via_openpagerank(clean_domain)
    
    # Fallback: Try Exa search for DA from Moz
    if not da:
        da = await lookup_da_via_exa(clean_domain)
    
    # MUV via LLM estimation
    muv_result = await estimate_monthly_traffic_via_llm(clean_domain, da)
    
    # Safely extract MUV from nested response
    muv = None
    if muv_result and isinstance(muv_result, dict):
        estimate = muv_result.get("estimate")
        if estimate and isinstance(estimate, dict):
            muv = estimate.get("base")
    
    logger.info("lookup_da_muv result for domain=%s: da=%s muv=%s", clean_domain, da, muv)
    return da, muv


async def estimate_monthly_traffic_via_llm(
    domain: str,
    opr_rank: int | None,
    country: str = "global",
    vertical: str | None = None,
    known_monthly_uniques: int | None = None,
    timeframe: str = "last 30 days",
) -> dict | None:
    """
    Estimate monthly unique visitors using OpenRouter LLM with monthlytrafficprompt.md.
    
    Args:
        domain: Root domain (e.g., "example.com")
        opr_rank: OpenPageRank rank/authority score
        country: ISO country code or "global" (default: "global")
        vertical: One of [ecommerce, local_service, publisher, saas, marketplace, nonprofit, other]
        known_monthly_uniques: Optional benchmark value (treated as ground truth)
        timeframe: "month" or "last 30 days" (default: "last 30 days")
    
    Returns:
        Parsed JSON response with estimate, confidence, evidence, etc., or None on failure
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OpenRouter API key not set, skipping monthly traffic estimation")
        return None
    
    # Load prompt from file
    # Try multiple path resolutions to handle both local dev and Docker container paths
    # Local: backend/app/services/email/metadata.py -> backend/system_prompts/
    # Docker: /app/app/services/email/metadata.py -> /app/system_prompts/
    possible_paths = [
        Path(__file__).parent.parent.parent.parent / "system_prompts" / "monthlytrafficprompt.md",  # 4 levels up
        Path(__file__).parent.parent.parent / "system_prompts" / "monthlytrafficprompt.md",  # 3 levels up (fallback)
        Path("/app") / "system_prompts" / "monthlytrafficprompt.md",  # Docker absolute path
    ]
    
    prompt_path = None
    for path in possible_paths:
        if path.exists():
            prompt_path = path
            break
    
    if not prompt_path:
        logger.error("Failed to find monthlytrafficprompt.md. Tried paths: %s", possible_paths)
        return None
    
    logger.debug("Loading monthly traffic prompt from: %s", prompt_path)
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except Exception as e:
        logger.error("Failed to load monthlytrafficprompt.md from %s: %s", prompt_path, e)
        return None
    
    # Build user message with inputs
    user_parts = [f"domain: {domain}"]
    if opr_rank is not None:
        user_parts.append(f"opr_rank: {opr_rank}")
    if country:
        user_parts.append(f"country: {country}")
    if vertical:
        user_parts.append(f"vertical: {vertical}")
    if known_monthly_uniques is not None:
        user_parts.append(f"known_monthly_uniques: {known_monthly_uniques}")
    if timeframe:
        user_parts.append(f"timeframe: {timeframe}")
    
    user_message = "\n".join(user_parts)
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shift6.local/",
        "X-Title": "Shift6 Monthly Traffic Estimator",
    }
    
    payload = {
        "model": OPENROUTER_MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message + "\n\nIMPORTANT: Respond ONLY with valid JSON. No explanations, no tool calls, no markdown code blocks - just the raw JSON object."},
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    
    logger.info("Calling OpenRouter for monthly traffic estimation: domain=%s opr_rank=%s", domain, opr_rank)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            logger.info("OpenRouter monthly traffic response: status_code=%s", resp.status_code)
            if resp.status_code == 200:
                j = resp.json()
                msg = (j.get("choices") or [{}])[0].get("message") or {}
                content = msg.get("content") or (j.get("choices") or [{}])[0].get("text")
                if content:
                    # Try to parse JSON from the response
                    try:
                        # The LLM should return JSON, but it might be wrapped in markdown code blocks
                        content_clean = content.strip()
                        if content_clean.startswith("```"):
                            # Extract JSON from code block
                            lines = content_clean.split("\n")
                            json_lines = []
                            in_json = False
                            for line in lines:
                                if line.strip().startswith("```json") or line.strip().startswith("```"):
                                    in_json = True
                                    continue
                                if line.strip() == "```":
                                    break
                                if in_json:
                                    json_lines.append(line)
                            content_clean = "\n".join(json_lines)
                        result = json.loads(content_clean)
                        logger.info("Monthly traffic estimation successful for domain=%s", domain)
                        return result
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse JSON from OpenRouter response: %s content_preview=%s", e, content[:200])
                        return None
            else:
                logger.error("OpenRouter monthly traffic request failed: status_code=%s response=%s", resp.status_code, resp.text[:500])
                return None
    except Exception as e:
        logger.exception("OpenRouter monthly traffic exception for domain=%s: %s", domain, e)
        return None


async def fetch_or_scrape(url: str) -> tuple[str | None, str | None, str | None, str]:
    domain = get_domain(url)
    # Try Exa first
    title, desc, body = await fetch_article_via_exa(url)
    if not body:
        try:
            title, desc, body = await fetch_article_http(url)
        except Exception:
            title, desc, body = None, None, None
    return title, desc, body, domain


