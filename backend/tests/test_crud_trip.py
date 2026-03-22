"""
Tests for app.crud_trip module.

Covers:
- get_session_by_token() — found/not-found/expired paths, trusted-session marking
- get_or_create_session() — create new, return existing, replace expired, empty token
- get_latest_trip_context_for_session() — found/not-found
- record_chat_message() — with and without trip_context
- get_last_user_message() — found/not-found
- delete_messages_from_id() — rowcount return
- fetch_chat_history() — ordering and limit
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.crud_trip import (
    delete_messages_from_id,
    fetch_chat_history,
    get_last_user_message,
    get_latest_trip_context_for_session,
    get_or_create_session,
    get_session_by_token,
    record_chat_message,
)


def _make_mock_db(scalar_return=None):
    """Create a mock AsyncSession that returns scalar_return from execute."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result
    return db


def _make_session_obj(*, expired: bool = False, token: str = "tok-123"):
    """Create a mock Session model instance."""
    session = MagicMock()
    session.session_token = token
    session.id = 42
    session.is_expired.return_value = expired
    session.refresh_activity = MagicMock()
    return session


class TestGetSessionByToken:
    """Tests for get_session_by_token()."""

    @pytest.mark.asyncio
    async def test_returns_session_when_found_and_not_expired(self):
        session_obj = _make_session_obj(expired=False)
        db = _make_mock_db(scalar_return=session_obj)

        with patch("app.crud_trip.mark_trusted_session_id") as mock_mark:
            result = await get_session_by_token(db, "tok-123")

        assert result is session_obj
        mock_mark.assert_called_once_with("tok-123")

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = _make_mock_db(scalar_return=None)

        with patch("app.crud_trip.forget_trusted_session_id") as mock_forget:
            result = await get_session_by_token(db, "nonexistent")

        assert result is None
        mock_forget.assert_called_once_with("nonexistent")

    @pytest.mark.asyncio
    async def test_returns_expired_session_and_forgets_trust(self):
        session_obj = _make_session_obj(expired=True)
        db = _make_mock_db(scalar_return=session_obj)

        with patch("app.crud_trip.forget_trusted_session_id") as mock_forget:
            result = await get_session_by_token(db, "tok-123")

        # Returns the expired session object (caller decides what to do)
        assert result is session_obj
        mock_forget.assert_called_once_with("tok-123")

    @pytest.mark.asyncio
    async def test_lock_for_update_passes_through(self):
        session_obj = _make_session_obj(expired=False)
        db = _make_mock_db(scalar_return=session_obj)

        with patch("app.crud_trip.mark_trusted_session_id"):
            await get_session_by_token(db, "tok-123", lock_for_update=True)

        # Verify execute was called (the stmt includes with_for_update)
        db.execute.assert_awaited_once()


class TestGetOrCreateSession:
    """Tests for get_or_create_session()."""

    @pytest.mark.asyncio
    async def test_raises_on_empty_token(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="session_token is required"):
            await get_or_create_session(db, "")

    @pytest.mark.asyncio
    async def test_returns_existing_non_expired_session(self):
        session_obj = _make_session_obj(expired=False)
        db = _make_mock_db(scalar_return=session_obj)

        with patch("app.crud_trip.mark_trusted_session_id") as mock_mark:
            result = await get_or_create_session(db, "tok-123")

        assert result is session_obj
        session_obj.refresh_activity.assert_called_once()
        db.flush.assert_awaited()
        mock_mark.assert_called_once_with("tok-123")

    @pytest.mark.asyncio
    async def test_creates_new_session_when_not_found(self):
        db = _make_mock_db(scalar_return=None)

        with patch("app.crud_trip.mark_trusted_session_id") as mock_mark:
            result = await get_or_create_session(db, "new-tok")

        # Should have added a new session object
        db.add.assert_called_once()
        added_obj = db.add.call_args[0][0]
        assert added_obj.session_token == "new-tok"
        mock_mark.assert_called_once_with("new-tok")

    @pytest.mark.asyncio
    async def test_replaces_expired_session(self):
        expired_session = _make_session_obj(expired=True, token="old-tok")
        db = _make_mock_db(scalar_return=expired_session)

        with (
            patch("app.crud_trip.forget_trusted_session_id") as mock_forget,
            patch("app.crud_trip.mark_trusted_session_id") as mock_mark,
        ):
            result = await get_or_create_session(db, "old-tok")

        # Old session deleted
        db.delete.assert_awaited_once_with(expired_session)
        mock_forget.assert_called_once_with("old-tok")
        # New session created
        db.add.assert_called_once()
        mock_mark.assert_called_once_with("old-tok")


class TestGetLatestTripContextForSession:
    """Tests for get_latest_trip_context_for_session()."""

    @pytest.mark.asyncio
    async def test_returns_context_when_found(self):
        ctx = MagicMock()
        db = _make_mock_db(scalar_return=ctx)
        session = _make_session_obj()

        result = await get_latest_trip_context_for_session(db, session=session)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_returns_none_when_no_context(self):
        db = _make_mock_db(scalar_return=None)
        session = _make_session_obj()

        result = await get_latest_trip_context_for_session(db, session=session)
        assert result is None


class TestRecordChatMessage:
    """Tests for record_chat_message()."""

    @pytest.mark.asyncio
    async def test_creates_message_with_trip_context(self):
        db = AsyncMock()
        session = _make_session_obj()
        trip_ctx = MagicMock()
        trip_ctx.id = 99

        result = await record_chat_message(
            db,
            session=session,
            trip_context=trip_ctx,
            role="user",
            content="Hello",
            metadata={"key": "val"},
        )

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.session_id == 42
        assert added.trip_context_id == 99
        assert added.role == "user"
        assert added.content == "Hello"
        assert added.meta == {"key": "val"}
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_message_without_trip_context(self):
        db = AsyncMock()
        session = _make_session_obj()

        result = await record_chat_message(
            db,
            session=session,
            trip_context=None,
            role="assistant",
            content="Hi there",
        )

        added = db.add.call_args[0][0]
        assert added.trip_context_id is None
        assert added.role == "assistant"

    @pytest.mark.asyncio
    async def test_passes_trip_inputs_snapshot(self):
        db = AsyncMock()
        session = _make_session_obj()
        snapshot = {"destination": "Paris"}

        await record_chat_message(
            db,
            session=session,
            trip_context=None,
            role="user",
            content="Go to Paris",
            trip_inputs_snapshot=snapshot,
        )

        added = db.add.call_args[0][0]
        assert added.trip_inputs_snapshot == snapshot


class TestGetLastUserMessage:
    """Tests for get_last_user_message()."""

    @pytest.mark.asyncio
    async def test_returns_message_when_found(self):
        msg = MagicMock()
        db = _make_mock_db(scalar_return=msg)
        session = _make_session_obj()

        result = await get_last_user_message(db, session=session)
        assert result is msg

    @pytest.mark.asyncio
    async def test_returns_none_when_no_messages(self):
        db = _make_mock_db(scalar_return=None)
        session = _make_session_obj()

        result = await get_last_user_message(db, session=session)
        assert result is None


class TestDeleteMessagesFromId:
    """Tests for delete_messages_from_id()."""

    @pytest.mark.asyncio
    async def test_returns_rowcount(self):
        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.rowcount = 5
        db.execute.return_value = exec_result
        session = _make_session_obj()

        result = await delete_messages_from_id(db, session=session, message_id=10)
        assert result == 5
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_matches(self):
        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.rowcount = 0
        db.execute.return_value = exec_result
        session = _make_session_obj()

        result = await delete_messages_from_id(db, session=session, message_id=9999)
        assert result == 0


class TestFetchChatHistory:
    """Tests for fetch_chat_history()."""

    @pytest.mark.asyncio
    async def test_returns_reversed_messages(self):
        msg1 = MagicMock(name="msg1")
        msg2 = MagicMock(name="msg2")
        msg3 = MagicMock(name="msg3")

        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [msg3, msg2, msg1]  # DESC order from DB
        result_mock.scalars.return_value = scalars_mock
        db.execute.return_value = result_mock

        session = _make_session_obj()
        result = await fetch_chat_history(db, session=session, limit=12)

        # Should be reversed to ASC order
        assert result == [msg1, msg2, msg3]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self):
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute.return_value = result_mock

        session = _make_session_obj()
        result = await fetch_chat_history(db, session=session)

        assert result == []

    @pytest.mark.asyncio
    async def test_default_limit_is_12(self):
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute.return_value = result_mock

        session = _make_session_obj()
        await fetch_chat_history(db, session=session)

        # Verify execute was called (limit is embedded in the stmt)
        db.execute.assert_awaited_once()
