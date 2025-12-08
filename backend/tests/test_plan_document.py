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
                "adults": 2,
                "children": 0,
                "requires_assistance": False,
                "budget": 2000,
                "currency": "USD",
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
                    "adults": 2,
                    "children": 0,
                    "requires_assistance": False,
                    "budget": 2000,
                    "currency": "USD",
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
                    "adults": 2,
                    "children": 0,
                    "requires_assistance": False,
                    "budget": 2000,
                    "currency": "USD",
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
                    "currency": "USD",
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
    """Test that GET /v1/document returns 204 for missing session (no document yet)."""
    response = client.get(
        "/v1/document",
        cookies=get_session_cookies("missing-session"),
    )

    assert response.status_code == 204


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

    # Verify document endpoint returns 204 (no content, session gone)
    doc_response = client.get("/v1/document", params={"session_id": seed["session_token"]})
    assert doc_response.status_code == 204


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
            adults=4,
            children=0,
            requires_assistance=False,
            budget=5000,
            currency="EUR",
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
        assert data.trip_inputs.currency == "EUR"

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
        assert primary_branch.adults == 4
        assert primary_branch.budget == 5000
        assert primary_branch.currency == "EUR"

        # Verify NON-PRIMARY branch was NOT updated (stays with its own values)
        non_primary_branch = next(b for b in data.branches if not b.is_primary)
        assert non_primary_branch.destinations == [
            "Paris"
        ], "Non-primary branch should retain its own destinations"
        assert (
            non_primary_branch.origin == "London"
        ), "Non-primary branch should retain its own origin"
        assert non_primary_branch.currency == "USD"


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
            adults=None,
            children=None,
            requires_assistance=None,
            budget=None,
            missing_fields=["destinations", "start_date", "end_date", "adults", "budget"],
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
        adults=2,
        children=0,
        requires_assistance=False,
        budget=2000,
        missing_fields=[],
    )

    incoming = DocumentTripInputs(
        destinations=[],  # User removed all destinations
        origin=None,  # Keep existing
        start_date=None,
        end_date=None,
        adults=None,
        children=None,
        requires_assistance=None,
        budget=None,
        missing_fields=["destinations"],
    )

    result = merge_trip_inputs(existing, incoming, replace_destinations=True)

    assert result.destinations == [], "Empty destinations should not fall back to existing"
    assert result.origin == "London", "Origin should fall back to existing when None"


# =============================================================================
# Tests for merge_trip_inputs explicit null handling
# =============================================================================


def test_merge_trip_inputs_explicit_null_clears_origin():
    """Test that merge_trip_inputs clears origin when explicit_nulls contains 'origin'.

    When user clicks X on the origin badge, the field should be cleared.
    This is different from LLM returning origin=null (which preserves existing value).
    """
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    # Existing state with origin set
    existing = DocumentTripInputs(
        destinations=["Paris"],
        origin="London",
        start_date="2025-12-01",
        end_date="2025-12-07",
        adults=2,
        children=0,
        requires_assistance=False,
        budget=2000,
    )

    # Incoming patch with origin=None (simulating user clicking X)
    # The explicit_nulls set tells merge that this was intentional
    incoming = {"origin": None}

    result = merge_trip_inputs(
        existing,
        incoming,
        explicit_nulls={"origin"},
    )

    assert result.origin is None, "Origin should be cleared when in explicit_nulls"
    assert "origin" in result.missing_fields, "Origin should be in missing_fields"


def test_merge_trip_inputs_llm_null_preserves_origin():
    """Test that merge_trip_inputs preserves origin when LLM returns null.

    When LLM returns origin=null without explicit_nulls, existing value is preserved.
    """
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    # Existing state with origin set
    existing = DocumentTripInputs(
        destinations=["Paris"],
        origin="London",
        start_date="2025-12-01",
        end_date="2025-12-07",
        adults=2,
        children=0,
        requires_assistance=False,
        budget=2000,
    )

    # LLM response with origin=None (not intentional deletion)
    incoming = {
        "destinations": ["Paris"],
        "origin": None,
    }

    result = merge_trip_inputs(
        existing,
        incoming,
        # No explicit_nulls - null means "not provided"
    )

    assert result.origin == "London", "Origin should be preserved when LLM returns null"


def test_merge_trip_inputs_explicit_null_clears_dates():
    """Test that explicit_nulls clears date fields."""
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    existing = DocumentTripInputs(
        destinations=["Paris"],
        origin="London",
        start_date="2025-12-01",
        end_date="2025-12-07",
        adults=2,
        children=0,
        requires_assistance=False,
        budget=2000,
    )

    # User clicks X on both date badges
    incoming = {
        "start_date": None,
        "end_date": None,
    }

    result = merge_trip_inputs(
        existing,
        incoming,
        explicit_nulls={"start_date", "end_date"},
    )

    assert result.start_date is None, "start_date should be cleared"
    assert result.end_date is None, "end_date should be cleared"
    assert "start_date" in result.missing_fields
    assert "end_date" in result.missing_fields


def test_merge_trip_inputs_explicit_null_clears_vibes():
    """Test that explicit_nulls clears vibes array."""
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    existing = DocumentTripInputs(
        destinations=["Paris"],
        origin="London",
        vibes=["adventure", "foodie"],
    )

    # User clears all vibes
    incoming = {"vibes": None}

    result = merge_trip_inputs(
        existing,
        incoming,
        explicit_nulls={"vibes"},
    )

    assert result.vibes == [], "vibes should be empty list after explicit null"


def test_apply_user_patch_clears_origin():
    """Test that apply_user_patch clears origin when user clicks X badge.

    When user clicks X on the origin badge, the frontend sends a patch with
    origin=null. This should actually clear the origin field.
    """
    from app.crud_document import apply_user_patch, get_document_data, save_document_data
    from app.schemas import DocumentTripInputsPatch, PlanDocumentPatch

    seed = seed_session_with_document(session_token="session-clear-origin")

    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None

        # First set up a document with origin
        data = get_document_data(doc)
        data.trip_inputs.origin = "London"
        doc = save_document_data(db, doc=doc, data=data, updated_by="user")

        # Verify origin is set
        data = get_document_data(doc)
        assert data.trip_inputs.origin == "London"

        # Create a patch that clears origin (user clicked X)
        # Using DocumentTripInputsPatch which tracks model_fields_set
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputsPatch(origin=None),
        )

        updated_doc = apply_user_patch(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        assert data.trip_inputs.origin is None, "Origin should be cleared"
        assert "origin" in data.trip_inputs.missing_fields


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
                adults=2,
                children=0,
                requires_assistance=False,
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
                "adults": 2,
                "children": 0,
                "requires_assistance": False,
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
                adults=2,
                children=0,
                requires_assistance=False,
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
                adults=2,
                children=0,
                requires_assistance=False,
                budget=2000,
                missing_fields=["destinations"],
            ),
        )

        updated_doc = apply_user_patch(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        # Verify trip_inputs updated
        assert data.trip_inputs.destinations == [], "trip_inputs.destinations should be empty"

        # Branches should be pruned when all destinations are removed
        # (they referenced "Nice" which is no longer a valid destination)
        assert data.branches == [], "Branches should be pruned when destinations are cleared"


def test_patch_trip_inputs_vibes_preserves_existing_fields():
    """PATCH /v1/document should not reset destinations when only vibes change."""

    seed = seed_session_with_document(session_token="session-vibes-patch")

    response = client.patch(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={
            "version": 1,
            "trip_inputs": {"vibes": ["adventure", "foodie"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["trip_inputs"]["destinations"] == ["Nice"]
    assert payload["document"]["trip_inputs"]["vibes"] == ["adventure", "foodie"]

    persisted = client.get(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
    )
    assert persisted.status_code == 200
    persisted_doc = persisted.json()
    assert persisted_doc["document"]["trip_inputs"]["vibes"] == ["adventure", "foodie"]


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

    def fake_call(req, history_rows=None, history=None, document_data=None, **kwargs):
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
                        adults=2,
                        children=0,
                        requires_assistance=False,
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
                "adults": 2,
                "children": 0,
                "requires_assistance": False,
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


def test_plan_flow_persists_llm_vibes(monkeypatch: object):
    """When the planner returns vibes, they should be saved to the document."""

    from app import plan as plan_module

    seed = seed_session_with_document(session_token="session-plan-vibes")

    def fake_call(req, history=None, document_data=None, **kwargs):
        return plan_module.PlannerLLMOutput(
            branches=[],
            assistant_message="ready",
            trip_inputs={
                "destinations": ["Nice"],
                "origin": "London",
                "start_date": "2025-12-01",
                "end_date": "2025-12-07",
                "adults": 2,
                "children": 0,
                "requires_assistance": False,
                "budget": 2000,
                "missing_fields": [],
                "multi_city_intent": None,
                "vibes": ["adventure", "f1"],
            },
            ready_to_generate=True,
        )

    monkeypatch.setattr(plan_module, "_call_openai_for_plan", fake_call)

    response = client.post(
        "/v1/plan",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={"message": "Set vibes"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["trip_inputs"]["vibes"] == ["adventure", "f1"]

    persisted = client.get(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
    )
    assert persisted.status_code == 200
    persisted_doc = persisted.json()
    assert persisted_doc["document"]["trip_inputs"]["vibes"] == ["adventure", "f1"]


# =============================================================================
# Tests for trip inputs sync - user changes before/during LLM call
# =============================================================================


def test_plan_flow_llm_destinations_overwrite_user_removals(monkeypatch: object):
    """Plan endpoint applies LLM destinations as most-recent-wins.

    With the simplified merge logic, LLM updates are applied last and win.
    The LLM is expected to acknowledge any changes in its assistant_message.

    This tests the scenario where:
    1. User has destinations ["Nice", "Rome"]
    2. User removes "Rome" via UI (PATCH /v1/document)
    3. User sends a chat message
    4. LLM returns destinations ["Nice", "Rome"]
    5. LLM values are applied (most recent wins)
    """
    from app import plan as plan_module
    from app.crud_document import get_document_data

    seed = seed_session_with_document(session_token="session-sync-before-request")

    # Step 1: Set up initial state with multiple destinations
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

    # Step 2: User removes "Rome" via PATCH endpoint (before the /plan request)
    patch_response = client.patch(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={
            "version": 1,
            "trip_inputs": {
                "destinations": ["Nice"],  # Rome removed
            },
        },
    )
    assert patch_response.status_code == 200
    # Verify the patch was applied
    assert patch_response.json()["document"]["trip_inputs"]["destinations"] == ["Nice"]

    # Step 3: Mock LLM to return destinations including Rome (LLM is most recent, so it wins)
    def fake_call(req, history=None, document_data=None, **kwargs):
        # LLM returns its own view of destinations
        # With most-recent-wins, LLM output will be applied
        return plan_module.PlannerLLMOutput(
            branches=[],
            assistant_message="Here are your options",
            trip_inputs={
                "destinations": ["Nice", "Rome"],  # LLM's output (most recent wins)
                "origin": "London",
                "start_date": "2025-12-01",
                "end_date": "2025-12-07",
                "adults": 2,
                "children": 0,
                "requires_assistance": False,
                "budget": 2000,
                "missing_fields": [],
            },
            ready_to_generate=True,
        )

    monkeypatch.setattr(plan_module, "_call_openai_for_plan", fake_call)

    # Step 4: User sends chat message
    response = client.post(
        "/v1/plan",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={"message": "What should I do in Nice?"},
    )

    # Step 5: Verify LLM values are applied (most recent wins)
    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["trip_inputs"]["destinations"] == [
        "Nice",
        "Rome",
    ], "LLM output should be applied (most recent wins)"

    # Verify persisted state also has the LLM's destinations
    persisted = client.get(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
    )
    assert persisted.status_code == 200
    assert persisted.json()["document"]["trip_inputs"]["destinations"] == ["Nice", "Rome"]


def test_plan_flow_llm_updates_overwrite_previous_values(monkeypatch: object):
    """Plan endpoint applies LLM updates as most-recent-wins.

    When a user modifies fields before sending a message, and the LLM returns
    different values, the LLM values win (most recent update wins).
    The LLM is expected to acknowledge any changes in its assistant_message.
    """
    from app import plan as plan_module
    from app.crud_document import get_document_data

    seed = seed_session_with_document(session_token="session-sync-all-fields")

    # Step 1: Set up initial state
    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None
        data = get_document_data(doc)
        data.trip_inputs.destinations = ["Nice"]
        data.trip_inputs.origin = "London"
        data.trip_inputs.start_date = "2025-12-01"
        data.trip_inputs.end_date = "2025-12-07"
        data.trip_inputs.adults = 2
        data.trip_inputs.children = 0
        data.trip_inputs.requires_assistance = False
        data.trip_inputs.budget = 2000
        data.trip_inputs.vibes = ["beach"]
        data.branches = []
        data.tiles = {}
        doc.document = data.model_dump()
        db.commit()

    # Step 2: User modifies multiple fields via PATCH
    patch_response = client.patch(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={
            "version": 1,
            "trip_inputs": {
                "origin": "Paris",  # Changed from London
                "start_date": "2025-12-10",  # Changed from 12-01
                "adults": 4,  # Changed from 2
                "vibes": ["adventure", "culture"],  # Changed from ["beach"]
            },
        },
    )
    assert patch_response.status_code == 200

    # Step 3: Mock LLM to return its own values (LLM is most recent, so it wins)
    def fake_call(req, history=None, document_data=None, **kwargs):
        return plan_module.PlannerLLMOutput(
            branches=[],
            assistant_message=(
                "I've updated your departure city from Paris to London and your dates."
            ),
            trip_inputs={
                "destinations": ["Nice"],
                "origin": "London",  # LLM returns London
                "start_date": "2025-12-01",  # LLM returns 12-01
                "end_date": "2025-12-07",
                "adults": 2,  # LLM returns 2
                "children": 0,
                "requires_assistance": False,
                "budget": 2000,
                "missing_fields": [],
                "vibes": ["beach"],  # LLM returns ["beach"]
            },
            ready_to_generate=True,
        )

    monkeypatch.setattr(plan_module, "_call_openai_for_plan", fake_call)

    # Step 4: User sends chat message
    response = client.post(
        "/v1/plan",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={"message": "Update my trip details"},
    )

    # Step 5: Verify LLM values win (most recent update)
    assert response.status_code == 200
    payload = response.json()
    trip_inputs = payload["document"]["trip_inputs"]

    # LLM values should be applied (most recent wins)
    assert trip_inputs["origin"] == "London", "LLM value should win (most recent)"
    assert trip_inputs["start_date"] == "2025-12-01", "LLM value should win (most recent)"
    assert trip_inputs["adults"] == 2, "LLM value should win (most recent)"
    assert trip_inputs["vibes"] == ["beach"], "LLM value should win (most recent)"


@pytest.mark.skipif(
    "sqlite" in TEST_DATABASE_URL,
    reason="SQLite does not support concurrent write transactions needed for this test",
)
def test_plan_flow_preserves_user_additions_during_llm_call(monkeypatch: object):
    """Plan endpoint should preserve user ADDITIONS made during the LLM call.

    If user adds a destination while the LLM is processing, the addition
    should be preserved and merged with the LLM's output.
    """
    from app import plan as plan_module
    from app.crud_document import apply_user_patch, get_document, get_document_data
    from app.schemas import PlanDocumentPatch

    seed = seed_session_with_document(session_token="session-sync-additions")

    # Set up initial state with one destination
    with TestingSessionLocal() as db:
        doc = (
            db.query(models.PlanDocument)
            .filter(models.PlanDocument.id == seed["document_id"])
            .first()
        )
        assert doc is not None
        data = get_document_data(doc)
        data.trip_inputs.destinations = ["Nice"]
        data.branches = []
        data.tiles = {}
        doc.document = data.model_dump()
        db.commit()

    def fake_call(req, history=None, document_data=None, **kwargs):
        # Simulate user ADDING "Florence" during the LLM call
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
                    trip_inputs={"destinations": ["Nice", "Florence"]},  # User added Florence
                ),
            )
            db2.commit()

        # LLM returns only Nice (doesn't know about Florence)
        return plan_module.PlannerLLMOutput(
            branches=[],
            assistant_message="Great trip to Nice",
            trip_inputs={
                "destinations": ["Nice"],  # Doesn't include user-added Florence
                "origin": "London",
                "start_date": "2025-12-01",
                "end_date": "2025-12-07",
                "adults": 2,
                "children": 0,
                "requires_assistance": False,
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
        json={"message": "Plan my trip"},
    )

    assert response.status_code == 200
    payload = response.json()
    destinations = payload["document"]["trip_inputs"]["destinations"]

    # Both Nice (from LLM) and Florence (user-added) should be present
    assert "Nice" in destinations, "LLM destination should be present"
    assert "Florence" in destinations, "User-added destination should be preserved"
