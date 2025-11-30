"""
Tests for the PlanDocument-based API.
Tests document creation, retrieval, patching, and session deletion.
"""

import os
import sys
from pathlib import Path

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
    connect_args={"check_same_thread": False},
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
        session = models.Session(session_token=session_token)
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


def setup_module(_: object):
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module(_: object):
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_get_document_returns_branches_and_tiles():
    """Test that GET /v1/document returns the document with branches and tiles."""
    seed = seed_session_with_document(session_token="session-get-doc")

    response = client.get("/v1/document", params={"session_id": seed["session_token"]})

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
    response = client.get("/v1/document", params={"session_id": "missing-session"})

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
        params={"session_id": seed["session_token"]},
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

    response = client.delete("/v1/session", params={"session_id": seed["session_token"]})

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
