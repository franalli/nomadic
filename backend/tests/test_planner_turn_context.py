"""Tests for the planner's per-turn model context (prompts/planner.py).

The model re-listed a generic travel checklist (visa/insurance/embassy/currency)
in chat every turn because that boilerplate was re-injected into CURRENT CONTEXT
each turn via the "Active constraints" line. These tests pin the deterministic
fix: generic-fallback constraints are filtered OUT of the model context, while
real specialist safety constraints survive so the model can still cite them.
"""

from app.planner.prompts.planner import build_trip_state_summary, build_turn_context
from app.planner.tools.get_local_intel import _GENERIC_FALLBACK_CONSTRAINTS

_BOILERPLATE_PHRASES = [
    "visa",
    "insurance",
    "photocopies",
    "embassy",
    "Confirm hotel bookings",
    "exchange options",
]

_REAL_CONSTRAINT = {
    "constraint_id": "no_fly_24h",
    "rule": "no_fly_24h",
    "label": "24h no-fly buffer after diving",
    "type": "temporal",
    "severity": "blocking",
}


def _base_state(constraints):
    return {
        "trip_plan": {
            "destination": "Bali",
            "start_date": "2026-07-01",
            "end_date": "2026-07-07",
            "activity_categories": ["diving"],
        },
        "constraints": constraints,
        "tiles": {},
        "day_cards": [],
    }


def test_generic_fallback_constraints_excluded_from_model_context():
    """The 6 generic travel-info constraints must never reach the model context."""
    # Use the real source list so this also guards the generic_fallback tag.
    state = _base_state([dict(c) for c in _GENERIC_FALLBACK_CONSTRAINTS])
    context = build_turn_context(state)

    for phrase in _BOILERPLATE_PHRASES:
        assert phrase.lower() not in context.lower(), (
            f"generic boilerplate '{phrase}' leaked into the per-turn model context"
        )
    # When every constraint is generic, the constraints line is omitted entirely.
    assert "safety constraints" not in context.lower()


def test_real_specialist_constraint_survives():
    """Genuine safety constraints stay in context so the model can cite them."""
    state = _base_state([_REAL_CONSTRAINT])
    summary = build_trip_state_summary(state)

    assert "safety constraints" in summary.lower()
    assert "24h no-fly buffer after diving" in summary


def test_mixed_constraints_keep_only_real_ones():
    """A mix renders only the real constraint; the generic floor is dropped."""
    state = _base_state([*[dict(c) for c in _GENERIC_FALLBACK_CONSTRAINTS], _REAL_CONSTRAINT])
    summary = build_trip_state_summary(state)

    assert "24h no-fly buffer after diving" in summary
    for phrase in _BOILERPLATE_PHRASES:
        assert phrase.lower() not in summary.lower()


def test_generic_fallback_constraints_are_tagged():
    """Guard the provenance flag the filter depends on."""
    assert all(c.get("generic_fallback") is True for c in _GENERIC_FALLBACK_CONSTRAINTS)


# --- Model-facing get_local_intel summary (Option X: tool-result on the call turn) ---


def test_local_intel_summary_drops_generic_checklist():
    """The model-facing get_local_intel summary must carry no generic boilerplate."""
    import json as _json

    from app.planner.middleware import _summarize_local_intel_for_model

    # A realistic skeleton result: generic floor in both `constraints` and the section tips.
    parsed = {
        "destination": "Bali",
        "constraints": [dict(c) for c in _GENERIC_FALLBACK_CONSTRAINTS],
        "section": {
            "content_added": [
                {"type": "tip", "title": "Check visa requirements before travel"},
                {"type": "tip", "title": "Carry photocopies of passport and important documents"},
            ]
        },
        "enrichment_status": "pending",
    }
    summary = _summarize_local_intel_for_model(parsed)
    low = summary.lower()
    for phrase in _BOILERPLATE_PHRASES:
        assert phrase.lower() not in low, f"'{phrase}' leaked into the model-facing intel summary"
    # Still a parseable dict that names the destination so the model knows intel ran.
    payload = _json.loads(summary)
    assert payload["destination"] == "Bali"
    assert "safety_constraints" not in payload  # only generic constraints → none preserved


def test_local_intel_summary_preserves_real_constraints():
    """A genuine (non-generic) constraint survives into the model-facing summary."""
    import json as _json

    from app.planner.middleware import _summarize_local_intel_for_model

    parsed = {
        "destination": "Bali",
        "constraints": [
            *[dict(c) for c in _GENERIC_FALLBACK_CONSTRAINTS],
            {"rule": "typhoon_season_advisory", "label": "Typhoon season advisory"},
        ],
    }
    payload = _json.loads(_summarize_local_intel_for_model(parsed))
    assert payload["safety_constraints"] == ["Typhoon season advisory"]
