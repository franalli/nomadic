"""
Tests for the PlanDocument-based API.
Tests document creation, retrieval, patching, and session deletion.
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import app.db_models as models  # noqa: E402  pylint: disable=C0413
from app.db import Base, get_db  # noqa: E402  pylint: disable=C0413
from app.main import app  # noqa: E402  pylint: disable=C0413

TEST_DB_PATH = BACKEND_DIR / "test_plan_document_pytest.db"
TEST_DATABASE_URL = f"sqlite+pysqlite:///{TEST_DB_PATH.as_posix()}"
engine = create_engine(
    TEST_DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_session_with_document(session_token: str = "session-123") -> dict:
    """Create a session with a PlanDocument containing branches and tiles."""
    with TestingSessionLocal() as db:
        # Explicitly set timezone-aware datetimes for SQLite compatibility
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=90)
        session = models.Session(
            session_token=session_token,
            last_activity_at=now,
            expires_at=expires_at,
        )
        db.add(session)
        db.flush()

        trip_ctx = models.TripContext(
            session_id=session.id,
            raw_prompt="Some context",
        )
        db.add(trip_ctx)
        db.flush()

        # Create the PlanDocument with branches and tiles
        document_data = {
            "trip_context_id": trip_ctx.id,
            "trip_inputs": {
                "destinations": ["Nice"],
                "origin": "London",
                "start_date": "2025-12-01",
                "end_date": "2025-12-07",
                "traveler_count": 2,
                "budget": 2000,
                "missing_fields": [],
            },
            "branches": [
                {
                    "id": "branch_1",
                    "label": "Beach Escape",
                    "description": "Relax on the coast",
                    "destinations": ["Nice"],
                    "origin": "London",
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-07",
                    "traveler_count": 2,
                    "budget": 2000,
                    "is_primary": True,
                    "tiles": {
                        "stays": ["tile_1"],
                        "flights": [],
                        "activities": [],
                    },
                    "selections": {
                        "stay": None,
                        "flight": None,
                        "activities": [],
                    },
                },
                {
                    "id": "branch_2",
                    "label": "City Lights",
                    "description": "Explore the city",
                    "destinations": ["Paris"],
                    "origin": "London",
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-07",
                    "traveler_count": 2,
                    "budget": 2000,
                    "is_primary": False,
                    "tiles": {
                        "stays": [],
                        "flights": [],
                        "activities": [],
                    },
                    "selections": {
                        "stay": None,
                        "flight": None,
                        "activities": [],
                    },
                },
            ],
            "tiles": {
                "tile_1": {
                    "id": "tile_1",
                    "type": "hotel",
                    "partner": "nomadic",
                    "partner_product_id": "hotel-1",
                    "title": "Seaside Hotel",
                    "subtitle": "Cozy stay",
                    "image_url": None,
                    "price_estimate": 120.0,
                    "currency": "EUR",
                    "price_basis": "per_night",
                    "is_estimate_only": True,
                    "deeplink_url": "https://example.com/hotel",
                    "rating": 4.5,
                    "review_count": 120,
                    "tags": ["beach"],
                    "location_label": "Nice, France",
                    "meta": {},
                    "availability_status": "unknown",
                },
            },
        }

        plan_doc = models.PlanDocument(
            session_id=session.id,
            version=1,
            updated_by="planner",
            document=document_data,
        )
        db.add(plan_doc)
        db.commit()

        return {
            "session_token": session_token,
            "trip_context_id": trip_ctx.id,
            "document_id": plan_doc.id,
        }


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

# CSRF token for tests - must match what we set in cookies
TEST_CSRF_TOKEN = "test-csrf-token-12345"


def get_session_cookies(session_token: str) -> dict:
    """Get cookies dict for a session."""
    return {
        "session_id": session_token,
        "csrf": TEST_CSRF_TOKEN,
    }


def get_csrf_headers() -> dict:
    """Get headers with CSRF token for unsafe methods."""
    return {"X-CSRF-Token": TEST_CSRF_TOKEN}


def setup_module(_: object):
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Enable WAL mode for better concurrency with SQLite
    import sqlite3

    conn = sqlite3.connect(TEST_DB_PATH.as_posix())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()


def teardown_module(_: object):
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_get_document_returns_branches_and_tiles():
    """Test that GET /v1/document returns the document with branches and tiles."""
    seed = seed_session_with_document(session_token="session-get-doc")

    response = client.get(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["version"] == 1
    assert payload["updated_by"] == "planner"
    assert "updated_at" in payload

    doc = payload["document"]
    assert doc["trip_context_id"] == seed["trip_context_id"]
    assert len(doc["branches"]) == 2
    assert doc["branches"][0]["label"] == "Beach Escape"
    assert doc["branches"][0]["is_primary"] is True
    assert doc["branches"][1]["destinations"] == ["Paris"]

    assert "tile_1" in doc["tiles"]
    assert doc["tiles"]["tile_1"]["title"] == "Seaside Hotel"


def test_get_document_handles_missing_session():
    """Test that GET /v1/document returns 404 for missing session."""
    response = client.get(
        "/v1/document",
        cookies=get_session_cookies("missing-session"),
    )

    assert response.status_code == 404
    assert "Session not found" in response.json()["detail"]


def test_patch_document_updates_selections():
    """Test that PATCH /v1/document updates tile selections."""
    seed = seed_session_with_document(session_token="session-patch-doc")

    # Update selections for branch_1
    patch = {
        "version": 1,
        "selections": {
            "branch_1": {
                "stay": "tile_1",
                "flight": None,
                "activities": [],
            },
        },
    }

    response = client.patch(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json=patch,
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["version"] == 2  # Version incremented
    assert payload["updated_by"] == "user"

    # Check that selections were updated
    branch_1 = next(b for b in payload["document"]["branches"] if b["id"] == "branch_1")
    assert branch_1["selections"]["stay"] == "tile_1"


def test_session_delete_wipes_document():
    """Test that DELETE /v1/session removes the PlanDocument."""
    seed = seed_session_with_document(session_token="session-delete-doc")

    response = client.delete(
        "/v1/session",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
    )

    assert response.status_code == 204

    # Verify session and document are gone
    with TestingSessionLocal() as db:
        session_row = (
            db.query(models.Session)
            .filter(models.Session.session_token == seed["session_token"])
            .first()
        )
        assert session_row is None

        doc_row = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc_row is None

    # Verify document endpoint returns 404
    doc_response = client.get("/v1/document", params={"session_id": seed["session_token"]})
    assert doc_response.status_code == 404


def test_apply_planner_update_cascades_trip_inputs_to_primary_branch():
    """Test that apply_planner_update updates the primary branch when trip_inputs change.

    When the LLM modifies trip_inputs (e.g., user says "add Florence"), the primary branch
    should reflect the new values immediately, not just the trip_inputs field.
    """
    from app.crud_document import apply_planner_update, get_document_data
    from app.schemas import DocumentTripInputs

    seed = seed_session_with_document(session_token="session-cascade-test")

    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None

        # Verify initial state
        data = get_document_data(doc)
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert primary_branch.destinations == ["Nice"]
        assert primary_branch.origin == "London"
        assert data.trip_inputs.destinations == ["Nice"]

        # Apply planner update with NEW trip_inputs but no new branches
        # (simulates LLM updating destinations in response to "add Florence")
        new_trip_inputs = DocumentTripInputs(
            destinations=["Nice", "Florence"],  # User added Florence
            origin="Oslo",  # User changed origin
            start_date="2025-12-10",
            end_date="2025-12-20",
            traveler_count=4,
            budget=5000,
            missing_fields=[],
        )

        doc = apply_planner_update(
            db,
            doc=doc,
            trip_context_id=seed["trip_context_id"],
            trip_inputs=new_trip_inputs,
            branches=None,  # No new branches from LLM
            tiles=None,
        )

        # Verify trip_inputs updated
        data = get_document_data(doc)
        assert data.trip_inputs.destinations == ["Nice", "Florence"]
        assert data.trip_inputs.origin == "Oslo"

        # Verify PRIMARY branch was updated to match trip_inputs
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert primary_branch.destinations == [
            "Nice",
            "Florence",
        ], "Primary branch destinations should cascade from trip_inputs"
        assert (
            primary_branch.origin == "Oslo"
        ), "Primary branch origin should cascade from trip_inputs"
        assert primary_branch.start_date == "2025-12-10"
        assert primary_branch.end_date == "2025-12-20"
        assert primary_branch.traveler_count == 4
        assert primary_branch.budget == 5000

        # Verify NON-PRIMARY branch was NOT updated (stays with its own values)
        non_primary_branch = next(b for b in data.branches if not b.is_primary)
        assert non_primary_branch.destinations == [
            "Paris"
        ], "Non-primary branch should retain its own destinations"
        assert (
            non_primary_branch.origin == "London"
        ), "Non-primary branch should retain its own origin"


def test_apply_planner_update_handles_empty_destinations():
    """Test that apply_planner_update correctly handles empty destinations.

    When the user removes all destinations, the trip_inputs.destinations should become
    empty and the primary branch should also have empty destinations.
    """
    from app.crud_document import apply_planner_update, get_document_data
    from app.schemas import DocumentTripInputs

    seed = seed_session_with_document(session_token="session-empty-dest-test")

    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None

        # Verify initial state has Nice as destination
        data = get_document_data(doc)
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert primary_branch.destinations == ["Nice"]
        assert data.trip_inputs.destinations == ["Nice"]

        # Apply planner update with EMPTY destinations
        # (simulates user removing all destinations)
        new_trip_inputs = DocumentTripInputs(
            destinations=[],  # User removed all destinations
            origin="London",
            start_date=None,
            end_date=None,
            traveler_count=None,
            budget=None,
            missing_fields=["destinations", "start_date", "end_date", "traveler_count", "budget"],
        )

        doc = apply_planner_update(
            db,
            doc=doc,
            trip_context_id=seed["trip_context_id"],
            trip_inputs=new_trip_inputs,
            branches=None,  # No new branches from LLM
            tiles=None,
        )

        # Verify trip_inputs has empty destinations
        data = get_document_data(doc)
        assert data.trip_inputs.destinations == [], "trip_inputs.destinations should be empty"

        # Verify PRIMARY branch destinations are also empty
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert (
            primary_branch.destinations == []
        ), "Primary branch destinations should be empty when user removes all"


def test_merge_trip_inputs_replace_mode_handles_empty_list():
    """Test that merge_trip_inputs in replace mode correctly uses empty destinations.

    When replace_destinations=True and incoming.destinations is empty, the result
    should have empty destinations (not fall back to existing).
    """
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    existing = DocumentTripInputs(
        destinations=["Nice", "Paris"],
        origin="London",
        start_date="2025-12-01",
        end_date="2025-12-07",
        traveler_count=2,
        budget=2000,
        missing_fields=[],
    )

    incoming = DocumentTripInputs(
        destinations=[],  # User removed all destinations
        origin=None,  # Keep existing
        start_date=None,
        end_date=None,
        traveler_count=None,
        budget=None,
        missing_fields=["destinations"],
    )

    result = merge_trip_inputs(existing, incoming, replace_destinations=True)

    assert result.destinations == [], "Empty destinations should not fall back to existing"
    assert result.origin == "London", "Origin should fall back to existing when None"


# =============================================================================
# Tests for _clean_trip_inputs field deletion handling
# =============================================================================


def test_clean_trip_inputs_origin_persists_with_allow_overwrite():
    """Test that _clean_trip_inputs preserves origin even when allow_overwrite=True.

    Origin and other non-destination fields persist once set. Even if the LLM
    returns origin: null, the existing value should be preserved.
    """
    from app.plan import _clean_trip_inputs

    # Existing state with origin set
    existing = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    # LLM response explicitly sets origin to null (key is present)
    llm_response = {
        "destinations": ["Paris"],
        "origin": None,  # Should be ignored - origin persists
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    result = _clean_trip_inputs(existing, llm_response, allow_overwrite=True)

    assert result["origin"] == "London", "Origin should persist even with allow_overwrite=True"
    assert result["destinations"] == ["Paris"], "Destinations should remain unchanged"
    assert "origin" not in result["missing_fields"], "Origin should NOT be in missing_fields"


def test_clean_trip_inputs_delete_origin_without_allow_overwrite():
    """Test that _clean_trip_inputs preserves origin when allow_overwrite=False.

    When allow_overwrite is False (default), null values should NOT delete existing values.
    """
    from app.plan import _clean_trip_inputs

    # Existing state with origin set
    existing = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    # Second source with origin null
    second_source = {
        "origin": None,
    }

    result = _clean_trip_inputs(existing, second_source, allow_overwrite=False)

    assert result["origin"] == "London", "Origin should be preserved when allow_overwrite=False"


def test_clean_trip_inputs_partial_destination_removal():
    """Test that _clean_trip_inputs properly handles partial destination removal.

    When the LLM returns fewer destinations (e.g., removes one from list),
    it should update to the new list.
    """
    from app.plan import _clean_trip_inputs

    # Existing state with multiple destinations
    existing = {
        "destinations": ["Paris", "Nice", "Lyon"],
        "origin": "London",
    }

    # LLM response removes Nice from the list
    llm_response = {
        "destinations": ["Paris", "Lyon"],  # Nice removed
        "origin": "London",
    }

    result = _clean_trip_inputs(existing, llm_response, allow_overwrite=True)

    assert result["destinations"] == ["Paris", "Lyon"], "Destinations should match LLM response"
    assert "Nice" not in result["destinations"], "Nice should be removed"


def test_clean_trip_inputs_delete_all_destinations():
    """Test that _clean_trip_inputs properly deletes all destinations.

    When the LLM returns empty destinations list, all destinations should be removed.
    """
    from app.plan import _clean_trip_inputs

    # Existing state with destinations
    existing = {
        "destinations": ["Paris", "Nice"],
        "origin": "London",
    }

    # LLM response with empty destinations (explicitly present)
    llm_response = {
        "destinations": [],  # All destinations removed
        "origin": "London",
    }

    result = _clean_trip_inputs(existing, llm_response, allow_overwrite=True)

    assert result["destinations"] == [], "Destinations should be empty"
    assert "destinations" in result["missing_fields"], "Destinations should be in missing_fields"


def test_clean_trip_inputs_field_not_present_preserves_existing():
    """Test that _clean_trip_inputs preserves values when field is not in source.

    When a field is NOT present in the source (vs explicitly null), existing value is kept.
    """
    from app.plan import _clean_trip_inputs

    # Existing state
    existing = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    # LLM response doesn't include origin key at all
    llm_response = {
        "destinations": ["Paris"],
        # "origin" key is NOT present - should preserve existing
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    result = _clean_trip_inputs(existing, llm_response, allow_overwrite=True)

    assert result["origin"] == "London", "Origin should be preserved when key not in source"


def test_clean_trip_inputs_date_fields_persist():
    """Test that _clean_trip_inputs preserves date fields.

    Date fields persist once set. Even if the LLM returns null, existing values are preserved.
    """
    from app.plan import _clean_trip_inputs

    existing = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    llm_response = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": None,  # Should be ignored - dates persist
        "end_date": None,  # Should be ignored - dates persist
        "traveler_count": 2,
        "budget": 2000,
    }

    result = _clean_trip_inputs(existing, llm_response, allow_overwrite=True)

    assert result["start_date"] == "2025-12-01", "start_date should persist"
    assert result["end_date"] == "2025-12-07", "end_date should persist"
    assert "start_date" not in result["missing_fields"]
    assert "end_date" not in result["missing_fields"]


def test_clean_trip_inputs_numeric_fields_persist():
    """Test that _clean_trip_inputs preserves numeric fields.

    Numeric fields (traveler_count, budget) persist once set.
    Even if the LLM returns null, existing values are preserved.
    """
    from app.plan import _clean_trip_inputs

    existing = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": 2,
        "budget": 2000,
    }

    llm_response = {
        "destinations": ["Paris"],
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "traveler_count": None,  # Should be ignored - persists
        "budget": None,  # Should be ignored - persists
    }

    result = _clean_trip_inputs(existing, llm_response, allow_overwrite=True)

    assert result["traveler_count"] == 2, "traveler_count should persist"
    assert result["budget"] == 2000, "budget should persist"
    assert "traveler_count" not in result["missing_fields"]
    assert "budget" not in result["missing_fields"]


# =============================================================================
# Tests for apply_user_patch destination removal
# =============================================================================


def test_apply_user_patch_removes_destination():
    """Test that apply_user_patch correctly handles destination removal.

    When a user removes a destination from the UI, the PATCH should
    result in the updated destinations list, not a union with the old list.
    """
    from app.crud_document import apply_user_patch, get_document_data
    from app.schemas import DocumentTripInputs, PlanDocumentPatch

    seed = seed_session_with_document(session_token="session-user-patch-remove")

    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None

        # Verify initial state has Nice as destination
        data = get_document_data(doc)
        assert data.trip_inputs.destinations == ["Nice"]

        # Create a patch that removes Nice (empty destinations list)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputs(
                destinations=[],  # User removed Nice
                origin="London",
                start_date="2025-12-01",
                end_date="2025-12-07",
                traveler_count=2,
                budget=2000,
                missing_fields=["destinations"],
            ),
        )

        updated_doc = apply_user_patch(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        assert data.trip_inputs.destinations == [], "Nice should have been removed"
        assert "destinations" in data.trip_inputs.missing_fields


def test_apply_user_patch_removes_one_destination_from_multiple():
    """Test that apply_user_patch correctly removes one destination from a list.

    When a user removes one destination from multiple, the remaining
    destinations should be preserved.
    """
    from app.crud_document import apply_user_patch, get_document_data
    from app.schemas import DocumentTripInputs, PlanDocumentPatch

    # First seed a document with multiple destinations
    with TestingSessionLocal() as db:
        session = models.Session(session_token="session-user-patch-partial-remove")
        db.add(session)
        db.flush()

        trip_ctx = models.TripContext(session_id=session.id, raw_prompt="Some context")
        db.add(trip_ctx)
        db.flush()

        document_data = {
            "trip_context_id": trip_ctx.id,
            "trip_inputs": {
                "destinations": ["Nice", "Paris", "Lyon"],
                "origin": "London",
                "start_date": "2025-12-01",
                "end_date": "2025-12-07",
                "traveler_count": 2,
                "budget": 2000,
                "missing_fields": [],
            },
            "branches": [],
            "tiles": {},
        }

        plan_doc = models.PlanDocument(
            session_id=session.id,
            version=1,
            updated_by="planner",
            document=document_data,
        )
        db.add(plan_doc)
        db.commit()

        doc_id = plan_doc.id

    with TestingSessionLocal() as db:
        doc = db.query(models.PlanDocument).filter(models.PlanDocument.id == doc_id).first()
        assert doc is not None

        # Verify initial state
        data = get_document_data(doc)
        assert data.trip_inputs.destinations == ["Nice", "Paris", "Lyon"]

        # Create a patch that removes Paris (keeping Nice and Lyon)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputs(
                destinations=["Nice", "Lyon"],  # Paris removed
                origin="London",
                start_date="2025-12-01",
                end_date="2025-12-07",
                traveler_count=2,
                budget=2000,
                missing_fields=[],
            ),
        )

        updated_doc = apply_user_patch(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        assert data.trip_inputs.destinations == ["Nice", "Lyon"], "Paris should have been removed"
        assert "Paris" not in data.trip_inputs.destinations


def test_apply_user_patch_cascades_destination_removal_to_branch():
    """Test that apply_user_patch cascades destination removal to the primary branch.

    When a user removes a destination from trip_inputs, the primary branch should
    also have its destinations updated to match.
    """
    from app.crud_document import apply_user_patch, get_document_data
    from app.schemas import DocumentTripInputs, PlanDocumentPatch

    seed = seed_session_with_document(session_token="session-cascade-user-patch")

    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None

        # Verify initial state - trip_inputs and primary branch both have Nice
        data = get_document_data(doc)
        assert data.trip_inputs.destinations == ["Nice"]
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert primary_branch.destinations == ["Nice"]

        # User removes the destination (empty list)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputs(
                destinations=[],  # User removed Nice
                origin="London",
                start_date="2025-12-01",
                end_date="2025-12-07",
                traveler_count=2,
                budget=2000,
                missing_fields=["destinations"],
            ),
        )

        updated_doc = apply_user_patch(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        # Verify trip_inputs updated
        assert data.trip_inputs.destinations == [], "trip_inputs.destinations should be empty"

        # Verify primary branch destinations are also updated
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert (
            primary_branch.destinations == []
        ), "Primary branch destinations should cascade from trip_inputs"


@pytest.mark.skipif(
    "sqlite" in TEST_DATABASE_URL,
    reason="SQLite does not support concurrent write transactions needed for this test",
)
def test_plan_flow_preserves_user_removed_destinations(monkeypatch: object):
    """Plan endpoint should not reintroduce destinations the user removed mid-turn."""
    from app import plan as plan_module
    from app.crud_document import apply_user_patch, get_document, get_document_data
    from app.schemas import DocumentTripInputs, PlanDocumentPatch

    seed = seed_session_with_document(session_token="session-plan-respects-removal")

    # Start with two destinations and no branches to simplify the scenario
    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None
        data = get_document_data(doc)
        data.trip_inputs.destinations = ["Nice", "Rome"]
        data.branches = []
        data.tiles = {}
        doc.document = data.model_dump()
        db.commit()

    def fake_call(req, history_rows, history, document_data):
        # Simulate the user removing "Rome" while the LLM call is in flight
        # Note: We use the seed session_token since req no longer contains session_id
        with TestingSessionLocal() as db2:
            session = (
                db2.query(models.Session)
                .filter(models.Session.session_token == seed["session_token"])
                .first()
            )
            doc = get_document(db2, session=session)
            apply_user_patch(
                db2,
                doc=doc,
                patch=PlanDocumentPatch(
                    version=doc.version,
                    trip_inputs=DocumentTripInputs(
                        destinations=["Nice"],
                        origin="London",
                        start_date="2025-12-01",
                        end_date="2025-12-07",
                        traveler_count=2,
                        budget=2000,
                        missing_fields=["destinations"],
                    ),
                ),
            )
            db2.commit()

        return plan_module.PlannerLLMOutput(
            branches=[],
            assistant_message="stubbed response",
            trip_inputs={
                "destinations": ["Nice", "Rome"],  # Stale planner output
                "origin": "London",
                "start_date": "2025-12-01",
                "end_date": "2025-12-07",
                "traveler_count": 2,
                "budget": 2000,
                "missing_fields": [],
            },
            ready_to_generate=True,
        )

    monkeypatch.setattr(plan_module, "_call_openai_for_plan", fake_call)

    response = client.post(
        "/v1/plan",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={
            "message": "Plan while removing destination",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["trip_inputs"]["destinations"] == ["Nice"]

    # Persisted document should also reflect the removal
    persisted_response = client.get(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
    )
    assert persisted_response.status_code == 200
    persisted = persisted_response.json()
    assert persisted["document"]["trip_inputs"]["destinations"] == ["Nice"]
