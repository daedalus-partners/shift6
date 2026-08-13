from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pytest


sys.path.insert(0, "backend")

# The scoring/router tests do not load an embedding model.  Keep the focused
# test environment lightweight when the optional model runtime is absent.
try:
    import sentence_transformers  # noqa: F401
except ImportError:
    sentence_transformers_stub = types.ModuleType("sentence_transformers")

    class _UnusedSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("embedding model should not load in scoring tests")

    sentence_transformers_stub.SentenceTransformer = _UnusedSentenceTransformer
    sys.modules["sentence_transformers"] = sentence_transformers_stub

from app.api.v1.email import router as email_router  # noqa: E402
from app.models import (  # noqa: E402
    Article,
    ArticleEmbedding,
    ArticleSourceRevision,
    ArticleSummary,
    CoverageScoreSnapshot,
    Publication,
    PublicationMetricSnapshot,
)
from app.services.email.scoring import (  # noqa: E402
    FORMULA_HASH,
    METHODOLOGY_SPEC,
    METHODOLOGY_VERSION,
    calculate_shift6_score,
    render_shift6_score_markdown,
)
from app.services.email.scraper import ArticleDocument  # noqa: E402


MOZ_METRIC = {
    "label": "Moz Domain Authority",
    "value": "76/100",
    "source": "Moz Link Explorer API v2",
    "method": "URL Metrics domain_authority for the publication domain",
    "confidence": "high",
    "estimated": False,
    "observed_at": "2026-08-13",
}

SEMRUSH_METRIC = {
    "label": "Estimated monthly visits",
    "value": "~136,000",
    "source": "Semrush website traffic overview",
    "method": "Semrush all-device monthly visits estimate",
    "confidence": "medium",
    "estimated": True,
    "observed_at": "2026-06-01",
}


def test_draft_formula_is_versioned_hashed_and_does_not_invent_subrubrics():
    components = METHODOLOGY_SPEC["formula"]["components"]

    assert METHODOLOGY_VERSION == "shift6-draft-2026-08-11"
    assert len(FORMULA_HASH) == 64
    assert {name: value["weight_percent"] for name, value in components.items()} == {
        "impact": 35,
        "quality": 30,
        "outlet_strength": 20,
        "outlet_audience": 15,
    }
    assert METHODOLOGY_SPEC["status"] == "awaiting_lexi_review"
    assert METHODOLOGY_SPEC["rules"]["impact"]["status"] == "pending"
    assert METHODOLOGY_SPEC["rules"]["quality"]["status"] == "pending"
    assert METHODOLOGY_SPEC["rules"]["outlet_audience"]["status"] == "pending"


def test_real_moz_scores_only_outlet_strength_without_reweighting_missing_components():
    score = calculate_shift6_score(
        {"site_authority": MOZ_METRIC, "monthly_audience": SEMRUSH_METRIC}
    )

    assert score.status == "partial"
    assert score.total_score is None
    assert score.components["outlet_strength"] == {
        "weight_percent": 20,
        "score": 76.0,
        "weighted_points": 15.2,
        "status": "scored",
        "rule_id": "moz_domain_authority_identity_v1",
        "reason": None,
        "provenance": {
            "provider": "Moz Link Explorer API v2",
            "method": "URL Metrics domain_authority for the publication domain",
            "confidence": "high",
            "estimated": False,
            "observed_at": "2026-08-13",
            "raw_value": "76/100",
        },
    }
    assert score.components["impact"]["score"] is None
    assert score.components["quality"]["score"] is None
    assert score.components["outlet_audience"]["status"] == "evidence_only"
    assert score.components["outlet_audience"]["score"] is None


def test_opr_and_internal_audience_fallback_are_not_score_inputs():
    score = calculate_shift6_score(
        {
            "site_authority": {
                "value": "72/100",
                "source": "Open PageRank",
                "confidence": "medium",
                "estimated": True,
            },
            "monthly_audience": {
                "value": "~100,000",
                "source": "Internal authority-based fallback",
                "confidence": "low",
                "estimated": True,
            },
        }
    )

    assert score.status == "unscorable"
    assert score.total_score is None
    assert score.components["outlet_strength"]["score"] is None
    assert score.components["outlet_audience"]["provenance"] is None
    assert render_shift6_score_markdown(score) == ""


def test_partial_score_note_is_transparent_about_draft_and_pending_total():
    note = render_shift6_score_markdown(calculate_shift6_score({"site_authority": MOZ_METRIC}))

    assert note.startswith("## Shift6 Score (Draft)")
    assert "Composite score: **Pending**" in note
    assert "Missing components are not reweighted" in note
    assert "Outlet strength: **76/100**" in note
    assert "awaiting Lexi review" in note
    assert "Impact click bands remain pending calibration" in note


@pytest.mark.asyncio
async def test_summarize_persists_revision_metrics_and_versioned_partial_score(monkeypatch):
    document = ArticleDocument(
        requested_url="https://www.publisher.example/story",
        final_url="https://publisher.example/story",
        canonical_url="https://publisher.example/story",
        domain="www.publisher.example",
        publication="The Publisher",
        title="Acme launches | Publisher",
        description="A publication.",
        body="Acme announced a launch.",
        links=[{"text": "Acme", "url": "https://acme.example/about"}],
        fetched_at="2026-08-13T15:30:00+00:00",
        content_sha256="c" * 64,
        source_method="direct_http",
        author="Jane Reporter",
        published_at=datetime(2026, 8, 12, 14, 0, tzinfo=timezone.utc),
        published_date_raw="2026-08-12T09:00:00-05:00",
        published_date_source="json_ld.datePublished",
        published_date_confidence="high",
        published_date_candidates=[
            {
                "raw": "2026-08-12T09:00:00-05:00",
                "source": "json_ld.datePublished",
                "confidence": "high",
                "published_at": "2026-08-12T14:00:00+00:00",
            }
        ],
    )

    async def fake_fetch(_url):
        return document

    async def fake_about(_domain):
        return "Publisher description"

    async def fake_metrics(_domain, cached_metrics=None):
        return {"site_authority": MOZ_METRIC, "monthly_audience": SEMRUSH_METRIC}

    async def fake_summary(_data):
        return "Verified markdown"

    monkeypatch.setattr(email_router, "fetch_or_scrape", fake_fetch)
    monkeypatch.setattr(email_router, "try_fetch_about_description", fake_about)
    monkeypatch.setattr(email_router, "lookup_da_muv", fake_metrics)
    monkeypatch.setattr(email_router, "_cached_publication_metrics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(email_router, "summarize_to_markdown", fake_summary)
    monkeypatch.setattr(email_router, "embed_texts", lambda _texts: [np.zeros(768)])
    monkeypatch.setattr(
        email_router,
        "queue_screenshot_capture",
        lambda *_args, **_kwargs: (
            types.SimpleNamespace(id=91, kind="screenshot_full", status="pending"),
            types.SimpleNamespace(id=92, kind="screenshot_thumbnail", status="pending"),
        ),
    )
    scheduled_captures = []
    monkeypatch.setattr(
        email_router,
        "schedule_screenshot_capture",
        lambda **kwargs: scheduled_captures.append(kwargs),
    )

    class FakeQuery:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class FakeSession:
        def __init__(self):
            self.added = []
            self.next_id = 1

        def query(self, *_models):
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

    publication = next(value for value in db.added if isinstance(value, Publication))
    article = next(value for value in db.added if isinstance(value, Article))
    revision = next(value for value in db.added if isinstance(value, ArticleSourceRevision))
    summary = next(value for value in db.added if isinstance(value, ArticleSummary))
    score = next(value for value in db.added if isinstance(value, CoverageScoreSnapshot))
    metric_rows = [value for value in db.added if isinstance(value, PublicationMetricSnapshot)]

    assert publication.domain == "publisher.example"
    assert article.publication_id == publication.id
    assert article.published_at_utc == document.published_at
    assert article.published_date_source == "json_ld.datePublished"
    assert revision.article_id == article.id
    assert revision.body == document.body
    assert revision.links == document.links
    assert summary.source_revision_id == revision.id
    assert score.source_revision_id == revision.id
    assert score.methodology_version == METHODOLOGY_VERSION
    assert score.formula_hash == FORMULA_HASH
    assert score.status == "partial"
    assert score.total_score is None
    assert score.inputs["source_revision"]["source_sha256"] == "c" * 64
    assert len(metric_rows) == 2
    assert {row.provider for row in metric_rows} == {
        "Moz Link Explorer API v2",
        "Semrush website traffic overview",
    }
    assert {row.metric_key: row.value_numeric for row in metric_rows} == {
        "site_authority": Decimal("76"),
        "monthly_audience": Decimal("136000"),
    }
    assert result["source_revision_id"] == revision.id
    assert result["shift6_score"]["status"] == "partial"
    assert result["shift6_score"]["total_score"] is None
    assert result["evidence"]["status"] == "pending"
    assert scheduled_captures == [{"article_id": article.id, "source_revision_id": revision.id}]
    assert "## Shift6 Score (Draft)" in result["body_markdown"]
    assert "Composite score: **Pending**" in result["body_markdown"]
    assert any(isinstance(value, ArticleEmbedding) for value in db.added)


def test_history_and_summary_responses_include_the_persisted_score_snapshot():
    article = Article(
        id=4,
        client_name="Acme",
        url="https://publisher.example/story",
        domain="publisher.example",
        title="Story",
        publication="Publisher",
    )
    summary = ArticleSummary(
        id=8,
        article_id=4,
        source_revision_id=12,
        markdown="Verified markdown",
        subject="Coverage Live: Publisher",
        validation_status="source_verified",
        metrics={},
        created_at=datetime(2026, 8, 13, 16, 0),
    )
    score = CoverageScoreSnapshot(
        id=16,
        article_id=4,
        source_revision_id=12,
        methodology_version=METHODOLOGY_VERSION,
        formula_hash=FORMULA_HASH,
        status="partial",
        total_score=None,
        components=calculate_shift6_score({"site_authority": MOZ_METRIC}).components,
        inputs={"methodology": METHODOLOGY_SPEC},
    )

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def join(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def offset(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return self.result

        def first(self):
            if isinstance(self.result, list):
                return self.result[0] if self.result else None
            return self.result

    class FakeSession:
        def query(self, *models):
            if models == (CoverageScoreSnapshot,):
                return FakeQuery(score)
            return FakeQuery([(summary, article)] if len(models) == 2 else None)

    db = FakeSession()
    history = email_router.history(limit=5, offset=0, client_name="Acme", db=db)
    detail = email_router.get_summary(summary_id=8, client_name="Acme", db=db)

    assert history["items"][0]["source_revision_id"] == 12
    assert history["items"][0]["shift6_score"]["formula_hash"] == FORMULA_HASH
    assert history["items"][0]["shift6_score"]["total_score"] is None
    assert detail["source_revision_id"] == 12
    assert detail["shift6_score"]["status"] == "partial"
