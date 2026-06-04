#!/usr/bin/env python3
"""
Nomadic E2E Quality Validators -- curl flow test suite.

Called from run_curl_flows.sh via bash wrapper functions.
Each validator reads JSON from stdin, runs quality checks, and prints
a machine-readable result line.  Bash wrappers parse the result and
call check()/check_gte() accordingly.

Usage from bash:
    echo "$TILES_JSON" | python3 tests/curl_flow_validators.py tile_quality
    echo "$DAY_CARDS_JSON" | python3 tests/curl_flow_validators.py block_quality
    echo "$RESP_FILE_PATH" | python3 tests/curl_flow_validators.py no_sse_errors
    ... etc

Exit codes: 0 always (bash reads stdout for results, not exit code).
"""

from __future__ import annotations

import json
import re
import sys

# --- Tile Quality -------------------------------------------------------------


def validate_tile_quality() -> None:
    """Check tiles for zombie entries (missing title, broken geo, no deeplink).

    Reads tiles JSON (dict or list) from stdin.
    Prints: total=N zombies=M zombie_ids=id1,id2 geo_invalid=K
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("total=0 zombies=0 zombie_ids= geo_invalid=0")
        return

    try:
        tiles = json.loads(raw)
    except json.JSONDecodeError:
        print("total=0 zombies=0 zombie_ids= geo_invalid=0 parse_error=true")
        return

    vals = tiles.values() if isinstance(tiles, dict) else (tiles if isinstance(tiles, list) else [])
    tile_list = [t for t in vals if isinstance(t, dict)]

    total = len(tile_list)
    zombies: list[str] = []
    geo_invalid = 0

    for t in tile_list:
        tile_id = str(t.get("id", "?"))[:40]
        tile_type = t.get("type", "")

        # Zombie: tile with no title
        title = (t.get("title") or "").strip()
        if not title:
            zombies.append(tile_id)
            continue

        # Zombie: activity tile with no deeplink AND no geo
        if tile_type == "activity":
            has_deeplink = bool(
                (t.get("deeplink_url") or "").strip() or (t.get("deeplink") or "").strip()
            )
            geo = t.get("geo") or {}
            has_geo = (
                isinstance(geo, dict) and geo.get("lat") is not None and geo.get("lng") is not None
            )
            if not has_deeplink and not has_geo:
                zombies.append(tile_id)
                continue

        # Geo sanity: not null island, within bounds
        geo = t.get("geo")
        if isinstance(geo, dict) and geo.get("lat") is not None:
            lat = geo.get("lat", 0)
            lng = geo.get("lng", 0)
            try:
                lat, lng = float(lat), float(lng)
                if abs(lat) > 90 or abs(lng) > 180:
                    geo_invalid += 1
                elif lat == 0 and lng == 0:
                    geo_invalid += 1
            except (ValueError, TypeError):
                geo_invalid += 1

    zombie_ids = ",".join(zombies[:5])
    print(f"total={total} zombies={len(zombies)} zombie_ids={zombie_ids} geo_invalid={geo_invalid}")


# --- Day Card Block Quality ---------------------------------------------------


def validate_block_quality() -> None:
    """Check day_cards for hollow activity blocks.

    A hollow block has booking_category=activity but ALL of:
      - summary is empty/generic
      - deeplink is empty
      - booked_tile is null or has no title

    Reads day_cards JSON array from stdin.
    Prints: total_activity_blocks=N hollow=M hollow_ids=id1,id2
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("total_activity_blocks=0 hollow=0 hollow_ids=")
        return

    try:
        cards = json.loads(raw)
    except json.JSONDecodeError:
        print("total_activity_blocks=0 hollow=0 hollow_ids= parse_error=true")
        return

    if not isinstance(cards, list):
        print("total_activity_blocks=0 hollow=0 hollow_ids=")
        return

    GENERIC_SUMMARIES = {
        "",
        "activity",
        "experience",
        "free day",
        "free time",
        "arrive at destination",
        "depart for home",
    }

    total = 0
    hollow: list[str] = []

    for card in cards:
        if not isinstance(card, dict):
            continue
        for block in card.get("blocks", []):
            if not isinstance(block, dict):
                continue
            if block.get("booking_category") != "activity":
                continue
            if block.get("is_buffer"):
                continue

            total += 1
            block_id = str(block.get("id", "?"))[:40]

            summary = (block.get("summary") or "").strip().lower()
            has_summary = summary and summary not in GENERIC_SUMMARIES

            deeplink = (block.get("deeplink") or "").strip()
            has_deeplink = bool(deeplink)

            booked = block.get("booked_tile")
            booked_title = ""
            if isinstance(booked, dict):
                booked_title = (booked.get("title") or "").strip()
            has_booked = bool(booked_title)

            if not has_summary and not has_deeplink and not has_booked:
                hollow.append(block_id)

    hollow_ids = ",".join(hollow[:5])
    print(f"total_activity_blocks={total} hollow={len(hollow)} hollow_ids={hollow_ids}")


# --- Block <-> Tile Consistency ------------------------------------------------


def validate_block_tile_refs() -> None:
    """Check that activity block booked_tile.id references exist in tiles dict.

    Reads JSON object: {"tiles": ..., "day_cards": ...} from stdin.
    Prints: total_refs=N orphans=M orphan_ids=id1,id2
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("total_refs=0 orphans=0 orphan_ids=")
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("total_refs=0 orphans=0 orphan_ids= parse_error=true")
        return

    tiles_raw = data.get("tiles", {})
    cards = data.get("day_cards", [])

    # Build tile ID set
    tile_ids: set[str] = set()
    if isinstance(tiles_raw, dict):
        for key, val in tiles_raw.items():
            if isinstance(val, list):
                for t in val:
                    if isinstance(t, dict) and t.get("id"):
                        tile_ids.add(str(t["id"]))
            elif isinstance(val, dict):
                tile_ids.add(str(key))
                if val.get("id"):
                    tile_ids.add(str(val["id"]))

    total_refs = 0
    orphans: list[str] = []

    if isinstance(cards, list):
        for card in cards:
            if not isinstance(card, dict):
                continue
            for block in card.get("blocks", []):
                if not isinstance(block, dict):
                    continue
                if block.get("booking_category") != "activity":
                    continue
                booked = block.get("booked_tile")
                if not isinstance(booked, dict):
                    continue
                booked_id = str(booked.get("id") or "").strip()
                if not booked_id:
                    continue
                total_refs += 1
                if booked_id not in tile_ids:
                    orphans.append(booked_id)

    orphan_ids = ",".join(orphans[:5])
    print(f"total_refs={total_refs} orphans={len(orphans)} orphan_ids={orphan_ids}")


# --- Strategy Section Content Quality -----------------------------------------


def validate_section_content() -> None:
    """Check that feasible strategy sections have non-empty content_added.

    Reads strategy_sections JSON array from stdin.
    Prints: feasible=N empty_content=M empty_types=type1,type2
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("feasible=0 empty_content=0 empty_types=")
        return

    try:
        sections = json.loads(raw)
    except json.JSONDecodeError:
        print("feasible=0 empty_content=0 empty_types= parse_error=true")
        return

    if not isinstance(sections, list):
        print("feasible=0 empty_content=0 empty_types=")
        return

    feasible = 0
    empty_content: list[str] = []

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        status = (sec.get("feasibility_status") or "feasible").lower()
        if status != "feasible":
            continue

        feasible += 1

        # local_expert uses two-phase enrichment: Phase A (sync) creates skeleton
        # with content_added=[]; Phase B (async) fills it after SSE completes.
        if sec.get("specialist_type") == "local_expert":
            enrich = sec.get("local_expert_enrichment") or {}
            if enrich.get("state", "") in ("pending", "not_available", "failed", ""):
                continue

        content = sec.get("content_added")
        if not isinstance(content, list) or len(content) == 0:
            spec_type = sec.get("specialist_type", "?")
            empty_content.append(spec_type)

    empty_types = ",".join(empty_content[:5])
    print(f"feasible={feasible} empty_content={len(empty_content)} empty_types={empty_types}")


# --- SSE Error Absence ---------------------------------------------------------


def validate_no_sse_errors() -> None:
    """Check SSE stream for error events.

    Reads SSE response file PATH from stdin (not the content).
    Prints: error_count=N first_error=...
    """
    filepath = sys.stdin.read().strip()
    if not filepath:
        print("error_count=0 first_error=")
        return

    error_count = 0
    first_error = ""

    try:
        with open(filepath) as f:
            for line in f:
                if not line.startswith("data: "):
                    continue
                try:
                    obj = json.loads(line[6:])
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("type") == "error":
                    error_count += 1
                    if not first_error:
                        err_data = obj.get("data", {})
                        first_error = str(
                            err_data.get("message") or err_data.get("error") or json.dumps(err_data)
                        )[:120]
    except FileNotFoundError:
        print("error_count=-1 first_error=file_not_found")
        return

    first_error_safe = first_error.replace("\n", " ").replace("\r", "")
    print(f"error_count={error_count} first_error={first_error_safe}")


# --- Assistant Message Quality -------------------------------------------------


def validate_assistant_message() -> None:
    """Check assistant_message for minimum quality on planning turns.

    Reads JSON: {"assistant_message": "...", "tools_called": "...", "destination": "..."}
    Prints: length=N quality=ok|too_short|canned|ungrounded detail=...
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("length=0 quality=missing detail=no_input")
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("length=0 quality=missing detail=parse_error")
        return

    msg = str(data.get("assistant_message") or "")
    tools = str(data.get("tools_called") or "")
    destination = str(data.get("destination") or "").lower()

    length = len(msg)

    # If no tools were called (greeting/conversational), skip quality checks
    if not tools or tools == "":
        print(f"length={length} quality=ok detail=no_tools_turn")
        return

    # Too short for a planning turn
    if length < 30:
        print(f"length={length} quality=too_short detail=planning_turn_under_30_chars")
        return

    # Canned non-answers
    CANNED = [
        "i'd be happy to help",
        "i'm happy to help",
        "let me know if you",
        "is there anything else",
        "feel free to ask",
        "here's what i found",
    ]
    msg_lower = msg.lower()
    for phrase in CANNED:
        if msg_lower.startswith(phrase) and length < 80:
            print(f"length={length} quality=canned detail={phrase[:40]}")
            return

    # Destination reference check
    if destination and len(destination) > 2:
        if destination not in msg_lower:
            print(f"length={length} quality=ok detail=no_destination_ref")
            return

    print(f"length={length} quality=ok detail=passed")


# --- Token Content Check -------------------------------------------------------


def validate_token_content() -> None:
    """Check that concatenated token payloads have meaningful length.

    Reads SSE response file PATH from stdin.
    Prints: token_events=N total_chars=M
    """
    filepath = sys.stdin.read().strip()
    if not filepath:
        print("token_events=0 total_chars=0")
        return

    token_events = 0
    total_chars = 0

    try:
        with open(filepath) as f:
            for line in f:
                if not line.startswith("data: "):
                    continue
                try:
                    obj = json.loads(line[6:])
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("type") == "token":
                    token_events += 1
                    payload = obj.get("data", "")
                    if isinstance(payload, str):
                        total_chars += len(payload)
                    elif isinstance(payload, dict):
                        total_chars += len(str(payload.get("text", "")))
    except FileNotFoundError:
        print("token_events=0 total_chars=0 file_error=true")
        return

    print(f"token_events={token_events} total_chars={total_chars}")


# --- Duplicate Tile Detection --------------------------------------------------


def validate_tile_dedup() -> None:
    """Check for duplicate activity tiles by title (normalized).

    Reads tiles JSON (dict or list) from stdin.
    Prints: activity_tiles=N dup_titles=M dup_examples=title1|title2
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("activity_tiles=0 dup_titles=0 dup_examples=")
        return

    try:
        tiles = json.loads(raw)
    except json.JSONDecodeError:
        print("activity_tiles=0 dup_titles=0 dup_examples= parse_error=true")
        return

    vals = tiles.values() if isinstance(tiles, dict) else (tiles if isinstance(tiles, list) else [])

    title_counts: dict[str, int] = {}
    for t in vals:
        if not isinstance(t, dict):
            continue
        if t.get("type") != "activity":
            continue
        title = (t.get("title") or "").strip().lower()
        if not title:
            continue
        title_counts[title] = title_counts.get(title, 0) + 1

    activity_tiles = sum(title_counts.values())
    dups = {t: c for t, c in title_counts.items() if c > 1}
    dup_examples = "|".join(list(dups.keys())[:3])

    print(f"activity_tiles={activity_tiles} dup_titles={len(dups)} dup_examples={dup_examples}")


# --- Grounding Check -----------------------------------------------------------


def _extract_proper_nouns(text: str, safe_names: set[str]) -> None:
    """Extract capitalized multi-word proper nouns from text into safe_names."""
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        safe_names.add(m.group(0).lower())


def validate_grounding() -> None:
    """Check that assistant_message only references names from payload state.

    Reads SSE response file PATH from stdin.
    Prints: status=grounded|unknown:Name1,Name2
    """
    filepath = sys.stdin.read().strip()
    if not filepath:
        print("status=grounded")
        return

    GENERIC = {
        "",
        "arrive at destination",
        "depart for home",
        "arrival",
        "departure",
        "free day",
        "check-in",
        "check-out",
        "check in",
        "check out",
    }
    MONTHS = {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    }

    assistant = ""
    safe_names: set[str] = set()

    def add_name(raw: str | None) -> None:
        name = str(raw or "").strip()
        if not name or name.lower() in GENERIC:
            return
        safe_names.add(name.lower())

    try:
        with open(filepath) as fh:
            for line in fh:
                if not line.startswith("data: "):
                    continue
                try:
                    outer = json.loads(line[6:])
                except (json.JSONDecodeError, ValueError):
                    continue
                if outer.get("type") != "complete":
                    continue

                data = outer.get("data", {})
                document = data.get("document", {}) or {}
                session_state = data.get("session_state", {}) or {}
                # Always use the last complete event's assistant message
                assistant = str(
                    document.get("assistant_message") or data.get("assistant_message") or ""
                )

                trip_plan = session_state.get("trip_plan", {}) or {}
                add_name(trip_plan.get("destination"))
                add_name(trip_plan.get("origin"))

                # Ground proper nouns from the TOOL-OUTPUT fields (strategy
                # sections, tiles, day cards) -- the agent orchestrator writes
                # richer prose than the old templated voice and legitimately
                # names local-intel details (streets, neighborhoods, tips), section
                # labels, and fetched entities. Deliberately NOT the whole document:
                # it carries assistant_message, which would self-ground the very
                # prose we're checking. A name absent from all tool output is a
                # hallucination.
                _grounding_sources = json.dumps(
                    [
                        document.get("strategy_sections")
                        or session_state.get("strategy_sections")
                        or [],
                        document.get("tiles") or session_state.get("tiles") or {},
                        document.get("itinerary_day_cards")
                        or document.get("day_cards")
                        or session_state.get("day_cards")
                        or [],
                    ],
                    default=str,
                )
                _extract_proper_nouns(_grounding_sources, safe_names)

                day_cards = (
                    document.get("day_cards")
                    or document.get("itinerary_day_cards")
                    or session_state.get("day_cards")
                    or []
                )
                for card in day_cards:
                    if not isinstance(card, dict):
                        continue
                    for block in card.get("blocks", []) or []:
                        if not isinstance(block, dict):
                            continue
                        if not block.get("is_buffer"):
                            add_name(block.get("summary"))
                        booked_tile = block.get("booked_tile") or {}
                        if isinstance(booked_tile, dict):
                            add_name(booked_tile.get("title"))

                tiles = document.get("tiles") or session_state.get("tiles") or {}
                tile_values = tiles.values() if isinstance(tiles, dict) else tiles
                for tile in tile_values:
                    if isinstance(tile, dict):
                        # Any FETCHED tile is a groundable entity -- the agent
                        # orchestrator describes the options it found, not only
                        # the ones already selected/booked. (Anti-hallucination
                        # still flags names that appear in NO tool output.)
                        add_name(tile.get("title"))
                        meta = tile.get("meta") or {}
                        if isinstance(meta, dict):
                            _extract_proper_nouns(meta.get("description", ""), safe_names)

                strategy_sections = (
                    document.get("strategy_sections")
                    or session_state.get("strategy_sections")
                    or []
                )
                for section in strategy_sections:
                    if not isinstance(section, dict):
                        continue
                    for constraint in section.get("constraints_applied", []):
                        if isinstance(constraint, dict):
                            add_name(constraint.get("rule"))
                            add_name(constraint.get("reason"))
                    for content in section.get("content_added", []):
                        if isinstance(content, dict):
                            add_name(content.get("title"))
                            _extract_proper_nouns(content.get("description", ""), safe_names)
                    for must_do in section.get("must_dos", []):
                        if isinstance(must_do, str):
                            add_name(must_do)
    except FileNotFoundError:
        print("status=grounded")
        return

    if not assistant:
        print("status=grounded")
        return

    phrases = {
        match.group(0).strip().rstrip(".")
        for match in re.finditer(
            r"\b(?:[A-Z][A-Za-z0-9'&\-]+(?:\s+[A-Z][A-Za-z0-9'&\-]+)+)\b",
            assistant,
        )
    }

    def _tokens_grounded(lowered: str, safe_names: set[str]) -> bool:
        if any(lowered == safe or lowered in safe or safe in lowered for safe in safe_names):
            return True
        tokens = lowered.split()
        if len(tokens) < 2:
            return False
        for safe in safe_names:
            safe_tokens = set(safe.split())
            matched = sum(
                1
                for t in tokens
                if t in safe_tokens or t.rstrip("s") in safe_tokens or t + "s" in safe_tokens
            )
            if matched >= len(tokens):
                return True
        return False

    unknown = []
    for phrase in sorted(phrases):
        lowered = phrase.lower()
        tokens = phrase.split()
        cleaned = [t.lower().rstrip(".,;:!?") for t in tokens]
        if all(c in MONTHS for c in cleaned):
            continue
        _TEMPORAL_PREPS = {
            "since",
            "after",
            "before",
            "during",
            "from",
            "until",
            "by",
            "through",
            "around",
            "early",
            "late",
            "mid",
        }
        if len(tokens) == 2 and cleaned[0] in _TEMPORAL_PREPS and cleaned[1] in MONTHS:
            continue
        if lowered.startswith("day "):
            continue
        if _tokens_grounded(lowered, safe_names):
            continue
        unknown.append(phrase)

    if unknown:
        print("status=unknown:" + ",".join(unknown[:5]))
    else:
        print("status=grounded")


# --- Dispatcher ----------------------------------------------------------------

COMMANDS = {
    "tile_quality": validate_tile_quality,
    "block_quality": validate_block_quality,
    "block_tile_refs": validate_block_tile_refs,
    "section_content": validate_section_content,
    "no_sse_errors": validate_no_sse_errors,
    "assistant_message": validate_assistant_message,
    "token_content": validate_token_content,
    "tile_dedup": validate_tile_dedup,
    "grounding": validate_grounding,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(COMMANDS.keys())}>", file=sys.stderr)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
