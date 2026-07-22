from __future__ import annotations

import sys

sys.path.insert(0, "backend")

from app.services.coverage.matching import (
    has_client_name,
    has_normalized_exact_quote,
    normalize_for_exact_match,
)


def test_exact_quote_matching_normalizes_typography_and_whitespace():
    quote = '“Coverage should be accurate — every single time.”'
    article = 'Acme said, "Coverage should be accurate - every\n single time."'
    assert has_normalized_exact_quote(quote, article)


def test_exact_quote_matching_rejects_embedded_partial_words():
    assert not has_normalized_exact_quote("coverage matters", "precoverage matterstone")


def test_client_matching_uses_name_boundaries():
    assert has_client_name("Acme", "Acme announced a launch")
    assert not has_client_name("Acme", "Acmeology announced a launch")


def test_normalization_is_case_insensitive_without_rewriting_words():
    assert normalize_for_exact_match("  ACME   Launches ") == "acme launches"
