"""Deprecated tests for the legacy /v1/plan endpoint."""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import app.db_models as models  # noqa: E402  pylint: disable=C0413
from app.db import Base, get_db  # noqa: E402  pylint: disable=C0413
from app.main import app  # noqa: E402  pylint: disable=C0413

TEST_DB_PATH = BACKEND_DIR / "test_v1_plan_pytest.db"
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

        return {
            "session_token": session_token,
            "trip_context_id": trip_ctx.id,
            "document_id": plan_doc.id,
        }


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

TEST_CSRF_TOKEN = "test-csrf-token-12345"


def get_session_cookies(session_token: str) -> dict:
    return {
        "session_id": session_token,
        "csrf": TEST_CSRF_TOKEN,
    }


def get_csrf_headers() -> dict:
    return {"X-CSRF-Token": TEST_CSRF_TOKEN}


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


def test_plan_flow_persists_llm_activity_categories(monkeypatch: object):
    """When the planner returns activity categories, they should be saved to the document."""

    from app import plan as plan_module

    seed = seed_session_with_document(session_token="session-plan-activities")

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
                "activity_settings": {"categories": ["🧗 adventure", "🏎️ f1"]},
            },
            ready_to_generate=True,
        )

    monkeypatch.setattr(plan_module, "_call_openai_for_plan", fake_call)

    response = client.post(
        "/v1/plan",
        cookies=get_session_cookies(seed["session_token"]),
        headers=get_csrf_headers(),
        json={"message": "Set activities"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["trip_inputs"]["activity_settings"]["categories"] == [
        "🧗 adventure",
        "🏎️ f1",
    ]

    persisted = client.get(
        "/v1/document",
        cookies=get_session_cookies(seed["session_token"]),
    )
    assert persisted.status_code == 200
    persisted_doc = persisted.json()
    assert persisted_doc["document"]["trip_inputs"]["activity_settings"]["categories"] == [
        "🧗 adventure",
        "🏎️ f1",
    ]


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
        data.trip_inputs.activity_settings.categories = ["🏖️ beach"]
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
                "activity_settings": {"categories": ["🧗 adventure", "🏛️ culture"]},
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
                "activity_settings": {"categories": ["🏖️ beach"]},
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
    assert trip_inputs["activity_settings"]["categories"] == [
        "🏖️ beach"
    ], "LLM value should win (most recent)"


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
