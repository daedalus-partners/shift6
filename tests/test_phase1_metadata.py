from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest


sys.path.insert(0, "backend")

from app.models import (  # noqa: E402
    Article,
    ArticleSourceRevision,
    ArticleSummary,
    CoverageScoreSnapshot,
    EvidenceArtifact,
    Publication,
    PublicationMetricSnapshot,
)
from app.services.email import metadata as email_metadata  # noqa: E402
from app.services.email.exa import extract_exact_article_result  # noqa: E402
from app.services.email.scraper import (  # noqa: E402
    parse_article_html,
    parse_publication_datetime,
)


def test_json_ld_article_date_and_author_win_with_all_candidates_preserved():
    html = """
    <html>
      <head>
        <title>Shift6 coverage</title>
        <meta property="article:published_time" content="2026-08-11T09:00:00Z">
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@graph": [
              {
                "@type": "WebPage",
                "name": "Publisher page",
                "datePublished": "2026-08-01T12:00:00Z"
              },
              {
                "@type": "NewsArticle",
                "datePublished": "2026-08-10T18:30:00-05:00",
                "author": [
                  {"@type": "Person", "name": "Lexi Mills"},
                  {"@type": "Person", "name": "Johnny Gabriele"}
                ]
              }
            ]
          }
        </script>
      </head>
      <body>
        <article>
          <time itemprop="datePublished" datetime="2026-08-09">August 9</time>
          <p>Shift6 is named in the story.</p>
        </article>
      </body>
    </html>
    """

    parsed = parse_article_html(html, "https://publisher.example/story")

    assert parsed.author == "Lexi Mills, Johnny Gabriele"
    assert parsed.published_at == datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc)
    assert parsed.published_date_raw == "2026-08-10T18:30:00-05:00"
    assert parsed.published_date_source == "json_ld.datePublished"
    assert parsed.published_date_confidence == "high"
    assert [candidate["source"] for candidate in parsed.published_date_candidates or []] == [
        "json_ld.datePublished",
        "json_ld.datePublished",
        "meta.article:published_time",
        "article.time",
    ]
    assert (parsed.published_date_candidates or [])[1]["raw"] == "2026-08-01T12:00:00Z"


def test_invalid_json_ld_date_is_auditable_and_next_priority_valid_date_is_used():
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type":"Article", "datePublished":"not-a-date"}
      </script>
      <meta property="article:published_time" content="2026-08-12T14:20:00Z">
    </head><body><article><p>Story body.</p></article></body></html>
    """

    parsed = parse_article_html(html, "https://publisher.example/story")

    assert parsed.published_at == datetime(2026, 8, 12, 14, 20, tzinfo=timezone.utc)
    assert parsed.published_date_source == "meta.article:published_time"
    assert parsed.published_date_candidates == [
        {
            "raw": "not-a-date",
            "source": "json_ld.datePublished",
            "confidence": "low",
            "published_at": None,
        },
        {
            "raw": "2026-08-12T14:20:00Z",
            "source": "meta.article:published_time",
            "confidence": "high",
            "published_at": "2026-08-12T14:20:00+00:00",
        },
    ]


def test_only_article_scoped_time_is_used_and_date_only_uncertainty_is_explicit():
    html = """
    <html><body>
      <time datetime="2020-01-01">Navigation date</time>
      <article>
        <time class="updated" datetime="2026-08-14">Updated August 14, 2026</time>
        <time class="published" datetime="2026-08-13">August 13, 2026</time>
        <p>Story body.</p>
      </article>
    </body></html>
    """

    parsed = parse_article_html(html, "https://publisher.example/story")

    assert parsed.published_at == datetime(2026, 8, 13, tzinfo=timezone.utc)
    assert parsed.published_date_raw == "2026-08-13"
    assert parsed.published_date_source == "article.time"
    assert parsed.published_date_confidence == "medium"
    assert len(parsed.published_date_candidates or []) == 1


def test_meta_author_fallback_and_timezone_less_date_lower_confidence():
    html = """
    <html><head>
      <meta name="author" content="  Jane   Reporter ">
      <meta property="article:published_time" content="2026-08-13T08:15:00">
    </head><body><article><p>Story body.</p></article></body></html>
    """

    parsed = parse_article_html(html, "https://publisher.example/story")

    assert parsed.author == "Jane Reporter"
    assert parsed.published_at == datetime(2026, 8, 13, 8, 15, tzinfo=timezone.utc)
    assert parsed.published_date_confidence == "medium"


def test_exa_exact_result_keeps_published_date():
    result = extract_exact_article_result(
        "https://publisher.example/story",
        [
            {
                "url": "https://www.publisher.example/story/?utm_source=test",
                "title": "Story",
                "text": "Verified story body.",
                "publishedDate": "2026-08-12T11:00:00Z",
            }
        ],
    )

    assert result == (
        "Story",
        None,
        "Verified story body.",
        "https://www.publisher.example/story/?utm_source=test",
        "2026-08-12T11:00:00Z",
    )


@pytest.mark.asyncio
async def test_exa_fallback_projects_published_date_with_provenance(monkeypatch):
    async def direct_failure(_url: str):
        raise RuntimeError("publisher blocked direct fetch")

    async def exact_fallback(_url: str):
        return (
            "Story",
            "Description",
            "Verified story body.",
            "https://publisher.example/story",
            "2026-08-12T11:00:00Z",
        )

    monkeypatch.setattr(email_metadata, "fetch_article_http", direct_failure)
    monkeypatch.setattr(email_metadata, "fetch_article_via_exa", exact_fallback)

    document = await email_metadata.fetch_or_scrape("https://publisher.example/story")

    assert document.published_at == datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc)
    assert document.published_date_raw == "2026-08-12T11:00:00Z"
    assert document.published_date_source == "exa.publishedDate"
    assert document.published_date_confidence == "medium"
    assert document.published_date_candidates == [
        {
            "raw": "2026-08-12T11:00:00Z",
            "source": "exa.publishedDate",
            "confidence": "medium",
            "published_at": "2026-08-12T11:00:00+00:00",
        }
    ]


def test_publication_datetime_accepts_rfc_2822_and_normalizes_to_utc():
    parsed, confidence = parse_publication_datetime("Wed, 12 Aug 2026 18:00:00 -0500")
    assert parsed == datetime(2026, 8, 12, 23, 0, tzinfo=timezone.utc)
    assert confidence == "high"


def test_phase1_model_contract_retains_legacy_projection_and_new_evidence_links():
    assert {
        "client_id",
        "publication_id",
        "published_at",
        "published_at_utc",
        "published_date_raw",
        "published_date_source",
        "published_date_confidence",
        "published_date_candidates",
    } <= set(Article.__table__.columns.keys())
    assert "source_revision_id" in ArticleSummary.__table__.columns
    assert {
        "author",
        "published_at",
        "published_date_raw",
        "published_date_source",
        "published_date_confidence",
        "published_date_candidates",
        "links",
    } <= set(ArticleSourceRevision.__table__.columns.keys())
    assert Publication.__tablename__ == "publications"
    assert PublicationMetricSnapshot.__tablename__ == "publication_metric_snapshots"
    assert EvidenceArtifact.__tablename__ == "evidence_artifacts"
    assert CoverageScoreSnapshot.__tablename__ == "coverage_score_snapshots"
