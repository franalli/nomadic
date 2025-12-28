"""
Strategy Stage 0 Coordinator - Pre-core value-first strategy response.

Provides immediate value (destination archetypes + mini itinerary) with
a single clarifying question, before core fields are complete.

This is the authoritative implementation for Stage 0 logic.
The _strategy_stage0 function in strategy_main.py delegates to this module.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.plan_graph import GraphState


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
        "Great choice! Hiking adventures are incredibly rewarding.\n\n"
        "Here are some amazing destinations to consider:\n"
        "- **Swiss Alps** - Iconic trails like the Haute Route\n"
        "- **Patagonia, Chile** - Torres del Paine circuit\n"
        "- **New Zealand** - Milford Track and Routeburn\n"
        "- **Nepal** - Classic Annapurna or Everest base camp\n\n"
        "When are you thinking of going?"
    ),
    "skiing": (
        "Exciting! Let's plan an amazing ski trip.\n\n"
        "Top destinations to consider:\n"
        "- **French Alps** - Chamonix, Val d'Isère, Les 3 Vallées\n"
        "- **Swiss Alps** - Zermatt, Verbier, St. Moritz\n"
        "- **Japan** - Niseko, Hakuba for legendary powder\n"
        "- **Colorado** - Vail, Aspen, Breckenridge\n\n"
        "When are you thinking of hitting the slopes?"
    ),
    "diving": (
        "Fantastic! Diving opens up a whole underwater world.\n\n"
        "World-class dive destinations:\n"
        "- **Maldives** - Pristine reefs and manta rays\n"
        "- **Great Barrier Reef, Australia** - Bucket-list diving\n"
        "- **Red Sea, Egypt** - Wrecks and colorful reefs\n"
        "- **Indonesia** - Raja Ampat biodiversity hotspot\n\n"
        "When are you thinking of diving?"
    ),
    "cycling": (
        "Love it! Cycling trips offer amazing ways to explore.\n\n"
        "Epic cycling destinations:\n"
        "- **Netherlands** - Classic flat cycling with canals\n"
        "- **French countryside** - Loire Valley vineyards\n"
        "- **Italian Dolomites** - Stunning mountain passes\n"
        "- **Vietnam** - Ha Long Bay to Hoi An adventure\n\n"
        "When are you thinking of cycling?"
    ),
    "boating": (
        "Wonderful! Sailing adventures are unforgettable.\n\n"
        "Amazing sailing destinations:\n"
        "- **Greek Islands** - Island-hop through the Cyclades\n"
        "- **Croatia** - Dalmatian coast beauty\n"
        "- **Caribbean** - BVI, Grenadines, or Bahamas\n"
        "- **Thailand** - Phuket and the Andaman Sea\n\n"
        "When are you thinking of setting sail?"
    ),
}


def get_dest_known_fallback(topic: str, dest_name: str) -> str:
    """Get destination-specific fallback template."""
    templates = {
        "diving": (
            f"Excellent choice! {dest_name} offers incredible diving opportunities.\n\n"
            "Here's what makes it special:\n"
            "- **Pristine reefs** - World-class visibility and marine life\n"
            "- **Best conditions** - Varies by season, so timing matters\n"
            "- **Options** - Liveaboard vs resort-based diving\n"
            "- **Experience levels** - Sites for beginners to advanced\n\n"
            "When are you thinking of going? The season really impacts conditions."
        ),
        "hiking": (
            f"Great pick! {dest_name} has amazing hiking trails.\n\n"
            "Key things to know:\n"
            "- **Trail variety** - Routes for all fitness levels\n"
            "- **Seasonal access** - Weather affects trail conditions\n"
            "- **Permits** - Some routes require advance booking\n"
            "- **Altitude** - May need acclimatization time\n\n"
            "When are you planning to hike? Season affects trail access."
        ),
        "skiing": (
            f"Awesome! {dest_name} is a fantastic ski destination.\n\n"
            "What to expect:\n"
            "- **Terrain** - Varied runs for all skill levels\n"
            "- **Snow season** - Peak conditions vary by month\n"
            "- **Lift access** - Multiple areas to explore\n"
            "- **Off-piste** - Options for advanced skiers\n\n"
            "When are you thinking of skiing? Season matters for snow quality."
        ),
        "cycling": (
            f"Perfect! {dest_name} offers fantastic cycling.\n\n"
            "Here's the overview:\n"
            "- **Routes** - Scenic roads and dedicated paths\n"
            "- **Terrain** - Mix of flat and challenging climbs\n"
            "- **Weather** - Best conditions vary by season\n"
            "- **Bike rentals** - Quality bikes available locally\n\n"
            "When are you thinking of cycling? Weather is key."
        ),
        "boating": (
            f"Wonderful! {dest_name} is beautiful for sailing.\n\n"
            "Key considerations:\n"
            "- **Waters** - Calm harbors and open passages\n"
            "- **Season** - Wind and weather patterns vary\n"
            "- **Charter options** - Bareboat or crewed\n"
            "- **Island-hopping** - Multiple stops possible\n\n"
            "When are you thinking of sailing? Season affects conditions."
        ),
    }
    return templates.get(
        topic,
        (
            f"Exciting! {dest_name} is a great choice for your trip.\n\n"
            "I'll help you plan an amazing adventure there.\n\n"
            "When are you thinking of traveling?"
        ),
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
        call_llm_with_timeout,
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

    # Load the pre-core prompt with Jinja2 templating
    try:
        template = _JINJA_ENV.get_template("strategy_pre_core.txt")
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
            dest_known_mode=dest_known_mode,
        )
    except FileNotFoundError:
        _debug_error("strategy_pre_core.txt not found, falling back to required_fields")
        return await required_fields_node(state)

    # Use conservative token limit for stage 0
    llm_config = _get_node_llm_config("strategy_stage1")
    llm_config["max_output_tokens"] = 300  # Hard cap for value-first response

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
            out = await call_llm_with_timeout(
                model=llm_config["model_hint"],
                prompt=prompt,
                timeout_seconds=timeout,
                max_tokens=llm_config["max_output_tokens"],
                user_message=state.user_text or "",
            )

            j = jloads_safe(out)
            if not j:
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

    # Destination-known mode: use destination-specific fallback
    if dest_known_mode and destinations:
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
