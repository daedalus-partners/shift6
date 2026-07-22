from __future__ import annotations

from typing import Dict, List, Tuple, Optional
import math
import os
import json
import re
import unicodedata

import numpy as np
from app import embedding as emb
import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "anthropic/claude-3.7-sonnet")


def normalize_for_exact_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"}))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def has_normalized_exact_quote(quote_text: str, article_text: str) -> bool:
    quote = normalize_for_exact_match(quote_text).strip('"\' ')
    article = normalize_for_exact_match(article_text)
    if len(quote) < 12 or not article:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(quote)}(?!\w)", article))


def has_client_name(client_name: str, text: str) -> bool:
    name = normalize_for_exact_match(client_name)
    return bool(name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalize_for_exact_match(text)))


def tokenize_words(text: str) -> List[str]:
    return [t for t in text.split() if t.strip()]


def shingles(words: List[str], size: int = 8) -> List[str]:
    if size <= 0 or len(words) < size:
        return []
    return [" ".join(words[i : i + size]) for i in range(len(words) - size + 1)]


def jaccard_similarity(a: str, b: str) -> float:
    sa = set(tokenize_words(a.lower()))
    sb = set(tokenize_words(b.lower()))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa.intersection(sb))
    union = len(sa.union(sb))
    return inter / union if union else 0.0


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def embed(text: str) -> np.ndarray:
    return emb.embed_texts([text])[0]


async def adjudicate_with_claude(client_name: str, quote_text: str, excerpt: str) -> Tuple[bool, str, float, str]:
    if not OPENROUTER_API_KEY:
        # Offline deterministic fallback: require both name and at least 50% Jaccard
        jac = jaccard_similarity(quote_text, excerpt)
        mt = "exact" if has_normalized_exact_quote(quote_text, excerpt) else ("paraphrase" if jac >= 0.6 else "no_match")
        return jac >= 0.6 and has_client_name(client_name, excerpt), mt, min(1.0, jac + 0.2), excerpt[:280]

    system = (
        "You are a precise media fact-checker. Return ONLY JSON with keys match, type, confidence, matched_text."
    )
    user = (
        f"CLIENT: \"{client_name}\"\n"
        f"QUOTE: \"{quote_text}\"\n"
        f"ARTICLE_EXCERPT: \"{excerpt}\"\n"
        "Does the excerpt use or closely paraphrase the QUOTE attributed to the CLIENT?"
        " Return JSON only: {\n  \"match\": true|false,\n  \"type\": \"exact\"|\"partial\"|\"paraphrase\"|\"no_match\",\n  \"confidence\": 0.0-1.0,\n  \"matched_text\": \"...\"\n}"
    )
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shift6.local/",
        "X-Title": "Shift6 Coverage",
    }
    payload = {
        "model": OPENROUTER_MODEL_ID,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45)) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            if r.status_code == 200:
                j = r.json()
                msg = (j.get("choices") or [{}])[0].get("message") or {}
                content = msg.get("content") or (j.get("choices") or [{}])[0].get("text") or "{}"
                parsed = json.loads(content)
                mt = str(parsed.get("type") or "no_match")
                conf = float(parsed.get("confidence") or 0.0)
                m = bool(parsed.get("match") or False)
                matched_text = str(parsed.get("matched_text") or "")
                return m, mt, conf, matched_text
    except Exception:
        pass
    # fallback
    jac = jaccard_similarity(quote_text, excerpt)
    mt = "exact" if has_normalized_exact_quote(quote_text, excerpt) else ("paraphrase" if jac >= 0.6 else "no_match")
    return jac >= 0.6 and has_client_name(client_name, excerpt), mt, min(1.0, jac + 0.2), excerpt[:280]
