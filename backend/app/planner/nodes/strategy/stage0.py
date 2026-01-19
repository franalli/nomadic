"""
Strategy Stage 0 Coordinator - Duration-aware strategy response.

Provides immediate value (destination archetypes + tailored suggestions) with
a single clarifying question. Now requires dates and destinations before firing
to provide meaningful, duration-aware suggestions.

This is the authoritative implementation for Stage 0 logic.
The _strategy_stage0 function in strategy_main.py delegates to this module.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from app.plan_graph import GraphState


def calculate_trip_duration(ti) -> Tuple[Optional[int], str]:
    """
    Calculate trip duration in days and return duration context string.

    Args:
        ti: TripInputs with start_date and optionally end_date

    Returns:
        Tuple of (duration_days, duration_context_string)
        - duration_days is None if dates are incomplete
        - duration_context is empty string if can't determine duration
    """
    if not ti.start_date:
        return None, ""

    try:
        start = datetime.strptime(ti.start_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None, ""

    if ti.end_date:
        try:
            end = datetime.strptime(ti.end_date, "%Y-%m-%d")
            days = (end - start).days + 1
        except (ValueError, TypeError):
            return None, ""
    else:
        # No end_date, can't determine duration
        return None, ""

    # Generate context based on duration
    if days <= 0:
        return None, ""
    elif days <= 3:
        return days, (
            f"This is a short {days}-day trip. "
            "Focus on highlights and compact experiences that maximize the limited time. "
            "Suggest intensive but achievable itineraries."
        )
    elif days <= 5:
        return days, (
            f"This is a {days}-day trip. "
            "Balance key highlights with some flexibility for exploration. "
            "Include the must-see experiences plus one or two hidden gems."
        )
    elif days <= 7:
        return days, (
            f"This is a week-long trip ({days} days). "
            "Balance exploration with relaxation time. "
            "Suggest a mix of active days and easier-paced experiences."
        )
    elif days <= 14:
        return days, (
            f"This is an extended {days}-day trip. "
            "Include regional exploration and deeper immersion opportunities. "
            "Suggest multi-region itineraries or in-depth single-area focus."
        )
    else:
        return days, (
            f"This is a long {days}-day adventure. "
            "Design a comprehensive journey with multiple regions or themes. "
            "Include rest days and flexibility for spontaneous discoveries."
        )


class Stage0Coordinator:
    """
    Coordinator for Stage 0: Pre-core field collection.

    Handles the value-first approach where we provide destination
    archetypes and helpful information before asking for missing
    core fields (dates, origin, etc.).
    """

    @staticmethod
    async def execute(state: "GraphState", topic: str) -> "GraphState":
        """
        Execute Stage 0 logic.

        This is the main entry point for Stage 0 processing.
        Delegates to strategy_stage0 for the actual implementation.

        Args:
            state: Current graph state
            topic: Strategy topic (hiking, skiing, diving, etc.)

        Returns:
            Updated graph state
        """
        return await strategy_stage0(state, topic)


# Deterministic fallback templates with value + single question
STAGE0_FALLBACK_TEMPLATES = {
    "hiking": (
        "**Hiking Destinations:**\n\n"
        "**Top Options:**\n"
        "- **Swiss Alps** — Iconic trails like the Haute Route\n"
        "- **Patagonia, Chile** — Torres del Paine circuit\n"
        "- **New Zealand** — Milford Track and Routeburn\n"
        "- **Nepal** — Classic Annapurna or Everest base camp\n\n"
        "When are you thinking of going?"
    ),
    "skiing": (
        "**Ski Destinations:**\n\n"
        "**Top Options:**\n"
        "- **French Alps** — Chamonix, Val d'Isère, Les 3 Vallées\n"
        "- **Swiss Alps** — Zermatt, Verbier, St. Moritz\n"
        "- **Japan** — Niseko, Hakuba for legendary powder\n"
        "- **Colorado** — Vail, Aspen, Breckenridge\n\n"
        "When are you thinking of going?"
    ),
    "diving": (
        "**Dive Destinations:**\n\n"
        "**Top Options:**\n"
        "- **Maldives** — Pristine reefs and manta rays\n"
        "- **Great Barrier Reef, Australia** — World-class diving\n"
        "- **Red Sea, Egypt** — Wrecks and colorful reefs\n"
        "- **Indonesia** — Raja Ampat biodiversity hotspot\n\n"
        "When are you thinking of going?"
    ),
    "cycling": (
        "**Cycling Destinations:**\n\n"
        "**Top Options:**\n"
        "- **Netherlands** — Classic flat cycling with canals\n"
        "- **French countryside** — Loire Valley vineyards\n"
        "- **Italian Dolomites** — Stunning mountain passes\n"
        "- **Vietnam** — Ha Long Bay to Hoi An adventure\n\n"
        "When are you thinking of going?"
    ),
    "boating": (
        "**Sailing Destinations:**\n\n"
        "**Top Options:**\n"
        "- **Greek Islands** — Island-hop through the Cyclades\n"
        "- **Croatia** — Dalmatian coast beauty\n"
        "- **Caribbean** — BVI, Grenadines, or Bahamas\n"
        "- **Thailand** — Phuket and the Andaman Sea\n\n"
        "When are you thinking of going?"
    ),
}


# =============================================================================
# MINIMAL CENTRAL PLANNER TEMPLATES - just destination names, no descriptions
# =============================================================================
# Design principle: Central planner = plan state. Split view = option evaluation.
# Shows only minimal destination lists to keep central view clean for coherence checking.
STAGE0_MINIMAL_TEMPLATES: Dict[str, Tuple[str, List[str]]] = {
    "hiking": (
        "Hiking destinations: Swiss Alps · Patagonia · New Zealand · Nepal",
        ["Swiss Alps", "Patagonia", "Show more options"],
    ),
    "skiing": (
        "Ski destinations: French Alps · Swiss Alps · Japan · Colorado",
        ["French Alps", "Japan", "Show more options"],
    ),
    "diving": (
        "Dive destinations: Maldives · Great Barrier Reef · Red Sea · Indonesia",
        ["Maldives", "Indonesia", "Show more options"],
    ),
    "cycling": (
        "Cycling destinations: Netherlands · France · Italian Dolomites · Vietnam",
        ["Netherlands", "France", "Show more options"],
    ),
    "boating": (
        "Sailing destinations: Greek Islands · Croatia · Caribbean · Thailand",
        ["Greek Islands", "Caribbean", "Show more options"],
    ),
    "surfing": (
        "Surf destinations: Bali · Hawaii · Portugal · Costa Rica",
        ["Bali", "Hawaii", "Show more options"],
    ),
    "climbing": (
        "Climbing destinations: Yosemite · Dolomites · Chamonix · Kalymnos",
        ["Yosemite", "Chamonix", "Show more options"],
    ),
    "safari": (
        "Safari destinations: Tanzania · Kenya · Botswana · South Africa",
        ["Tanzania", "Kenya", "Show more options"],
    ),
}


def apply_minimal_strategy_template(
    state: "GraphState",
    topic: str,
    is_stage0: bool = True,
) -> None:
    """
    Apply minimal template for central planner view.

    Shows just destination names without detailed descriptions.
    Used when ready_to_generate=False to keep central view clean.
    """
    from app.debug_utils import _debug

    template = STAGE0_MINIMAL_TEMPLATES.get(topic)
    if not template:
        # Fallback for unknown topic
        state.last_summary = f"{topic.capitalize()} trip options available."
        state.suggested_responses = ["Show options", "Set dates"]
    else:
        message, suggestions = template
        state.last_summary = message
        state.suggested_responses = suggestions

    state.metadata["response_writer_node"] = (
        f"strategy_node:stage{'0' if is_stage0 else '1'}:minimal"
    )
    state.metadata["response_generation_provenance"] = "template"
    state.metadata["strategy_minimal_central"] = True

    _debug(
        f"STRATEGY_MINIMAL_TEMPLATE: {topic}",
        stage="0" if is_stage0 else "1",
        response_preview=state.last_summary[:50] if state.last_summary else "",
    )


# Destination+topic specific templates for enhanced guidance (Tier 10.22)
# These provide expert knowledge for popular destination+activity combinations
DESTINATION_TOPIC_TEMPLATES: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("patagonia", "hiking"): {
        "highlights": "Torres del Paine W Trek, Fitz Roy circuits, Perito Moreno views",
        "best_season": "December-February (Patagonian summer)",
        "key_tips": "Book refugios 6+ months ahead, expect strong winds",
        "duration_note": "W Trek: 4-5 days, O Circuit: 8-10 days",
    },
    ("maldives", "diving"): {
        "highlights": "Manta ray season, whale sharks at Ari Atoll, pristine house reefs",
        "best_season": "January-April (dry), November-December (mantas)",
        "key_tips": "Liveaboards reach outer atolls, resorts for convenience",
        "duration_note": "5-7 days ideal for multiple dive sites",
    },
    ("switzerland", "skiing"): {
        "highlights": "Zermatt (Matterhorn), Verbier backcountry, St. Moritz glamour",
        "best_season": "December-April, peak January-March",
        "key_tips": "Swiss Pass for transport, book mountain restaurants ahead",
        "duration_note": "7+ days to explore multiple resorts",
    },
    ("japan", "skiing"): {
        "highlights": "Niseko powder, Hakuba variety, Nozawa Onsen tradition",
        "best_season": "January-February for best powder",
        "key_tips": "JR Pass for transport, combine with hot springs",
        "duration_note": "7-10 days for skiing + cultural stops",
    },
    ("croatia", "boating"): {
        "highlights": "Dubrovnik to Split route, Kornati archipelago, Hvar nightlife",
        "best_season": "May-June or September (avoid August crowds)",
        "key_tips": "Skippered charters popular, book marina berths in advance",
        "duration_note": "7-10 days for leisurely island-hopping",
    },
    ("greece", "boating"): {
        "highlights": "Cyclades island-hopping, Ionian calm waters, Saronic near Athens",
        "best_season": "May-October, shoulder months less crowded",
        "key_tips": "Meltemi winds July-August, Ionian calmer for beginners",
        "duration_note": "7-14 days depending on route ambition",
    },
    ("france", "cycling"): {
        "highlights": "Loire Valley chateaux, Provence lavender, Tour de France cols",
        "best_season": "May-June or September for pleasant weather",
        "key_tips": "E-bikes available everywhere, wine tasting en route",
        "duration_note": "5-7 days per region, 2+ weeks for grand tour",
    },
    ("italy", "cycling"): {
        "highlights": "Tuscany hills, Dolomites climbs, Amalfi Coast (challenging)",
        "best_season": "April-May or September-October",
        "key_tips": "Book agriturismos early, start climbs early morning",
        "duration_note": "7-10 days for immersive cycling experience",
    },
    ("red sea", "diving"): {
        "highlights": "SS Thistlegorm wreck, Ras Mohammed sharks, Brothers Islands",
        "best_season": "March-May and September-November",
        "key_tips": "Egypt visa on arrival, liveaboards for best sites",
        "duration_note": "7-day liveaboard ideal, 4-5 days shore-based",
    },
    ("nepal", "hiking"): {
        "highlights": "Everest Base Camp, Annapurna Circuit, Langtang Valley",
        "best_season": "October-November (post-monsoon), March-May (pre-monsoon)",
        "key_tips": "Acclimatize properly, hire local guides/porters",
        "duration_note": "EBC: 12-14 days, Annapurna Circuit: 15-21 days",
    },
}


def _format_destination_template(content: Dict[str, str], dest_name: str, topic: str) -> str:
    """Format destination-specific template into a response string."""
    return (
        f"**{dest_name}** for {topic}:\n\n"
        f"**Details:**\n"
        f"- **Highlights:** {content['highlights']}\n"
        f"- **Best Season:** {content['best_season']}\n"
        f"- **Tips:** {content['key_tips']}\n"
        f"- **Ideal Duration:** {content['duration_note']}\n\n"
        "When are you thinking of going?"
    )


def get_destination_specific_template(topic: str, destinations: List[str]) -> Optional[str]:
    """Get destination+topic specific template if available.

    Checks DESTINATION_TOPIC_TEMPLATES for expert knowledge about popular
    destination+activity combinations before falling back to generic templates.

    Args:
        topic: Strategy topic (hiking, diving, skiing, cycling, boating)
        destinations: List of destination names from trip inputs

    Returns:
        Formatted template string if a specific match is found, None otherwise
    """
    if not destinations:
        return None
    dest_lower = destinations[0].lower()
    for (dest_key, topic_key), content in DESTINATION_TOPIC_TEMPLATES.items():
        if dest_key in dest_lower and topic_key == topic:
            return _format_destination_template(content, destinations[0], topic)
    return None


def get_dest_known_fallback(topic: str, dest_name: str) -> str:
    """Get destination-specific fallback template."""
    templates = {
        "diving": (
            f"**{dest_name}** for diving:\n\n"
            "**Key Details:**\n"
            "- **Reefs** — World-class visibility and marine life\n"
            "- **Conditions** — Varies by season\n"
            "- **Options** — Liveaboard vs resort-based diving\n"
            "- **Experience levels** — Sites for beginners to advanced\n\n"
            "When are you thinking of going?"
        ),
        "hiking": (
            f"**{dest_name}** for hiking:\n\n"
            "**Key Details:**\n"
            "- **Trail variety** — Routes for all fitness levels\n"
            "- **Seasonal access** — Weather affects trail conditions\n"
            "- **Permits** — Some routes require advance booking\n"
            "- **Altitude** — May need acclimatization time\n\n"
            "When are you planning to go?"
        ),
        "skiing": (
            f"**{dest_name}** for skiing:\n\n"
            "**Key Details:**\n"
            "- **Terrain** — Varied runs for all skill levels\n"
            "- **Snow season** — Peak conditions vary by month\n"
            "- **Lift access** — Multiple areas to explore\n"
            "- **Off-piste** — Options for advanced skiers\n\n"
            "When are you thinking of going?"
        ),
        "cycling": (
            f"**{dest_name}** for cycling:\n\n"
            "**Key Details:**\n"
            "- **Routes** — Scenic roads and dedicated paths\n"
            "- **Terrain** — Mix of flat and challenging climbs\n"
            "- **Weather** — Best conditions vary by season\n"
            "- **Bike rentals** — Quality bikes available locally\n\n"
            "When are you thinking of going?"
        ),
        "boating": (
            f"**{dest_name}** for sailing:\n\n"
            "**Key Details:**\n"
            "- **Waters** — Calm harbors and open passages\n"
            "- **Season** — Wind and weather patterns vary\n"
            "- **Charter options** — Bareboat or crewed\n"
            "- **Island-hopping** — Multiple stops possible\n\n"
            "When are you thinking of going?"
        ),
    }
    return templates.get(
        topic,
        (f"**{dest_name}** selected.\n\n" "When are you thinking of traveling?"),
    )


async def strategy_stage0(state: "GraphState", topic: str) -> "GraphState":
    """
    Stage 0: Pre-core value-first strategy response.

    Provides immediate value (destination archetypes + mini itinerary) with
    a single clarifying question, before core fields are complete.

    This is triggered by:
    - STRATEGY_PRE_CORE_VALUE gate: topic detected, no destinations
    - STRATEGY_PRE_CORE_VALUE_WITH_DEST gate: topic + destinations present

    When destinations are present (strategy_dest_known=True), generates
    destination-specific guidance and asks for dates.
    """
    from app.config import settings
    from app.debug_utils import _debug, _debug_error
    from app.plan_graph import (
        _JINJA_ENV,
        ToneAdapter,
        _debug_node_entry,
        _debug_node_exit,
        _debug_suggestions,
        _estimate_prompt_tokens,
        _gate_stats,
        _get_node_llm_config,
        _record_node_tokens,
        can_call_llm,
        canonicalize_question_target,
        jloads_safe,
        llm_blocked_fallback,
        required_fields_node,
        set_question_target,
        store_suggestions_with_field,
    )
    from app.planner.gates.readiness import compute_trip_readiness
    from app.planner.gates.suppression import SuppressionPredicates
    from app.planner.nodes.strategy.base import (
        generate_date_suggestions,
        get_question_guidance,
        track_strategy_pre_core_question,
    )
    from app.planner.streaming import (
        StreamingContext,
        call_llm_streaming_with_json_field,
        get_streaming_context,
    )

    _, start_ns = _debug_node_entry("strategy_node:stage0", state)
    ti = state.trip_inputs

    # Check if this is destination-known mode
    dest_known_mode = state.metadata.get("strategy_dest_known", False)
    destinations = ti.destinations or []

    # Use question_target from gate (which determined it based on missing fields)
    raw_target = state.question_target or "dates"
    question_target = canonicalize_question_target(raw_target)

    # Get question guidance
    question_guidance = get_question_guidance(question_target)

    # Compute missing core fields for context
    missing_core = compute_trip_readiness(state.trip_inputs).missing_core

    # Generate tone instruction
    user_intent = state.metadata.get("user_intent", "detailed_planner")
    user_tone = state.metadata.get("user_tone", "neutral")
    tone_instruction = ToneAdapter.get_instruction(user_intent, user_tone)

    # Build destination context for dest-known mode
    destination_context = ""
    if dest_known_mode and destinations:
        destination_context = (
            f"The user has already chosen: {', '.join(destinations)}. "
            "Provide destination-specific guidance for this location. "
            "Include details about: best areas/regions, seasonal considerations, "
            "local conditions, and practical tips specific to this destination."
        )

    # Calculate trip duration for duration-aware suggestions
    duration_days, duration_context = calculate_trip_duration(ti)
    _debug(
        "Stage 0 duration context",
        duration_days=duration_days,
        start_date=ti.start_date,
        end_date=ti.end_date,
    )

    # Load the pre-core prompt with Jinja2 templating
    # Select prompt based on whether destination is known (saves 300-400 tokens)
    prompt_file = (
        "strategy_pre_core_known_dest.txt"
        if dest_known_mode and destinations
        else "strategy_pre_core_discovery.txt"
    )
    try:
        template = _JINJA_ENV.get_template(prompt_file)
        prompt = template.render(
            strategy_topic=topic,
            question_target=question_target,
            question_guidance=question_guidance,
            user_text=state.user_text or "",
            missing_core_fields=", ".join(missing_core) if missing_core else "none",
            tone_instruction=tone_instruction,
            trip_inputs=ti.model_dump_json(exclude_none=True),
            destination_context=destination_context,
            destinations=destinations,
            # Duration-aware context (Issue 3)
            duration_days=duration_days,
            duration_context=duration_context,
        )
        _debug(
            "strategy_pre_core prompt selected",
            prompt_file=prompt_file,
            dest_known_mode=dest_known_mode,
        )
    except FileNotFoundError:
        _debug_error(f"{prompt_file} not found, falling back to required_fields")
        return await required_fields_node(state)

    # Use conservative token limit for stage 0
    llm_config = _get_node_llm_config("strategy_stage1")
    llm_config["max_output_tokens"] = 450  # Increased from 300 to avoid JSON truncation

    timeout = settings.llm_timeout_specialist
    attempts = settings.llm_max_retries
    last_error = None

    # Record token usage for observability
    tokens = _estimate_prompt_tokens(prompt, state.parsed_inputs)
    _record_node_tokens(state, "strategy_stage0", tokens, model=llm_config["model_hint"])

    # LLM Budget Gate
    if not can_call_llm(state, "strategy_stage0"):
        _debug(
            f"strategy_stage0: LLM budget exhausted, using fallback for {question_target}",
            question_target=question_target,
        )
        llm_blocked_fallback(
            state, asked_target=question_target, source="strategy_stage0:budget_blocked"
        )
        return state

    for attempt in range(attempts):
        try:
            # Get streaming context for real-time token streaming
            # Look up from registry using thread_id (avoids serialization issues)
            _streaming_thread_id = state.metadata.get("_streaming_thread_id")
            streaming_ctx: StreamingContext | None = get_streaming_context(_streaming_thread_id)

            # Use streaming call to emit assistant_message tokens in real-time
            out = await call_llm_streaming_with_json_field(
                model=llm_config["model_hint"],
                prompt=prompt,
                stream_field="assistant_message",
                streaming_ctx=streaming_ctx,
                max_tokens=llm_config["max_output_tokens"],
                user_message=state.user_text or "",
                timeout_seconds=timeout,
            )

            # AFTER streaming completes - parse JSON and apply deltas
            j = jloads_safe(out)
            if not j:
                # Try to extract message from truncated/malformed JSON
                from app.graph_plan_utils import extract_message_from_malformed_json

                recovered_message = extract_message_from_malformed_json(out)
                if recovered_message:
                    _debug(
                        "Stage 0 recovered message from truncated JSON",
                        length=len(recovered_message),
                    )
                    j = {"assistant_message": recovered_message}
                else:
                    raise json.JSONDecodeError("No JSON block found", out, 0)

            # Extract response
            response = j.get("assistant_message", j.get("response", ""))

            # Stage 0 Output Validation
            bullet_patterns = ["- ", "• ", "* ", "1.", "2.", "3."]
            bullet_count = sum(response.count(p) for p in bullet_patterns)
            if bullet_count < 2:
                _debug(f"Stage 0 response lacks value content ({bullet_count} bullets)")
                _gate_stats["strategy_stage0_low_value"] = (
                    _gate_stats.get("strategy_stage0_low_value", 0) + 1
                )

            # Validate: exactly one question mark
            question_marks = response.count("?")
            if question_marks == 0:
                _debug("Stage 0 response has no question, adding fallback")
                if question_target == "start_date":
                    response += "\n\nWhen are you thinking of going?"
                elif question_target == "origin":
                    response += "\n\nWhere will you be traveling from?"
                else:
                    response += "\n\nDo you have any destinations in mind?"
            elif question_marks > 1:
                _debug(f"Stage 0 response has {question_marks} questions, trimming")
                first_q_idx = response.find("?")
                response = response[: first_q_idx + 1]

            # Post-render length check
            max_chars = 1200
            if len(response) > max_chars:
                _debug(f"Stage 0 response too long ({len(response)} chars), trimming")
                q_idx = response.rfind("?")
                if q_idx > 0:
                    question_part = response[response.rfind("\n", 0, q_idx) : q_idx + 1]
                    available = max_chars - len(question_part) - 50
                    response = response[:available] + "\n\n..." + question_part

            state.last_summary = response
            set_question_target(
                state,
                j.get("question_target", question_target),
                source="strategy_stage0:llm_response",
            )
            state.suggested_responses = j.get("suggested_responses", [])[:3]

            # Generate default suggestions if none provided
            if not state.suggested_responses:
                if question_target == "start_date":
                    state.suggested_responses = [
                        "Next spring",
                        "This summer",
                        "I'm flexible on dates",
                    ]
                elif question_target == "origin":
                    state.suggested_responses = ["New York", "London", "Los Angeles"]
                else:
                    state.suggested_responses = ["Tell me more", "Show me options", "Not sure yet"]

            _debug_suggestions(state.suggested_responses, source="strategy_stage0")

            # Store suggestions with field key
            effective_field = canonicalize_question_target(question_target)
            store_suggestions_with_field(state, state.suggested_responses, effective_field)

            # Track loop guard
            track_strategy_pre_core_question(state, question_target)

            # Set metadata
            state.metadata["strategy_stage0_completed"] = True
            state.metadata["strategy_stage0_topic"] = topic
            state.metadata["model_used"] = llm_config["model_hint"]

            # Set lifecycle state
            state.metadata["last_strategy_topic"] = topic
            origin = state.trip_inputs.origin
            stage0_sig = SuppressionPredicates.compute_stage0_signature(topic, destinations, origin)
            state.metadata["stage0_completed_sig"] = stage0_sig
            state.metadata["last_stage0_question_target"] = question_target

            # Set provenance
            state.metadata["response_writer_node"] = "strategy_node:stage0"
            state.metadata["response_generation_provenance"] = "llm"

            _debug(
                "Stage 0 completed",
                topic=topic,
                question_target=question_target,
                response_length=len(response),
            )
            _debug_node_exit("strategy_node:stage0", state, start_ns)
            return state

        except json.JSONDecodeError as e:
            last_error = e
            _debug_error(f"Stage 0 JSON error on attempt {attempt + 1}", error=str(e))
            if attempt < attempts - 1:
                continue
            break
        except TimeoutError as e:
            last_error = e
            _debug_error(f"Stage 0 timeout on attempt {attempt + 1}")
            break
        except Exception as e:
            last_error = e
            _debug_error(f"Stage 0 error on attempt {attempt + 1}", error=str(e))
            break

    # Fallback: deterministic template
    _debug(
        "Stage 0 LLM failed, using deterministic template",
        error=str(last_error),
    )
    state.metadata["strategy_stage0_fallback"] = True
    state.metadata["strategy_stage0_error"] = str(last_error)
    state.metadata["strategy_stage0_deterministic"] = True

    # Destination-known mode: check for expert templates first, then fallback
    if dest_known_mode and destinations:
        # Try destination-specific expert templates first (Tier 10.22)
        fallback_response = get_destination_specific_template(topic, destinations)
        if fallback_response is None:
            # Fall back to generic destination templates
            dest_name = destinations[0] if destinations else "your destination"
            fallback_response = get_dest_known_fallback(topic, dest_name)
    else:
        fallback_response = STAGE0_FALLBACK_TEMPLATES.get(
            topic,
            (
                "Sounds like an exciting trip idea!\n\n"
                "To help you plan the perfect adventure, I'll need a few details.\n\n"
                "When are you thinking of traveling?"
            ),
        )

    state.last_summary = fallback_response
    set_question_target(state, "dates", source="strategy_stage0_fallback")
    state.suggested_responses = generate_date_suggestions()

    # Store suggestions with field key
    store_suggestions_with_field(state, state.suggested_responses, "dates")

    # Set lifecycle state
    state.metadata["last_strategy_topic"] = topic
    origin = state.trip_inputs.origin
    stage0_sig = SuppressionPredicates.compute_stage0_signature(topic, destinations, origin)
    state.metadata["stage0_completed_sig"] = stage0_sig
    state.metadata["last_stage0_question_target"] = "dates"

    # Set provenance
    state.metadata["response_writer_node"] = "strategy_node:stage0:fallback"
    state.metadata["response_generation_provenance"] = "template"

    _debug_suggestions(state.suggested_responses, source="strategy_stage0_fallback")
    _debug_node_exit("strategy_node:stage0:fallback", state, start_ns)
    return state
