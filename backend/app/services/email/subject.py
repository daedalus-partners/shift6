from __future__ import annotations

import re
from urllib.parse import urlparse


ACRONYM_SUFFIXES = ("usa", "abc", "ai", "tv", "fm", "pr", "uk")


def _format_host_label(value: str) -> str:
    words = re.sub(r"[-_]+", " ", value).split()
    formatted: list[str] = []
    for word in words:
        lower = word.lower()
        suffix = next(
            (item for item in ACRONYM_SUFFIXES if lower.endswith(item) and len(lower) > len(item)),
            None,
        )
        if suffix:
            formatted.append(f"{lower[:-len(suffix)].capitalize()}{suffix.upper()}")
        else:
            formatted.append(lower.capitalize())
    return " ".join(formatted)


def coverage_subject(
    article_url: str,
    domain: str | None = None,
    title: str | None = None,
    publication: str | None = None,
) -> str:
    """Return a deterministic, non-model-generated subject for coverage email."""
    host = (domain or urlparse(article_url).hostname or "").strip().lower()
    host = host.removeprefix("www.")
    label = host.split(".", 1)[0] if host else "Publication"
    normalized_label = re.sub(r"[-_]+", " ", label).strip()
    publication_name = re.sub(r"\s+", " ", publication or "").strip(" -|:;")[:128]
    normalized_publication = publication_name.lower().removeprefix("www.").rstrip(".")
    if normalized_publication in {host, label} or "." in normalized_publication:
        publication_name = ""
    has_explicit_publication = bool(publication_name)
    publication_name = publication_name or _format_host_label(label) or "Publication"
    # Preserve a publication's own casing when its hostname label appears in the
    # fetched page title (for example, `InfoPool` rather than `Infopool`).
    if not has_explicit_publication and title and normalized_label:
        match = re.search(re.escape(normalized_label), title, flags=re.IGNORECASE)
        if match:
            publication_name = match.group(0)
    return f"Coverage Live: {publication_name}"


def markdown_with_subject(markdown: str, subject: str) -> str:
    """Return a self-contained email for clients that only render Markdown."""
    body = str(markdown or "").lstrip()
    clean_subject = re.sub(r"\s+", " ", str(subject or "Coverage Live: Publication")).strip()
    if re.match(r"^Subject:\s*", body, flags=re.IGNORECASE):
        return body
    return f"Subject: {clean_subject}\n\n{body}"
