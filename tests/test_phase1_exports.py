from __future__ import annotations

import csv
import io
import sys


sys.path.insert(0, "backend")

from app.services.email.coverage_records import csv_safe, records_to_csv


def test_csv_safe_neutralizes_formula_cells_without_changing_normal_urls():
    assert csv_safe("=HYPERLINK(\"https://bad.example\")") == "'=HYPERLINK(\"https://bad.example\")"
    assert csv_safe("+SUM(1,2)") == "'+SUM(1,2)"
    assert csv_safe("https://publisher.example/story") == "https://publisher.example/story"


def test_records_to_csv_flattens_provenance_and_evidence():
    content = records_to_csv(
        [
            {
                "summary_id": 7,
                "article_id": 4,
                "client_name": "Acme",
                "publication": "Publisher",
                "domain": "publisher.example",
                "title": "=A dangerous spreadsheet title",
                "url": "https://publisher.example/story",
                "published_at": "2026-08-11T12:00:00Z",
                "published_date_source": "json_ld.datePublished",
                "published_date_confidence": "high",
                "source_fetched_at": "2026-08-13T11:59:00Z",
                "captured_at": "2026-08-13T12:00:00Z",
                "metrics": {
                    "site_authority": {
                        "value": "76/100",
                        "source": "Moz Link Explorer API v2",
                        "method": "URL Metrics domain_authority",
                        "confidence": "high",
                        "observed_at": "2026-08-11",
                    },
                    "monthly_audience": {
                        "value": "~136,000",
                        "source": "Semrush website traffic overview",
                        "method": "all-device monthly visits",
                        "confidence": "medium",
                        "observed_at": "2026-07-01",
                    },
                },
                "score": {
                    "total": None,
                    "status": "partial",
                    "methodology_version": "shift6-2026-draft.1",
                    "formula_hash": "abc",
                    "components": {"impact": {"status": "pending_calibration"}},
                    "inputs": {"methodology_approval": "pending_lexi_review"},
                },
                "evidence": [
                    {
                        "id": 11,
                        "kind": "screenshot_full",
                        "status": "ready",
                        "url": "/api/v1/email/evidence/11",
                        "sha256": "def",
                        "captured_at": "2026-08-13T12:00:00Z",
                    }
                ],
            }
        ]
    )
    row = next(csv.DictReader(io.StringIO(content)))
    assert row["title"].startswith("'=")
    assert row["site_authority_source"] == "Moz Link Explorer API v2"
    assert row["shift6_score_status"] == "partial"
    assert row["source_fetched_at"] == "2026-08-13T11:59:00Z"
    assert row["captured_at"] == "2026-08-13T12:00:00Z"
    assert row["screenshot_ids"] == "11"
    assert row["screenshot_urls"] == "/api/v1/email/evidence/11"
