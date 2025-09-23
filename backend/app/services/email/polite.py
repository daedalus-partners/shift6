from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
import httpx
import urllib.robotparser as robotparser


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# In-memory caches (process-local)
_robots_cache: Dict[str, Tuple[robotparser.RobotFileParser, float, float]] = {}
# domain -> (parser, expires_at_epoch, crawl_delay_seconds)
_rate_next_at: Dict[str, float] = {}  # domain -> next_allowed_epoch
_url_cache: Dict[str, Tuple[str, Optional[str], Optional[str], float]] = {}
# url -> (body, etag, last_modified, fetched_at_epoch)

ROBOTS_TTL_SECONDS = 24 * 3600
HTTP_CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_MIN_DELAY_SECONDS = 5.0


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


async def get_robots(domain: str) -> Tuple[robotparser.RobotFileParser, float]:
    now = time.time()
    if domain in _robots_cache:
        rp, exp, delay = _robots_cache[domain]
        if now < exp:
            return rp, delay
    rp = robotparser.RobotFileParser()
    robots_url = f"https://{domain}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            r = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200 and r.text:
                rp.parse(r.text.splitlines())
            else:
                # treat as allow-all if no robots
                rp.parse(["User-agent: *", "Disallow:"])
    except Exception:
        rp.parse(["User-agent: *", "Disallow:"])
    # Try crawl-delay for UA or *
    delay = 0.0
    try:
        delay = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*") or 0.0
    except Exception:
        delay = 0.0
    _robots_cache[domain] = (rp, now + ROBOTS_TTL_SECONDS, float(delay or 0.0))
    return rp, float(delay or 0.0)


async def is_allowed(url: str) -> bool:
    domain = _domain(url)
    rp, _ = await get_robots(domain)
    path = urlparse(url).path or "/"
    try:
        return bool(rp.can_fetch(USER_AGENT, path))
    except Exception:
        return True


async def rate_limit(url: str, min_delay: float = DEFAULT_MIN_DELAY_SECONDS) -> None:
    domain = _domain(url)
    _, robots_delay = await get_robots(domain)
    enforced_delay = max(min_delay, robots_delay or 0.0)
    now = time.monotonic()
    next_at = _rate_next_at.get(domain, 0.0)
    if next_at > now:
        await asyncio.sleep(next_at - now)
    # small jitter (0-200ms)
    jitter = (hash((domain, int(now))) % 200) / 1000.0
    _rate_next_at[domain] = time.monotonic() + enforced_delay + jitter


async def cached_get(url: str, headers: Optional[dict] = None) -> Tuple[int, str]:
    # simple conditional GET using ETag/Last-Modified if present in cache
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    etag = None
    last_mod = None
    body = None
    now = time.time()
    if url in _url_cache:
        body, etag, last_mod, ts = _url_cache[url]
        if now - ts < HTTP_CACHE_TTL_SECONDS:
            if etag:
                req_headers["If-None-Match"] = etag
            if last_mod:
                req_headers["If-Modified-Since"] = last_mod
    async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
        r = await client.get(url, headers=req_headers, follow_redirects=True)
        if r.status_code == 304 and body is not None:
            return 200, body
        if r.status_code == 200:
            etag = r.headers.get("etag")
            last_mod = r.headers.get("last-modified")
            body = r.text
            _url_cache[url] = (body, etag, last_mod, now)
        return r.status_code, r.text


