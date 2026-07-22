from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
import urllib.robotparser as robotparser

from .http_safety import safe_get_text


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# In-memory caches (process-local)
_robots_cache: Dict[str, Tuple[robotparser.RobotFileParser, float, float]] = {}
# domain -> (parser, expires_at_epoch, crawl_delay_seconds)
_rate_next_at: Dict[str, float] = {}  # domain -> next_allowed_epoch
_url_cache: OrderedDict[str, Tuple[str, str, str, float]] = OrderedDict()
# url -> (body, final_url, content_type, fetched_at_epoch)

ROBOTS_TTL_SECONDS = 24 * 3600
HTTP_CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_MIN_DELAY_SECONDS = 5.0
MAX_CACHE_ENTRIES = 128


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
        response = await safe_get_text(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout_seconds=10,
            max_bytes=256 * 1024,
        )
        if response.status_code == 200 and response.text:
            rp.parse(response.text.splitlines())
        else:
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


async def cached_get(url: str, headers: Optional[dict] = None) -> Tuple[int, str, str, str]:
    now = time.time()
    if url in _url_cache:
        body, final_url, content_type, ts = _url_cache[url]
        if now - ts < HTTP_CACHE_TTL_SECONDS:
            _url_cache.move_to_end(url)
            return 200, body, final_url, content_type
        del _url_cache[url]
    response = await safe_get_text(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    content_type = response.headers.get("content-type", "")
    if response.status_code == 200:
        _url_cache[url] = (response.text, response.final_url, content_type, now)
        _url_cache.move_to_end(url)
        while len(_url_cache) > MAX_CACHE_ENTRIES:
            _url_cache.popitem(last=False)
    return response.status_code, response.text, response.final_url, content_type
