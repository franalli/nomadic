"""
Tests for the PlanDocument-based API.
Tests document creation, retrieval, patching, and session deletion.
"""

import asyncio
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import app.db_models as models  # noqa: E402  pylint: disable=C0413
import app.main as main_module  # noqa: E402  pylint: disable=C0413
import app.request_dedup as request_dedup_module  # noqa: E402  pylint: disable=C0413
import app.services.spend_guard as spend_guard_module  # noqa: E402  pylint: disable=C0413
from app.db import Base, get_async_db, get_db  # noqa: E402  pylint: disable=C0413
from app.main import app  # noqa: E402  pylint: disable=C0413
from app.planner.state import ConstraintSeverity  # noqa: E402  pylint: disable=C0413
from app.services.itinerary_builder import (  # noqa: E402  pylint: disable=C0413
    BuilderConflict,
    DayCardOutput,
    ItineraryResult,
    Resolution,
)

TEST_DB_PATH = BACKEND_DIR / "test_plan_document_pytest.db"
TEST_DATABASE_URL = f"sqlite+pysqlite:///{TEST_DB_PATH.as_posix()}"
engine = create_engine(
    TEST_DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)

async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}",
    future=True,
    echo=False,
)

TestingAsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)


async def override_get_async_db():
    async with TestingAsyncSessionLocal() as db:
        yield db


def override_get_db():
    with TestingSessionLocal() as db:
        yield db


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
                "destination": "Nice",
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
                    "destination": "Nice",
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
                    "destination": "Paris",
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
                    "deeplink": "https://example.com/hotel",
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


def set_document_fields(
    session_token: str,
    *,
    trip_inputs: dict | None = None,
    day_cards: list[dict] | None = None,
) -> None:
    """Update selected plan document fields for a seeded session."""
    with TestingSessionLocal() as db:
        session = (
            db.query(models.Session).filter(models.Session.session_token == session_token).one()
        )
        doc = (
            db.query(models.PlanDocument).filter(models.PlanDocument.session_id == session.id).one()
        )
        payload = dict(doc.document or {})
        if trip_inputs is not None:
            payload["trip_inputs"] = trip_inputs
        if day_cards is not None:
            payload["day_cards"] = day_cards
        doc.document = payload
        db.add(doc)
        db.commit()


app.dependency_overrides[get_async_db] = override_get_async_db
app.dependency_overrides[get_db] = override_get_db
request_dedup_module.db_module.SessionLocal = TestingSessionLocal
spend_guard_module.db_module.SessionLocal = TestingSessionLocal
client = TestClient(app)

# CSRF token for tests - must match what we set in cookies
TEST_CSRF_TOKEN = "test-csrf-token-12345"


def get_session_cookies(session_token: str) -> dict:
    """Get cookies dict for a session."""
    return {
        "session_id": session_token,
        "csrf": TEST_CSRF_TOKEN,
    }


def set_client_session_cookies(client_instance: TestClient, session_token: str) -> None:
    """Set session + csrf cookies on the TestClient instance (non-deprecated style)."""
    cookies = get_session_cookies(session_token)
    client_instance.cookies.set("session_id", cookies["session_id"])
    client_instance.cookies.set("csrf", cookies["csrf"])


def request_with_session(
    client_instance: TestClient,
    method: str,
    path: str,
    session_token: str,
    **kwargs,
):
    """Issue a request after applying session cookies at the client level."""
    set_client_session_cookies(client_instance, session_token)
    return client_instance.request(method, path, **kwargs)


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
    import asyncio

    asyncio.run(async_engine.dispose())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_get_document_returns_branches_and_tiles():
    """Test that GET /api/document returns the document with branches and tiles."""
    seed = seed_session_with_document(session_token="session-get-doc")

    response = request_with_session(client, "GET", "/api/document", seed["session_token"])

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
    assert doc["branches"][1]["destination"] == "Paris"

    assert "tile_1" in doc["tiles"]
    assert doc["tiles"]["tile_1"]["title"] == "Seaside Hotel"


def test_get_document_handles_missing_session():
    """Test that GET /api/document returns 204 for missing session (no document yet)."""
    response = request_with_session(client, "GET", "/api/document", "missing-session")

    assert response.status_code == 204


def test_patch_document_updates_selections():
    """Test that PATCH /api/document updates tile selections."""
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

    response = request_with_session(
        client,
        "PATCH",
        "/api/document",
        seed["session_token"],
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


def test_patch_date_change_clears_stale_day_cards():
    """Date edits should invalidate derived day_cards."""
    seed = seed_session_with_document(session_token="session-date-clears-daycards")
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]
    set_document_fields(seed["session_token"], day_cards=day_cards)

    patch = {
        "version": 1,
        "trip_inputs": {
            "start_date": "2025-12-03",
        },
    }
    response = request_with_session(
        client,
        "PATCH",
        "/api/document",
        seed["session_token"],
        headers=get_csrf_headers(),
        json=patch,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["day_cards"] == []


def test_patch_non_date_change_preserves_day_cards():
    """Non-date edits should keep existing day_cards."""
    seed = seed_session_with_document(session_token="session-nondates-keep-daycards")
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]
    set_document_fields(seed["session_token"], day_cards=day_cards)

    patch = {
        "version": 1,
        "trip_inputs": {
            "budget": 3500,
        },
    }
    response = request_with_session(
        client,
        "PATCH",
        "/api/document",
        seed["session_token"],
        headers=get_csrf_headers(),
        json=patch,
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["document"]["day_cards"]) == 1
    assert payload["document"]["day_cards"][0]["day_number"] == 1


def test_fill_day_uses_effective_total_days_from_cards_and_trip_inputs():
    """
    Fill-day no-fly checks should use the later/effective departure day when
    trip_inputs and day_cards disagree.
    """
    seed = seed_session_with_document(session_token="session-fill-day-effective-span")
    trip_inputs = {
        "destination": "Nice",
        "origin": "London",
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",  # 7-day span
        "adults": 2,
        "children": 0,
        "requires_assistance": False,
        "budget": 2000,
        "currency": "USD",
        "missing_fields": [],
        "booking_types": {"hotels": "suggested", "flights": "suggested", "activities": "suggested"},
        "flight_settings": {"round_trip": True, "cabin_class": "economy", "direct_only": False},
        "hotel_settings": {"min_stars": 0, "amenities": []},
        "activity_settings": {"categories": ["diving"], "skill_level": None},
        "transport_settings": {"car": False, "train": False, "bus": False},
        "date_flex": False,
        "trip_duration": None,
        "date_window_start": None,
        "date_window_end": None,
    }
    day_cards = [{"day_number": i, "label": f"Day {i}", "blocks": []} for i in range(1, 10)]
    day_cards[-1]["blocks"] = [
        {
            "period": "evening",
            "activity_type": "Departure",
            "summary": "Fly home",
            "is_buffer": True,
            "buffer_type": "departure",
        }
    ]
    set_document_fields(seed["session_token"], trip_inputs=trip_inputs, day_cards=day_cards)

    # With 7-day trip span this would be rejected; with 9-day card span it should pass.
    response = request_with_session(
        client,
        "POST",
        "/api/document/fill-day",
        seed["session_token"],
        headers=get_csrf_headers(),
        json={"day_number": 7, "categories": ["diving"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("rejected") is not True


def test_fill_day_accepts_categories_at_schema_limit():
    seed = seed_session_with_document(session_token="session-fill-day-category-limit-ok")
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]
    set_document_fields(seed["session_token"], day_cards=day_cards)

    with patch(
        "app.services.experience_generator.generate_experience_tiles_for_day",
        new=AsyncMock(return_value=[]),
    ):
        response = request_with_session(
            client,
            "POST",
            "/api/document/fill-day",
            seed["session_token"],
            headers=get_csrf_headers(),
            json={"day_number": 1, "categories": ["food"] * 16},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["day_number"] == 1
    assert payload["tiles_added"] == 0


def test_fill_day_rejects_categories_above_schema_limit():
    seed = seed_session_with_document(session_token="session-fill-day-category-limit-too-long")
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]
    set_document_fields(seed["session_token"], day_cards=day_cards)

    response = request_with_session(
        client,
        "POST",
        "/api/document/fill-day",
        seed["session_token"],
        headers=get_csrf_headers(),
        json={"day_number": 1, "categories": ["food"] * 17},
    )

    assert response.status_code == 422
    assert any(
        error.get("loc") == ["body", "categories"] and error.get("type") == "too_long"
        for error in response.json().get("detail", [])
    )


@pytest.mark.slow
def test_fill_day_queues_behind_active_stream():
    """fill-day should wait for active graph stream work instead of rejecting."""
    seed = seed_session_with_document(session_token="session-fill-day-queue")
    day_cards = [{"day_number": 1, "label": "Day 1", "blocks": []}]
    set_document_fields(seed["session_token"], day_cards=day_cards)

    session_key = f"session:{seed['session_token']}"
    ip_key = "ip:test-fill-day-queue"
    acquired = asyncio.run(main_module._try_acquire_sse_slot(session_key, ip_key))
    assert acquired is None

    result: dict[str, object] = {}
    started = threading.Event()
    started_at = time.perf_counter()

    def _call_fill_day() -> None:
        started.set()
        with TestClient(app) as local_client:
            response = request_with_session(
                local_client,
                "POST",
                "/api/document/fill-day",
                seed["session_token"],
                headers=get_csrf_headers(),
                json={"day_number": 1, "pinned_tile_ids": ["tile_1"]},
            )
        result["response"] = response
        result["elapsed"] = time.perf_counter() - started_at

    worker = threading.Thread(target=_call_fill_day, daemon=True)
    worker.start()
    assert started.wait(timeout=1), "fill-day worker did not start"

    # Confirm request remains queued while the stream slot is occupied.
    time.sleep(0.15)
    assert worker.is_alive()

    asyncio.run(main_module._release_sse_slot(session_key, ip_key))

    worker.join(timeout=3)
    assert not worker.is_alive(), "fill-day did not resume after stream release"

    response = result.get("response")
    assert response is not None
    assert response.status_code == 200
    assert isinstance(result.get("elapsed"), float)
    assert result["elapsed"] >= 0.15


def test_session_delete_wipes_document():
    """Test that DELETE /api/session removes the PlanDocument."""
    seed = seed_session_with_document(session_token="session-delete-doc")

    response = request_with_session(
        client,
        "DELETE",
        "/api/session",
        seed["session_token"],
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
    doc_response = client.get("/api/document", params={"session_id": seed["session_token"]})
    assert doc_response.status_code == 204


def test_apply_planner_update_cascades_trip_inputs_to_primary_branch():
    """Test that apply_planner_update updates the primary branch when trip_inputs change.

    When the LLM modifies trip_inputs (e.g., user says "add Florence"), the primary branch
    should reflect the new values immediately, not just the trip_inputs field.
    """
    from app.crud_document import apply_planner_update_sync, get_document_data
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
        assert primary_branch.destination == "Nice"
        assert primary_branch.origin == "London"
        assert data.trip_inputs.destination == "Nice"

        # Apply planner update with NEW trip_inputs but no new branches
        # (simulates LLM updating destination in response to pivot to Florence)
        new_trip_inputs = DocumentTripInputs(
            destination="Florence",  # User pivoted to Florence
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

        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=seed["trip_context_id"],
            trip_inputs=new_trip_inputs,
            branches=None,  # No new branches from LLM
            tiles=None,
        )

        # Verify trip_inputs updated
        data = get_document_data(doc)
        assert data.trip_inputs.destination == "Florence"
        assert data.trip_inputs.origin == "Oslo"
        assert data.trip_inputs.currency == "EUR"

        # Verify PRIMARY branch was updated to match trip_inputs
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert primary_branch.destination == "Florence", (
            "Primary branch destination should cascade from trip_inputs"
        )
        assert primary_branch.origin == "Oslo", (
            "Primary branch origin should cascade from trip_inputs"
        )
        assert primary_branch.start_date == "2025-12-10"
        assert primary_branch.end_date == "2025-12-20"
        assert primary_branch.adults == 4
        assert primary_branch.budget == 5000
        assert primary_branch.currency == "EUR"

        # Verify NON-PRIMARY branch was NOT updated (stays with its own values)
        non_primary_branch = next(b for b in data.branches if not b.is_primary)
        assert non_primary_branch.destination == "Paris", (
            "Non-primary branch should retain its own destination"
        )
        assert non_primary_branch.origin == "London", (
            "Non-primary branch should retain its own origin"
        )
        assert non_primary_branch.currency == "USD"


def test_apply_planner_update_preserves_destination_when_null():
    """Test that apply_planner_update preserves existing destination when LLM returns None.

    Planner updates are designed to preserve existing values when None is passed,
    preventing accidental clearing. To clear destination, use apply_user_patch_sync
    which detects explicit nulls from the patch model.
    """
    from app.crud_document import apply_planner_update_sync, get_document_data
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
        assert primary_branch.destination == "Nice"
        assert data.trip_inputs.destination == "Nice"

        # Apply planner update with destination=None
        # (simulates LLM not returning destination field)
        new_trip_inputs = DocumentTripInputs(
            destination=None,  # LLM didn't return destination
            origin="London",
            start_date=None,
            end_date=None,
            adults=None,
            children=None,
            requires_assistance=None,
            budget=None,
            missing_fields=["destination", "start_date"],
        )

        doc = apply_planner_update_sync(
            db,
            doc=doc,
            trip_context_id=seed["trip_context_id"],
            trip_inputs=new_trip_inputs,
            branches=None,
            tiles=None,
        )

        # Verify destination is PRESERVED (not cleared) - this is the correct behavior
        # for planner updates where None means "not provided" not "clear it"
        data = get_document_data(doc)
        assert data.trip_inputs.destination == "Nice", (
            "Destination should be preserved when LLM returns None"
        )

        # Origin should be updated since it was explicitly set
        assert data.trip_inputs.origin == "London"


def test_merge_trip_inputs_replace_mode_handles_cleared_destination():
    """Test that merge_trip_inputs in replace mode correctly clears destination.

    When replace_destinations=True and incoming.destination is None, the result
    should have None destination (not fall back to existing).
    """
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    existing = DocumentTripInputs(
        destination="Nice",
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
        destination=None,  # User cleared destination
        origin=None,  # Keep existing
        start_date=None,
        end_date=None,
        adults=None,
        children=None,
        requires_assistance=None,
        budget=None,
        missing_fields=["destination"],
    )

    result = merge_trip_inputs(existing, incoming, replace_destinations=True)

    # When destination is explicitly None in incoming, keep existing (LLM doesn't clear fields)
    # To clear, use explicit_nulls parameter
    assert result.destination == "Nice", "Destination should not be cleared without explicit_nulls"
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
        destination="Paris",
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
    # Note: origin is OPTIONAL, so it's not tracked in missing_fields
    # Only destination and start_date are required fields


def test_merge_trip_inputs_llm_null_preserves_origin():
    """Test that merge_trip_inputs preserves origin when LLM returns null.

    When LLM returns origin=null without explicit_nulls, existing value is preserved.
    """
    from app.crud_document import merge_trip_inputs
    from app.schemas import DocumentTripInputs

    # Existing state with origin set
    existing = DocumentTripInputs(
        destination="Paris",
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
        "destination": "Paris",
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
        destination="Paris",
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
    # NOTE: end_date is NOT a required field, so it's not in missing_fields


def test_merge_trip_inputs_explicit_null_clears_activity_categories():
    """Test that explicit_nulls clears activity categories."""
    from app.crud_document import merge_trip_inputs
    from app.schemas import ActivitySettings, DocumentTripInputs

    existing = DocumentTripInputs(
        destination="Paris",
        origin="London",
        activity_settings=ActivitySettings(categories=["🏖️ beach", "💕 romantic"]),
    )

    # User clears all activity themes
    incoming = {"activity_settings": None}

    result = merge_trip_inputs(
        existing,
        incoming,
        explicit_nulls={"activity_settings"},
    )

    assert result.activity_settings.categories == [], (
        "activity categories should be cleared after explicit null"
    )


def test_apply_user_patch_clears_origin():
    """Test that apply_user_patch clears origin when user clicks X badge.

    When user clicks X on the origin badge, the frontend sends a patch with
    origin=null. This should actually clear the origin field.
    """
    from app.crud_document import apply_user_patch_sync, get_document_data, save_document_data_sync
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
        doc = save_document_data_sync(db, doc=doc, data=data, updated_by="user")

        # Verify origin is set
        data = get_document_data(doc)
        assert data.trip_inputs.origin == "London"

        # Create a patch that clears origin (user clicked X)
        # Using DocumentTripInputsPatch which tracks model_fields_set
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputsPatch(origin=None),
        )

        updated_doc = apply_user_patch_sync(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        assert data.trip_inputs.origin is None, "Origin should be cleared"
        # Note: origin is OPTIONAL, so it's not tracked in missing_fields
        # Only destination and start_date are required fields


# =============================================================================
# Tests for apply_user_patch destination removal
# =============================================================================


def test_apply_user_patch_clears_destination():
    """Test that apply_user_patch correctly handles destination clearing.

    When a user sets destination=None in the patch, it's auto-detected as
    an explicit null (via model_fields_set) and cleared.
    """
    from app.crud_document import apply_user_patch_sync, get_document_data
    from app.schemas import DocumentTripInputsPatch, PlanDocumentPatch

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
        assert data.trip_inputs.destination == "Nice"

        # Create a patch that clears destination using explicit null
        # (Use patch model since full model doesn't support clearing)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputsPatch(
                destination=None,  # User cleared destination
            ),
        )

        updated_doc = apply_user_patch_sync(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        # Destination is cleared because setting destination=None in the patch
        # adds it to explicit_nulls (auto-detected via model_fields_set)
        assert data.trip_inputs.destination is None, (
            "Destination should be cleared when explicitly set to None in patch"
        )
        assert "destination" in data.trip_inputs.missing_fields


def test_apply_user_patch_cascades_destination_change_to_branch():
    """Test that apply_user_patch cascades destination change to the primary branch.

    When a user changes the destination (pivot), the primary branch should
    also have its destination updated to match.
    """
    from app.crud_document import apply_user_patch_sync, get_document_data
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
        assert data.trip_inputs.destination == "Nice"
        primary_branch = next(b for b in data.branches if b.is_primary)
        assert primary_branch.destination == "Nice"

        # User changes the destination (pivot to Florence)
        patch = PlanDocumentPatch(
            version=doc.version,
            trip_inputs=DocumentTripInputs(
                destination="Florence",  # User pivoted to Florence
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

        updated_doc = apply_user_patch_sync(db, doc=doc, patch=patch)
        data = get_document_data(updated_doc)

        # Verify trip_inputs updated
        assert data.trip_inputs.destination == "Florence", (
            "trip_inputs.destination should be Florence"
        )

        # Branches for old destination should be pruned
        # (they referenced "Nice" which is no longer the destination)
        assert data.branches == [], "Branches should be pruned when destination changes"


def test_patch_trip_inputs_activity_categories_preserves_existing_fields():
    """PATCH /api/document should not reset destinations when only activity categories change."""

    seed = seed_session_with_document(session_token="session-activities-patch")

    response = request_with_session(
        client,
        "PATCH",
        "/api/document",
        seed["session_token"],
        headers=get_csrf_headers(),
        json={
            "version": 1,
            "trip_inputs": {"activity_settings": {"categories": ["🏖️ beach", "🍝 food"]}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["trip_inputs"]["destination"] == "Nice"
    assert payload["document"]["trip_inputs"]["activity_settings"]["categories"] == [
        "🏖️ beach",
        "🍝 food",
    ]

    persisted = request_with_session(client, "GET", "/api/document", seed["session_token"])
    assert persisted.status_code == 200
    persisted_doc = persisted.json()
    assert persisted_doc["document"]["trip_inputs"]["activity_settings"]["categories"] == [
        "🏖️ beach",
        "🍝 food",
    ]


def test_patch_trip_inputs_noop_does_not_bump_version():
    """PATCH /api/document no-op should not write or increment version."""

    seed = seed_session_with_document(session_token="session-noop-trip-inputs")

    existing = request_with_session(client, "GET", "/api/document", seed["session_token"])
    assert existing.status_code == 200
    existing_payload = existing.json()
    existing_version = existing_payload["version"]
    existing_trip_inputs = existing_payload["document"]["trip_inputs"]

    response = request_with_session(
        client,
        "PATCH",
        "/api/document",
        seed["session_token"],
        headers=get_csrf_headers(),
        json={
            "version": existing_version,
            "trip_inputs": {
                "hotel_settings": existing_trip_inputs["hotel_settings"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changes_made"] is False
    assert payload["version"] == existing_version


def test_expand_itinerary_duplicate_idempotency_returns_done_noop():
    """POST /api/expand-itinerary should return duplicate_noop for reused idempotency key."""

    original_generate_ndjson = main_module.generate_ndjson

    async def fake_generate_ndjson(*, session_id, req, resolve_stage3_view_state):  # noqa: ANN001
        yield (
            json.dumps(
                {
                    "type": "done",
                    "plan_view_state": "S3_ITINERARY_READY",
                    "version": 1,
                }
            )
            + "\n"
        )

    session_token = f"session-expand-dup-{time.time_ns()}"
    headers = get_csrf_headers()
    idempotency_key = f"dup-key-{time.time_ns()}"
    main_module.generate_ndjson = fake_generate_ndjson
    try:
        first = request_with_session(
            client,
            "POST",
            "/api/expand-itinerary",
            session_token,
            headers=headers,
            json={"idempotency_key": idempotency_key},
        )
        assert first.status_code == 200

        second = request_with_session(
            client,
            "POST",
            "/api/expand-itinerary",
            session_token,
            headers=headers,
            json={"idempotency_key": idempotency_key},
        )
        assert second.status_code == 200

        lines = [line for line in second.text.splitlines() if line.strip()]
        assert lines
        event = json.loads(lines[-1])
        assert event["type"] == "done"
        assert event["message"] == "duplicate_noop"
    finally:
        main_module.generate_ndjson = original_generate_ndjson


def test_expand_itinerary_stream_contract_first_and_duplicate():
    """Expand-itinerary should stream normal NDJSON first, then duplicate_noop on replay."""

    original_generate_ndjson = main_module.generate_ndjson

    async def fake_generate_ndjson(*, session_id, req, resolve_stage3_view_state):  # noqa: ANN001
        yield (
            json.dumps(
                {
                    "type": "progress",
                    "stage": "itinerary",
                    "message": "mock-progress",
                    "pct": 10,
                }
            )
            + "\n"
        )
        yield (
            json.dumps(
                {
                    "type": "done",
                    "plan_view_state": "S3_ITINERARY_READY",
                    "version": 7,
                }
            )
            + "\n"
        )

    main_module.generate_ndjson = fake_generate_ndjson
    try:
        session_token = f"session-expand-stream-{time.time_ns()}"
        headers = get_csrf_headers()
        idempotency_key = f"stream-key-{time.time_ns()}"
        payload = {"idempotency_key": idempotency_key}

        first = request_with_session(
            client,
            "POST",
            "/api/expand-itinerary",
            session_token,
            headers=headers,
            json=payload,
        )
        assert first.status_code == 200
        first_events = [json.loads(line) for line in first.text.splitlines() if line.strip()]
        assert [evt["type"] for evt in first_events] == ["progress", "done"]
        assert first_events[0]["stage"] == "itinerary"
        assert first_events[0]["pct"] == 10
        assert first_events[1]["plan_view_state"] == "S3_ITINERARY_READY"
        assert first_events[1]["version"] == 7

        duplicate = request_with_session(
            client,
            "POST",
            "/api/expand-itinerary",
            session_token,
            headers=headers,
            json=payload,
        )
        assert duplicate.status_code == 200
        duplicate_events = [
            json.loads(line) for line in duplicate.text.splitlines() if line.strip()
        ]
        assert len(duplicate_events) == 1
        assert duplicate_events[0]["type"] == "done"
        assert duplicate_events[0]["message"] == "duplicate_noop"
        assert "plan_view_state" not in duplicate_events[0]
    finally:
        main_module.generate_ndjson = original_generate_ndjson


def test_expand_itinerary_conflict_error_includes_persisted_plan_view_state():
    """Conflict error payload should expose the same backend-owned Stage 3 state that persists."""

    session_token = f"session-expand-conflict-{time.time_ns()}"
    seed_session_with_document(session_token=session_token)
    headers = get_csrf_headers()
    idempotency_key = f"conflict-key-{time.time_ns()}"
    conflict_result = ItineraryResult(
        success=False,
        day_cards=[DayCardOutput(day_number=1, label="Arrival", blocks=[])],
        conflicts=[
            BuilderConflict(
                type="constraint_clash",
                severity=ConstraintSeverity.BLOCKING,
                day=2,
                message="Need a 24h no-fly buffer after diving",
                specialists=["diving"],
            )
        ],
        resolutions=[
            Resolution(
                action="reduce_activities",
                description="Move the dive earlier or reduce activities",
                feasibility="recommended",
            )
        ],
    )

    with (
        patch("app.streaming._get_async_session_factory", return_value=TestingAsyncSessionLocal),
        patch(
            "app.services.itinerary_builder.ItineraryBuilder.build",
            return_value=conflict_result,
        ),
    ):
        response = request_with_session(
            client,
            "POST",
            "/api/expand-itinerary",
            session_token,
            headers=headers,
            json={
                "idempotency_key": idempotency_key,
                "strategy_sections": [{"id": "diving-plan", "title": "Diving Plan"}],
            },
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert [event["type"] for event in events] == ["progress", "progress", "envelope", "error"]
    assert events[2]["plan_envelope"]["plan_view_state"] == "S3_PARTIAL_CONFLICT"

    error_payload = json.loads(events[3]["message"])
    assert error_payload["error"] == "CONSTRAINT_CONFLICT"
    assert error_payload["plan_view_state"] == "S3_PARTIAL_CONFLICT"
    assert error_payload["day_cards"][0]["label"] == "Arrival"

    with TestingSessionLocal() as db:
        session = (
            db.query(models.Session).filter(models.Session.session_token == session_token).one()
        )
        doc = (
            db.query(models.PlanDocument).filter(models.PlanDocument.session_id == session.id).one()
        )
        assert doc.document["plan_view_state"] == "S3_PARTIAL_CONFLICT"
