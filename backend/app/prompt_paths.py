from __future__ import annotations

import re
from pathlib import Path


SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
PROMPT_DIR = (Path(__file__).resolve().parent.parent / "system_prompts").resolve()


def validate_client_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not SLUG_PATTERN.fullmatch(normalized):
        raise ValueError("Slug must contain only lowercase letters, numbers, hyphens, or underscores")
    return normalized


def prompt_path(slug: str) -> Path:
    normalized = validate_client_slug(slug)
    candidate = (PROMPT_DIR / f"{normalized}.md").resolve()
    if candidate.parent != PROMPT_DIR:
        raise ValueError("Invalid prompt path")
    return candidate
