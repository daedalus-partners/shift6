from __future__ import annotations

import re
from typing import List, Tuple


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


