"""
Router Category Sync — Tier 2 activity detection and state synchronization.

Handles:
- Tier 2 activity keyword management (yoga, cooking, nightlife, etc.)
- Actionable input detection (additions, removals, skill level, setting resets)
- Planning readiness signals (exploration vs. planning mode)
- Destination context extraction
- Tier 2 experience prefetch coordination
- Activity category state synchronization
- Setting reset handling
"""

import asyncio
import logging
import re
from typing import List, Optional

from app.planner.nodes.router_extraction import (
    IntentClassification,
    _normalize_city_name,
)
from app.planner.specialist_registry import (
    ALL_SPECIALIST_KEYWORDS,
    TIER1_SPECIALIST_NAMES,
)
from app.planner.state import GraphState

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

TIER2_ACTIVITY_KEYWORDS: set[str] = {
    "yoga",
    "cooking",
    "nightlife",
    "temples",
    "beach",
    "shopping",
    "photography",
    "sailing",
    "wellness",
    "culture",
    "music",
    "wine",
    "food",
}

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

DATE_INDICATORS = [
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    r"\b(next week|next month|this weekend|tomorrow)\b",
    r"\b\d{1,2}[/-]\d{1,2}\b",
]

ORIGIN_PATTERNS = [
    r"^(?:i(?:'m|'m| am)\s+)?(?:leaving|departing|flying|coming|traveling)?\s*from\s+(\S.+)$",
    r"^(?:departure|depart(?:ing)?|leav(?:e|ing))\s+from\s+(\S.+)$",
    r"^from\s+(\S.+)$",  # Most common: "from rome"
]

SKILL_LEVEL_MAP: dict[str, str] = {
    "beginner": "beginner",
    "intermediate": "intermediate",
    "advanced": "advanced",
    "expert": "advanced",
    "novice": "beginner",
    "first time": "beginner",
}

REMOVAL_PATTERN = re.compile(
    r"(?:skip|remove|drop|no more|cancel|don't want|without)\s+(?:the\s+)?(\w+)"
)

RESET_BUDGET_PATTERN = re.compile(
    r"(?:no|remove|clear|unlimited|reset)\s+(?:budget|spending)\s*(?:limit)?"
)

RESET_HOTEL_PATTERN = re.compile(
    r"(?:no|remove|clear|reset)\s+(?:hotel|star)\s*(?:preference|filter|requirement)?"
    r"|any\s+(?:star|hotel)\s+(?:is fine|works|ok)"
)


# ============================================================================
# Actionable Input Detection
# ============================================================================


def _detect_actionable_input(user_text: str, state: "GraphState") -> Optional[dict]:
    """Catch actionable trip modifications that keyword/regex settings detection misses.

    Runs BEFORE exploration short-circuit to prevent swallowing valid input.
    Returns dict of changes if found, None if message is truly exploratory.
    """
    if not state.trip_plan.destination:
        return None

    text_lower = user_text.lower().strip()
    changes: dict = {}

    # 1. Tier 2 activity additions (word-boundary match)
    detected_t2 = {kw for kw in TIER2_ACTIVITY_KEYWORDS if re.search(rf"\b{kw}\b", text_lower)}
    if detected_t2:
        changes["add_categories"] = detected_t2

    # 2. Activity removals
    for m in REMOVAL_PATTERN.finditer(text_lower):
        target = m.group(1)
        all_known = TIER2_ACTIVITY_KEYWORDS | TIER1_SPECIALIST_NAMES
        if target in all_known:
            changes.setdefault("remove_categories", set()).add(target)

    # 3. Skill level
    for keyword, level in SKILL_LEVEL_MAP.items():
        if keyword in text_lower:
            changes["skill_level"] = level
            break

    # 4. Setting resets
    if RESET_BUDGET_PATTERN.search(text_lower):
        changes["reset_budget"] = True
    if RESET_HOTEL_PATTERN.search(text_lower):
        changes["reset_hotel"] = True

    # 5. Detect unresolved activity-like tokens
    # Runs even with zero keyword matches — catches synonyms like
    # "party" → nightlife, "clubbing" → nightlife, "spa" → wellness
    # that the LLM alias resolver can map to known categories.
    # The ≤5 words guard prevents questions like "what's the party scene
    # like in Bali" from being swallowed — those still reach exploration.
    all_known = TIER2_ACTIVITY_KEYWORDS | TIER1_SPECIALIST_NAMES
    stop_words = {
        # intent/filler
        "also",
        "and",
        "too",
        "as",
        "well",
        "add",
        "want",
        "with",
        "some",
        "plus",
        "the",
        "i",
        "we",
        "me",
        "my",
        "a",
        "in",
        "let",
        "can",
        "like",
        "maybe",
        "please",
        "for",
        "trip",
        # conversational — prevent chip/UI text from triggering ACTIONABLE
        "show",
        "more",
        "options",
        "change",
        "preferences",
        "other",
        "help",
        "what",
        "how",
        "about",
        "tell",
        "any",
        "get",
        "give",
        "see",
        "look",
        "try",
        "need",
        "could",
        "would",
        "should",
        "keep",
        "make",
        "take",
        "budget",
        "dates",
        "plan",
        "yes",
        "no",
        "sure",
        "okay",
        "thanks",
        "thank",
        "you",
        "that",
        "build",
        "itinerary",
        "set",
    }
    remaining = set(re.findall(r"\b[a-z]{3,}\b", text_lower))
    remaining -= all_known
    remaining -= stop_words
    remaining -= set(SKILL_LEVEL_MAP.keys())
    if remaining and len(text_lower.split()) <= 5:
        changes["unresolved_tokens"] = remaining

    return changes if changes else None


# ============================================================================
# Specialist Detection
# ============================================================================


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

    for specialist_type, keywords in ALL_SPECIALIST_KEYWORDS.items():
        if specialist_type in existing_specialists:
            continue  # Already have this specialist

        if any(kw in text_lower for kw in keywords):
            new_specialists.append(specialist_type)

    return new_specialists


# ============================================================================
# Planning Intent Detection
# ============================================================================


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
    has_activity = any(kw in text_lower for kws in ALL_SPECIALIST_KEYWORDS.values() for kw in kws)

    if has_date and has_activity:
        return "ready"  # "diving in February" → planning mode
    if has_date or has_activity:
        return "soft_transition"  # Just date or just activity

    return "exploring"


# ============================================================================
# Destination Context Extraction
# ============================================================================


def _extract_destination_context(text: str, state: "GraphState") -> Optional[str]:
    """
    Extract destination from question or use conversation context.

    Priority:
    1. Check if destination mentioned in current question (excluding origin cities)
    2. Use last_destination_context from state
    3. Use trip_plan.destination if set

    NOTE: Cities following origin indicators (e.g., "from rome") are NOT destinations.
    """
    from app.planner.nodes.local_expert import LOCAL_EXPERT_KNOWLEDGE

    text_lower = text.lower()

    # Extract cities that follow origin patterns - these are NOT destinations
    origin_cities = set()
    for pattern in ORIGIN_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            city = match.group(1).strip().rstrip(".!?,")
            # Truncate at destination indicators: "rome to bali" → "rome"
            city = re.split(r"\s+to\s+", city, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            city = city.lower()
            # Add both full match and first word (handles "rome italy")
            origin_cities.add(city)
            if city:
                origin_cities.add(city.split()[0])

    # Check LOCAL_EXPERT_KNOWLEDGE keys first (known destinations)
    # But SKIP cities that appear in origin context
    for dest_key in LOCAL_EXPERT_KNOWLEDGE.keys():
        dest_lower = dest_key.lower()
        if dest_lower in text_lower and dest_lower not in origin_cities:
            return dest_key.capitalize()

    # Fallback to conversation context
    if state.metadata.get("last_destination_context"):
        return state.metadata["last_destination_context"]

    if state.trip_plan and state.trip_plan.destination:
        return state.trip_plan.destination

    return None


# ============================================================================
# Greeting Detection
# ============================================================================


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


# ============================================================================
# Origin Detection
# ============================================================================


def _detect_origin_from_message(user_text: str) -> Optional[str]:
    """
    Detect if user message is specifying an origin/departure city.
    Returns normalized city name if detected, None otherwise.

    Must run BEFORE exploration mode check to prevent "from rome" being
    interpreted as exploring Rome when user means "departing from Rome".

    Examples:
        "from rome" → "Rome"
        "flying from london" → "London"
        "leaving from NYC" → "New York"
        "tell me about rome" → None (not an origin pattern)
    """
    text = user_text.strip()

    # Quick reject: if message doesn't contain "from", skip
    if "from" not in text.lower():
        return None

    for pattern in ORIGIN_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            city = match.group(1).strip().rstrip(".!?,")
            # Truncate at destination indicators: "rome to bali" → "rome"
            city = re.split(r"\s+to\s+", city, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            # Truncate at date-like tokens: "rome feb 11" → "rome"
            city = re.split(
                r"\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}[/-])\b",
                city,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            # Normalize: "rome italy" → "Rome", remove country suffixes
            city = _normalize_city_name(city)
            if city:
                # Title case the city name for display
                return city.title()

    return None


# ============================================================================
# Generate Plan Trigger Detection
# ============================================================================


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


# ============================================================================
# Tier 2 Experience Prefetch
# ============================================================================


def _prefetch_tier2_experiences(state: "GraphState", categories: set[str]) -> None:
    """Start Tier 2 experience generation speculatively to mask latency.

    CRITICAL: Passes state=None to avoid dict mutation race condition.
    Prefetch populates L1 cache. Logistics awaits task, then calls generate_experiences()
    with state=state, hits L1 cache instantly, and populates state.metadata safely.
    """

    from app.debug_utils import log
    from app.services.experience_generator import generate_experiences

    plan = state.trip_plan
    if not plan.destination:
        return

    month = str(plan.start_date)[:7] if plan.start_date else ""
    tiles_per_category = 2  # Logistics refines this based on trip length

    log(
        "ROUTER",
        f"[PREFETCH] Starting Tier 2 generation: dest={plan.destination}, categories={categories}",
    )

    task = asyncio.create_task(
        generate_experiences(
            destination=plan.destination,
            categories=list(categories),
            month=month,
            budget=plan.budget,
            tier1_specialists=None,
            tiles_per_category=tiles_per_category,
            state=None,  # ← CRITICAL: No state to avoid race condition
        )
    )

    # Add exception handler to surface errors from fire-and-forget task
    def _log_task_exception(t: asyncio.Task) -> None:
        if t.exception():
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"[PREFETCH] Task failed with exception: {t.exception()}",
                exc_info=t.exception(),
            )

    task.add_done_callback(_log_task_exception)

    state.metadata["tier2_prefetch_task"] = task
    state.metadata["tier2_prefetch_categories"] = list(categories)
