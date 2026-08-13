from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


METHODOLOGY_VERSION = "shift6-draft-2026-08-11"
METHODOLOGY_STATUS = "awaiting_lexi_review"
VERIFIED_AUDIENCE_PROVIDERS = {
    "Semrush website traffic overview",
}

# This is intentionally a small, immutable specification.  The top-level
# weights are the only score rules documented in the August 11 coverage book.
# In particular, it does not invent impact click bands, a quality rubric, or an
# audience-normalization curve that the source material does not define.
METHODOLOGY_SPEC: dict[str, Any] = {
    "methodology_version": METHODOLOGY_VERSION,
    "status": METHODOLOGY_STATUS,
    "source": {
        "document": "Weekly_Notes_Master_List.docx",
        "document_updated": "2026-08-11",
        "formula_location": "page 4",
    },
    "formula": {
        "scale": "0-100",
        "missing_input_policy": "do_not_reweight; total_score_is_null",
        "components": {
            "impact": {"weight_percent": 35},
            "quality": {"weight_percent": 30},
            "outlet_strength": {"weight_percent": 20},
            "outlet_audience": {"weight_percent": 15},
        },
    },
    "rules": {
        "impact": {
            "rule_id": "pending_impact_click_band_calibration",
            "status": "pending",
            "note": "Impact click bands require calibration from real trackable-link data.",
        },
        "quality": {
            "rule_id": "pending_quality_rubric_review",
            "status": "pending",
            "note": "No approved quality sub-rubric was present in the available methodology source.",
        },
        "outlet_strength": {
            "rule_id": "moz_domain_authority_identity_v1",
            "status": "active",
            "note": "A real, high-confidence Moz Domain Authority value is already on a 0-100 scale.",
        },
        "outlet_audience": {
            "rule_id": "pending_audience_normalization_review",
            "status": "pending",
            "note": "Verified audience evidence may be retained, but no approved 0-100 normalization rule is available.",
        },
    },
}


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


FORMULA_HASH = hashlib.sha256(_canonical_json(METHODOLOGY_SPEC).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Shift6Score:
    methodology_version: str
    methodology_status: str
    formula_hash: str
    status: str
    total_score: float | None
    components: dict[str, dict[str, Any]]
    inputs: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "methodology_version": self.methodology_version,
            "methodology_status": self.methodology_status,
            "formula_hash": self.formula_hash,
            "status": self.status,
            "total_score": self.total_score,
            "components": deepcopy(self.components),
        }


def _metric_value_0_100(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    else:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:/\s*100)?\s*", str(value or ""))
        if not match:
            return None
        parsed = float(match.group(1))
    return round(parsed, 2) if 0 <= parsed <= 100 else None


def _base_component(name: str) -> dict[str, Any]:
    formula = METHODOLOGY_SPEC["formula"]["components"][name]
    rule = METHODOLOGY_SPEC["rules"][name]
    return {
        "weight_percent": formula["weight_percent"],
        "score": None,
        "weighted_points": None,
        "status": "unavailable",
        "rule_id": rule["rule_id"],
        "reason": rule["note"],
        "provenance": None,
    }


def _eligible_audience_evidence(metric: Mapping[str, Any]) -> bool:
    provider = str(metric.get("source") or "").strip()
    publisher_verified = (
        metric.get("provider_type") == "publisher"
        and str(metric.get("confidence") or "").lower() == "high"
        and metric.get("estimated") is False
    )
    if provider not in VERIFIED_AUDIENCE_PROVIDERS and not publisher_verified:
        return False
    return bool(metric.get("value")) and str(metric.get("value")).lower() != "unavailable"


def calculate_shift6_score(metrics: Mapping[str, Any] | None) -> Shift6Score:
    """Calculate only the portions of the draft score backed by explicit rules.

    Missing components never redistribute their weights.  Until all four
    approved 0-100 component scores exist, ``total_score`` is deliberately
    null.  This makes partial evidence visible without publishing a misleading
    composite.
    """

    metric_snapshot = deepcopy(dict(metrics or {}))
    components = {
        name: _base_component(name)
        for name in ("impact", "quality", "outlet_strength", "outlet_audience")
    }

    authority = metric_snapshot.get("site_authority")
    if isinstance(authority, Mapping):
        authority_score = _metric_value_0_100(authority.get("value"))
        is_real_moz = (
            authority.get("source") == "Moz Link Explorer API v2"
            and str(authority.get("confidence") or "").lower() == "high"
            and authority.get("estimated") is False
        )
        if is_real_moz and authority_score is not None:
            components["outlet_strength"].update(
                {
                    "score": authority_score,
                    "weighted_points": round(authority_score * 0.20, 2),
                    "status": "scored",
                    "reason": None,
                    "provenance": {
                        "provider": authority.get("source"),
                        "method": authority.get("method"),
                        "confidence": authority.get("confidence"),
                        "estimated": False,
                        "observed_at": authority.get("observed_at"),
                        "raw_value": authority.get("value"),
                    },
                }
            )
        elif authority_score is not None:
            components["outlet_strength"]["reason"] = (
                "Outlet strength requires a real, high-confidence Moz Domain Authority value; "
                "estimates and Open PageRank are not eligible."
            )

    audience = metric_snapshot.get("monthly_audience")
    if isinstance(audience, Mapping) and _eligible_audience_evidence(audience):
        components["outlet_audience"].update(
            {
                "status": "evidence_only",
                "reason": (
                    "Verified provider or publisher audience evidence is retained, but no approved "
                    "0-100 audience normalization rule is available."
                ),
                "provenance": {
                    "provider": audience.get("source"),
                    "method": audience.get("method"),
                    "confidence": audience.get("confidence"),
                    "estimated": audience.get("estimated"),
                    "observed_at": audience.get("observed_at"),
                    "raw_value": audience.get("value"),
                },
            }
        )

    scored = [component for component in components.values() if component["status"] == "scored"]
    if len(scored) == len(components):
        status = "complete"
        total_score = round(sum(component["weighted_points"] for component in scored), 2)
    elif scored:
        status = "partial"
        total_score = None
    else:
        status = "unscorable"
        total_score = None

    return Shift6Score(
        methodology_version=METHODOLOGY_VERSION,
        methodology_status=METHODOLOGY_STATUS,
        formula_hash=FORMULA_HASH,
        status=status,
        total_score=total_score,
        components=components,
        inputs={
            "publication_metrics": metric_snapshot,
            "methodology": deepcopy(METHODOLOGY_SPEC),
        },
    )


def render_shift6_score_markdown(score: Shift6Score) -> str:
    """Render a factual client-facing note when at least one component is scored."""

    if score.status == "unscorable":
        return ""

    component = score.components["outlet_strength"]
    lines = [
        "## Shift6 Score (Draft)",
        "",
        "Composite score: **Pending**",
        "",
        (
            "The draft methodology weights Impact 35%, Quality 30%, Outlet strength 20%, and "
            "Outlet audience 15%. Missing components are not reweighted, so no total is published "
            "until all four component scores are available."
        ),
    ]
    if component["status"] == "scored":
        lines.extend(
            [
                "",
                f"Outlet strength: **{component['score']:g}/100** (verified Moz Domain Authority).",
            ]
        )
    lines.extend(
        [
            "",
            (
                "Methodology status: awaiting Lexi review. Impact click bands remain pending "
                "calibration from real trackable-link data."
            ),
        ]
    )
    return "\n".join(lines)
