"""
Unit tests for expert_constraints.py — Pydantic models and constraint data.

Tests:
- Pydantic schema validation for LocalExpertOutput and sub-models
"""

from __future__ import annotations

import importlib
from pathlib import Path

from app.planner.nodes.expert_constraints import (
    AirportTransfer,
    Connectivity,
    DailyBudget,
    DestinationOverview,
    ElectricalInfo,
    Festival,
    LocalConstraint,
    LocalExpertOutput,
    LocalRecommendation,
    MoneyCosts,
    MustDoExperience,
    Neighborhood,
    SafetyHealth,
    Scam,
    VisaEntry,
)

_le_mod = importlib.import_module("app.planner.nodes.local_expert")
_LOCAL_EXPERT_PROMPT = (
    Path(__file__).resolve().parent.parent / "app" / "prompts" / "specialists" / "local_expert.txt"
)


def _schema_contains_key(node: object, key: str) -> bool:
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_schema_contains_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_schema_contains_key(item, key) for item in node)
    return False


class TestPydanticModels:
    """Test that all schema models instantiate with defaults and validate."""

    def test_local_constraint_defaults(self) -> None:
        c = LocalConstraint(description="Test constraint")
        assert c.type == "general"
        assert c.severity == "info"

    def test_local_recommendation_required_fields(self) -> None:
        r = LocalRecommendation(
            title="Test Rec",
            description="A test recommendation",
        )
        assert r.category == "logistics"

    def test_local_expert_output_defaults(self) -> None:
        """Full output model should instantiate with all defaults."""
        output = LocalExpertOutput()
        assert output.constraints == []
        assert output.recommendations == []
        assert output.quick_tips == []
        assert isinstance(output.visa_entry, VisaEntry)
        assert isinstance(output.safety_health, SafetyHealth)
        assert isinstance(output.money_costs, MoneyCosts)

    def test_daily_budget_defaults(self) -> None:
        b = DailyBudget()
        assert b.backpacker == ""
        assert b.mid_range == ""
        assert b.luxury == ""

    def test_airport_transfer_required(self) -> None:
        t = AirportTransfer(method="Taxi")
        assert t.method == "Taxi"
        assert t.price == ""

    def test_safety_health_defaults(self) -> None:
        s = SafetyHealth()
        assert s.overall_safety == "Safe"
        assert s.tap_water_safe is False
        assert s.common_concerns == []

    def test_visa_entry_defaults(self) -> None:
        v = VisaEntry()
        assert v.visa_on_arrival is False
        assert v.max_stay_days == 30
        assert v.passport_validity_months == 6

    def test_connectivity_defaults(self) -> None:
        c = Connectivity()
        assert c.esim_works is True
        assert c.essential_apps == []

    def test_festival_required_name(self) -> None:
        f = Festival(name="Nyepi")
        assert f.name == "Nyepi"
        assert f.when == ""

    def test_scam_required_name(self) -> None:
        s = Scam(name="Taxi meter scam")
        assert s.how_it_works == ""
        assert s.how_to_avoid == ""

    def test_electrical_info_defaults(self) -> None:
        e = ElectricalInfo()
        assert e.adapter_needed is True

    def test_must_do_experience(self) -> None:
        m = MustDoExperience(name="Temple Visit")
        assert m.why == ""
        assert m.booking == ""
        assert m.cost == ""

    def test_neighborhood_required_name(self) -> None:
        n = Neighborhood(name="Seminyak")
        assert n.vibe == ""
        assert n.best_for == []

    def test_full_output_with_populated_data(self) -> None:
        """Round-trip: populate key fields and verify."""
        output = LocalExpertOutput(
            destination_overview=DestinationOverview(
                tagline="Island of the Gods",
                best_for=["diving", "surfing"],
                vibe="tropical paradise",
            ),
            visa_entry=VisaEntry(visa_on_arrival=True, max_stay_days=30),
            constraints=[
                LocalConstraint(
                    type="cultural",
                    description="Dress modestly in temples",
                    severity="warning",
                )
            ],
            quick_tips=["Carry cash", "Drink bottled water"],
        )
        assert output.destination_overview.tagline == "Island of the Gods"
        assert len(output.constraints) == 1
        assert output.constraints[0].severity == "warning"
        assert len(output.quick_tips) == 2


class TestLocalExpertStructuredOutputContract:
    def test_flat_schema_has_no_defs_or_refs(self) -> None:
        schema = _le_mod._LOCAL_EXPERT_FLAT_SCHEMA
        assert "$defs" not in schema
        assert not _schema_contains_key(schema, "$ref")


class TestLocalExpertPromptContract:
    def test_prompt_avoids_removed_json_keys(self) -> None:
        prompt = _LOCAL_EXPERT_PROMPT.read_text()
        for removed_key in (
            "visa_free_for",
            "street_food_safe",
            "public_transit",
            "scooter_rental",
            "avoid_months",
            "day_trips",
            "hidden_gems",
            "tourist_traps",
            "buy_locally",
            "clothing_tips",
        ):
            assert f'"{removed_key}"' not in prompt

    def test_prompt_mentions_current_schema_fields(self) -> None:
        prompt = _LOCAL_EXPERT_PROMPT.read_text()
        for current_key in (
            "passport_validity_months",
            "traffic_note",
            "important_taboos",
            "book_ahead",
            "constraints",
            "recommendations",
            "quick_tips",
        ):
            assert f'"{current_key}"' in prompt
