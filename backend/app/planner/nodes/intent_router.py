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

import hashlib
import json
import logging
import os
import re
from typing import List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.planner.state import GraphState, TripPlan

logger = logging.getLogger(__name__)


# =============================================================================
# Constraint Hash Utilities (for detecting input changes)
# =============================================================================


def _compute_constraint_hash(trip_plan: TripPlan, trip_inputs: dict) -> str:
    """
    Generate a stable hash of inputs that affect feasibility/pricing.

    Used to detect when constraints have changed and specialists need to re-run.

    Hash includes: destination, origin, dates, travelers, budget, activity categories.
    This matches the frontend hash in usePlanRegeneration.ts.
    """
    # Sort categories to ensure ["a", "b"] == ["b", "a"]
    activity_cats = sorted(trip_inputs.get("activity_settings", {}).get("categories", []))

    hash_payload = {
        "dest": (trip_plan.destination or "").lower().strip(),
        "origin": (trip_plan.origin or "").lower().strip(),  # Match frontend hash
        "dates": f"{trip_plan.start_date}|{trip_plan.end_date}",
        "pax": f"{trip_plan.adults}|{trip_plan.children}",
        "budget": str(trip_plan.budget),
        "activities": activity_cats,
    }
    return hashlib.md5(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()


def _clear_stale_specialist_content(state: GraphState) -> None:
    """
    Wipe old specialist data so we don't merge 'Aspen Skiing' into 'Hawaii'.

    Clears: itinerary_blocks, constraints, tiles, strategy_sections
    Preserves: trip_plan core fields (destination, dates, travelers, budget)
    """
    state.trip_plan.itinerary_blocks = []
    state.trip_plan.constraints = []
    state.tiles = {}  # Force fresh fetch

    # Clear UI sections but keep structure ready
    if "strategy_sections" in state.metadata:
        state.metadata["strategy_sections"] = []

    logger.info("[Router] Cleared stale specialist content for constraint change")


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


class RouterOutput(BaseModel):
    """
    Combined structured output for Router: Intent + Field Extraction in one LLM call.

    This eliminates the duplicate extraction problem where Router detects intent
    but ARCHITECT has to re-extract the same fields from the same message.
    Now Router extracts everything at once.
    """

    # Intent classification
    intent: Literal["GREETING", "RESET", "PLANNING"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str = Field(description="Brief explanation of classification")

    # Specialist hints
    specialist_hints: List[Literal["diving", "hiking", "skiing", "cycling", "boating"]] = Field(
        default_factory=list, description="List of detected specialist activities"
    )

    # Extracted trip fields (populated when intent=PLANNING)
    destination: Optional[str] = Field(None, description="Destination city/country if mentioned")
    origin: Optional[str] = Field(None, description="Origin city if mentioned")
    start_date: Optional[str] = Field(
        None, description="Start date in YYYY-MM-DD format (resolve 'March 1' to full date)"
    )
    end_date: Optional[str] = Field(
        None, description="End date in YYYY-MM-DD format (resolve 'March 8' to full date)"
    )
    duration_days: Optional[int] = Field(
        None, description="Trip duration if mentioned (e.g., 'for a week' = 7)"
    )
    adults: Optional[int] = Field(None, description="Number of adults if mentioned")
    children: Optional[int] = Field(None, description="Number of children if mentioned")
    budget: Optional[float] = Field(None, description="Budget amount in USD if mentioned")

    # Flags for downstream processing
    has_dates_in_message: bool = Field(
        default=False,
        description=(
            "True if user provided any date info in this message "
            "(month, dates, 'next week', etc.)"
        ),
    )
    has_activity_in_message: bool = Field(
        default=False,
        description="True if user mentioned specific activities (diving, hiking, etc.)",
    )
    planning_ready: bool = Field(
        default=False,
        description="True if user explicitly wants to plan (not just asking questions)",
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

# Speculative execution trigger from frontend (preload specialists in Setup)
SPECULATE_TRIGGER = "SPECULATE_SPECIALISTS"


# =============================================================================
# Exploration Mode: Question Type Classification
# =============================================================================

QUESTION_TYPE_MAPPING = {
    # Keywords → (question_type, Local Expert section)
    "couples|romantic|honeymoon": ("couples", "destination_overview"),
    "family|kids|children": ("family", "destination_overview"),
    "weather|climate|rain|season|temperature": ("weather", "seasonality"),
    "safe|dangerous|crime|security": ("safety", "safety_health"),
    "cost|expensive|cheap|budget|afford|price": ("costs", "money_costs"),
    "visa|passport|entry|immigration": ("visa", "visa_entry"),
    "get around|transport|taxi|uber|scooter": ("transport", "transportation"),
    "wear|dress|clothes|attire": ("cultural", "cultural_norms"),
    "must see|must do|attractions|things to do": ("activities", "things_to_do"),
    "stay|hotel|neighborhood|area": ("accommodation", "neighborhoods"),
    "scam|rip off|tourist trap|avoid": ("scams", "scams_traps"),
    "pack|bring|luggage|adapter": ("packing", "packing"),
    "sim|wifi|internet|phone": ("connectivity", "connectivity"),
    "tip|tipping|currency|money|atm": ("money", "money_costs"),
}


def classify_question_type(text: str) -> Tuple[str, str]:
    """
    Classify a question into a type and corresponding Local Expert section.

    Returns (question_type, local_expert_section).
    """
    text_lower = text.lower()
    for pattern, (qtype, section) in QUESTION_TYPE_MAPPING.items():
        if any(kw in text_lower for kw in pattern.split("|")):
            return qtype, section
    return "general", "destination_overview"


# =============================================================================
# Exploration Mode: Planning Readiness Detection
# =============================================================================

PLANNING_READINESS_SIGNALS = [
    # Plan signals
    "plan my trip",
    "help me plan",
    "let's plan",
    "plan this",
    "plan it",  # Common short form
    # Readiness signals
    "i'm ready",
    "let's do it",
    "let's go",
    "book",
    "what are my options",
    "show me options",
    # Affirmative signals
    "go ahead",
    "yes let's",
    "sounds good",
    "do it",
    "create it",
    "build it",
    "make it",
    # Build/create signals
    "build the itinerary",
    "build itinerary",
    "build my itinerary",
    "create the itinerary",
    "create itinerary",
    "create my itinerary",
    "generate itinerary",
    "generate the itinerary",
    "make the plan",
    "make my plan",
    "make a plan",
]

# Split into separate constants for clarity and maintainability
DATE_INDICATORS = [
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    r"\b(next week|next month|this weekend|tomorrow)\b",
    r"\b\d{1,2}[/-]\d{1,2}\b",
]

ACTIVITY_INDICATORS = [
    r"\b(diving|dive|scuba|snorkel)\b",
    r"\b(hiking|trek|climb|trail)\b",
    r"\b(skiing|snowboard|ski)\b",
]

# Specialist detection patterns (map activity words to specialist type)
SPECIALIST_PATTERNS = {
    "diving": [r"\b(diving|dive|scuba|snorkel|underwater)\b"],
    "hiking": [r"\b(hiking|hike|trek|trekking|climb|trail|mountain)\b"],
    "skiing": [r"\b(skiing|ski|snowboard|snow|slopes)\b"],
    "cycling": [r"\b(cycling|bike|bicycle|biking)\b"],
    "boating": [r"\b(boating|boat|sailing|yacht|cruise)\b"],
}


def get_new_specialists_from_text(text: str, existing_specialists: List[str]) -> List[str]:
    """
    Get list of NEW specialists mentioned in text that aren't already in the plan.

    Args:
        text: User message
        existing_specialists: List of specialist types already in the plan

    Returns:
        List of new specialist types to add
    """
    text_lower = text.lower()
    new_specialists = []

    for specialist_type, patterns in SPECIALIST_PATTERNS.items():
        if specialist_type in existing_specialists:
            continue  # Already have this specialist

        for pattern in patterns:
            if re.search(pattern, text_lower):
                new_specialists.append(specialist_type)
                break  # Found match, move to next specialist type

    return new_specialists


def detect_planning_intent(text: str, state: "GraphState") -> str:
    """
    Detect if user is ready to plan or still exploring.

    Returns:
    - "ready" → User explicitly wants to plan
    - "soft_transition" → Has dates/activities, natural transition
    - "exploring" → Still asking questions
    """
    text_lower = text.lower()

    # Explicit planning signals
    for signal in PLANNING_READINESS_SIGNALS:
        if signal in text_lower:
            return "ready"

    # Pattern: "plan [destination] trip" (e.g., "Plan Bali trip", "plan the trip")
    if re.search(r"\bplan\b.*\btrip\b", text_lower):
        return "ready"

    # Has dates AND activities
    has_date = any(re.search(p, text_lower) for p in DATE_INDICATORS)
    has_activity = any(re.search(p, text_lower) for p in ACTIVITY_INDICATORS)

    if has_date and has_activity:
        return "ready"  # "diving in February" → planning mode
    if has_date or has_activity:
        return "soft_transition"  # Just date or just activity

    return "exploring"


def _extract_destination_context(text: str, state: "GraphState") -> Optional[str]:
    """
    Extract destination from question or use conversation context.

    Priority:
    1. Check if destination mentioned in current question
    2. Use last_destination_context from state
    3. Use trip_plan.destination if set
    """
    from app.planner.nodes.local_expert import LOCAL_EXPERT_KNOWLEDGE

    text_lower = text.lower()

    # Check LOCAL_EXPERT_KNOWLEDGE keys first (known destinations)
    for dest_key in LOCAL_EXPERT_KNOWLEDGE.keys():
        if dest_key.lower() in text_lower:
            return dest_key.capitalize()

    # Fallback to conversation context
    if state.metadata.get("last_destination_context"):
        return state.metadata["last_destination_context"]

    if state.trip_plan and state.trip_plan.destination:
        return state.trip_plan.destination

    return None


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


def _check_speculate_trigger(text: str) -> Optional[IntentClassification]:
    """
    Check if input is the speculative execution trigger from frontend.

    The frontend sends "SPECULATE_SPECIALISTS" when user pauses typing a destination
    and has specialist activity categories selected. This pre-loads specialist content
    (diving feasibility, constraints, etc.) during Setup before they click "Build Plan".

    Returns IntentClassification with PLANNING intent - the speculative handling
    happens in the router by setting state.intent = "speculative".
    """
    normalized = text.strip().upper()

    if normalized == SPECULATE_TRIGGER:
        logger.debug("Speculate trigger detected - preloading specialists")
        return IntentClassification(
            intent="PLANNING",
            confidence=1.0,
            reasoning="Speculative trigger - preload specialist content",
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


def _detect_specialists_from_activity_settings(state: GraphState) -> List[str]:
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


# Extended prompt for full field extraction (used when we need dates/destination too)
ROUTER_EXTRACTION_PROMPT = """You are an intent classifier AND field extractor \
for a travel planning assistant.
Today's date is {today_date}.

## Task 1: Intent Classification

Classify the user message into ONE of:

1. **GREETING** - Simple greetings or thanks with NO planning content
2. **RESET** - Explicit requests to start over
3. **PLANNING** - Everything else related to trip planning

## Task 2: Field Extraction (for PLANNING intent)

Extract ANY trip-related fields mentioned:
- **destination**: City or country (e.g., "Bali", "Thailand", "Dubai")
- **origin**: Origin city for flights if mentioned
- **start_date**: Convert to YYYY-MM-DD format. Examples:
  - "March 1" → "{current_year}-03-01"
  - "next Friday" → calculate from today
  - "February 15-22" → start_date = "{current_year}-02-15"
- **end_date**: Convert to YYYY-MM-DD format
  - "March 1-8" → end_date = "{current_year}-03-08"
- **duration_days**: If they say "for a week" = 7, "5 days" = 5
- **adults/children**: Number of travelers
- **budget**: Amount in USD (e.g., "$5000" = 5000, "5k" = 5000)

## Task 3: Flags

Set these boolean flags:
- **has_dates_in_message**: true if ANY date info present
  (month names, "next week", "March 1-8", etc.)
- **has_activity_in_message**: true if specific activities mentioned
  (diving, hiking, skiing, etc.)
- **planning_ready**: true if user explicitly wants to plan NOW
  (says "plan it", "let's go", "build itinerary", has both dates AND activities)

## Specialist Detection

Include all matching specialists: diving, hiking, skiing, cycling, boating

## User Message
"{user_message}"

Respond with valid JSON. Only include fields that are explicitly mentioned."""


def _get_router_llm() -> ChatOpenAI:
    """Get the fast LLM for intent classification."""
    return ChatOpenAI(
        model=os.getenv("ROUTER_MODEL", "gpt-4o-mini"),
        temperature=0,  # Deterministic classification
        max_tokens=150,  # Classification is short
    )


def _get_router_extraction_llm() -> ChatOpenAI:
    """Get the LLM for full Router extraction (intent + fields)."""
    return ChatOpenAI(
        model=os.getenv("ROUTER_MODEL", "gpt-4o-mini"),
        temperature=0,  # Deterministic extraction
        max_tokens=400,  # Need more tokens for field extraction
    )


async def _classify_and_extract_with_llm(
    user_text: str, state: "GraphState"
) -> Tuple[RouterOutput, dict]:
    """
    Classify intent AND extract trip fields in one LLM call with L1 caching.

    This is the new unified extraction that replaces the old pattern of:
    1. Router: classify intent only
    2. ARCHITECT: re-extract fields from same text

    Now Router does both, eliminating the duplicate extraction bug.

    Caching strategy:
    - Only caches self-contained queries (no context dependencies)
    - Key includes today_date for relative date resolution
    - 1h TTL (conversational context is short-lived)

    Returns tuple of (RouterOutput, token_usage_dict).
    """
    from datetime import datetime

    from app.services.router_cache import get_cached_extraction, set_cached_extraction

    today = datetime.now()
    today_date = today.strftime("%Y-%m-%d")

    # =========================================================================
    # CACHE CHECK
    # =========================================================================
    cached = get_cached_extraction(user_text, today_date)
    if cached is not None:
        try:
            output = RouterOutput.model_validate(cached)
            logger.debug(f"[ROUTER] Cache HIT: intent={output.intent}, dest={output.destination}")
            return output, {}  # Empty token_usage for cache hit
        except Exception as e:
            logger.debug(f"[ROUTER] Cache deserialize failed: {e}")

    # =========================================================================
    # CACHE MISS - LLM CALL
    # =========================================================================
    try:
        llm = _get_router_extraction_llm()

        # Use structured output for reliable JSON parsing
        structured_llm = llm.with_structured_output(RouterOutput, include_raw=True)

        # Format prompt with current date context
        current_year = today.year
        prompt = ROUTER_EXTRACTION_PROMPT.format(
            user_message=user_text,
            today_date=today_date,
            current_year=current_year,
        )

        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])

        # Extract parsed result and token usage
        parsed = result["parsed"]
        raw = result["raw"]
        token_usage = {}
        if hasattr(raw, "response_metadata"):
            token_usage = raw.response_metadata.get("token_usage", {})

        logger.debug(
            f"Router extraction: intent={parsed.intent}, "
            f"dest={parsed.destination}, dates={parsed.start_date}->{parsed.end_date}, "
            f"has_dates={parsed.has_dates_in_message}, planning_ready={parsed.planning_ready}"
        )

        # =====================================================================
        # CACHE WRITE (only if self-contained query)
        # =====================================================================
        set_cached_extraction(user_text, today_date, parsed.model_dump())

        return parsed, token_usage

    except Exception as e:
        logger.warning(f"Router extraction failed, using fallback: {e}")
        # Create fallback with keyword detection
        text_lower = user_text.lower()
        has_dates = any(re.search(p, text_lower) for p in DATE_INDICATORS)
        has_activity = any(re.search(p, text_lower) for p in ACTIVITY_INDICATORS)

        return (
            RouterOutput(
                intent="PLANNING",
                confidence=0.5,
                reasoning=f"LLM extraction failed: {e}",
                specialist_hints=_detect_specialist_keywords(user_text),
                has_dates_in_message=has_dates,
                has_activity_in_message=has_activity,
                planning_ready=has_dates and has_activity,
            ),
            {},
        )


async def _classify_intent_with_llm(
    user_text: str, state: "GraphState"
) -> Tuple[IntentClassification, dict]:
    """
    Classify user intent using LLM (legacy - for simple classification only).

    For full extraction (intent + dates + destination), use _classify_and_extract_with_llm.

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
# Exploration Mode: Comprehensive Answer Generation
# =============================================================================


def _format_section_answer(qtype: str, section: str, knowledge, destination: str) -> Optional[str]:
    """Format comprehensive answer from Local Expert section."""
    try:
        if qtype == "couples":
            overview = knowledge.destination_overview
            if not overview or not overview.tagline:
                return None
            best_for = (
                ", ".join(overview.best_for[:3]) if overview.best_for else "Various activities"
            )
            vibe = overview.vibe.lower() if overview.vibe else "relaxed"
            return (
                f"{destination} is fantastic for couples! {overview.tagline}\n\n"
                f"**What makes it special:**\n\n"
                f"- Great for: {best_for}\n"
                f"- The vibe is {vibe} and romantic\n"
                f"- Most couples spend 7-10 days to experience everything"
            )

        elif qtype == "family":
            overview = knowledge.destination_overview
            if not overview or not overview.tagline:
                return None
            best_for = (
                ", ".join(overview.best_for[:3]) if overview.best_for else "Various activities"
            )
            vibe = overview.vibe.lower() if overview.vibe else "relaxed"
            return (
                f"{destination} can be great for families! {overview.tagline}\n\n"
                f"**What to know:**\n\n"
                f"- Best for: {best_for}\n"
                f"- The vibe is {vibe}\n"
                f"- Consider kid-friendly activities and accommodation"
            )

        elif qtype == "weather":
            s = knowledge.seasonality
            if not s or not s.best_months:
                return None
            avoid_text = f"**Avoid:** {', '.join(s.avoid_months)}" if s.avoid_months else ""
            return (
                f"Here's the weather breakdown for {destination}:\n\n"
                f"**Best time to visit:** {', '.join(s.best_months)}\n"
                f"**High season:** {s.high_season or 'Varies'}\n"
                f"**Rainy season:** {s.rainy_season or 'Check local forecasts'}\n\n"
                f"{avoid_text}"
            ).strip()

        elif qtype == "safety":
            sh = knowledge.safety_health
            if not sh or not sh.overall_safety:
                return None
            concerns = (
                "\n".join(f"- {c}" for c in sh.common_concerns[:4])
                if sh.common_concerns
                else "- Standard travel precautions apply"
            )
            tap_water = "Safe" if sh.tap_water_safe else "Drink bottled only"
            return (
                f"{destination} is {sh.overall_safety.lower()} for tourists.\n\n"
                f"**Key things to know:**\n\n{concerns}\n\n"
                f"**Tap water:** {tap_water}\n\n"
                f"**Emergency:** {sh.emergency_number or '112 (general)'}"
            )

        elif qtype == "costs":
            mc = knowledge.money_costs
            if not mc or not mc.currency:
                return None
            # Use direct attribute access - these are Pydantic models, not dicts
            daily = mc.daily_budget
            typical = mc.typical_costs
            tipping = mc.tipping
            budget_meal = typical.budget_meal or "N/A" if typical else "N/A"
            mid_meal = typical.mid_range_meal or "N/A" if typical else "N/A"
            beer_cost = typical.beer or "N/A" if typical else "N/A"
            tip_info = (
                tipping.restaurants or "varies by culture" if tipping else "varies by culture"
            )
            return (
                f"Here's what to expect cost-wise in {destination}:\n\n"
                f"**Currency:** {mc.currency}\n\n"
                f"**Daily budget:**\n\n"
                f"- Backpacker: {daily.backpacker or 'N/A' if daily else 'N/A'}\n"
                f"- Mid-range: {daily.mid_range or 'N/A' if daily else 'N/A'}\n"
                f"- Luxury: {daily.luxury or 'N/A' if daily else 'N/A'}\n\n"
                f"**Typical costs:**\n\n"
                f"- Meal: {budget_meal} - {mid_meal}\n"
                f"- Beer: {beer_cost}\n\n"
                f"**Tipping:** {tip_info}"
            )

        elif qtype == "visa":
            ve = knowledge.visa_entry
            if not ve:
                return None
            visa_on_arrival = "Yes" if ve.visa_on_arrival else "No"
            visa_free = (
                ", ".join(ve.visa_free_for[:5]) + "..."
                if ve.visa_free_for
                else "Check requirements"
            )
            return (
                f"**Visa info for {destination}:**\n\n"
                f"- Visa on arrival: {visa_on_arrival}\n"
                f"- Max stay: {ve.max_stay_days or 'Varies'} days\n"
                f"- Passport validity: {ve.passport_validity_months or 6} months required\n"
                f"- Visa-free for: {visa_free}\n\n"
                f"**Tip:** {ve.immigration_tip or 'Have your documents ready'}"
            )

        elif qtype == "transport":
            t = knowledge.transportation
            if not t:
                return None
            # airport_to_city is a list of AirportTransfer Pydantic models
            airport = t.airport_to_city[0] if t.airport_to_city else None
            ride_apps = ", ".join(t.ride_apps[:3]) if t.ride_apps else "Local taxis"
            # scooter_rental is a ScooterRental Pydantic model
            scooter_info = (
                f"${t.scooter_rental.daily_rate}/day"
                if t.scooter_rental and t.scooter_rental.available
                else "Not recommended"
            )
            # Use direct attribute access for airport (AirportTransfer model)
            airport_method = airport.method if airport else "Taxi"
            airport_price = airport.price if airport else "varies"
            airport_time = airport.time if airport else "varies"
            airport_tip = airport.tip if airport else "Use official services"
            return (
                f"**Getting around {destination}:**\n\n"
                f"**From airport:**\n\n"
                f"- {airport_method}: {airport_price} ({airport_time})\n"
                f"- Tip: {airport_tip}\n\n"
                f"**Daily transport:**\n\n"
                f"- Ride apps: {ride_apps}\n"
                f"- Scooter rental: {scooter_info}\n\n"
                f"**Traffic note:** {t.traffic_note or 'Check local conditions'}"
            )

        elif qtype == "activities":
            td = knowledge.things_to_do
            if not td or not td.must_do:
                return None
            must_do = "\n".join(f"- **{m.name}** - {m.why}" for m in td.must_do[:3])
            hidden = (
                ", ".join(g.name for g in td.hidden_gems[:2]) if td.hidden_gems else "Ask locals!"
            )
            skip = ", ".join(td.skip_these[:2]) if td.skip_these else "None noted"
            return (
                f"**Must-do experiences in {destination}:**\n\n"
                f"{must_do}\n\n"
                f"**Hidden gems:** {hidden}\n\n"
                f"**Skip these tourist traps:** {skip}"
            )

        elif qtype == "scams":
            st = knowledge.scams_traps
            if not st:
                return None
            scams_text = (
                "\n".join(f"- **{s.name}:** {s.how_to_avoid}" for s in st.common_scams[:3])
                if st.common_scams
                else "- Be aware of standard tourist scams"
            )
            return (
                f"**Scams to watch out for in {destination}:**\n\n"
                f"{scams_text}\n\n"
                f"**Taxi tip:** {st.taxi_scam_tip or 'Use metered taxis or apps'}\n\n"
                f"**General advice:** {st.general_advice or 'Stay alert in tourist areas'}"
            )

        elif qtype == "cultural":
            cn = knowledge.cultural_norms
            if not cn:
                return None
            # dress_code is a DressCode Pydantic model, use direct attribute access
            dress = cn.dress_code
            taboos = (
                "\n".join(f"- {t}" for t in cn.important_taboos[:3])
                if cn.important_taboos
                else "- Respect local customs"
            )
            temple_dress = dress.temples if dress and dress.temples else "Cover shoulders and knees"
            beach_dress = dress.beaches if dress and dress.beaches else "Swimwear OK"
            return (
                f"**Cultural tips for {destination}:**\n\n"
                f"**Dress code:**\n\n"
                f"- Temples: {temple_dress}\n"
                f"- Beaches: {beach_dress}\n\n"
                f"**Important taboos:**\n\n{taboos}\n\n"
                f"**Religious note:** {cn.religious_notes or 'Respect local beliefs'}"
            )

        elif qtype == "accommodation":
            n = knowledge.neighborhoods
            if not n or not n.where_to_stay:
                return None

            def _fmt_area(a):
                best = ", ".join(a.best_for[:2]) if a.best_for else "General"
                return f"- **{a.name}** - {a.vibe} (Best for: {best})"

            areas = "\n".join(_fmt_area(a) for a in n.where_to_stay[:3])
            avoid = ", ".join(n.avoid_staying_in[:2]) if n.avoid_staying_in else "No major concerns"
            return (
                f"**Where to stay in {destination}:**\n\n"
                f"{areas}\n\n"
                f"**Avoid staying in:** {avoid or 'No major concerns'}"
            )

        elif qtype == "packing":
            p = knowledge.packing
            if not p or not p.must_pack:
                return None
            must_pack = "\n".join(f"- {item}" for item in p.must_pack[:5])
            buy_local = ", ".join(p.buy_locally[:3]) if p.buy_locally else "Check locally"
            # electrical is an ElectricalInfo Pydantic model, use direct attribute access
            elec = p.electrical
            plug_type = elec.plug_type if elec and elec.plug_type else "Check type"
            voltage = elec.voltage if elec and elec.voltage else "220V"
            adapter = "Adapter needed" if (not elec or elec.adapter_needed) else "No adapter needed"
            return (
                f"**Packing tips for {destination}:**\n\n"
                f"**Must pack:**\n\n{must_pack}\n\n"
                f"**Buy locally:** {buy_local}\n\n"
                f"**Electrical:** {plug_type}, {voltage} - {adapter}"
            )

        elif qtype == "connectivity":
            c = knowledge.connectivity
            if not c:
                return None
            esim = "Yes" if c.esim_works else "No"
            apps = ", ".join(c.essential_apps[:4]) if c.essential_apps else "Local apps vary"
            sim_provider = c.best_sim_provider or "Local providers"
            sim_cost = c.sim_cost or "$5-10"
            where_buy = c.where_to_buy or "Airport or convenience stores"
            return (
                f"**Staying connected in {destination}:**\n\n"
                f"**Best SIM:** {sim_provider} (~{sim_cost})\n"
                f"**Where to buy:** {where_buy}\n"
                f"**eSIM works:** {esim}\n\n"
                f"**Essential apps:** {apps}\n\n"
                f"**WiFi quality:** {c.wifi_quality or 'Varies by location'}"
            )

        else:  # general fallback
            overview = knowledge.destination_overview
            if not overview or not overview.tagline:
                return None
            best_for = (
                ", ".join(overview.best_for[:4]) if overview.best_for else "Various travelers"
            )
            return (
                f"{destination}! {overview.tagline}\n\n"
                f"Great for: {best_for}\n"
                f"Vibe: {overview.vibe or 'Unique'}"
            )

    except (AttributeError, KeyError, TypeError) as e:
        logger.warning(f"Error formatting section answer for {qtype}: {e}")
        return None


def _get_conversation_ending(count: int, qtype: str, destination: str) -> str:
    """Get appropriate ending based on conversation depth."""
    if count == 1:
        return "What else would you like to know?"

    elif count == 2:
        # Soft nudge toward planning
        nudges = {
            "weather": "When are you thinking of going?",
            "couples": "When are you planning the trip?",
            "family": "When are you planning to travel?",
            "costs": "What kind of budget are you working with?",
            "activities": "What activities interest you most?",
        }
        return nudges.get(qtype, f"When are you thinking of visiting {destination}?")

    else:  # count >= 3
        return (
            f"I can help plan your {destination} trip when you're ready. "
            "Just let me know your dates and what activities interest you!"
        )


async def _llm_fallback_answer(
    question: str,
    destination: str,
    qtype: str,
    count: int,
) -> str:
    """
    LLM fallback for destinations not in LOCAL_EXPERT_KNOWLEDGE.
    Uses GPT-4o-mini with ~300 token limit for cost efficiency.
    """
    ending = _get_conversation_ending(count, qtype, destination)

    prompt = f"""You are a knowledgeable travel advisor. Answer this question comprehensively:

Question: {question}
Destination: {destination}
Topic: {qtype}

Provide a helpful, detailed answer (4-5 sentences). Be conversational and warm.
Include specific examples, prices if relevant, and practical tips.
Format with bullet points where appropriate.

End with: {ending}"""

    llm = ChatOpenAI(
        model=os.getenv("ROUTER_MODEL", "gpt-4o-mini"),
        temperature=0.7,
        max_tokens=300,
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as e:
        logger.warning(f"LLM fallback failed for {destination}: {e}")
        # Generic safe response
        return (
            f"I'd love to help you learn more about {destination}! "
            f"While I don't have detailed info cached, I can help plan your trip. "
            f"{ending}"
        )


async def _safe_format_section_answer(
    qtype: str,
    section: str,
    knowledge,
    destination: str,
    question: str,
    count: int,
) -> str:
    """
    Wrapper that handles missing/malformed Local Expert sections gracefully.
    Falls back to LLM if section data is incomplete.
    """
    try:
        answer = _format_section_answer(qtype, section, knowledge, destination)
        if answer is None:
            # Section returned None (no data) - use LLM
            return await _llm_fallback_answer(question, destination, qtype, count)
        return answer
    except (AttributeError, KeyError, TypeError) as e:
        logger.warning(f"Missing Local Expert section '{section}' for {destination}: {e}")
        return await _llm_fallback_answer(question, destination, qtype, count)


async def generate_comprehensive_answer(
    question: str,
    destination: str,
    question_type: str,
    section: str,
    state: "GraphState",
) -> Tuple[str, str]:
    """
    Generate comprehensive answer for exploration questions.

    Returns (answer_body, ending_prompt).
    Uses Local Expert knowledge for comprehensive answers.
    Falls back to LLM for unknown destinations or missing sections.
    """
    from app.planner.nodes.local_expert import _get_static_local_knowledge

    knowledge = _get_static_local_knowledge(destination)
    question_count = state.metadata.get("generic_question_count", 0) + 1

    # Get answer with error handling and LLM fallback
    answer = await _safe_format_section_answer(
        question_type, section, knowledge, destination, question, question_count
    )

    # Get appropriate ending based on question count
    ending = _get_conversation_ending(question_count, question_type, destination)

    return answer, ending


def _get_exploration_suggestions(qtype: str, destination: str) -> List[str]:
    """Get contextual suggestion chips for exploration mode."""
    base_suggestions = {
        "couples": ["Best romantic spots?", "When to visit?", f"Plan {destination} trip"],
        "family": ["Kid-friendly activities?", "When to visit?", f"Plan {destination} trip"],
        "weather": ["What to pack?", "Best activities?", f"Plan {destination} trip"],
        "safety": ["Health tips?", "What to avoid?", f"Plan {destination} trip"],
        "costs": ["Is it worth it?", "Budget tips?", f"Plan {destination} trip"],
        "activities": ["Hidden gems?", "What to skip?", f"Plan {destination} trip"],
        "visa": ["Entry requirements?", "Best time to go?", f"Plan {destination} trip"],
        "transport": ["Best way around?", "Taxi tips?", f"Plan {destination} trip"],
        "cultural": ["What to wear?", "Local customs?", f"Plan {destination} trip"],
        "accommodation": ["Best area to stay?", "Budget options?", f"Plan {destination} trip"],
        "packing": ["What to bring?", "Weather tips?", f"Plan {destination} trip"],
        "connectivity": ["SIM options?", "WiFi quality?", f"Plan {destination} trip"],
        "scams": ["Safety tips?", "What to avoid?", f"Plan {destination} trip"],
    }

    return base_suggestions.get(
        qtype,
        ["What else to know?", "Best time to visit?", f"Plan {destination} trip"],
    )


def _get_date_suggestions(user_text: str) -> List[str]:
    """
    Generate context-aware date suggestions based on user's message.

    If user mentioned a specific month (e.g., "March"), use that month in suggestions.
    Otherwise, use generic suggestions.
    """
    text_lower = user_text.lower()

    # Month mapping for detection and capitalization
    months = {
        "january": "January",
        "february": "February",
        "march": "March",
        "april": "April",
        "may": "May",
        "june": "June",
        "july": "July",
        "august": "August",
        "september": "September",
        "october": "October",
        "november": "November",
        "december": "December",
    }

    # Check if user mentioned a specific month
    for month_lower, month_cap in months.items():
        if month_lower in text_lower:
            # Return suggestions with the mentioned month
            return [
                f"{month_cap} 1-8",
                f"{month_cap} 10-17",
                "I'm flexible on dates",
            ]

    # Generic suggestions if no month mentioned
    return [
        "Next month for 7 days",
        "I'm flexible on dates",
        "Show me best times to visit",
    ]


# =============================================================================
# State Population from RouterOutput
# =============================================================================


def _populate_trip_plan_from_router_output(
    state: "GraphState", router_output: RouterOutput, fallback_destination: Optional[str]
) -> None:
    """
    Populate state.trip_plan fields from RouterOutput extraction.

    This is the key fix for the date extraction bug - we populate the state
    IMMEDIATELY after extraction, before any checks for missing dates.

    Args:
        state: GraphState to update
        router_output: Extracted fields from LLM
        fallback_destination: Destination from context extraction (used if LLM didn't extract one)
    """
    from datetime import datetime

    # Set destination (prefer extracted, fallback to context)
    if router_output.destination:
        state.trip_plan.destination = router_output.destination
    elif fallback_destination and not state.trip_plan.destination:
        state.trip_plan.destination = fallback_destination

    # Set dates - TripPlan expects strings in YYYY-MM-DD format
    if router_output.start_date:
        # Validate format but keep as string
        try:
            datetime.strptime(router_output.start_date, "%Y-%m-%d")
            state.trip_plan.start_date = router_output.start_date
        except ValueError:
            logger.warning(f"Invalid start_date format: {router_output.start_date}")

    if router_output.end_date:
        # Validate format but keep as string
        try:
            datetime.strptime(router_output.end_date, "%Y-%m-%d")
            state.trip_plan.end_date = router_output.end_date
        except ValueError:
            logger.warning(f"Invalid end_date format: {router_output.end_date}")

    # Calculate duration if we have both dates but no explicit duration
    if state.trip_plan.start_date and state.trip_plan.end_date and not router_output.duration_days:
        try:
            start = datetime.strptime(state.trip_plan.start_date, "%Y-%m-%d")
            end = datetime.strptime(state.trip_plan.end_date, "%Y-%m-%d")
            state.trip_plan.duration_days = (end - start).days + 1  # Inclusive
        except ValueError:
            pass  # Skip duration calculation if dates are invalid

    # INVERSE: Calculate end_date if we have start_date + duration but no end_date
    # Handles cases like "a week in March" where LLM extracts start + duration
    if router_output.start_date and router_output.duration_days and not router_output.end_date:
        try:
            from datetime import timedelta

            start = datetime.strptime(router_output.start_date, "%Y-%m-%d")
            end = start + timedelta(days=router_output.duration_days - 1)  # Inclusive
            state.trip_plan.end_date = end.strftime("%Y-%m-%d")
            state.trip_plan.duration_days = router_output.duration_days
            logger.debug(f"Calculated end_date from duration: {state.trip_plan.end_date}")
        except ValueError:
            pass  # Skip if date format is invalid

    # Set other extracted fields if present
    if router_output.origin:
        state.trip_plan.origin = router_output.origin

    if router_output.adults is not None:
        state.trip_plan.adults = router_output.adults

    if router_output.children is not None:
        state.trip_plan.children = router_output.children

    if router_output.budget is not None:
        state.trip_plan.budget = router_output.budget

    logger.debug(
        f"Populated trip_plan: dest={state.trip_plan.destination}, "
        f"dates={state.trip_plan.start_date} → {state.trip_plan.end_date}"
    )


# =============================================================================
# Node Function
# =============================================================================


async def intent_router(state: GraphState) -> GraphState:
    """
    IntentRouter node function for LangGraph.

    Uses LLM to classify user intent and either:
    - Returns static response for GREETING/RESET (skips architect)
    - Passes PLANNING intent to architect for handling

    The panic button (/reset, stop, clear) is handled in run_turn BEFORE
    the graph is invoked, so we don't need to check for it here.
    """
    from app.debug_utils import (
        _debug_node_end,
        _debug_node_start,
        _debug_node_timer_end,
        _debug_node_timer_start,
    )

    # Start timing this node execution
    _debug_node_timer_start("router")

    # Get user message from last message
    user_text = ""
    if state.messages:
        last_msg = state.messages[-1]
        if hasattr(last_msg, "content"):
            user_text = last_msg.content

    _debug_node_start(
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

    # Check for speculative execution trigger from frontend (preload specialists in Setup)
    is_speculate_trigger = False
    if classification is None:
        speculate_classification = _check_speculate_trigger(user_text)
        if speculate_classification is not None:
            classification = speculate_classification
            is_speculate_trigger = True
            from app.debug_utils import log

            log("ROUTER", f"🔮 Speculative Trigger Detected for {state.trip_plan.destination}")

    # ==========================================================================
    # EXPLORATION MODE: Check if this is a generic travel question
    # ==========================================================================
    # Before falling through to LLM classification, check if this is an exploration
    # question that we can answer directly using Local Expert knowledge.
    if classification is None:
        from app.debug_utils import log

        # Check for planning readiness
        planning_intent = detect_planning_intent(user_text, state)
        destination = _extract_destination_context(user_text, state)

        # =====================================================================
        # OPPORTUNISTIC EXTRACTION: Extract dates/fields from EVERY message
        # that contains extractable data, regardless of planning intent.
        # This ensures dates mentioned during exploration are NOT lost.
        # =====================================================================
        text_lower = user_text.lower()
        has_date_in_message = any(re.search(p, text_lower) for p in DATE_INDICATORS)

        if has_date_in_message:
            log("ROUTER", "[OPPORTUNISTIC] Dates detected, extracting immediately...")

            try:
                router_output, token_usage = await _classify_and_extract_with_llm(user_text, state)

                if token_usage:
                    from app.debug_utils import log_tokens

                    log_tokens(
                        "ROUTER",
                        token_usage.get("prompt_tokens", 0),
                        token_usage.get("completion_tokens", 0),
                        token_usage.get("total_tokens", 0),
                    )

                # Immediately persist to state.trip_plan
                _populate_trip_plan_from_router_output(state, router_output, destination)

                # Store for downstream reference
                state.metadata["router_output"] = router_output.model_dump()
                state.metadata["router_extracted_fields"] = True

                log(
                    "ROUTER",
                    f"[OPPORTUNISTIC] Extracted: dest={state.trip_plan.destination}, "
                    f"dates={state.trip_plan.start_date} → {state.trip_plan.end_date}",
                )
            except Exception as e:
                logger.warning(f"[OPPORTUNISTIC] Extraction failed: {e}")
                # Continue with normal flow even if extraction fails
        # =====================================================================
        # END OPPORTUNISTIC EXTRACTION
        # =====================================================================

        log(
            "ROUTER",
            f"[EXPLORATION] planning_intent={planning_intent}, destination={destination}",
        )

        # If user is ready to plan, check for required info first
        if planning_intent == "ready":
            # Check if we have required dates for planning
            # NOTE: Dates may already be populated by opportunistic extraction above
            has_start = bool(state.trip_plan.start_date)
            has_end = bool(state.trip_plan.end_date)
            dest = destination or state.trip_plan.destination

            # If we have dates (from opportunistic extraction or previous turns),
            # proceed to planning
            if dest and has_start and has_end:
                log(
                    "ROUTER",
                    f"[READY] All required fields present, routing to ARCHITECT. "
                    f"dest={dest}, dates={state.trip_plan.start_date} → {state.trip_plan.end_date}",
                )

                state.metadata["exploration_mode"] = False
                state.metadata["short_circuit_response"] = False  # Let ARCHITECT run
                state.intent = "general"  # ARCHITECT will handle planning

                # Set specialist hints from router_output if we have it
                all_specialists = []
                router_output = state.metadata.get("router_output")
                if router_output and router_output.get("specialist_hints"):
                    all_specialists = list(router_output["specialist_hints"])

                # Ensure local_expert runs first (Trip DNA anchor)
                if all_specialists and "local_expert" not in all_specialists:
                    all_specialists = ["local_expert"] + all_specialists
                elif not all_specialists and state.trip_plan.destination:
                    all_specialists = ["local_expert"]

                if all_specialists:
                    state.pending_specialists = (
                        all_specialists[1:] if len(all_specialists) > 1 else []
                    )
                    state.active_specialist = all_specialists[0]
                    state.active_agent_id = all_specialists[0]
                    state.ui_events.append("SPECIALIST_ACTIVE")
                    log("ROUTER", f"[READY] Specialists queue: {all_specialists}")

                _debug_node_end(
                    "router",
                    "🧭",
                    intent="PLANNING_READY",
                    destination=state.trip_plan.destination,
                    dates=f"{state.trip_plan.start_date} → {state.trip_plan.end_date}",
                    specialists=all_specialists,
                )

                return state

            if dest and (not has_start or not has_end):
                # User wants to plan but missing dates AND didn't provide any - ask for them
                log("ROUTER", f"[READY] Missing dates: start={has_start}, end={has_end}")

                if not has_start and not has_end:
                    missing_text = "dates"
                elif not has_start:
                    missing_text = "start date"
                else:
                    missing_text = "end date (how long will you stay?)"

                state.last_summary = (
                    f"I'd love to build your {dest} itinerary! "
                    f"I just need your {missing_text} to create the timeline. "
                    f"When would you like to travel?"
                )

                # Generate context-aware date suggestions based on any month mentioned
                state.suggested_replies = _get_date_suggestions(user_text)
                state.metadata["short_circuit_response"] = True
                state.metadata["short_circuit_type"] = "exploration"
                state.metadata["awaiting_dates"] = True

                _debug_node_end(
                    "router",
                    "🧭",
                    intent="AWAITING_DATES",
                    destination=dest,
                    short_circuit=True,
                )
                return state

            # Has all required info - proceed to planning
            log("ROUTER", "[EXPLORATION] User ready to plan - continuing to LLM classification")
            state.metadata["exploration_mode"] = False
            # Fall through to LLM classification below

        # If exploring and we have destination context, generate comprehensive answer
        elif planning_intent == "exploring" and destination:
            qtype, section = classify_question_type(user_text)
            log("ROUTER", f"[EXPLORATION] Detected question type: {qtype}, section: {section}")

            # Generate comprehensive answer
            answer, ending = await generate_comprehensive_answer(
                user_text, destination, qtype, section, state
            )

            # Update conversation tracking
            count = state.metadata.get("generic_question_count", 0) + 1
            state.metadata["generic_question_count"] = count
            state.metadata["last_destination_context"] = destination
            state.metadata["exploration_mode"] = True

            # Set short-circuit response
            state.last_summary = f"{answer}\n\n{ending}"
            state.suggested_replies = _get_exploration_suggestions(qtype, destination)
            state.metadata["short_circuit_response"] = True
            state.metadata["short_circuit_type"] = "exploration"

            # Pre-set destination for when they're ready to plan
            if not state.trip_plan.destination:
                state.trip_plan.destination = destination

            log("ROUTER", f"[EXPLORATION] Returning exploration response (question #{count})")

            _debug_node_end(
                "router",
                "🧭",
                intent="EXPLORATION",
                destination=destination,
                question_type=qtype,
                question_count=count,
                short_circuit=True,
            )
            return state

        # Soft transition: has date OR activity but exploring question format
        elif planning_intent == "soft_transition" and destination:
            # CRITICAL FIX: If plan already has dates AND user mentions a NEW activity,
            # route to the specialist instead of soft_transition
            plan_has_dates = state.trip_plan.start_date and state.trip_plan.end_date

            # Get existing specialists from strategy sections
            existing_specialists = [
                s.get("specialist_type")
                for s in state.metadata.get("strategy_sections", [])
                if s.get("specialist_type") not in ("general", "local_expert")
            ]

            # Detect NEW specialists from the message
            new_specialists = get_new_specialists_from_text(user_text, existing_specialists)

            # CRITICAL: Route to planning immediately when user provides actionable input:
            # 1. dates + destination (e.g., "bali Mar 1-9")
            # 2. destination + activities (e.g., "bali diving")
            # Input parameters have highest priority - don't ask exploration questions
            if plan_has_dates or new_specialists:
                if plan_has_dates:
                    log(
                        "ROUTER",
                        f"[SOFT_TRANSITION→PLANNING] Dates provided: "
                        f"{state.trip_plan.start_date} → {state.trip_plan.end_date}",
                    )
                if new_specialists:
                    log(
                        "ROUTER",
                        f"[SOFT_TRANSITION→PLANNING] Activities provided: {new_specialists}",
                    )

                # Only add local_expert if it hasn't run yet
                has_local_expert = "local_expert" in [
                    s.get("specialist_type") for s in state.metadata.get("strategy_sections", [])
                ]

                if has_local_expert and new_specialists:
                    # Local expert already ran, just queue the new niche specialists
                    state.pending_specialists = (
                        new_specialists[1:] if len(new_specialists) > 1 else []
                    )
                    state.active_specialist = new_specialists[0]
                    state.active_agent_id = new_specialists[0]
                elif new_specialists:
                    # No local expert yet, add it first, then the specialists
                    state.pending_specialists = new_specialists
                    state.active_specialist = "local_expert"
                    state.active_agent_id = "local_expert"
                else:
                    # No specialist mentioned, just start with local_expert
                    state.pending_specialists = []
                    state.active_specialist = "local_expert"
                    state.active_agent_id = "local_expert"

                state.ui_events.append("SPECIALIST_ACTIVE")

                # Ensure we don't short-circuit so the specialist actually runs
                state.metadata["short_circuit_response"] = False
                state.metadata["exploration_mode"] = False

                _debug_node_end(
                    "router",
                    "🧭",
                    intent="SOFT_TRANSITION→PLANNING",
                    destination=destination,
                    dates=(
                        f"{state.trip_plan.start_date} → {state.trip_plan.end_date}"
                        if plan_has_dates
                        else "TBD"
                    ),
                    specialists=new_specialists if new_specialists else ["local_expert"],
                )
                return state

            qtype, section = classify_question_type(user_text)
            log("ROUTER", f"[SOFT_TRANSITION] Detected question type: {qtype}")

            # Generate comprehensive answer
            answer, _ = await generate_comprehensive_answer(
                user_text, destination, qtype, section, state
            )

            # Stronger planning-focused ending based on what's missing
            text_lower = user_text.lower()
            has_date = any(re.search(p, text_lower) for p in DATE_INDICATORS)

            activity_prompt = (
                "What activities are you interested in? "
                "I specialize in diving, hiking, and skiing trips."
            )
            if has_date:
                # Has date, needs activity
                # Check if dates were actually extracted and acknowledge them
                if state.trip_plan.start_date and state.trip_plan.end_date:
                    start = state.trip_plan.start_date
                    end = state.trip_plan.end_date
                    ending = (
                        f"Great, I've noted your dates ({start} to {end}). " f"{activity_prompt}"
                    )
                elif state.trip_plan.start_date:
                    ending = f"Got it, starting {state.trip_plan.start_date}. " f"{activity_prompt}"
                else:
                    ending = activity_prompt
                suggestions = [
                    f"Plan {destination} diving trip",
                    f"Plan {destination} hiking trip",
                    "Show me all options",
                ]
            else:
                # Has activity, needs date
                ending = "When are you thinking of going? Timing can affect the best activities."
                suggestions = [
                    "Next month",
                    "I'm flexible on dates",
                    f"Plan {destination} trip",
                ]

            # Update state
            count = state.metadata.get("generic_question_count", 0) + 1
            state.metadata["generic_question_count"] = count
            state.metadata["last_destination_context"] = destination
            state.metadata["exploration_mode"] = True

            state.last_summary = f"{answer}\n\n{ending}"
            state.suggested_replies = suggestions
            state.metadata["short_circuit_response"] = True
            state.metadata["short_circuit_type"] = "soft_transition"

            if not state.trip_plan.destination:
                state.trip_plan.destination = destination

            log("ROUTER", "[SOFT_TRANSITION] Returning soft transition response")

            _debug_node_end(
                "router",
                "🧭",
                intent="SOFT_TRANSITION",
                destination=destination,
                question_type=qtype,
                short_circuit=True,
            )
            return state

    # ==========================================================================
    # END EXPLORATION MODE
    # ==========================================================================

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

        _debug_node_end(
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

        _debug_node_end(
            "router",
            "🧭",
            intent="RESET",
            short_circuit=True,
        )
        return state

    # PLANNING intent - pass to architect
    # Check if this is the generate plan trigger (user clicked "Build plan")
    # Use "booking" intent to trigger tile fetching in the Architect
    # Use "speculative" intent to preload specialists without tiles (Setup phase)
    is_generate_trigger = user_text.strip().upper() == GENERATE_PLAN_TRIGGER
    if is_speculate_trigger:
        state.intent = "speculative"
    elif is_generate_trigger:
        state.intent = "booking"
    else:
        state.intent = "general"
    state.metadata["short_circuit_response"] = False
    state.metadata["router_output"] = classification.model_dump()
    state.metadata["is_generate_trigger"] = is_generate_trigger
    state.metadata["is_speculative"] = is_speculate_trigger

    # Set specialist if detected from text OR from UI activity settings
    # Combine detected specialists from LLM and activity settings
    specialist_hints = list(classification.specialist_hints)  # Copy to avoid mutation

    # =========================================================================
    # CONSTRAINT CHANGE DETECTION: Re-run specialists when inputs change
    # =========================================================================
    # Check if critical inputs changed since the last run
    # NOTE: Hash is computed from trip_inputs (from frontend) which has latest values
    trip_inputs = state.metadata.get("trip_inputs", {})
    current_hash = _compute_constraint_hash(state.trip_plan, trip_inputs)
    previous_hash = state.last_constraint_hash
    executed = state.metadata.get("executed_strategy_topics", [])

    # Debug logging - CRITICAL for debugging reactivity
    from app.debug_utils import log

    prev_hash_str = previous_hash[:8] if previous_hash else "None"
    log(
        "ROUTER",
        f"[REACTIVITY] Hash: prev={prev_hash_str} → curr={current_hash[:8]}",
    )
    log("ROUTER", f"[REACTIVITY] executed_strategy_topics={executed}")
    dest = trip_inputs.get("destination")
    start = trip_inputs.get("start_date")
    end = trip_inputs.get("end_date")
    log(
        "ROUTER",
        f"[REACTIVITY] trip_inputs: dest={dest}, dates={start} to {end}",
    )
    log("ROUTER", f"[REACTIVITY] is_generate_trigger={is_generate_trigger}")

    # Detect constraint changes (only if we have a previous hash to compare)
    constraints_changed = previous_hash is not None and current_hash != previous_hash

    # Re-run specialists in two cases:
    # 1. Constraints changed (destination, dates, budget, etc. modified)
    # 2. GENERATE_PLAN_NOW + specialists were executed before (ensures fresh run with complete data)
    should_rerun_specialists = (constraints_changed or is_generate_trigger) and executed

    log(
        "ROUTER",
        f"[REACTIVITY] constraints_changed={constraints_changed}, "
        f"should_rerun={should_rerun_specialists}",
    )

    if should_rerun_specialists:
        # Filter to niche specialists only (not local_expert/general which run automatically)
        niche_specialists = [t for t in executed if t not in ("general", "local_expert")]

        if niche_specialists:
            if constraints_changed:
                log("ROUTER", f"Constraints changed! Re-running specialists: {niche_specialists}")
            else:
                log(
                    "ROUTER",
                    f"GENERATE_PLAN_NOW: Re-running specialists "
                    f"with fresh data: {niche_specialists}",
                )

            _clear_stale_specialist_content(state)

            # Re-inject niche specialists into hints so they run again
            for topic in niche_specialists:
                if topic not in specialist_hints:
                    specialist_hints.append(topic)
                    log("ROUTER", f"Re-queued specialist: {topic}")

    # ALWAYS update the hash for future comparisons
    state.last_constraint_hash = current_hash
    # =========================================================================

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
    #
    # CRITICAL: Local Expert ALWAYS runs FIRST (Trip DNA anchor)
    # Even when niche specialists (diving, hiking) are detected, we need Local Expert
    # to generate the "Trip Overview" card with destination vibes and context.
    # The niche specialist then ADDS their strategy on top, not replaces it.
    # @see docs/ux_unified_architecture.md - "Local Expert Always First"
    if specialist_hints:
        # Prepend local_expert if not already in the queue
        if "local_expert" not in specialist_hints:
            all_specialists = ["local_expert"] + specialist_hints
        else:
            # Move local_expert to front if it's somewhere in the list
            hints_without_local = [s for s in specialist_hints if s != "local_expert"]
            all_specialists = ["local_expert"] + hints_without_local

        state.pending_specialists = all_specialists[1:]  # Rest of the queue
        first_specialist = all_specialists[0]  # Should be "local_expert"
        state.active_specialist = first_specialist
        state.active_agent_id = first_specialist
        state.ui_events.append("SPECIALIST_ACTIVE")

        from app.debug_utils import log

        log("ROUTER", f"Specialists queue: local_expert first, then {state.pending_specialists}")
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

    _debug_node_timer_end(
        "router",
        "🧭",
        intent=state.intent,
        specialist=state.active_specialist,
        confidence=classification.confidence,
    )

    return state
