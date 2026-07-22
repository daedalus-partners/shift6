from __future__ import annotations

import re
from typing import List
import difflib
from urllib.parse import urlsplit


BOILERPLATE_MARKERS = (
    "read more",
    "view all",
    "latest features",
    "sign up",
    "skip to content",
    "privacy policy",
    "cookie policy",
)
GENERIC_CLIENT_TOKENS = {
    "airline",
    "airlines",
    "company",
    "corp",
    "corporation",
    "group",
    "inc",
    "limited",
    "llc",
    "ltd",
    "technology",
    "technologies",
}
SOCIAL_SHARE_PATH_MARKERS = (
    "/share",
    "/sharer",
    "/sharing/",
    "/submit",
    "/intent/",
)


def client_name_pattern(client_name: str) -> re.Pattern[str] | None:
    """Match a client name while tolerating common separator corruption.

    Historical imports have converted separators such as ``/`` into ``?``. The
    alphanumeric name components must still match exactly and in order; only the
    punctuation/whitespace between them is interchangeable.
    """
    parts = re.findall(r"\w+", re.sub(r"\s+", " ", client_name.strip()), flags=re.UNICODE)
    if not parts:
        return None
    separator = r"(?:[\s/&+?_.-]+)"
    expression = separator.join(re.escape(part) for part in parts)
    return re.compile(rf"(?<!\w){expression}(?!\w)", re.IGNORECASE)


def _mention_snippet(body: str, start: int, end: int, *, limit: int = 600) -> str:
    # Article paragraphs are newline-delimited by the scraper. Prefer that
    # verified source unit so decimal points (for example £20.75 million) are
    # never mistaken for sentence boundaries.
    left = body.rfind("\n", 0, start) + 1
    next_newline = body.find("\n", end)
    right = next_newline if next_newline >= 0 else len(body)
    snippet = re.sub(r"\s+", " ", body[left:right]).strip()
    if len(snippet) <= limit:
        return snippet

    # Preserve whole words and make intentional clipping visible for unusually
    # long source sentences instead of returning broken word fragments.
    local_start = max(0, start - left - limit // 2)
    local_end = min(len(snippet), local_start + limit)
    if local_start:
        space = snippet.find(" ", local_start)
        local_start = space + 1 if space >= 0 else local_start
    if local_end < len(snippet):
        space = snippet.rfind(" ", local_start, local_end)
        local_end = space if space >= 0 else local_end
    return f"{'…' if local_start else ''}{snippet[local_start:local_end].strip()}{'…' if local_end < len(snippet) else ''}"


def extract_mentions_and_links(client_name: str, body: str) -> tuple[List[str], List[str]]:
    mentions: List[str] = []
    links: List[str] = []
    if not body:
        return mentions, links
    pattern = client_name_pattern(client_name)
    if pattern is None:
        return mentions, links
    if pattern.search(body):
        candidates: list[tuple[int, int, str]] = []
        for m in pattern.finditer(body):
            snippet = _mention_snippet(body, m.start(), m.end())
            lower = snippet.lower()
            marker_penalty = sum(250 for marker in BOILERPLATE_MARKERS if marker in lower)
            prose_bonus = 100 if 60 <= len(snippet) <= 600 else 0
            punctuation_bonus = 20 if re.search(r"[.!?]", snippet) else 0
            score = prose_bonus + punctuation_bonus + min(len(snippet), 400) // 10 - marker_penalty
            candidates.append((score, m.start(), snippet))
        seen: set[str] = set()
        for _score, _position, snippet in sorted(candidates, key=lambda item: (-item[0], item[1])):
            normalized = snippet.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            mentions.append(snippet)
            if len(mentions) >= 3:
                break
    # Links: naive href/http(s) URLs
    url_pattern = re.compile(r"https?://[^\s)\]]+")
    for u in url_pattern.findall(body):
        links.append(u)
        if len(links) >= 10:
            break
    return mentions, links


def find_best_quote(body: str, client_name: str | None = None) -> str | None:
    """
    Find the best verbatim quote from the article, prioritizing quotes
    that are directly attributed to the client.
    """
    if not body:
        return None
    
    # Prep client tokens for matching
    client_tokens: List[str] = []
    if client_name:
        client_tokens = [t.lower() for t in re.split(r"\s+", client_name.strip()) if len(t) > 2]
    
    # First, try to find quotes with explicit attribution to the client
    # Pattern: "quote" + attribution verb + client name (or reverse)
    attribution_verbs = r"(?:said|stated|told|according to|noted|explained|argued|added|commented|remarked)"
    
    # Build patterns that capture quotes WITH their attribution context
    attributed_patterns = []
    if client_tokens:
        # Pattern 1: "quote," client_name said/noted/etc.
        # Pattern 2: client_name said/noted "quote"
        client_pattern = r"(?:" + "|".join(re.escape(t) for t in client_tokens) + r")"
        attributed_patterns = [
            # "Quote" ... ClientName said/noted
            rf'[""]([^""]{15,800}?)[""][,.]?\s*{client_pattern}.*?{attribution_verbs}',
            # "Quote," said ClientName
            rf'[""]([^""]{15,800}?)[""][,.]?\s*{attribution_verbs}\s+.*?{client_pattern}',
            # ClientName said "quote"
            rf'{client_pattern}.*?{attribution_verbs}[^""]*[""]([^""]{15,800}?)[""]',
        ]
    
    # Try attributed patterns first (highest priority)
    for pat in attributed_patterns:
        for m in re.finditer(pat, body, flags=re.IGNORECASE | re.DOTALL):
            q = m.group(1).strip()
            if 15 <= len(q) <= 800:
                # Clean and return - this is a quote attributed to the client
                q = re.sub(r"\s+", " ", q)
                return q
    
    # Fallback: Collect all quoted text and score by proximity to client name
    candidates: List[tuple[str, int, int]] = []
    quote_patterns = [
        r'[""]([^""]{15,800}?)[""]',     # curly double quotes
        r'"([^"]{15,800}?)"',            # straight double quotes
        r"'([^']{15,600}?)'",            # single quotes (shorter max)
    ]
    
    for pat in quote_patterns:
        for m in re.finditer(pat, body, flags=re.DOTALL):
            q = m.group(1).strip()
            if 15 <= len(q) <= 600:
                candidates.append((q, m.start(1), m.end(1)))
            if len(candidates) > 100:
                break
        if len(candidates) > 100:
            break

    if not candidates or not client_tokens:
        return None

    def ctx_has_client(start: int, end: int) -> bool:
        # Check a window around the quote for client name
        window = body[max(0, start - 300): min(len(body), end + 300)].lower()
        return any(re.search(rf"(?<!\w){re.escape(tok)}(?!\w)", window) for tok in client_tokens)
    
    def ctx_has_attribution(start: int, end: int) -> bool:
        # Check if there's an attribution verb near the quote
        window = body[max(0, start - 100): min(len(body), end + 100)]
        return bool(re.search(attribution_verbs, window, re.IGNORECASE))

    def score(entry: tuple[str, int, int]) -> int:
        q, s, e = entry
        sc = 0
        # Heavy bonus for quotes near client name
        if client_tokens and ctx_has_client(s, e):
            sc += 500
        # Bonus for attribution verbs nearby
        if ctx_has_attribution(s, e):
            sc += 200
        # Prefer medium-length quotes (not too short, not too long)
        if 40 <= len(q) <= 300:
            sc += 100
        elif len(q) > 400:
            sc -= 50
        return sc

    eligible = [entry for entry in candidates if ctx_has_client(entry[1], entry[2]) and ctx_has_attribution(entry[1], entry[2])]
    if not eligible:
        return None
    eligible.sort(key=score, reverse=True)
    best = eligible[0][0].strip()
    best = re.sub(r"\s+", " ", best)
    return best or None


def classify_sentiment(text: str) -> str:
    if not text:
        return "Neutral"
    t = text.lower()
    positive_terms = [
        "strong", "record", "surge", "growth", "positive", "promising", "gains", "beat",
        "improved", "leading", "innovative", "successful", "opportunity",
    ]
    negative_terms = [
        "decline", "drop", "fall", "concern", "risk", "negative", "loss", "miss",
        "delay", "issue", "criticism", "uncertain", "downturn",
    ]
    pos = sum(1 for w in positive_terms if w in t)
    neg = sum(1 for w in negative_terms if w in t)
    if pos > neg * 1.5 and pos >= 2:
        return "Positive"
    if neg > pos * 1.5 and neg >= 2:
        return "Negative"
    return "Neutral"


def extract_client_links(
    links: list[str] | list[dict[str, str]],
    client_name: str,
    article_url: str | None = None,
) -> List[str]:
    out: List[str] = []
    all_name_tokens = [t for t in re.findall(r"\w+", client_name.lower()) if len(t) > 2]
    name_tokens = [token for token in all_name_tokens if token not in GENERIC_CLIENT_TOKENS]
    name_tokens = name_tokens or all_name_tokens
    exact_name = client_name_pattern(client_name)
    publisher_host = (urlsplit(article_url).hostname or "").lower().removeprefix("www.") if article_url else ""
    for link in links:
        if isinstance(link, dict):
            u = str(link.get("url") or "")
            anchor_text = str(link.get("text") or "")
        else:
            u = str(link)
            anchor_text = ""
        parsed = urlsplit(u)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = parsed.path.lower()
        if parsed.scheme.lower() not in {"http", "https"} or not host:
            continue
        if publisher_host and host == publisher_host:
            continue
        if any(marker in path for marker in SOCIAL_SHARE_PATH_MARKERS):
            continue
        searchable_url = f"{host}{path}".lower()
        url_matches = bool(name_tokens) and all(token in searchable_url for token in name_tokens)
        anchor_matches = bool(exact_name and exact_name.search(anchor_text))
        if url_matches or anchor_matches:
            out.append(u)
    # dedupe keep order
    seen = set()
    dedup: List[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        dedup.append(u)
    return dedup[:5]


def normalize_text(t: str) -> str:
    if not t:
        return ""
    # Unify quotes and whitespace
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def approximate_substring(haystack: str, needle: str, threshold: float = 0.92) -> str | None:
    H = normalize_text(haystack)
    N = normalize_text(needle)
    if not H or not N:
        return None
    # Split haystack into sentences/paragraphs to reduce cost
    parts = re.split(r"[\n\.\!\?]", H)
    best = (0.0, None)
    for p in parts:
        p = p.strip()
        if not p:
            continue
        ratio = difflib.SequenceMatcher(None, p, N).ratio()
        if ratio > best[0]:
            best = (ratio, p)
    if best[0] >= threshold and best[1]:
        return best[1]
    return None
