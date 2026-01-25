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
from typing import Literal, Optional

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
    specialist_hint: Optional[Literal["diving", "hiking", "skiing", "cycling", "boating"]] = None


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
include a specialist_hint field with the appropriate value.

## User Message
"{user_message}"

Respond with valid JSON matching this schema:
{{
  "intent": "GREETING" | "RESET" | "PLANNING",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "specialist_hint": null | "diving" | "hiking" | "skiing" | "cycling" | "boating"
}}"""


def _get_router_llm() -> ChatOpenAI:
    """Get the fast LLM for intent classification."""
    return ChatOpenAI(
        model=os.getenv("ROUTER_MODEL", "gpt-4o-mini"),
        temperature=0,  # Deterministic classification
        max_tokens=150,  # Classification is short
    )


async def _classify_intent_with_llm(user_text: str, state: GraphStateV2) -> IntentClassification:
    """
    Classify user intent using LLM.

    Returns IntentClassification with intent, confidence, reasoning, and optional specialist_hint.
    """
    try:
        llm = _get_router_llm()

        # Use structured output for reliable JSON parsing
        structured_llm = llm.with_structured_output(IntentClassification)

        prompt = CLASSIFICATION_PROMPT.format(user_message=user_text)

        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])

        logger.debug(f"Intent classification: {result.intent} (confidence={result.confidence})")
        return result

    except Exception as e:
        logger.warning(f"LLM classification failed, defaulting to PLANNING: {e}")
        # Default to PLANNING on error - let the architect handle it
        return IntentClassification(
            intent="PLANNING",
            confidence=0.5,
            reasoning=f"LLM classification failed: {e}",
            specialist_hint=_detect_specialist_keyword(user_text),
        )


def _detect_specialist_keyword(user_text: str) -> Optional[str]:
    """
    Fallback keyword detection for specialist hints.

    Used when LLM fails or for quick detection.
    """
    import re

    text_lower = user_text.lower()

    for topic, keywords in SPECIALIST_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                return topic

    return None


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

    # Classify intent using LLM
    classification = await _classify_intent_with_llm(user_text, state)

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
    state.intent = "general"
    state.metadata["short_circuit_response"] = False
    state.metadata["router_output"] = classification.model_dump()

    # Set specialist if detected
    if classification.specialist_hint:
        state.active_specialist = classification.specialist_hint
        state.active_agent_id = classification.specialist_hint
        state.ui_events.append("SPECIALIST_ACTIVE")

    _debug_v2_node_end(
        "router",
        "🧭",
        intent=state.intent,
        specialist=state.active_specialist,
        confidence=classification.confidence,
    )

    return state
