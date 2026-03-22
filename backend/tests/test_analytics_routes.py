"""Tests for app.analytics_routes — event tracking and tile click endpoints."""

import pytest
from pydantic import ValidationError

from app.analytics_routes import TrackEventRequest


class TestTrackEventRequest:
    """Validate the Pydantic request schema."""

    def test_valid_event(self) -> None:
        req = TrackEventRequest(event_type="page_view", destination="Paris")
        assert req.event_type == "page_view"
        assert req.destination == "Paris"

    def test_event_type_max_length(self) -> None:
        with pytest.raises(ValidationError):
            TrackEventRequest(event_type="x" * 49)

    def test_destination_optional(self) -> None:
        req = TrackEventRequest(event_type="click")
        assert req.destination is None

    def test_metadata_optional(self) -> None:
        req = TrackEventRequest(event_type="click", metadata={"key": "value"})
        assert req.metadata == {"key": "value"}

    def test_metadata_defaults_none(self) -> None:
        req = TrackEventRequest(event_type="click")
        assert req.metadata is None
