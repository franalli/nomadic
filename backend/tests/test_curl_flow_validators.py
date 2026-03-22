"""
Tests for curl_flow_validators.py -- quality gate functions.

Validates that each validator correctly catches zombie tiles, hollow blocks,
orphan refs, empty sections, SSE errors, canned messages, and ungrounded names.

Run with: pytest tests/test_curl_flow_validators.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VALIDATOR = str(Path(__file__).with_name("curl_flow_validators.py"))


def _run(command: str, stdin_data: str) -> str:
    """Run a validator command with stdin data, return stdout."""
    result = subprocess.run(
        [sys.executable, VALIDATOR, command],
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _parse(output: str) -> dict[str, str]:
    """Parse key=value output into a dict."""
    d: dict[str, str] = {}
    for token in output.split():
        if "=" in token:
            k, v = token.split("=", 1)
            d[k] = v
    return d


# =============================================================================
# tile_quality
# =============================================================================


class TestTileQuality:
    def test_healthy_tiles_zero_zombies(self):
        tiles = {
            "t1": {
                "id": "t1",
                "type": "activity",
                "title": "Dive Site",
                "geo": {"lat": -8.5, "lng": 115.2},
                "deeplink_url": "https://x.com",
            },
            "t2": {
                "id": "t2",
                "type": "hotel",
                "title": "Beach Hotel",
                "deeplink_url": "https://y.com",
            },
        }
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["total"] == "2"
        assert out["zombies"] == "0"
        assert out["geo_invalid"] == "0"

    def test_zombie_no_title(self):
        tiles = {"t1": {"id": "t1", "type": "activity", "title": ""}}
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["zombies"] == "1"

    def test_zombie_activity_no_deeplink_no_geo(self):
        tiles = {"t1": {"id": "t1", "type": "activity", "title": "Dive"}}
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["zombies"] == "1"

    def test_activity_with_deeplink_only_is_ok(self):
        tiles = {
            "t1": {
                "id": "t1",
                "type": "activity",
                "title": "Dive",
                "deeplink_url": "https://viator.com/tours/123",
            }
        }
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["zombies"] == "0"

    def test_activity_with_geo_only_is_ok(self):
        tiles = {
            "t1": {
                "id": "t1",
                "type": "activity",
                "title": "Dive",
                "geo": {"lat": -8.5, "lng": 115.2},
            }
        }
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["zombies"] == "0"

    def test_null_island_flagged(self):
        tiles = {
            "t1": {
                "id": "t1",
                "type": "activity",
                "title": "Dive",
                "geo": {"lat": 0, "lng": 0},
                "deeplink_url": "https://x.com",
            }
        }
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["geo_invalid"] == "1"
        assert out["zombies"] == "0"

    def test_out_of_bounds_geo(self):
        tiles = {
            "t1": {"id": "t1", "type": "hotel", "title": "Hotel", "geo": {"lat": 999, "lng": -200}}
        }
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["geo_invalid"] == "1"

    def test_list_format_tiles(self):
        tiles = [
            {"id": "t1", "type": "activity", "title": "Dive", "geo": {"lat": -8.5, "lng": 115.2}},
        ]
        out = _parse(_run("tile_quality", json.dumps(tiles)))
        assert out["total"] == "1"
        assert out["zombies"] == "0"

    def test_empty_input(self):
        out = _parse(_run("tile_quality", ""))
        assert out["total"] == "0"


# =============================================================================
# block_quality
# =============================================================================


class TestBlockQuality:
    def _make_block(self, **overrides):
        base = {
            "id": "b1",
            "booking_category": "activity",
            "summary": "Temple Visit",
            "deeplink": "https://maps.google.com/?q=123",
            "booked_tile": {"title": "Temple Visit", "id": "t1"},
        }
        base.update(overrides)
        return base

    def test_healthy_blocks(self):
        cards = [{"blocks": [self._make_block()]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["total_activity_blocks"] == "1"
        assert out["hollow"] == "0"

    def test_hollow_block_all_empty(self):
        block = self._make_block(summary="", deeplink="", booked_tile=None)
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["hollow"] == "1"

    def test_hollow_block_generic_summary(self):
        block = self._make_block(summary="Activity", deeplink="", booked_tile=None)
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["hollow"] == "1"

    def test_block_with_only_summary_is_ok(self):
        block = self._make_block(summary="Snorkel at Manta Point", deeplink="", booked_tile=None)
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["hollow"] == "0"

    def test_block_with_only_deeplink_is_ok(self):
        block = self._make_block(
            summary="", deeplink="https://maps.google.com/?q=123", booked_tile=None
        )
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["hollow"] == "0"

    def test_block_with_only_booked_title_is_ok(self):
        block = self._make_block(summary="", deeplink="", booked_tile={"title": "Real Place"})
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["hollow"] == "0"

    def test_buffer_blocks_skipped(self):
        block = self._make_block(is_buffer=True, summary="", deeplink="", booked_tile=None)
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["total_activity_blocks"] == "0"

    def test_hotel_blocks_skipped(self):
        block = {"id": "h1", "booking_category": "hotel", "summary": ""}
        cards = [{"blocks": [block]}]
        out = _parse(_run("block_quality", json.dumps(cards)))
        assert out["total_activity_blocks"] == "0"


# =============================================================================
# block_tile_refs
# =============================================================================


class TestBlockTileRefs:
    def test_all_refs_exist(self):
        data = {
            "tiles": {"t1": {"id": "t1", "title": "Dive"}},
            "day_cards": [
                {
                    "blocks": [
                        {"booking_category": "activity", "booked_tile": {"id": "t1"}},
                    ]
                }
            ],
        }
        out = _parse(_run("block_tile_refs", json.dumps(data)))
        assert out["total_refs"] == "1"
        assert out["orphans"] == "0"

    def test_orphan_detected(self):
        data = {
            "tiles": {"t1": {"id": "t1", "title": "Dive"}},
            "day_cards": [
                {
                    "blocks": [
                        {"booking_category": "activity", "booked_tile": {"id": "t_missing"}},
                    ]
                }
            ],
        }
        out = _parse(_run("block_tile_refs", json.dumps(data)))
        assert out["orphans"] == "1"

    def test_nested_list_format_tiles(self):
        data = {
            "tiles": {"activities": [{"id": "t1", "title": "Dive"}]},
            "day_cards": [
                {
                    "blocks": [
                        {"booking_category": "activity", "booked_tile": {"id": "t1"}},
                    ]
                }
            ],
        }
        out = _parse(_run("block_tile_refs", json.dumps(data)))
        assert out["total_refs"] == "1"
        assert out["orphans"] == "0"


# =============================================================================
# section_content
# =============================================================================


class TestSectionContent:
    def test_feasible_with_content(self):
        secs = [
            {
                "specialist_type": "diving",
                "feasibility_status": "feasible",
                "content_added": [{"title": "Manta Point"}],
            }
        ]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "1"
        assert out["empty_content"] == "0"

    def test_feasible_no_content(self):
        secs = [
            {"specialist_type": "diving", "feasibility_status": "feasible", "content_added": []}
        ]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["empty_content"] == "1"

    def test_infeasible_skipped(self):
        secs = [
            {"specialist_type": "skiing", "feasibility_status": "infeasible", "content_added": []}
        ]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "0"
        assert out["empty_content"] == "0"

    def test_default_feasible_when_status_missing(self):
        """Sections without feasibility_status default to feasible."""
        secs = [{"specialist_type": "diving", "content_added": []}]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "1"
        assert out["empty_content"] == "1"

    def test_local_expert_pending_exempted(self):
        """local_expert with pending enrichment is exempt from empty content check."""
        secs = [
            {
                "specialist_type": "local_expert",
                "content_added": [],
                "local_expert_enrichment": {"state": "pending"},
            }
        ]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "1"
        assert out["empty_content"] == "0"

    def test_local_expert_not_available_exempted(self):
        """local_expert with not_available enrichment is exempt."""
        secs = [
            {
                "specialist_type": "local_expert",
                "content_added": [],
                "local_expert_enrichment": {"state": "not_available"},
            }
        ]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "1"
        assert out["empty_content"] == "0"

    def test_local_expert_no_enrichment_dict_exempted(self):
        """local_expert with no enrichment dict at all is exempt."""
        secs = [{"specialist_type": "local_expert", "content_added": []}]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "1"
        assert out["empty_content"] == "0"

    def test_local_expert_ready_with_empty_content_flagged(self):
        """local_expert with ready enrichment but empty content SHOULD be flagged."""
        secs = [
            {
                "specialist_type": "local_expert",
                "content_added": [],
                "local_expert_enrichment": {"state": "ready"},
            }
        ]
        out = _parse(_run("section_content", json.dumps(secs)))
        assert out["feasible"] == "1"
        assert out["empty_content"] == "1"


# =============================================================================
# no_sse_errors
# =============================================================================


class TestNoSseErrors:
    def test_clean_stream(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sse", delete=False) as f:
            f.write('data: {"type":"token","data":"hello"}\n')
            f.write('data: {"type":"complete","data":{}}\n')
            path = f.name
        try:
            out = _parse(_run("no_sse_errors", path))
            assert out["error_count"] == "0"
        finally:
            os.unlink(path)

    def test_error_detected(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sse", delete=False) as f:
            f.write('data: {"type":"token","data":"hello"}\n')
            f.write('data: {"type":"error","data":{"message":"LLM failed"}}\n')
            f.write('data: {"type":"complete","data":{}}\n')
            path = f.name
        try:
            out = _parse(_run("no_sse_errors", path))
            assert out["error_count"] == "1"
        finally:
            os.unlink(path)


# =============================================================================
# assistant_message
# =============================================================================


class TestAssistantMessage:
    def _payload(self, msg, tools="extract_trip_fields", dest="Bali"):
        return json.dumps(
            {
                "assistant_message": msg,
                "tools_called": tools,
                "destination": dest,
            }
        )

    def test_good_planning_message(self):
        out = _parse(
            _run(
                "assistant_message",
                self._payload(
                    "I've planned a diving trip to Bali with visits to Manta Point and the USAT Liberty wreck."
                ),
            )
        )
        assert out["quality"] == "ok"

    def test_too_short(self):
        out = _parse(_run("assistant_message", self._payload("Done.")))
        assert out["quality"] == "too_short"

    def test_canned_response(self):
        out = _parse(
            _run("assistant_message", self._payload("I'd be happy to help you with your trip!"))
        )
        assert out["quality"] == "canned"

    def test_no_tools_skips_check(self):
        out = _parse(_run("assistant_message", self._payload("Hi!", tools="", dest="")))
        assert out["quality"] == "ok"
        assert out["detail"] == "no_tools_turn"

    def test_no_destination_ref(self):
        out = _parse(
            _run(
                "assistant_message",
                self._payload(
                    "I've set up your trip with diving activities across several great spots.",
                    dest="Bali",
                ),
            )
        )
        assert out["quality"] == "ok"
        assert out["detail"] == "no_destination_ref"


# =============================================================================
# token_content
# =============================================================================


class TestTokenContent:
    def test_normal_tokens(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sse", delete=False) as f:
            f.write('data: {"type":"token","data":"Hello "}\n')
            f.write('data: {"type":"token","data":"world!"}\n')
            path = f.name
        try:
            out = _parse(_run("token_content", path))
            assert out["token_events"] == "2"
            assert int(out["total_chars"]) >= 10
        finally:
            os.unlink(path)

    def test_empty_tokens(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sse", delete=False) as f:
            f.write('data: {"type":"token","data":""}\n')
            path = f.name
        try:
            out = _parse(_run("token_content", path))
            assert out["token_events"] == "1"
            assert out["total_chars"] == "0"
        finally:
            os.unlink(path)


# =============================================================================
# tile_dedup
# =============================================================================


class TestTileDedup:
    def test_no_duplicates(self):
        tiles = {
            "t1": {"id": "t1", "type": "activity", "title": "Manta Point"},
            "t2": {"id": "t2", "type": "activity", "title": "USAT Liberty"},
        }
        out = _parse(_run("tile_dedup", json.dumps(tiles)))
        assert out["dup_titles"] == "0"

    def test_duplicate_detected(self):
        tiles = {
            "t1": {"id": "t1", "type": "activity", "title": "Manta Point"},
            "t2": {"id": "t2", "type": "activity", "title": "Manta Point"},
        }
        out = _parse(_run("tile_dedup", json.dumps(tiles)))
        assert out["dup_titles"] == "1"

    def test_hotel_duplicates_ignored(self):
        tiles = {
            "t1": {"id": "t1", "type": "hotel", "title": "Beach Hotel"},
            "t2": {"id": "t2", "type": "hotel", "title": "Beach Hotel"},
        }
        out = _parse(_run("tile_dedup", json.dumps(tiles)))
        assert out["dup_titles"] == "0"


# =============================================================================
# grounding
# =============================================================================


class TestGrounding:
    def _make_sse_file(self, assistant_msg, destination="Bali", day_cards=None, tiles=None):
        payload = {
            "type": "complete",
            "data": {
                "document": {
                    "assistant_message": assistant_msg,
                    "day_cards": day_cards or [],
                    "tiles": tiles or {},
                },
                "session_state": {
                    "trip_plan": {"destination": destination},
                },
            },
        }
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".sse", delete=False)
        f.write(f"data: {json.dumps(payload)}\n")
        f.close()
        return f.name

    def test_grounded_message(self):
        path = self._make_sse_file(
            "I've planned your trip to Bali with a visit to Manta Point.",
            day_cards=[{"blocks": [{"summary": "Manta Point", "is_buffer": False}]}],
        )
        try:
            out = _run("grounding", path)
            assert "grounded" in out
        finally:
            os.unlink(path)

    def test_ungrounded_name(self):
        path = self._make_sse_file(
            "You should visit the Grand Palace and Floating Market in Bangkok!",
            destination="Bali",
        )
        try:
            out = _run("grounding", path)
            assert "unknown:" in out
        finally:
            os.unlink(path)

    def test_month_names_ignored(self):
        path = self._make_sse_file(
            "Your trip starts on March 15 in Bali.",
        )
        try:
            out = _run("grounding", path)
            assert "grounded" in out
        finally:
            os.unlink(path)
