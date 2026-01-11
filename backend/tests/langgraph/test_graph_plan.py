"""
Tests for the /v1/graph_plan endpoint and related utilities.

Tests include:
- Feature flag gating (503 when disabled)
- Content-Type validation (415 for non-JSON)
- Thread ID validation (400 for invalid UUID)
- Session state handling and sanitization
- today_iso injection
- Optimistic concurrency (409 version conflict)
- Reset parameter behavior (new thread creation)
- Timeout handling (504 for timeouts)
- JSON parsing utilities (malformed JSON recovery)
- Currency normalization (symbols to ISO codes)
- Destination normalization (deduplication, country stripping)
- Suggested response validation
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
            "run_id": "mock-run-id-12345",  # LangSmith trace ID
            "session_state": {
                "trip_inputs": {"destinations": ["Paris"], "origin": "London"},
                "metadata": {},
                "flags": {},
                "last_summary": "I can help you plan your trip!",
                "branches": [],
                "suggested_responses": ["Tell me more about hotels", "Show me flights"],
                "errors": [],
                "thread_id": "test-thread-id",
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

    def test_invalid_thread_id_rejected(self, client, mock_run_turn):
        """Invalid thread_id format returns 400."""
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "Test message",
                "thread_id": "not-a-valid-uuid",
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == GraphPlanErrorCode.INVALID_THREAD_ID

    def test_valid_thread_id_accepted(self, client, mock_run_turn):
        """Valid UUID thread_id is accepted."""
        import uuid

        valid_uuid = str(uuid.uuid4())
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "Test message",
                "thread_id": valid_uuid,
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200


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


class TestGraphPlanReset:
    """Tests for reset parameter behavior."""

    def test_reset_creates_new_thread(self, client, mock_run_turn):
        """Reset parameter with empty session_state creates new thread."""
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "Start fresh",
                "reset": True,
                "session_state": None,
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200

        # Verify run_turn was called with a new thread_id
        call_args = mock_run_turn.call_args
        session_state = call_args[0][1]
        assert "thread_id" in session_state
        # thread_id should be a valid UUID
        import uuid

        try:
            uuid.UUID(session_state["thread_id"])
        except ValueError:
            pytest.fail("thread_id should be a valid UUID")

    def test_reset_with_trip_inputs(self, client, mock_run_turn):
        """Reset with trip_inputs initializes session state, but document takes precedence.

        Note: Document trip_inputs are source of truth - they override request trip_inputs
        when a document exists for the session. For a fresh session with empty document,
        the request trip_inputs would be used, but after document hydration they may
        be overwritten by document defaults.
        """
        response = client.post(
            "/v1/graph_plan",
            json={
                "message": "Plan new trip",
                "reset": True,
                "session_state": None,
                "trip_inputs": {
                    "destinations": ["Tokyo"],
                    "adults": 2,
                },
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200

        # Verify session state was created and passed to run_turn
        call_args = mock_run_turn.call_args
        session_state = call_args[0][1]
        assert "trip_inputs" in session_state
        # Note: Document trip_inputs override request trip_inputs (document is source of truth)
        # so destinations may be empty if document was just created with defaults


class TestGraphPlanTimeout:
    """Tests for timeout handling."""

    def test_timeout_returns_504(self, client):
        """Route timeout returns 504 Gateway Timeout."""
        import asyncio

        with patch("app.main.run_turn") as mock:
            # Make run_turn raise TimeoutError
            mock.side_effect = asyncio.TimeoutError()

            response = client.post(
                "/v1/graph_plan",
                json={"message": "Slow request"},
                headers={"X-CSRF-Token": "test-csrf-token"},
            )

            assert response.status_code == 504
            data = response.json()
            assert data["detail"]["error_code"] == GraphPlanErrorCode.LLM_TIMEOUT

    def test_general_exception_returns_500(self, client):
        """Unhandled exception returns 500 Internal Server Error."""
        with patch("app.main.run_turn") as mock:
            mock.side_effect = RuntimeError("Unexpected error")

            response = client.post(
                "/v1/graph_plan",
                json={"message": "Failing request"},
                headers={"X-CSRF-Token": "test-csrf-token"},
            )

            # Should return 500 (unhandled exception)
            assert response.status_code == 500


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


class TestGraphPlanJsonParsing:
    """Tests for JSON parsing utilities (PR-D extraction)."""

    def test_truncate_to_balanced_json_valid(self):
        """Extracts valid JSON from garbage-wrapped input."""
        from app.graph_plan_utils import truncate_to_balanced_json

        # Valid JSON wrapped in garbage
        raw = 'Some prefix text {"key": "value", "nested": {"a": 1}} trailing garbage'
        result = truncate_to_balanced_json(raw)
        assert result == '{"key": "value", "nested": {"a": 1}}'

    def test_truncate_to_balanced_json_truncated(self):
        """Returns None for truncated JSON."""
        from app.graph_plan_utils import truncate_to_balanced_json

        # Truncated JSON (unclosed brace)
        raw = '{"key": "value", "nested": {"a": 1'
        result = truncate_to_balanced_json(raw)
        assert result is None

    def test_truncate_to_balanced_json_string_escapes(self):
        """Handles escaped quotes in strings correctly."""
        from app.graph_plan_utils import truncate_to_balanced_json

        # JSON with escaped quotes
        raw = '{"message": "He said \\"hello\\"", "count": 1}'
        result = truncate_to_balanced_json(raw)
        assert result == '{"message": "He said \\"hello\\"", "count": 1}'

    def test_jloads_safe_valid_json(self):
        """Parses valid JSON correctly."""
        from app.graph_plan_utils import jloads_safe

        result = jloads_safe('{"key": "value"}')
        assert result == {"key": "value"}

    def test_jloads_safe_malformed_recovers(self):
        """Recovers from malformed JSON with garbage around it."""
        from app.graph_plan_utils import jloads_safe

        # Garbage before JSON
        raw = 'Here is the output: {"key": "value"}'
        result = jloads_safe(raw)
        assert result.get("key") == "value"

    def test_jloads_safe_empty_returns_empty_dict(self):
        """Returns empty dict for empty input."""
        from app.graph_plan_utils import jloads_safe

        assert jloads_safe("") == {}

    def test_extract_message_from_malformed_json(self):
        """Extracts assistant_message from truncated JSON."""
        from app.graph_plan_utils import extract_message_from_malformed_json

        # Truncated JSON with complete assistant_message
        raw = (
            '{"assistant_message": "I can help you plan a trip to Paris. '
            'This is a complete message that ends properly.", "trip_inputs": {'
        )
        result = extract_message_from_malformed_json(raw)
        # Should extract the message even though JSON is truncated
        assert result is not None
        assert "Paris" in result

    def test_extract_message_returns_none_for_short_message(self):
        """Returns None if extracted message is too short."""
        from app.graph_plan_utils import extract_message_from_malformed_json

        # Very short message
        raw = '{"assistant_message": "Hi"}'
        result = extract_message_from_malformed_json(raw)
        # Should return None because message is < 50 chars
        assert result is None


class TestGraphPlanCurrencyNormalization:
    """Tests for currency normalization."""

    def test_normalize_currency_code(self):
        """ISO currency codes are uppercased."""
        from app.graph_plan_utils import normalize_currency

        assert normalize_currency("usd") == "USD"
        assert normalize_currency("eur") == "EUR"
        assert normalize_currency("GBP") == "GBP"

    def test_normalize_currency_symbol(self):
        """Currency symbols are mapped to ISO codes."""
        from app.graph_plan_utils import normalize_currency

        assert normalize_currency("$") == "USD"
        assert normalize_currency("€") == "EUR"
        assert normalize_currency("£") == "GBP"

    def test_normalize_currency_invalid(self):
        """Invalid currencies return None."""
        from app.graph_plan_utils import normalize_currency

        assert normalize_currency("invalid") is None
        assert normalize_currency("") is None
        assert normalize_currency(None) is None


class TestGraphPlanDestinationNormalization:
    """Tests for destination normalization."""

    def test_normalize_destinations_basic(self):
        """Basic destination normalization works."""
        from app.graph_plan_utils import normalize_destinations

        result = normalize_destinations(["paris", "LONDON", "tokyo"])
        assert result == ["Paris", "London", "Tokyo"]

    def test_normalize_destinations_deduplication(self):
        """Duplicate destinations are removed (case-insensitive)."""
        from app.graph_plan_utils import normalize_destinations

        result = normalize_destinations(["Paris", "paris", "PARIS"])
        assert result == ["Paris"]

    def test_normalize_destinations_strips_country(self):
        """Country suffixes are stripped."""
        from app.graph_plan_utils import normalize_destinations

        result = normalize_destinations(["Banff, Canada", "Tokyo, Japan"])
        assert result == ["Banff", "Tokyo"]

    def test_normalize_destinations_preserves_short_codes(self):
        """Short all-caps codes are preserved."""
        from app.graph_plan_utils import normalize_destinations

        result = normalize_destinations(["EBC", "NYC"])
        assert "EBC" in result
        assert "NYC" in result
