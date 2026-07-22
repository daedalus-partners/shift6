from __future__ import annotations

import sys

import httpx
import pytest
import numpy as np

sys.path.insert(0, "backend")

from app.services.email.exa import extract_exact_article_result
from app.services.email.http_safety import (
    SafeTextResponse,
    UnsafeUrlError,
    canonicalize_url,
    same_source_url,
    validate_public_url,
)
from app.services.email.scraper import parse_article_html
from app.services.email.scraper import ArticleDocument
from app.services.email import metadata as email_metadata
from app.services.email.nlp import extract_client_links, extract_mentions_and_links
from app.services.email.subject import coverage_subject, markdown_with_subject, markdown_without_subject
from app.services.email.summarizer import (
    SummaryGenerationError,
    _parse_analysis_content,
    render_verified_email,
    summarize_to_markdown,
)
from app.api.v1.email import router as email_router


def test_exa_rejects_an_unrelated_top_result():
    results = [{"url": "https://unrelated.example/landing", "title": "Wrong", "text": "Wrong body"}]
    assert extract_exact_article_result("https://publisher.example/story", results) is None


def test_exa_accepts_only_the_same_normalized_article_url():
    results = [{"url": "https://www.publisher.example/story/?utm_source=test", "title": "Right", "text": "Body"}]
    result = extract_exact_article_result("http://publisher.example/story", results)
    assert result is not None
    assert result[0] == "Right"


def test_article_parser_preserves_structured_links():
    html = """
    <html><head><title>Coverage | InfoPool</title><meta property="og:site_name" content="InfoPool"><link rel="canonical" href="https://infopool.example/story"></head>
    <body><article><p>Acme announced a launch.</p><a href="/clients/acme">Acme profile</a></article></body></html>
    """
    parsed = parse_article_html(html, "https://infopool.example/story")
    assert parsed.title == "Coverage | InfoPool"
    assert parsed.publication == "InfoPool"
    assert parsed.canonical_url == "https://infopool.example/story"
    assert parsed.links == [{"text": "Acme profile", "url": "https://infopool.example/clients/acme"}]


def test_client_mentions_tolerate_historical_separator_corruption():
    mentions, _ = extract_mentions_and_links(
        "Factor A?E",
        "The 2026 report ranks Factor A/E as its top pick.",
    )
    assert mentions
    assert mentions == ["The 2026 report ranks Factor A/E as its top pick."]


def test_client_mentions_still_require_exact_name_components():
    mentions, _ = extract_mentions_and_links("Acme", "Acmeology published a report.")
    assert mentions == []


def test_client_mention_preserves_decimal_funding_context():
    source = (
        "The private sector is also keen to participate. Last autumn, International Airlines Group "
        "was one of the investors in a £20.75 million funding round for OXCCU, an Oxford University "
        "spin-out, which the company says can reduce costs."
    )
    mentions, _ = extract_mentions_and_links("OXCCU", source)
    assert mentions == [source]
    assert "£20.75 million" in mentions[0]


def test_client_mention_prefers_article_prose_over_navigation():
    body = (
        "News News View All Airlines Latest Features Read More Hawaiian Airlines fleet news Read More\n"
        "Hawaiian Airlines plans to begin replacing its Boeing 717 fleet in 2028 with larger 737-800 aircraft."
    )
    mentions, _ = extract_mentions_and_links("Hawaiian Airlines", body)
    assert mentions[0] == (
        "Hawaiian Airlines plans to begin replacing its Boeing 717 fleet in 2028 with larger 737-800 aircraft."
    )


def test_client_mention_uses_title_topic_to_select_central_source_language():
    body = (
        "The Boeing 717s flying for Hawaiian Airlines are entering their final years.\n"
        "Hawaiian Airlines To Replace The Boeing 717 With Larger 737-800"
    )
    mentions, _ = extract_mentions_and_links(
        "Hawaiian Airlines",
        body,
        "Hawaiian Airlines To Replace The Boeing 717 With Larger 737-800",
    )
    assert mentions[0] == "Hawaiian Airlines To Replace The Boeing 717 With Larger 737-800"


def test_client_links_exclude_publisher_navigation_and_share_links():
    links = [
        {"text": "Airlines", "url": "https://publisher.example/news/airlines/"},
        {"text": "Hawaiian Airlines story", "url": "https://publisher.example/news/hawaiian-airlines-story/"},
        {"text": "Share", "url": "https://facebook.com/sharer/sharer.php?u=hawaiian-airlines"},
        {"text": "Hawaiian Airlines analysis", "url": "https://industry-news.example/related-story"},
        {"text": "Hawaiian analysis", "url": "https://crankyflier.com/2026/07/22/hawaiian-fleet-analysis"},
        {"text": "Official site", "url": "https://www.hawaiianairlines.com/about-us"},
    ]
    assert extract_client_links(
        links,
        "Hawaiian Airlines",
        "https://publisher.example/news/hawaiian-airlines-story/",
    ) == ["https://www.hawaiianairlines.com/about-us"]


def test_subject_normalizes_domain_style_publication_metadata():
    assert coverage_subject(
        "https://businessabc.net/story",
        "businessabc.net",
        "A story",
        "businessabc.net",
    ) == "Coverage Live: BusinessABC"


def test_markdown_subject_line_is_self_contained_and_not_duplicated():
    markdown = markdown_with_subject("Outlet — [Story](https://example.com)", "Coverage Live: Example")
    assert markdown.startswith("Subject: Coverage Live: Example\n\n")
    assert markdown_with_subject(markdown, "Coverage Live: Example") == markdown
    assert markdown_without_subject(markdown) == "Outlet — [Story](https://example.com)"


def test_source_url_comparison_ignores_only_safe_normalization():
    assert same_source_url("http://www.example.com/story/", "https://example.com/story?utm_source=x")
    assert not same_source_url("https://example.com/story", "https://example.com/other")
    assert canonicalize_url("HTTPS://WWW.Example.com/story/?utm_campaign=x") == "https://example.com/story"


@pytest.mark.asyncio
async def test_private_destinations_are_rejected(monkeypatch):
    async def fake_resolve(_host: str, _port: int):
        return {"127.0.0.1"}

    monkeypatch.setattr("app.services.email.http_safety.resolve_addresses", fake_resolve)
    with pytest.raises(UnsafeUrlError):
        await validate_public_url("https://example.com/private")


def test_verified_renderer_labels_metrics_and_preserves_exact_source_values():
    markdown = render_verified_email(
        {
            "client_name": "Acme",
            "url": "https://publisher.example/story",
            "domain": "publisher.example",
            "publication": "The Publisher",
            "title": "Acme launches",
            "outlet_description": "A publication.",
            "metrics": {
                "site_authority": {
                    "label": "Site authority estimate",
                    "value": "72/100",
                    "source": "Open PageRank",
                    "method": "page_rank_decimal × 10; not Moz Domain Authority",
                    "confidence": "medium",
                    "estimated": True,
                },
                "monthly_audience": {
                    "label": "Monthly audience estimate",
                    "value": "Unavailable",
                    "source": "No verified traffic source",
                    "method": "Not estimated when evidence is insufficient",
                    "confidence": "low",
                    "estimated": True,
                },
            },
            "client_links": ["https://publisher.example/clients/acme"],
            "mentions": ["Acme announced a launch."],
            "best_quote": "We are ready to launch.",
        },
        {
            "message_pull_through": "The coverage centers on the launch.",
            "strategic_value": "The article places the announcement before a relevant audience.",
            "performance_reach": "Use the labeled estimates as directional context only.",
        },
    )
    assert "[Acme launches](https://publisher.example/story)" in markdown
    assert markdown.startswith("The Publisher —")
    assert "Site authority estimate: **72/100**" in markdown
    assert "Best-effort estimate; Source: Open PageRank" in markdown
    assert "not Moz Domain Authority" in markdown
    assert "Monthly audience estimate: **Unavailable**" in markdown
    assert '“We are ready to launch.”' in markdown


def test_renderer_rejects_analysis_with_unverified_links():
    with pytest.raises(SummaryGenerationError):
        render_verified_email(
            {"url": "https://publisher.example/story", "title": "Story", "domain": "publisher.example"},
            {"message_pull_through": "See https://unverified.example", "strategic_value": "x", "performance_reach": "x"},
        )


def test_analysis_parser_accepts_fenced_and_prefixed_json():
    parsed = _parse_analysis_content(
        'Result:\n```json\n{"message_pull_through":"m","strategic_value":"s","performance_reach":"p"}\n```'
    )
    assert parsed["strategic_value"] == "s"


@pytest.mark.asyncio
async def test_summary_uses_exact_evidence_instead_of_model_paraphrase():
    source_language = (
        "International Airlines Group was one of the investors in a £20.75 million funding round "
        "for Acme, which the company says can reduce costs."
    )
    markdown = await summarize_to_markdown(
        {
            "client_name": "Acme",
            "url": "https://publisher.example/story",
            "domain": "publisher.example",
            "publication": "The Publisher",
            "title": "Acme coverage",
            "mentions": [source_language],
            "client_links": ["https://acme.example/report"],
        }
    )
    assert f"Verified article language: {source_language}" in markdown
    assert "No verified article-level reach or performance data is available" in markdown
    assert "Acme reduces costs" not in markdown


@pytest.mark.asyncio
async def test_about_description_skips_redirected_candidate(monkeypatch):
    requested = []

    async def fake_get(url, **_kwargs):
        requested.append(url)
        if url.endswith("/about"):
            return SafeTextResponse(
                200,
                '<meta name="description" content="Unrelated SEO page">',
                "https://publisher.example/unrelated",
                {"content-type": "text/html"},
            )
        return SafeTextResponse(
            200,
            '<meta name="description" content="The real publication description">',
            url + "/",
            {"content-type": "text/html"},
        )

    monkeypatch.setattr(email_metadata, "safe_get_text", fake_get)
    description = await email_metadata.try_fetch_about_description("publisher.example")
    assert description == "The real publication description."
    assert requested == [
        "https://publisher.example/about",
        "https://publisher.example/about-us",
    ]


@pytest.mark.asyncio
async def test_summarize_route_persists_verified_document_contract(monkeypatch):
    document = ArticleDocument(
        requested_url="https://publisher.example/story",
        final_url="https://publisher.example/story",
        canonical_url="https://publisher.example/story",
        domain="publisher.example",
        publication="The Publisher",
        title="Acme launches | Publisher",
        description="A publication.",
        body='Acme said, “We are ready to launch.”',
        links=[{"text": "Acme", "url": "https://acme.example/about"}],
        fetched_at="2026-07-21T12:00:00+00:00",
        content_sha256="a" * 64,
        source_method="direct_http",
    )

    async def fake_fetch(_url):
        return document

    async def fake_about(_domain):
        return "Publisher description"

    async def fake_metrics(_domain):
        return {
            "site_authority": {"value": "Unavailable"},
            "monthly_audience": {"value": "Unavailable"},
        }

    async def fake_summary(data):
        assert data["url"] == document.requested_url
        assert data["publication"] == "The Publisher"
        assert data["client_links"] == ["https://acme.example/about"]
        return "Verified markdown"

    monkeypatch.setattr(email_router, "fetch_or_scrape", fake_fetch)
    monkeypatch.setattr(email_router, "try_fetch_about_description", fake_about)
    monkeypatch.setattr(email_router, "lookup_da_muv", fake_metrics)
    monkeypatch.setattr(email_router, "summarize_to_markdown", fake_summary)
    monkeypatch.setattr(email_router, "embed_texts", lambda _texts: [np.zeros(768)])

    class FakeQuery:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class FakeSession:
        def __init__(self):
            self.added = []
            self.next_id = 1

        def query(self, _model):
            return FakeQuery()

        def add(self, value):
            self.added.append(value)
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1

        def flush(self):
            pass

        def commit(self):
            pass

        def refresh(self, _value):
            pass

        def rollback(self):
            pass

    db = FakeSession()
    result = await email_router.summarize(
        email_router.SummarizeIn(client_name="Acme", article_url=document.requested_url),
        db=db,
    )
    assert result["subject"] == "Coverage Live: The Publisher"
    assert result["markdown"] == "Subject: Coverage Live: The Publisher\n\nVerified markdown"
    assert result["validation_status"] == "source_verified"
    article = next(value for value in db.added if value.__class__.__name__ == "Article")
    assert article.source_sha256 == "a" * 64
    assert article.final_url == document.final_url


@pytest.mark.asyncio
async def test_canonical_identity_mismatch_never_falls_back_to_search(monkeypatch):
    document = ArticleDocument(
        requested_url="https://publisher.example/story",
        final_url="https://publisher.example/story",
        canonical_url="https://publisher.example/different-story",
        domain="publisher.example",
        publication="Publisher",
        title="Story",
        description=None,
        body="Verified article body.",
        links=[],
        fetched_at="2026-07-21T12:00:00+00:00",
        content_sha256="b" * 64,
        source_method="direct_http",
    )
    fallback_called = False

    async def fake_direct(_url):
        return document

    async def fake_fallback(_url):
        nonlocal fallback_called
        fallback_called = True
        return None

    monkeypatch.setattr(email_metadata, "fetch_article_http", fake_direct)
    monkeypatch.setattr(email_metadata, "fetch_article_via_exa", fake_fallback)
    with pytest.raises(email_metadata.SourceVerificationError):
        await email_metadata.fetch_or_scrape(document.requested_url)
    assert not fallback_called
