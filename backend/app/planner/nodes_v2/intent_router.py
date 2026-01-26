"""
IntentRouter Node - LLM-based intent classification.

This node uses a fast LLM (GPT-4o-mini) to classify user input into:
- GREETING: Simple greetings/thanks with no planning content
- RESET: Explicit requests to start over
- PLANNING: Everything else (trip-related)

The LLM approach solves the "regex minefield" problem where patterns like
"no" incorrectly trigger cancellation instead of recognizing corrections
like "No, I want Paris instead."
"""

import logging
import os
from typing import List, Literal, Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.planner.state import GraphStateV2, TripPlan

logger = logging.getLogger(__name__)


# =============================================================================
# Classification Schema
# =============================================================================


class IntentClassification(BaseModel):
    """LLM-structured output for intent classification."""

    intent: Literal["GREETING", "RESET", "PLANNING"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str = Field(description="Brief explanation of classification")
    # Multiple specialist hints (e.g., "diving and hiking trip")
    specialist_hints: List[Literal["diving", "hiking", "skiing", "cycling", "boating"]] = Field(
        default_factory=list, description="List of detected specialist activities (can be multiple)"
    )


# =============================================================================
# Static Responses
# =============================================================================

STATIC_RESPONSES = {
    "GREETING": {
        "message": (
            "Hey there! I'm excited to help you plan an amazing trip. "
            "What kind of adventure are you dreaming of?"
        ),
        "suggested_replies": ["Beach destination", "Mountain adventure", "City break"],
    },
    "RESET": {
        "message": "No problem! Let's start fresh. What kind of trip are you thinking about?",
        "suggested_replies": ["Relaxing vacation", "Adventure trip", "Cultural exploration"],
        "ui_event": "UI_RESET",
    },
}


# =============================================================================
# Exact Match Short Circuit (saves LLM call for trivial inputs)
# =============================================================================

EXACT_MATCH_GREETINGS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "hi!",
        "hello!",
        "hey!",
        "good morning",
        "good afternoon",
        "good evening",
        "morning",
        "afternoon",
        "evening",
        "thanks",
        "thank you",
        "thanks!",
        "thank you!",
        "bye",
        "goodbye",
        "bye!",
        "goodbye!",
        "cheers",
        "ciao",
        "hola",
    }
)

# Generate plan trigger from frontend "Build plan" button
GENERATE_PLAN_TRIGGER = "GENERATE_PLAN_NOW"


def _check_exact_match_greeting(text: str) -> Optional[IntentClassification]:
    """
    Check if input matches known greeting patterns exactly.

    Returns IntentClassification if matched, None otherwise.
    Saves an LLM call for trivial inputs (~300ms, ~150 tokens).
    """
    normalized = text.strip().lower()

    if normalized in EXACT_MATCH_GREETINGS:
        logger.debug(f"Exact match greeting detected: '{text}'")
        return IntentClassification(
            intent="GREETING",
            confidence=1.0,
            reasoning="Exact match greeting - no LLM needed",
            specialist_hints=[],
        )

    return None


def _check_generate_plan_trigger(text: str) -> Optional[IntentClassification]:
    """
    Check if input is the generate plan trigger from frontend.

    The frontend sends "GENERATE_PLAN_NOW" when user clicks "Build plan".
    Returns IntentClassification with PLANNING intent to trigger tile fetching.
    """
    normalized = text.strip().upper()

    if normalized == GENERATE_PLAN_TRIGGER:
        logger.debug("Generate plan trigger detected")
        return IntentClassification(
            intent="PLANNING",
            confidence=1.0,
            reasoning="Generate plan trigger - execute plan with tiles",
            specialist_hints=[],
        )

    return None


# =============================================================================
# Specialist Keywords (for hint detection)
# =============================================================================

SPECIALIST_KEYWORDS = {
    "diving": [
        "dive",
        "diving",
        "scuba",
        "snorkel",
        "wreck",
        "reef",
        "padi",
        "ssi",
        "freedive",
        "underwater",
        "coral",
        "marine",
        "decompression",
        "nitrox",
        "liveaboard",
        "drift dive",
        "night dive",
        "cave dive",
        "cenote",
    ],
    "hiking": [
        "hike",
        "hiking",
        "trek",
        "trekking",
        "trail",
        "mountain",
        "summit",
        "backpack",
        "backpacking",
        "camping",
        "wilderness",
        "scramble",
        "peak",
        "ridge",
        "alpine",
        "elevation",
        "altitude",
    ],
    "skiing": [
        "ski",
        "skiing",
        "snowboard",
        "snowboarding",
        "slope",
        "piste",
        "powder",
        "resort",
        "lift",
        "chairlift",
        "gondola",
        "apres",
        "black diamond",
        "mogul",
        "backcountry",
        "off-piste",
    ],
    "cycling": [
        "cycle",
        "cycling",
        "bike",
        "biking",
        "bicycle",
        "mtb",
        "road bike",
        "gravel",
        "velodrome",
        "peloton",
        "criterium",
        "sportive",
    ],
    "boating": [
        "sail",
        "sailing",
        "boat",
        "boating",
        "yacht",
        "charter",
        "catamaran",
        "anchor",
        "marina",
        "mooring",
        "regatta",
        "cruising",
    ],
}

# =============================================================================
# Activity Category to Specialist Mapping (for UI pill selection)
# =============================================================================

# Maps activity category strings (from UI) to specialist types
# These are the canonical category names that should show in the activity pill
ACTIVITY_CATEGORY_TO_SPECIALIST = {
    # Diving
    "diving": "diving",
    "scuba": "diving",
    "scuba diving": "diving",
    "snorkeling": "diving",
    "freediving": "diving",
    # Hiking
    "hiking": "hiking",
    "trekking": "hiking",
    "mountaineering": "hiking",
    "camping": "hiking",
    "backpacking": "hiking",
    # Skiing
    "skiing": "skiing",
    "snowboarding": "skiing",
    "snow sports": "skiing",
    "winter sports": "skiing",
    # Cycling
    "cycling": "cycling",
    "biking": "cycling",
    "mountain biking": "cycling",
    "road cycling": "cycling",
    # Boating
    "sailing": "boating",
    "boating": "boating",
    "yachting": "boating",
}

# Canonical specialist activity categories (should appear at top of activity pill)
SPECIALIST_ACTIVITY_CATEGORIES = [
    "diving",
    "hiking",
    "skiing",
    "cycling",
    "sailing",
]


def _detect_specialists_from_activity_settings(state: GraphStateV2) -> List[str]:
    """
    Detect specialists from activity_settings.categories (UI pill selection).

    Returns list of all matching specialist types (can be multiple).
    """
    # Get activity categories from trip_inputs in metadata
    trip_inputs = state.metadata.get("trip_inputs", {})
    activity_settings = trip_inputs.get("activity_settings", {})
    categories = activity_settings.get("categories", [])

    if not categories:
        return []

    # Check each category for a specialist match
    detected: List[str] = []
    for category in categories:
        category_lower = category.lower().strip()
        if category_lower in ACTIVITY_CATEGORY_TO_SPECIALIST:
            specialist = ACTIVITY_CATEGORY_TO_SPECIALIST[category_lower]
            if specialist not in detected:
                detected.append(specialist)
                logger.debug(
                    f"Detected specialist '{specialist}' from activity category '{category}'"
                )

    return detected


# =============================================================================
# LLM Classification
# =============================================================================

CLASSIFICATION_PROMPT = """You are an intent classifier for a travel planning assistant.

## Classification Rules

Classify the user message into ONE of:

1. **GREETING** - Simple greetings or thanks with NO planning content
   - Examples: "Hi", "Hello", "Thanks!", "Bye", "Good morning"
   - NOT if combined with content: "Hi, I want to go to Paris" = PLANNING

2. **RESET** - Explicit requests to start over or stop the current conversation
   - Examples: "Start over", "Reset everything", "Begin again", "New trip"
   - NOT: "Stop in Rome" (this is PLANNING about a layover!)

3. **PLANNING** - Everything else related to trip planning
   - Destinations, dates, preferences, questions
   - Affirmations WITH context: "Yes, Paris sounds good" = PLANNING
   - Negations WITH alternatives: "No, I prefer Rome" = PLANNING
   - Activity mentions: "diving", "hiking", "skiing", etc.

## CRITICAL RULES

- If the user says "No" or "Yes" followed by ANY trip content, classify as PLANNING
- If unsure, default to PLANNING (let the architect handle it)
- Do NOT classify based on sentiment, only on intent
- "Stop in Rome" = PLANNING (layover), "Stop" alone = RESET

## Specialist Detection

If the message mentions activities like diving, hiking, skiing, cycling, or boating,
include ALL matching specialists in the specialist_hints array.
For example, "diving and hiking trip" should return ["diving", "hiking"].

## User Message
"{user_message}"

Respond with valid JSON matching this schema:
{{
  "intent": "GREETING" | "RESET" | "PLANNING",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "specialist_hints": ["diving", "hiking", "skiing", "cycling", "boating"]
}}"""  # specialist_hints: array of matching activities, empty if none


def _get_router_llm() -> ChatOpenAI:
    """Get the fast LLM for intent classification."""
    return ChatOpenAI(
        model=os.getenv("ROUTER_MODEL", "gpt-4o-mini"),
        temperature=0,  # Deterministic classification
        max_tokens=150,  # Classification is short
    )


async def _classify_intent_with_llm(
    user_text: str, state: GraphStateV2
) -> tuple[IntentClassification, dict]:
    """
    Classify user intent using LLM.

    Returns tuple of (IntentClassification, token_usage_dict).
    """
    try:
        llm = _get_router_llm()

        # Use structured output for reliable JSON parsing
        structured_llm = llm.with_structured_output(IntentClassification, include_raw=True)

        prompt = CLASSIFICATION_PROMPT.format(user_message=user_text)

        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])

        # Extract parsed result and token usage
        parsed = result["parsed"]
        raw = result["raw"]
        token_usage = {}
        if hasattr(raw, "response_metadata"):
            token_usage = raw.response_metadata.get("token_usage", {})

        logger.debug(f"Intent classification: {parsed.intent} (confidence={parsed.confidence})")
        return parsed, token_usage

    except Exception as e:
        logger.warning(f"LLM classification failed, defaulting to PLANNING: {e}")
        # Default to PLANNING on error - let the architect handle it
        return (
            IntentClassification(
                intent="PLANNING",
                confidence=0.5,
                reasoning=f"LLM classification failed: {e}",
                specialist_hints=_detect_specialist_keywords(user_text),
            ),
            {},
        )


def _detect_specialist_keywords(user_text: str) -> List[str]:
    """
    Fallback keyword detection for specialist hints.

    Used when LLM fails or for quick detection.
    Returns all matching specialist types (can be multiple).
    """
    import re

    text_lower = user_text.lower()
    detected: List[str] = []

    for topic, keywords in SPECIALIST_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                if topic not in detected:
                    detected.append(topic)
                break  # Found a match for this topic, move to next

    return detected


# =============================================================================
# Node Function
# =============================================================================


async def intent_router(state: GraphStateV2) -> GraphStateV2:
    """
    IntentRouter node function for LangGraph.

    Uses LLM to classify user intent and either:
    - Returns static response for GREETING/RESET (skips architect)
    - Passes PLANNING intent to architect for handling

    The panic button (/reset, stop, clear) is handled in run_turn BEFORE
    the graph is invoked, so we don't need to check for it here.
    """
    from app.debug_utils import _debug_v2_node_end, _debug_v2_node_start

    # Get user message from last message
    user_text = ""
    if state.messages:
        last_msg = state.messages[-1]
        if hasattr(last_msg, "content"):
            user_text = last_msg.content

    _debug_v2_node_start(
        "router",
        "🧭",
        user_text=user_text[:80] if user_text else "",
        current_specialist=state.active_specialist,
    )

    # Try exact match first (no LLM cost, instant response)
    classification = _check_exact_match_greeting(user_text)
    token_usage = {}

    # Check for generate plan trigger from frontend "Build plan" button
    if classification is None:
        classification = _check_generate_plan_trigger(user_text)

    # Fall back to LLM classification if no exact match
    if classification is None:
        from app.debug_utils import log, log_tokens

        classification, token_usage = await _classify_intent_with_llm(user_text, state)
        if token_usage:
            log_tokens(
                "ROUTER",
                token_usage.get("prompt_tokens", 0),
                token_usage.get("completion_tokens", 0),
                token_usage.get("total_tokens", 0),
            )
        else:
            log("ROUTER", "No LLM call (exact match or error)")
        log(
            "ROUTER",
            f"Intent: {classification.intent}",
            data=f"specialist_hints={classification.specialist_hints}",
        )

    # Handle GREETING - return static response, skip architect
    if classification.intent == "GREETING":
        state.last_summary = STATIC_RESPONSES["GREETING"]["message"]
        state.suggested_replies = list(STATIC_RESPONSES["GREETING"]["suggested_replies"])
        state.metadata["short_circuit_response"] = True
        state.metadata["router_output"] = classification.model_dump()

        _debug_v2_node_end(
            "router",
            "🧭",
            intent="GREETING",
            short_circuit=True,
        )
        return state

    # Handle RESET - clear state, return static response, skip architect
    if classification.intent == "RESET":
        state.last_summary = STATIC_RESPONSES["RESET"]["message"]
        state.suggested_replies = list(STATIC_RESPONSES["RESET"]["suggested_replies"])
        state.ui_events.append("UI_RESET")
        state.trip_plan = TripPlan()  # Clear the plan
        state.metadata["short_circuit_response"] = True
        state.metadata["router_output"] = classification.model_dump()

        _debug_v2_node_end(
            "router",
            "🧭",
            intent="RESET",
            short_circuit=True,
        )
        return state

    # PLANNING intent - pass to architect
    # Check if this is the generate plan trigger (user clicked "Build plan")
    # Use "booking" intent to trigger tile fetching in the Architect
    is_generate_trigger = user_text.strip().upper() == GENERATE_PLAN_TRIGGER
    state.intent = "booking" if is_generate_trigger else "general"
    state.metadata["short_circuit_response"] = False
    state.metadata["router_output"] = classification.model_dump()
    state.metadata["is_generate_trigger"] = is_generate_trigger

    # Set specialist if detected from text OR from UI activity settings
    # Combine detected specialists from LLM and activity settings
    specialist_hints = list(classification.specialist_hints)  # Copy to avoid mutation

    # Also check activity_settings.categories for UI-selected activities
    ui_specialists = _detect_specialists_from_activity_settings(state)
    for s in ui_specialists:
        if s not in specialist_hints:
            specialist_hints.append(s)

    if ui_specialists:
        from app.debug_utils import log

        log("ROUTER", f"Specialists {ui_specialists} detected from activity settings")

    # Store all specialists in the pending queue (multi-specialist support)
    # Pop the first one to activate, rest stay in queue for sequential processing
    if specialist_hints:
        state.pending_specialists = specialist_hints[1:]  # Rest of the queue
        first_specialist = specialist_hints[0]
        state.active_specialist = first_specialist
        state.active_agent_id = first_specialist
        state.ui_events.append("SPECIALIST_ACTIVE")
    elif state.trip_plan.destination and state.intent == "booking":
        # FALLBACK: No niche specialist detected, but user triggered "Build Plan"
        # Activate Local Expert for city-specific logistics
        # NOTE: Only trigger on "booking" intent (not "general") to avoid running during setup phase
        state.pending_specialists = []
        from app.debug_utils import log

        log("ROUTER", f"Auto-triggering Local Expert for {state.trip_plan.destination}")
        state.active_specialist = "local_expert"
        state.active_agent_id = "local_expert"
        state.ui_events.append("SPECIALIST_ACTIVE")
    else:
        state.pending_specialists = []

    _debug_v2_node_end(
        "router",
        "🧭",
        intent=state.intent,
        specialist=state.active_specialist,
        confidence=classification.confidence,
    )

    return state
