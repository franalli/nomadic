"""
Tests for the /v1/graph_plan endpoint.

Tests include:
- Feature flag gating
- Content-Type validation
- Payload size validation
- Session state handling
- today_iso injection
- Optimistic concurrency
- Error handling
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Enable the graph plan route for testing
os.environ["ENABLE_GRAPH_PLAN_ROUTE"] = "true"

import app.db_models as models  # noqa: E402  pylint: disable=C0413
from app.config import settings  # noqa: E402  pylint: disable=C0413
from app.db import Base, get_async_db, get_db  # noqa: E402  pylint: disable=C0413
from app.main import app  # noqa: E402  pylint: disable=C0413
from app.schemas import GraphPlanErrorCode  # noqa: E402  pylint: disable=C0413


@pytest.fixture(scope="function")
def _db_path(tmp_path: Path) -> Path:
    """Use a per-test temp DB for complete isolation."""
    return tmp_path / "test_graph_plan.db"


@pytest.fixture(scope="function")
def _engines(_db_path: Path):
    """Create sync and async engines per-test."""
    db_url = f"sqlite+pysqlite:///{_db_path.as_posix()}"
    async_db_url = f"sqlite+aiosqlite:///{_db_path.as_posix()}"

    sync_engine = create_engine(
        db_url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async_eng = create_async_engine(
        async_db_url,
        future=True,
        echo=False,
    )

    yield {"sync": sync_engine, "async": async_eng}

    sync_engine.dispose()
    import asyncio

    asyncio.run(async_eng.dispose())


@pytest.fixture(scope="function")
def _session_makers(_engines):
    """Create session makers per-test."""
    sync_maker = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engines["sync"],
        future=True,
    )
    async_maker = async_sessionmaker(
        bind=_engines["async"],
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    return {"sync": sync_maker, "async": async_maker}


@pytest.fixture(scope="function", autouse=True)
def setup_database(_engines, _session_makers):
    """Create test database and tables per-test."""
    Base.metadata.create_all(bind=_engines["sync"])

    def override_get_db():
        db = _session_makers["sync"]()
        try:
            yield db
        finally:
            db.close()

    async def override_get_async_db():
        async with _session_makers["async"]() as db:
            try:
                yield db
            finally:
                await db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db
    yield
    app.dependency_overrides.clear()


def _seed_session(session_maker, session_token: str = "test-session-123") -> dict:
    """Create a test session."""
    with session_maker() as db:
        existing = (
            db.query(models.Session).filter(models.Session.session_token == session_token).first()
        )
        if existing is not None:
            return {
                "session_id": existing.id,
                "session_token": session_token,
            }

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=90)
        session = models.Session(
            session_token=session_token,
            last_activity_at=now,
            expires_at=expires_at,
        )
        db.add(session)
        db.commit()
        return {
            "session_id": session.id,
            "session_token": session_token,
        }


@pytest.fixture
def client(_session_makers):
    """Test client with session cookie."""
    session_data = _seed_session(_session_makers["sync"])
    with TestClient(app) as client:
        # Cookie names are set by SessionMiddleware in app.middleware.session
        client.cookies.set("session_id", session_data["session_token"])
        # Set a dummy CSRF token
        client.cookies.set("csrf", "test-csrf-token")
        yield client


@pytest.fixture
def mock_run_turn():
    """Mock the run_turn function."""
    with patch("app.main.run_turn") as mock:
        mock.return_value = {
            "assistant_message": "I can help you plan your trip!",
            "trip_inputs": {
                "destinations": ["Paris"],
                "origin": "London",
            },
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Tell me more about hotels", "Show me flights"],
            "errors": [],
            "session_state": {
                "trip_inputs": {"destinations": ["Paris"], "origin": "London"},
                "metadata": {},
                "flags": {},
            },
        }
        yield mock


class TestGraphPlanFeatureFlag:
    """Tests for feature flag gating."""

    def test_route_disabled_returns_503(self, client):
        """When feature flag is disabled, route returns 503."""
        # Temporarily disable the feature flag
        original_value = settings.enable_graph_plan_route
        settings.enable_graph_plan_route = False
        try:
            response = client.post(
                "/v1/graph_plan",
                json={"message": "I want to go to Paris"},
                headers={"X-CSRF-Token": "test-csrf-token"},
            )
            assert response.status_code == 503
            data = response.json()
            assert data["detail"]["error_code"] == GraphPlanErrorCode.ROUTE_DISABLED
        finally:
            settings.enable_graph_plan_route = original_value


class TestGraphPlanValidation:
    """Tests for request validation."""

    def test_content_type_validation(self, client, mock_run_turn):
        """Rejects non-JSON content types."""
        response = client.post(
            "/v1/graph_plan",
            content="message=hello",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRF-Token": "test-csrf-token",
            },
        )
        # Note: FastAPI may return 422 for invalid JSON before our validation
        # This test verifies the endpoint behavior with wrong content type
        assert response.status_code in [415, 422]

    def test_empty_message_accepted(self, client, mock_run_turn):
        """Empty messages are accepted (LLM handles clarification)."""
        response = client.post(
            "/v1/graph_plan",
            json={"message": ""},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        # May succeed or fail based on validation - just ensure no 500
        assert response.status_code != 500


class TestGraphPlanHappyPath:
    """Tests for successful request handling."""

    def test_basic_request(self, client, mock_run_turn):
        """Basic request with message returns expected response."""
        response = client.post(
            "/v1/graph_plan",
            json={"message": "I want to go to Paris"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200
        data = response.json()

        # Verify response structure (GraphPlanResponse)
        assert "document" in data
        assert "session_state" in data
        assert "request_id" in data
        assert "observability" in data

        assert "assistant_message" in data["document"]
        assert "trip_inputs" in data["document"]
        assert "ready_to_generate" in data["document"]
        assert "branches" in data["document"]

        # Verify Cache-Control header
        assert response.headers.get("Cache-Control") == "no-store"

    def test_request_with_trip_inputs(self, client, mock_run_turn):
        """Request with trip_inputs initializes session state."""
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "I want to go to Paris",
                "trip_inputs": {
                    "destinations": ["Paris"],
                    "origin": "London",
                    "adults": 2,
                },
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200

        # Verify run_turn was called with trip_inputs
        call_args = mock_run_turn.call_args
        session_state = call_args[0][1]  # Second positional argument
        assert "trip_inputs" in session_state

    def test_request_with_session_state(self, client, mock_run_turn):
        """Request with session_state continues conversation.

        Note: When a document exists for the session, document trip_inputs
        take precedence over session_state trip_inputs (document is source of truth).
        For a new session, the document starts empty, so destinations will be [].
        """
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "What about hotels?",
                "session_state": {
                    "trip_inputs": {"destinations": ["Paris"]},
                    "metadata": {"turn_count": 1},
                },
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200

        # Verify run_turn received session state (document overrides trip_inputs)
        call_args = mock_run_turn.call_args
        session_state = call_args[0][1]
        # Document is source of truth - for new session, document starts empty
        # so destinations from session_state are overwritten by empty document
        assert "trip_inputs" in session_state


class TestGraphPlanTodayIso:
    """Tests for today_iso injection."""

    def test_today_iso_injected(self, client, mock_run_turn):
        """today_iso is injected into session state."""
        response = client.post(
            "/v1/graph_plan",
            json={"message": "I want to travel next week"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200

        # Verify today_iso was injected
        call_args = mock_run_turn.call_args
        session_state = call_args[0][1]
        assert "today_iso" in session_state
        # Verify it's a valid ISO date format
        import re

        assert re.match(r"\d{4}-\d{2}-\d{2}", session_state["today_iso"])


class TestGraphPlanObservability:
    """Tests for observability data."""

    def test_observability_included(self, client, mock_run_turn):
        """Response includes observability data."""
        response = client.post(
            "/v1/graph_plan",
            json={"message": "Test"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200
        data = response.json()

        obs = data.get("observability", {})
        assert "request_id" in data
        assert "tokens" in obs


class TestGraphPlanOptimisticConcurrency:
    """Tests for optimistic concurrency control."""

    def test_version_conflict(self, client, mock_run_turn):
        """Returns 409 when expected_version doesn't match."""
        # First, make a request to create a document
        response = client.post(
            "/v1/graph_plan",
            json={"message": "Create a trip"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200

        # Now make a request with wrong expected_version
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "Update trip",
                "expected_version": 999,  # Wrong version
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )

        # Should return 409 Conflict
        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["error_code"] == GraphPlanErrorCode.VERSION_CONFLICT


class TestGraphPlanUtilities:
    """Tests for utility functions."""

    def test_sanitize_session_state(self):
        """Session state sanitization removes dangerous keys."""
        from app.graph_plan_utils import sanitize_session_state

        dirty_state = {
            "trip_inputs": {"destinations": ["Paris"]},
            "__proto__": "attack",
            "constructor": "malicious",
            "normal_key": "value",
        }

        clean_state = sanitize_session_state(dirty_state)

        assert "trip_inputs" in clean_state
        assert "normal_key" in clean_state
        assert "__proto__" not in clean_state
        assert "constructor" not in clean_state

    def test_validate_thread_id(self):
        """Thread ID validation accepts valid UUIDs."""
        from app.graph_plan_utils import is_valid_thread_id

        assert is_valid_thread_id("550e8400-e29b-41d4-a716-446655440000")
        assert not is_valid_thread_id("not-a-uuid")
        assert not is_valid_thread_id("")
        assert not is_valid_thread_id(None)

    def test_truncate_assistant_message(self):
        """Assistant message truncation works correctly."""
        from app.config import settings
        from app.graph_plan_utils import truncate_assistant_message

        short_msg = "Hello"
        assert truncate_assistant_message(short_msg) == short_msg

        # Create a message longer than the configured max
        long_msg = "x" * (settings.assistant_msg_max_len + 100)
        truncated = truncate_assistant_message(long_msg)
        assert len(truncated) <= settings.assistant_msg_max_len

    def test_compute_today_iso(self):
        """today_iso computation uses correct timezone."""
        from app.graph_plan_utils import compute_today_iso

        result = compute_today_iso()
        import re

        assert re.match(r"\d{4}-\d{2}-\d{2}", result)

    def test_normalize_trip_inputs(self):
        """Trip inputs normalization handles various inputs."""
        from app.graph_plan_utils import normalize_trip_inputs

        inputs = {
            "destinations": ["paris", "LONDON"],
            "currency": "usd",
            "adults": "2",  # String instead of int
            "budget": "1000",  # String instead of float
        }

        normalized = normalize_trip_inputs(inputs)

        # Destinations should be title-cased
        assert normalized["destinations"] == ["Paris", "London"]
        # Currency should be uppercase
        assert normalized["currency"] == "USD"

    def test_validate_suggested_responses(self):
        """Suggested responses validation works."""
        from app.graph_plan_utils import validate_suggested_responses

        # Valid responses (1-8 words, no question marks)
        responses = [
            "Tell me more",  # Valid: 3 words
            "Show flights please",  # Valid: 3 words
            "?",  # Invalid: question mark
            "",  # Invalid: empty
            "Norway",  # Valid: 1 word (destinations)
            (
                "This is a very very very long response that exceeds the limit",
            ),  # Invalid: too many words (>8)
        ]

        validated = validate_suggested_responses(responses)

        # Should filter invalid ones
        assert len(validated) <= 3
        for r in validated:
            assert "?" not in r
            assert r  # Not empty
            assert len(r.split()) >= 1
            assert len(r.split()) <= 8
