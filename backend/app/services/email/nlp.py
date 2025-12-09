from __future__ import annotations

import re
from typing import List, Tuple
import difflib


def extract_mentions_and_links(client_name: str, body: str) -> tuple[List[str], List[str]]:
    mentions: List[str] = []
    links: List[str] = []
    if not body:
        return mentions, links
    # Mentions: simple case-insensitive find of client name
    pattern = re.compile(re.escape(client_name), re.IGNORECASE)
    if pattern.search(body):
        # Collect up to 3 snippets around mentions
        for m in pattern.finditer(body):
            start = max(0, m.start() - 80)
            end = min(len(body), m.end() + 80)
            snippet = body[start:end].strip()
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

    if not candidates:
        return None

    def ctx_has_client(start: int, end: int) -> bool:
        # Check a window around the quote for client name
        window = body[max(0, start - 300): min(len(body), end + 300)].lower()
        return any(tok in window for tok in client_tokens)
    
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

    candidates.sort(key=score, reverse=True)
    best = candidates[0][0].strip()
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


def extract_client_links(links: List[str], client_name: str) -> List[str]:
    out: List[str] = []
    name_tokens = [t for t in re.split(r"\s+", client_name.strip().lower()) if t and len(t) > 2]
    for u in links:
        ul = u.lower()
        if "linkedin.com/" in ul:
            out.append(u)
            continue
        if any(tok in ul for tok in name_tokens):
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


