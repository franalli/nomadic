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

Regex Fast-Path Principle:
    The regex patterns in this module (REMOVAL_PATTERN, RESET_BUDGET_PATTERN,
    RESET_HOTEL_PATTERN, _CATEGORY_REPLACE_PATTERNS, _CATEGORY_INTENT_PATTERNS,
    DATE_INDICATORS) are OPTIMIZATIONS, not gates. They provide instant detection
    for common user phrasings before the LLM runs.

    The LLM extraction (_collect_modifications_from_extraction) is the AUTHORITY.
    If a regex misses a novel phrasing, the LLM will still catch it. Do NOT
    expand the regex patterns to chase edge cases — that's the LLM's job.
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Optional

from app.config import settings
from app.planner.specialist_registry import (
    ALL_SPECIALIST_KEYWORDS,
    TIER1_SPECIALIST_NAMES,
    TIER2_COMMON_HINTS,
)
from app.planner.state import GraphState

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz, process

    _FUZZY_AVAILABLE = True
except ImportError:
    _FUZZY_AVAILABLE = False

_BASE_FUZZY_VOCAB = sorted(TIER2_COMMON_HINTS | TIER1_SPECIALIST_NAMES)


def _get_fuzzy_vocab(state: "GraphState") -> list[str]:
    """Fuzzy match vocabulary: hints + session-active categories."""
    session_cats = set(
        state.metadata.get("trip_inputs", {}).get("activity_settings", {}).get("categories", [])
    )
    if not session_cats:
        return _BASE_FUZZY_VOCAB
    return sorted(TIER2_COMMON_HINTS | TIER1_SPECIALIST_NAMES | session_cats)


def _fuzzy_resolve_token(token: str, vocab: list[str]) -> Optional[str]:
    """Resolve misspelled token to nearest known category/specialist. None if no match."""
    if not _FUZZY_AVAILABLE or len(token) < 3:
        return None
    match = process.extractOne(
        token.lower(),
        vocab,
        scorer=fuzz.ratio,
        score_cutoff=settings.fuzzy_match_score_cutoff,
    )
    return match[0] if match else None


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

# ORIGIN_PATTERNS now imported from router_utils.py

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

# Explicit user language that indicates replacing current categories for this turn.
_CATEGORY_REPLACE_PATTERNS = (
    re.compile(r"\bonly\b"),
    re.compile(r"\binstead of\b"),
    re.compile(r"\brather than\b"),
    re.compile(r"\breplace\b"),
    re.compile(r"\bswap\b"),
    re.compile(r"\bnot\b.+\bbut\b"),
)

_CATEGORY_INTENT_PATTERNS = (
    re.compile(r"\b(add|include|with|plus|also)\b"),
    re.compile(r"\b(remove|drop|skip|without)\b"),
    re.compile(r"\b(only|instead of|rather than|replace|swap)\b"),
    re.compile(r"\b(more|another|extra)\b"),
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

    # 1. Tier 2 activity additions — fast path for common hints
    detected_t2 = {kw for kw in TIER2_COMMON_HINTS if re.search(rf"\b{kw}\b", text_lower)}
    if detected_t2:
        changes["add_categories"] = detected_t2

    # 2. Activity removals — accept any category string (could be novel Tier 2)
    for m in REMOVAL_PATTERN.finditer(text_lower):
        target = m.group(1).strip()
        if target:
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
    all_known = TIER2_COMMON_HINTS | TIER1_SPECIALIST_NAMES
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
        "think",
        "thinking",
        "start",
        "starting",
    }
    remaining = set(re.findall(r"\b[a-z]{3,}\b", text_lower))
    remaining -= all_known
    remaining -= stop_words
    remaining -= set(SKILL_LEVEL_MAP.keys())

    # Fuzzy-match before declaring unresolved.
    # Guardrails: only allow fuzzy category adds when the user shows explicit
    # category mutation intent and the message is not date-centric.
    has_category_mutation_intent = any(p.search(text_lower) for p in _CATEGORY_INTENT_PATTERNS)
    has_date_like_content = any(re.search(p, text_lower) for p in DATE_INDICATORS)
    allow_fuzzy_category_adds = has_category_mutation_intent and not has_date_like_content

    fuzzy_vocab = _get_fuzzy_vocab(state)
    still_unresolved = set()
    for token in remaining:
        match = _fuzzy_resolve_token(token, fuzzy_vocab) if allow_fuzzy_category_adds else None
        if match:
            logger.info(f"[CATEGORY_SYNC] Fuzzy: '{token}' → '{match}'")
            changes.setdefault("add_categories", set()).add(match)
        else:
            still_unresolved.add(token)

    if still_unresolved and len(text_lower.split()) <= 5:
        changes["unresolved_tokens"] = still_unresolved

    return changes if changes else None


# get_new_specialists_from_text now imported from router_utils.py


# ============================================================================
# Post-LLM Modification Collection (Phase 2)
# Reads from RouterOutput dict instead of re-parsing user text with regex.
# ============================================================================


def _collect_modifications_from_extraction(
    router_output: dict,
    state: "GraphState",
    pre_populate_categories: Optional[set] = None,
    allow_category_modifications: bool = True,
) -> Optional[dict]:
    """
    Read LLM extraction output and collect trip modifications.

    Returns dict matching _detect_actionable_input() output shape
    (add_categories, remove_categories, skill_level, reset_budget, reset_hotel)
    or None if no modifications detected.

    Args:
        pre_populate_categories: Snapshot of categories from BEFORE
            _populate_trip_plan_from_router_output ran. Required for the
            post-plan path where _populate already wrote categories to state.
            If None, reads current categories from state (pre-plan path).
    """
    changes: dict = {}

    # 1. Activity additions (Tier 1 + Tier 2) — detect NEW categories only
    # Tier 1 hints gated by registry; Tier 2 is open-ended
    if pre_populate_categories is not None:
        existing = pre_populate_categories
    else:
        existing = set(_get_current_categories(state))

    if allow_category_modifications:
        cats = router_output.get("activity_categories", [])
        hints = router_output.get("specialist_hints", [])
        new_cats = {c.lower().strip() for c in cats if c.strip()}
        new_hints = {
            h.lower().strip() for h in hints if h.lower().strip() in TIER1_SPECIALIST_NAMES
        }
        requested = new_cats | new_hints
        additions = requested - existing
        already_active = requested & existing
        if additions:
            changes["add_categories"] = additions
        if already_active:
            state.metadata["requested_already_active"] = sorted(already_active)

    # 2. Activity removals
    if allow_category_modifications:
        removals_raw = router_output.get("removal_targets", [])
        if removals_raw:
            removals = {r.lower().strip() for r in removals_raw if r.strip()}
            if removals:
                changes["remove_categories"] = removals

    # 3. Skill level
    skill = router_output.get("skill_level")
    if skill and skill.lower() in ("beginner", "intermediate", "advanced"):
        changes["skill_level"] = skill.lower()

    # 4. Setting resets
    if router_output.get("reset_budget"):
        changes["reset_budget"] = True
    if router_output.get("reset_hotel"):
        changes["reset_hotel"] = True

    return changes if changes else None


def has_explicit_category_intent(
    user_text: str,
    router_output: Optional[dict] = None,
) -> bool:
    """Return True when this turn explicitly intends to mutate activity categories."""
    text = (user_text or "").lower().strip()
    if not text:
        return False

    # Check Tier 1 by registry, Tier 2 by common hints (fast path)
    all_hints = TIER2_COMMON_HINTS | TIER1_SPECIALIST_NAMES
    if any(re.search(rf"\b{re.escape(category)}\b", text) for category in all_hints):
        return True

    # LLM-extracted removals are authoritative category mutations.
    # Example: "remove all cultural" may not include a known hint token in text.
    if router_output:
        removals = {
            r.lower().strip()
            for r in (router_output.get("removal_targets") or [])
            if r and r.strip()
        }
        if removals:
            return True

    # LLM extraction may have found novel Tier 2 categories not in hints
    extracted: set[str] = set()
    if router_output:
        extracted = {
            c.lower() for c in (router_output.get("activity_categories") or []) if c and c.strip()
        } | {
            s.lower()
            for s in (router_output.get("specialist_hints") or [])
            if s and s.lower().strip() in TIER1_SPECIALIST_NAMES
        }

    if not extracted:
        return False

    if "?" not in text and len(text.split()) <= 3:
        return True

    return any(pattern.search(text) for pattern in _CATEGORY_INTENT_PATTERNS)


def detect_category_merge_mode(user_text: str, router_output: Optional[dict] = None) -> str:
    """Return category merge mode for this turn: 'add' (default) or 'replace'."""
    text = (user_text or "").lower()
    if not has_explicit_category_intent(user_text, router_output):
        return "add"
    for pattern in _CATEGORY_REPLACE_PATTERNS:
        if pattern.search(text):
            return "replace"
    return "add"


def _get_current_categories(state: "GraphState") -> list:
    """Get current activity categories from state."""
    trip_inputs = state.metadata.get("trip_inputs", {})
    activity_settings = trip_inputs.get("activity_settings", {})
    return activity_settings.get("categories", [])


def _collect_settings_from_extraction(router_output: dict) -> Optional[dict]:
    """
    Read settings changes from LLM RouterOutput dict.

    Returns dict matching _detect_settings_from_message() output shape
    (budget, adults, children, hotel_settings, flight_settings)
    or None if no settings detected.
    """
    detected: dict = {}

    # Budget (new value, not reset — reset is handled by _collect_modifications)
    budget = router_output.get("budget")
    if budget is not None and not router_output.get("reset_budget"):
        detected["budget"] = int(budget)

    # Travelers
    if router_output.get("adults") is not None:
        detected["adults"] = router_output["adults"]
    if router_output.get("children") is not None:
        detected["children"] = router_output["children"]

    # Hotel settings
    hotel: dict = {}
    if router_output.get("hotel_min_stars") is not None:
        hotel["min_stars"] = router_output["hotel_min_stars"]
    if router_output.get("hotel_style"):
        hotel["style"] = router_output["hotel_style"]
    if router_output.get("hotel_amenities"):
        hotel["amenities"] = router_output["hotel_amenities"]
    if router_output.get("hotel_location"):
        hotel["location"] = router_output["hotel_location"]
    if hotel:
        detected["hotel_settings"] = hotel

    # Flight settings
    flight: dict = {}
    if router_output.get("flight_direct_only") is not None:
        flight["direct_only"] = router_output["flight_direct_only"]
    if router_output.get("flight_cabin_class"):
        flight["cabin_class"] = router_output["flight_cabin_class"]
    if flight:
        detected["flight_settings"] = flight

    return detected if detected else None


# ============================================================================
# Planning Intent Detection
# ============================================================================


def detect_planning_intent(text: str, _state: "GraphState") -> str:
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
# Tier 2 Experience Prefetch
# ============================================================================


def _estimate_prefetch_tiles_per_category(state: "GraphState", categories: set[str]) -> int:
    """Estimate tiles/category so router prefetch cache keys match logistics generation."""
    plan = state.trip_plan
    if not plan.start_date or not plan.end_date or not categories:
        return 2

    try:
        start = datetime.strptime(plan.start_date, "%Y-%m-%d")
        end = datetime.strptime(plan.end_date, "%Y-%m-%d")
        trip_days = (end - start).days + 1
    except ValueError:
        return 2

    specialist_days = 0
    for section in state.metadata.get("strategy_sections", []):
        if section.get("specialist_type", "") in ("local_expert", "general"):
            continue
        specialist_days += len(section.get("content_added", []))

    free_days = max(0, trip_days - specialist_days - 2)
    total_placeable = free_days + specialist_days
    per_category = total_placeable // len(categories)
    return max(2, min(4, per_category))


def _tier2_prefetch_key(
    destination: str,
    month: str,
    categories: set[str],
    tiles_per_category: int,
) -> str:
    normalized_destination = (destination or "").strip().lower()
    normalized_month = (month or "").strip().lower()
    normalized_categories = "|".join(sorted(c.strip().lower() for c in categories if c.strip()))
    return (
        f"tier2:{normalized_destination}:{normalized_month}:"
        f"{normalized_categories}:n{tiles_per_category}"
    )


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
    tiles_per_category = _estimate_prefetch_tiles_per_category(state, categories)
    prefetch_key = _tier2_prefetch_key(
        plan.destination or "",
        month,
        categories,
        tiles_per_category,
    )

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
        import logging

        logger = logging.getLogger(__name__)

        if t.cancelled():
            logger.info("[PREFETCH] Task cancelled before completion")
            return

        try:
            exc = t.exception()
        except asyncio.CancelledError:
            logger.info("[PREFETCH] Task cancelled while collecting result")
            return

        if exc is not None:
            logger.error(
                "[PREFETCH] Task failed with exception: %s",
                exc,
                exc_info=exc,
            )

    task.add_done_callback(_log_task_exception)

    state.metadata["tier2_prefetch_task"] = task
    state.metadata["tier2_prefetch_categories"] = list(categories)
    state.metadata["tier2_prefetch_tiles_per_category"] = tiles_per_category
    state.metadata["tier2_prefetch_started_at"] = time.time()
    state.metadata["tier2_prefetch_destination"] = plan.destination
    state.metadata["tier2_prefetch_month"] = month
    state.metadata["tier2_prefetch_key"] = prefetch_key
    state.metadata["tier2_prefetch_intent"] = "activity"
