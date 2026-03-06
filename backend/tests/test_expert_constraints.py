"""
Unit tests for expert_constraints.py — Pydantic models and constraint data.

Tests:
- LOCAL_EXPERT_CONSTRAINTS data integrity (all entries well-formed)
- _get_constraint_context() prompt formatting
- _get_constraints_as_list() raw constraint retrieval
- _get_static_must_dos() deprecated (always returns [])
- Pydantic schema validation for LocalExpertOutput and sub-models
"""

from __future__ import annotations

from app.planner.nodes.expert_constraints import (
    LOCAL_EXPERT_CONSTRAINTS,
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
    _get_constraint_context,
    _get_constraints_as_list,
    _get_static_must_dos,
)

# =============================================================================
# Data integrity for LOCAL_EXPERT_CONSTRAINTS
# =============================================================================


class TestConstraintDataIntegrity:
    """All entries in LOCAL_EXPERT_CONSTRAINTS must be well-formed."""

    VALID_SEVERITY = {"warning", "info"}
    VALID_TYPES = {
        "cultural",
        "seasonal",
        "safety",
        "transport",
        "booking_window",
        "opening_hours",
        "general",
    }

    def test_all_keys_are_lowercase(self) -> None:
        for key in LOCAL_EXPERT_CONSTRAINTS:
            assert key == key.lower(), f"Key {key!r} should be lowercase"

    def test_all_entries_have_constraints(self) -> None:
        for key, entry in LOCAL_EXPERT_CONSTRAINTS.items():
            assert "constraints" in entry, f"{key} missing 'constraints'"
            assert isinstance(entry["constraints"], list)
            assert len(entry["constraints"]) > 0, f"{key} has empty constraints"

    def test_no_entries_have_must_dos(self) -> None:
        """must_dos have been removed from all entries."""
        for key, entry in LOCAL_EXPERT_CONSTRAINTS.items():
            assert "must_dos" not in entry, f"{key} should not have 'must_dos'"

    def test_constraint_fields_valid(self) -> None:
        for key, entry in LOCAL_EXPERT_CONSTRAINTS.items():
            for i, c in enumerate(entry["constraints"]):
                assert "type" in c, f"{key} constraint[{i}] missing 'type'"
                assert "desc" in c, f"{key} constraint[{i}] missing 'desc'"
                assert "severity" in c, f"{key} constraint[{i}] missing 'severity'"

                assert c["severity"] in self.VALID_SEVERITY, (
                    f"{key} constraint[{i}] has invalid severity: {c['severity']!r}"
                )
                assert c["type"] in self.VALID_TYPES, (
                    f"{key} constraint[{i}] has invalid type: {c['type']!r}"
                )
                assert len(c["desc"]) > 10, f"{key} constraint[{i}] desc too short: {c['desc']!r}"

    def test_entries_only_have_constraints_key(self) -> None:
        """After must_dos removal, entries should only contain 'constraints'."""
        for key, entry in LOCAL_EXPERT_CONSTRAINTS.items():
            assert set(entry.keys()) == {"constraints"}, (
                f"{key} has unexpected keys: {set(entry.keys())}"
            )

    def test_known_destinations_present(self) -> None:
        expected = {"paris", "tokyo", "bali", "london", "rome", "dubai"}
        actual = set(LOCAL_EXPERT_CONSTRAINTS.keys())
        missing = expected - actual
        assert not missing, f"Missing expected destinations: {missing}"


# =============================================================================
# _get_constraint_context
# =============================================================================


class TestGetConstraintContext:
    def test_known_destination_returns_context(self) -> None:
        result = _get_constraint_context("Bali")
        assert result != ""
        assert "Known constraints" in result
        assert "Bali" in result

    def test_case_insensitive_lookup(self) -> None:
        result = _get_constraint_context("PARIS")
        assert result != ""
        assert "Paris" in result or "PARIS" in result

    def test_unknown_destination_returns_empty(self) -> None:
        result = _get_constraint_context("Atlantis")
        assert result == ""

    def test_severity_tags_present(self) -> None:
        result = _get_constraint_context("Bali")
        assert "[WARNING]" in result or "[INFO]" in result

    def test_partial_match_works(self) -> None:
        """'New York City' should match 'new york' key."""
        result = _get_constraint_context("New York City")
        assert result != ""
        assert "constraint" in result.lower() or "Known" in result

    def test_whitespace_handling(self) -> None:
        result = _get_constraint_context("  tokyo  ")
        assert result != ""


# =============================================================================
# _get_constraints_as_list
# =============================================================================


class TestGetConstraintsAsList:
    def test_returns_list_of_dicts(self) -> None:
        result = _get_constraints_as_list("Dubai")
        assert isinstance(result, list)
        assert len(result) > 0
        for c in result:
            assert isinstance(c, dict)
            assert "type" in c
            assert "desc" in c

    def test_unknown_returns_empty_list(self) -> None:
        result = _get_constraints_as_list("Narnia")
        assert result == []

    def test_matches_source_data(self) -> None:
        result = _get_constraints_as_list("paris")
        source = LOCAL_EXPERT_CONSTRAINTS["paris"]["constraints"]
        assert len(result) == len(source)


# =============================================================================
# _get_static_must_dos
# =============================================================================


class TestGetStaticMustDos:
    """_get_static_must_dos is deprecated and always returns []."""

    def test_always_returns_empty(self) -> None:
        result = _get_static_must_dos("Bali")
        assert result == []

    def test_unknown_returns_empty(self) -> None:
        result = _get_static_must_dos("Mordor")
        assert result == []

    def test_known_destination_returns_empty(self) -> None:
        result = _get_static_must_dos("Tokyo")
        assert result == []


# =============================================================================
# Pydantic model validation
# =============================================================================


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
