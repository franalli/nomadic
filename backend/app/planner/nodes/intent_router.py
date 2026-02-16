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
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from app.config import settings
from app.planner.llm_factory import get_llm_by_model
from app.planner.nodes.input_gates import GateRegistry
from app.planner.nodes.router_category_sync import (
    DATE_INDICATORS,
    _collect_modifications_from_extraction,
    _collect_settings_from_extraction,
    _detect_actionable_input,
    _prefetch_tier2_experiences,
    detect_category_merge_mode,
    detect_planning_intent,
    has_explicit_category_intent,
)
from app.planner.nodes.router_extraction import (
    CLASSIFICATION_PROMPT,
    IntentClassification,
    _classify_and_extract_with_llm,
    _get_router_llm,
    _populate_trip_plan_from_router_output,
)
from app.planner.nodes.router_utils import (
    _check_exact_match_greeting,
    _detect_origin_from_message,
    _extract_destination_context,
    get_new_specialists_from_text,
)
from app.planner.specialist_registry import (
    ALL_CATEGORY_TO_SPECIALIST,
    ALL_SPECIALIST_KEYWORDS,
    TIER1_SPECIALIST_NAMES,
    TIER2_ACTIVITY_KEYWORDS,
)
from app.planner.state import GraphState, TripPlan
from app.planner.state.typed_meta import get_trip_settings

logger = logging.getLogger(__name__)

_gate_registry = GateRegistry()

# Tier 2 activities — not in ALL_SPECIALIST_KEYWORDS (Tier 1 only).
# "sailing" included: Tier 1 in registry but KNOWN_CATEGORIES lists it,
# and logistics treats it as Tier 2 for tile generation.
# Now imported from router_category_sync.py


# Derived constant for suggestion prompts
_SPECIALIST_NAMES_CSV = ", ".join(sorted(TIER1_SPECIALIST_NAMES))

# =============================================================================
# Constraint Hash Utilities (for detecting input changes)
# =============================================================================


def _compute_constraint_hash(trip_plan: TripPlan, settings: Any) -> str:
    """
    Hash inputs that affect SPECIALIST output (not just pricing/filtering).

    Includes:
    - destination (different locations = different recommendations)
    - start_date month only (seasonal conditions)
    - activities (different topics = different specialists)
    - origin (ONLY if flights enabled - affects no-fly constraints)

    Excludes:
    - adults/children (only affects capacity/pricing)
    - budget (only affects filtering)
    - full dates (only month matters for seasonal)

    Args:
        trip_plan: The TripPlan instance.
        settings: A TripSettings instance (typed).
    """
    # Sort categories to ensure ["a", "b"] == ["b", "a"]
    activity_cats = sorted(settings.activity_settings.categories)

    # Check if flights are enabled
    flights_enabled = settings.booking_types.flights != "off"

    hash_payload = {
        "dest": (trip_plan.destination or "").lower().strip(),
        "month": (trip_plan.start_date or "")[:7],  # YYYY-MM only (seasonal)
        "activities": activity_cats,
        "skill": settings.activity_settings.skill_level,
    }

    # Only include origin if flights enabled (affects diving no-fly constraints)
    if flights_enabled and trip_plan.origin:
        hash_payload["origin"] = trip_plan.origin.lower().strip()

    hash_str = json.dumps(hash_payload, sort_keys=True)
    computed_hash = hashlib.md5(hash_str.encode()).hexdigest()

    logger.debug(f"[REACTIVITY] Hash components: {hash_payload}")
    logger.debug(f"[REACTIVITY] Computed hash: {computed_hash[:8]}")

    return computed_hash


def _clear_stale_specialist_content(state: GraphState) -> None:
    """
    Wipe old specialist data so we don't merge 'Aspen Skiing' into 'Hawaii'.

    Clears: itinerary_blocks, constraints, tiles, strategy_sections, infeasibility flags
    Preserves: trip_plan core fields (destination, dates, travelers, budget)
    """
    state.trip_plan.itinerary_blocks = []
    state.trip_plan.constraints = []
    state.tiles = {}  # Force fresh fetch

    # Clear UI sections but keep structure ready
    if "strategy_sections" in state.metadata:
        state.metadata["strategy_sections"] = []

    # Clear infeasibility flags so specialists get fresh evaluation
    state.metadata.pop("specialist_infeasible", None)
    state.metadata.pop("specialist_infeasible_reason", None)
    state.metadata.pop("specialist_alternative", None)

    logger.info("[Router] Cleared stale specialist content for constraint change")


# =============================================================================
# Classification Schema — Extracted to router_extraction.py
# =============================================================================
# IntentClassification and RouterOutput schemas now in router_extraction.py


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
    "stay|hotel|neighborhood|area|lodging|resort|hostel|airbnb|accommodation": (
        "accommodation",
        "neighborhoods",
    ),
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


# Question type → Local Expert knowledge section (structural, not parsing)
QUESTION_TYPE_TO_SECTION = {
    "weather": "seasonality",
    "safety": "safety_health",
    "costs": "money_costs",
    "visa": "visa_entry",
    "transport": "transportation",
    "cultural": "cultural_norms",
    "activities": "things_to_do",
    "accommodation": "neighborhoods",
    "scams": "scams_traps",
    "packing": "packing",
    "connectivity": "connectivity",
    "money": "money_costs",
    "couples": "destination_overview",
    "family": "destination_overview",
}


def _is_plan_active(state: "GraphState") -> bool:
    """Check if an active plan exists (niche specialists have run)."""
    # TODO: evaluate prefix match (pvs.startswith("S2_")) when substates stabilize.
    # Blocked substates (S2_BLOCKED, S3_EDITING, S3_PARTIAL_CONFLICT) should NOT
    # trigger post-plan LLM extraction — explicit set is safer for now.
    pvs = state.metadata.get("plan_view_state", "")
    if pvs in ("S2_STRATEGY_READY", "S3_ITINERARY_READY"):
        return True
    sections = state.metadata.get("strategy_sections", [])
    return any(s.get("specialist_type") not in ("general", "local_expert") for s in sections)


def _classify_question(
    user_text: str, state: "GraphState", plan_is_active: bool
) -> Tuple[str, str]:
    """LLM classification post-plan, keyword fallback pre-plan."""
    ro = state.metadata.get("router_output")
    if plan_is_active and ro and ro.get("question_type"):
        qtype = ro["question_type"]
        return qtype, QUESTION_TYPE_TO_SECTION.get(qtype, "destination_overview")
    return classify_question_type(user_text)


# =============================================================================
# Exploration Mode: Planning Readiness Detection
# =============================================================================

# PLANNING_READINESS_SIGNALS now imported from router_category_sync.py


# Split into separate constants for clarity and maintainability
# DATE_INDICATORS now imported from router_category_sync.py

# Origin specification patterns - detect "from [city]" as departure city
# These patterns identify when user is specifying origin, NOT a destination to explore
# ORIGIN_PATTERNS now imported from router_category_sync.py

# SETTINGS PATTERNS - Detect trip setting changes from chat messages
# These trigger LogisticsNode to refetch tiles with updated parameters
# =============================================================================

# Budget patterns - extract numeric budget values
BUDGET_PATTERNS = [
    r"(?:budget|bugdet|spend|spending)\s*(?:is|of|around|about|to|at)?\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?",
    r"\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?\s*(?:budget|bugdet)",
    # Pattern: "have/got $X to spend" or "have/got $X for the trip"
    r"(?:have|got)\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?"
    r"\s*(?:to spend|for (?:the |this )?trip)?",
    r"(?:up to|max(?:imum)?|around|about)\s*\$?([\d,]+(?:\.\d{2})?)\s*(?:k|K|thousand)?",
]

# Traveler patterns - extract number of adults/children
# IMPORTANT: Order matters! Most specific patterns first.
TRAVELER_PATTERNS = [
    # Combined adults AND children - MUST BE FIRST to capture "4 adults 2 kids"
    r"(\d+)\s*(?:adult|person)s?\s*(?:and|,|&)\s*(\d+)\s*(?:child|kid|children|minor)s?",
    # Children only (e.g., "2 children", "3 kids")
    r"(\d+)\s*(?:child|kid|children|minor)s?",
    # Group/party size (e.g., "party of 4")
    r"(?:party of|group of|traveling with)\s*(\d+)",
    # Adults only - AFTER combined pattern (e.g., "2 adults", "4 people")
    r"(\d+)\s*(?:adult|person|people|traveler)s?(?:\s+of us)?",
    # Qualitative patterns - LAST (e.g., "family of 4", "couple", "solo")
    r"(?:family of|couple|solo|alone)",
]

# Hotel preference patterns
HOTEL_PATTERNS = [
    r"(\d)\s*[-]?\s*star\s*(?:hotel|resort|accommodation)?",
    r"(?:luxury|boutique|budget|mid-range|upscale)\s*(?:hotel|resort|stay|accommodation)",
    r"(?:beachfront|oceanview|city center|downtown|airport)\s*(?:hotel|resort|stay|accommodation)",
    r"(?:with|want|need)\s*(?:pool|spa|gym|breakfast|parking|wifi)",
]

# Flight preference patterns
FLIGHT_PATTERNS = [
    r"(?:direct|non-?stop|connecting)\s*(?:flight|flights)?",
    r"(?:business|first|economy|premium)\s*(?:class)?",
    r"(?:morning|afternoon|evening|red-?eye|overnight)\s*(?:flight|departure)?",
    r"(?:flexible|fixed)\s*(?:dates|schedule)?",
]

# =============================================================================
# ACTIONABLE INPUT PATTERNS — Catch Tier 2 activities, skill levels, removals,
# and setting resets that regex settings detection (above) doesn't handle.
# Runs before exploration short-circuit to prevent swallowing valid input.
# =============================================================================

# SKILL_LEVEL_MAP now imported from router_category_sync.py


# REMOVAL_PATTERN, RESET_BUDGET_PATTERN, RESET_HOTEL_PATTERN
# are now imported from router_category_sync.py


# =============================================================================
# Suggestion Pool (registry-driven chip generation)
# =============================================================================

# Month names for contextual date suggestions
_MONTHS = {
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

# Subset of QUESTION_TYPE_MAPPING that makes good suggestion chips.
# Template keywords MUST match QUESTION_TYPE_MAPPING patterns for routability.
SUGGESTABLE_QUESTION_TYPES = {
    "weather": "What's the weather like in {destination}?",
    "safety": "Is {destination} safe to visit?",
    "costs": "How expensive is {destination}?",
    "accommodation": "Where should I stay in {destination}?",
    "packing": "What should I pack for {destination}?",
    "visa": "Do I need a visa for {destination}?",
    "transport": "How do I get around {destination}?",
    "activities": "What are must-do activities in {destination}?",
}


class SuggestionPool:
    """
    Declarative suggestion pool. Each entry specifies:
    - template: text sent to backend (can use {destination}/{month} placeholders)
    - source: which router capability handles it
    - condition: when this suggestion is relevant (function of state)
    - priority: lower = higher priority (0 = critical, 10 = nice-to-have)
    - category: for deduplication (max 1 per category in final output)
    """

    @staticmethod
    def get_pool() -> list[dict]:
        return [
            # ── Missing destination (highest priority) ──
            {
                "template": "I want a beach vacation",
                "source": "planning_signal",
                "condition": lambda s: not s.trip_plan.destination,
                "priority": 0,
                "category": "destination_choice",
            },
            {
                "template": "I want a mountain adventure",
                "source": "planning_signal",
                "condition": lambda s: not s.trip_plan.destination,
                "priority": 0,
                "category": "destination_choice",
            },
            {
                "template": "I want a city break",
                "source": "planning_signal",
                "condition": lambda s: not s.trip_plan.destination,
                "priority": 0,
                "category": "destination_choice",
            },
            # ── Contextual date prompts (month detected) ──
            {
                "template": "{month} 1-8",
                "source": "date_extraction",
                "condition": lambda s: (
                    s.trip_plan.destination
                    and not s.trip_plan.start_date
                    and s.metadata.get("detected_month")
                ),
                "priority": 0,
                "category": "date_contextual",
            },
            {
                "template": "{month} 10-17",
                "source": "date_extraction",
                "condition": lambda s: (
                    s.trip_plan.destination
                    and not s.trip_plan.start_date
                    and s.metadata.get("detected_month")
                ),
                "priority": 0,
                "category": "date_contextual",
            },
            {
                "template": "I'm flexible on dates",
                "source": "date_extraction",
                "condition": lambda s: (
                    s.trip_plan.destination
                    and not s.trip_plan.start_date
                    and s.metadata.get("detected_month")
                ),
                "priority": 0,
                "category": "date_contextual",
            },
            # ── Generic date prompts: generated dynamically by _build_date_suggestions() ──
        ]


def _build_specialist_suggestions(state: "GraphState") -> list[dict]:
    """
    Generate cross-sell suggestions for specialists the user selected in the
    activity pill but that haven't been executed yet.
    Only pill-selected specialists appear — no blind cross-sell from the full registry.
    """
    executed = set(state.metadata.get("executed_strategy_topics", []))
    dest = state.trip_plan.destination

    if not dest or not state.trip_plan.start_date:
        return []

    # Only suggest specialists the user explicitly chose in the activity pill
    selected_categories = get_trip_settings(state).activity_settings.categories

    pending = []
    for category in selected_categories:
        specialist_id = ALL_CATEGORY_TO_SPECIALIST.get(category.lower())
        if specialist_id and specialist_id not in executed:
            pending.append(specialist_id)

    suggestions = []
    for specialist_id in pending:
        suggestions.append(
            {
                "template": f"I also want to go {specialist_id} in {{destination}}",
                "source": "specialist_pattern",
                "condition": lambda s, _id=specialist_id: _id
                not in set(s.metadata.get("executed_strategy_topics", [])),
                "priority": 3,
                "category": f"specialist_{specialist_id}",
            }
        )

    return suggestions


def _build_date_suggestions(state: "GraphState") -> list[dict]:
    """
    Generate concrete date range chips when destination is set but dates are missing.
    Produces parseable date text (e.g., "Feb 14-16") that the router's
    opportunistic LLM extraction can reliably convert to start_date/end_date.
    """
    if not state.trip_plan.destination or state.trip_plan.start_date:
        return []
    if state.metadata.get("detected_month"):
        return []  # Contextual date chips handle this case

    from datetime import date, timedelta

    today = date.today()

    # Next weekend (Fri-Sun)
    days_until_fri = (4 - today.weekday()) % 7 or 7
    next_fri = today + timedelta(days=days_until_fri)
    next_sun = next_fri + timedelta(days=2)

    # Week-long trip starting 1st of next month
    next_month_1st = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    week_end = next_month_1st + timedelta(days=6)

    # Mid-month week trip
    mid_month = next_month_1st.replace(day=15)
    mid_end = mid_month + timedelta(days=7)

    chips = [
        f"{next_fri.strftime('%b %d')}-{next_sun.strftime('%d')}",
        f"{next_month_1st.strftime('%b %d')}-{week_end.strftime('%d')}",
        f"{mid_month.strftime('%b %d')}-{mid_end.strftime('%d')}",
    ]

    return [
        {
            "template": chip,
            "source": "date_extraction",
            "condition": lambda s: (s.trip_plan.destination and not s.trip_plan.start_date),
            "priority": 0,
            "category": "date_prompt",
        }
        for chip in chips
    ]


def _build_question_suggestions(state: "GraphState") -> list[dict]:
    """
    Generate local expert question suggestions.
    Only suggests questions whose keywords exist in QUESTION_TYPE_MAPPING.
    Excludes question types already shown in previous turns (rotation).
    """
    if not state.trip_plan.destination:
        return []

    already_suggested = set(state.metadata.get("suggested_question_types", []))

    suggestions = []
    for qtype, template in SUGGESTABLE_QUESTION_TYPES.items():
        if qtype in already_suggested:
            continue

        # Verify this question type exists in the router
        type_exists = any(qtype == qt for _, (qt, _) in QUESTION_TYPE_MAPPING.items())
        if not type_exists:
            continue

        suggestions.append(
            {
                "template": template,
                "source": "question_type",
                "condition": lambda s: bool(s.trip_plan.destination),
                "priority": 6,
                "category": f"question_{qtype}",
            }
        )

    return suggestions


def _build_plan_progression_suggestions(state: "GraphState") -> list[dict]:
    """
    Generate plan-progression suggestions at S2+ (active plan with dates).
    These nudge the user toward refining preferences instead of exploring.
    Priority 4: above exploration questions (6), below specialists (3).
    """
    if not _is_plan_active(state):
        return []

    dest = state.trip_plan.destination
    if not dest or not state.trip_plan.start_date:
        return []

    _settings = get_trip_settings(state)

    suggestions = []

    # Hotel preference (if min_stars not set)
    if not _settings.hotel_settings.min_stars:
        suggestions.append(
            {
                "template": "5-star hotels only",
                "source": "settings_detection",
                "condition": lambda s: bool(s.trip_plan.destination and s.trip_plan.start_date),
                "priority": 4,
                "category": "plan_hotel_pref",
            }
        )

    # Flight preference (if direct_only not set AND origin exists AND flights enabled)
    if (
        not _settings.flight_settings.direct_only
        and state.trip_plan.origin
        and _settings.booking_types.flights != "off"
    ):
        suggestions.append(
            {
                "template": "Direct flights only",
                "source": "settings_detection",
                "condition": lambda s: bool(s.trip_plan.destination and s.trip_plan.start_date),
                "priority": 4,
                "category": "plan_flight_pref",
            }
        )

    # Activity exploration (if no categories selected and destination has activities)
    if not _settings.activity_settings.categories:
        suggestions.append(
            {
                "template": "What are must-do activities in {destination}?",
                "source": "question_type",
                "condition": lambda s: bool(s.trip_plan.destination),
                "priority": 5,
                "category": "plan_activities",
            }
        )

    return suggestions


def _detect_settings_from_message(user_text: str, state: "GraphState") -> Optional[Dict[str, Any]]:
    """
    Detect if user message is specifying trip settings (budget, travelers, hotel/flight prefs).
    Returns dict of detected settings if found, None otherwise.

    Only triggers for active plans (has destination) to avoid false positives during exploration.
    """
    if not state.trip_plan.destination:
        return None

    text = user_text.strip().lower()
    detected = {}

    # Budget detection
    for pattern in BUDGET_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                amount = float(amount_str)
                # Handle "k" suffix (5k = 5000)
                if "k" in text.lower() or "thousand" in text.lower():
                    # Check if the k/thousand is near the number
                    if re.search(rf"{amount_str}\s*(?:k|K|thousand)", text, re.IGNORECASE):
                        amount *= 1000
                detected["budget"] = int(amount)
            except ValueError:
                pass
            break

    # Traveler detection
    for pattern_idx, pattern in enumerate(TRAVELER_PATTERNS):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if "solo" in text or "alone" in text:
                detected["adults"] = 1
                detected["children"] = 0
            elif "couple" in text:
                detected["adults"] = 2
                detected["children"] = 0
            elif "family" in text:
                # Default family size if not specified
                fam_match = re.search(r"family of (\d+)", text)
                if fam_match:
                    total = int(fam_match.group(1))
                    detected["adults"] = min(2, total)
                    detected["children"] = max(0, total - 2)
                else:
                    detected["adults"] = 2
                    detected["children"] = 2
            else:
                # Numeric extraction - handle based on pattern index
                groups = match.groups()
                if pattern_idx == 0:  # Combined adults AND children pattern
                    if groups[0]:
                        detected["adults"] = int(groups[0])
                    if len(groups) > 1 and groups[1]:
                        detected["children"] = int(groups[1])
                elif pattern_idx == 1:  # Children-only pattern
                    if groups[0]:
                        detected["children"] = int(groups[0])
                elif pattern_idx == 2:  # Group/party size pattern
                    if groups[0]:
                        detected["adults"] = int(groups[0])  # Assume all adults for party
                elif pattern_idx == 3:  # Adults-only pattern
                    if groups[0]:
                        detected["adults"] = int(groups[0])
                # pattern_idx == 4 is qualitative with no numeric groups
            break

    # Hotel preference detection. Guard against budget-only text accidentally
    # mutating hotel settings (e.g., "increase budget to $2800").
    hotel_context = bool(
        re.search(
            r"\b(hotel|hotels|resort|resorts|stay|stays|accommodation|accommodations)\b",
            text,
            re.IGNORECASE,
        )
    )
    star_match = re.search(r"(\d)\s*[-]?\s*star", text, re.IGNORECASE)
    hotel_pattern_match = any(re.search(pattern, text, re.IGNORECASE) for pattern in HOTEL_PATTERNS)

    hotel_settings = {}
    if hotel_pattern_match and (hotel_context or star_match):
        # Star rating
        if star_match:
            hotel_settings["min_stars"] = int(star_match.group(1))

        # Hotel type keywords
        if "luxury" in text or "upscale" in text:
            hotel_settings["min_stars"] = max(hotel_settings.get("min_stars", 0), 4)
        elif "boutique" in text:
            hotel_settings["style"] = "boutique"
        elif "budget" in text and hotel_context:
            hotel_settings["min_stars"] = 0
            hotel_settings["budget_friendly"] = True

        # Amenities
        amenities = []
        if "pool" in text:
            amenities.append("pool")
        if "spa" in text:
            amenities.append("spa")
        if "gym" in text or "fitness" in text:
            amenities.append("gym")
        if "breakfast" in text:
            amenities.append("breakfast")
        if amenities:
            hotel_settings["amenities"] = amenities

        # Location preferences
        if "beachfront" in text or "oceanview" in text or "ocean view" in text:
            hotel_settings["location"] = "beachfront"
        elif "city center" in text or "downtown" in text:
            hotel_settings["location"] = "city_center"

    if hotel_settings:
        detected["hotel_settings"] = hotel_settings

    # Flight preference detection
    flight_settings = {}
    for pattern in FLIGHT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            # Direct/non-stop preference
            if "direct" in text or "non-stop" in text or "nonstop" in text:
                flight_settings["direct_only"] = True

            # Cabin class
            if "business" in text:
                flight_settings["cabin_class"] = "business"
            elif "first" in text and "class" in text:
                flight_settings["cabin_class"] = "first"
            elif "premium" in text:
                flight_settings["cabin_class"] = "premium_economy"
            elif "economy" in text:
                flight_settings["cabin_class"] = "economy"

            # Time preferences
            if "morning" in text:
                flight_settings["departure_time"] = "morning"
            elif "evening" in text or "red-eye" in text or "overnight" in text:
                flight_settings["departure_time"] = "evening"

    if flight_settings:
        detected["flight_settings"] = flight_settings

    return detected if detected else None

    # _detect_actionable_input now imported from router_category_sync.py

    # get_new_specialists_from_text now imported from router_utils.py

    # detect_planning_intent now imported from router_category_sync.py

    # _extract_destination_context now imported from router_utils.py
    # _check_exact_match_greeting now imported from router_utils.py
    # _detect_origin_from_message now imported from router_utils.py


def _message_has_hotel_signal(user_text: str) -> bool:
    """Return True when the message explicitly talks about hotel preferences."""
    text = (user_text or "").lower()
    return bool(
        re.search(r"(\d)\s*[-]?\s*star", text, re.IGNORECASE)
        or re.search(
            r"\b(hotel|hotels|resort|resorts|stay|stays|accommodation|accommodations)\b",
            text,
            re.IGNORECASE,
        )
    )


def _sanitize_settings_from_message(
    detected_settings: Optional[Dict[str, Any]], user_text: str
) -> Optional[Dict[str, Any]]:
    """
    Guardrail for LLM extraction drift.

    Budget-only turns can occasionally return accidental hotel settings; drop
    them unless the user message actually includes hotel-specific language.
    """
    if not detected_settings:
        return detected_settings

    sanitized = dict(detected_settings)
    if "hotel_settings" in sanitized and not _message_has_hotel_signal(user_text):
        sanitized.pop("hotel_settings", None)

    return sanitized or None


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

# Re-export for backward compat (logistics_node.py, synthesizer.py import these)
TIER1_SPECIALISTS = TIER1_SPECIALIST_NAMES
SPECIALIST_KEYWORDS = ALL_SPECIALIST_KEYWORDS


def _detect_specialists_from_activity_settings(state: GraphState) -> List[str]:
    """
    Detect specialists from activity_settings.categories (UI pill selection).

    Returns list of all matching specialist types (can be multiple).
    """
    # Get activity categories from typed settings
    categories = get_trip_settings(state).activity_settings.categories

    if not categories:
        return []

    # Check each category for a specialist match
    detected: List[str] = []
    for category in categories:
        category_lower = category.lower().strip()
        if category_lower in ALL_CATEGORY_TO_SPECIALIST:
            specialist = ALL_CATEGORY_TO_SPECIALIST[category_lower]
            if specialist not in detected:
                detected.append(specialist)
                logger.debug(
                    f"Detected specialist '{specialist}' from activity category '{category}'"
                )

    return detected


# =============================================================================
# LLM Classification — Extracted to router_extraction.py
# =============================================================================
# CLASSIFICATION_PROMPT and ROUTER_EXTRACTION_PROMPT now in router_extraction.py


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
        logger.error(f"[ROUTER] Intent classification FAILED: {e}")
        state.metadata["router_extraction_failed"] = True
        raise


# =============================================================================
# Exploration Mode: Comprehensive Answer Generation
# =============================================================================


def _format_section_answer(qtype: str, _section: str, knowledge, destination: str) -> Optional[str]:
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
            reqs = ""
            if ve.key_requirements:
                reqs = "\n".join(f"  - {r}" for r in ve.key_requirements)
                reqs = f"\n- Key requirements:\n{reqs}\n"
            return (
                f"**Visa info for {destination}:**\n\n"
                f"- Visa on arrival: {visa_on_arrival}\n"
                f"- Max stay: {ve.max_stay_days or 'Varies'} days\n"
                f"- Passport validity: {ve.passport_validity_months or 6} months required\n"
                f"- Visa-free for: {visa_free}"
                f"{reqs}\n"
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

    llm = get_llm_by_model(
        settings.router_model,
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
    """Get contextual suggestion chips for exploration mode.

    DEPRECATED: replaced by SuggestionPool. Kept for router backward compat.
    """
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
    DEPRECATED: replaced by SuggestionPool + detected_month metadata.
    Kept for router backward compat.

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


# =============================================================================
# State-Mutation Helpers (used by both pre-plan regex and post-plan LLM paths)
# =============================================================================


async def _apply_origin_to_state(state: GraphState, detected_origin: str, _clog) -> bool:
    """
    Apply detected origin to state: sync trip_inputs, enable flights,
    resolve IATA, set routing flags, build response message.

    Returns True if caller should ``return state`` (destination exists),
    False if fall-through needed (no destination yet).
    """
    from app.debug_utils import _debug_node_end, log

    log(
        "ROUTER",
        f"[ORIGIN] Detected origin: {detected_origin} "
        f"(destination: {state.trip_plan.destination or 'not set'})",
    )

    # Set origin on trip_plan
    state.trip_plan.origin = detected_origin

    # Sync to metadata.trip_inputs for LogisticsNode
    trip_inputs = state.metadata.get("trip_inputs", {})
    trip_inputs["origin"] = detected_origin
    state.metadata["trip_inputs"] = trip_inputs

    # Mark for frontend
    state.metadata["origin_just_set"] = True

    # Enable flights for origin-based search unless the user explicitly set
    # flights on/off in prior settings updates.
    booking_types = trip_inputs.setdefault("booking_types", {})
    current_toggle = booking_types.get("flights")
    explicit_toggle = state.metadata.get("explicit_flights_toggle")
    if explicit_toggle in {"on", "off"}:
        target_toggle = explicit_toggle
    elif current_toggle == "on":
        target_toggle = "on"
    elif current_toggle == "off":
        # Default "off" auto-upgrades to "suggested" when origin is set.
        target_toggle = "suggested"
    else:
        target_toggle = current_toggle or "suggested"

    if "extracted_settings" not in state.metadata:
        state.metadata["extracted_settings"] = {}
    if target_toggle != "off":
        state.metadata["extracted_settings"]["flights_toggle"] = target_toggle

    booking_types["flights"] = target_toggle
    state.metadata["trip_inputs"] = trip_inputs
    state.metadata.pop("trip_settings", None)
    state.metadata["trip_settings"] = get_trip_settings(state).model_dump()

    # Resolve IATA codes before fast-path to logistics
    if state.trip_plan.destination:
        from app.planner.services.iata_resolver import resolve_iata_codes

        await resolve_iata_codes(detected_origin, state.trip_plan.destination, state)
        trip_inputs["origin_iata"] = state.trip_plan.origin_iata
        trip_inputs["destination_iata"] = state.trip_plan.destination_iata
        state.metadata["trip_inputs"] = trip_inputs

    if state.trip_plan.destination:
        state.metadata["origin_only_logistics"] = True
        state.metadata["skip_architect"] = True
        state.metadata["skip_specialists"] = True

        dest = state.trip_plan.destination
        state.last_summary = (
            f"Got it - departing from **{detected_origin}**. "
            f"Searching for flights from {detected_origin} to {dest}..."
        )
        state.suggested_replies = [
            "Direct flights only",
            "Flexible dates",
            "Show me hotels too",
        ]

        _debug_node_end("router", "🧭", intent="ORIGIN_TO_LOGISTICS", origin=detected_origin)
        return True  # Caller should return state
    else:
        state.last_summary = (
            f"Got it - I've set your departure city to **{detected_origin}**. "
            f"Where would you like to go?"
        )
        state.suggested_replies = ["Paris", "Tokyo", "New York"]

        _debug_node_end("router", "🧭", intent="ORIGIN_ONLY_PLANNING", origin=detected_origin)
        return False  # Fall through


def _apply_settings_to_state(state: GraphState, detected_settings: dict, _clog) -> None:
    """
    Apply detected settings to state: sync trip_inputs, set routing flags,
    build response message.  Caller should ``return state`` after this.
    """
    from app.debug_utils import _debug_node_end, log

    log(
        "ROUTER",
        f"[SETTINGS] Detected settings change: {list(detected_settings.keys())} "
        f"(destination: {state.trip_plan.destination})",
    )

    # Sync settings to trip_inputs for LogisticsNode
    trip_inputs = state.metadata.get("trip_inputs", {})

    # Apply detected settings
    if "budget" in detected_settings:
        trip_inputs["budget"] = detected_settings["budget"]
        state.trip_plan.budget = detected_settings["budget"]

    if "adults" in detected_settings:
        trip_inputs["adults"] = detected_settings["adults"]
        state.trip_plan.adults = detected_settings["adults"]

    if "children" in detected_settings:
        trip_inputs["children"] = detected_settings["children"]
        state.trip_plan.children = detected_settings["children"]

    if "hotel_settings" in detected_settings:
        existing_hotel = trip_inputs.get("hotel_settings", {})
        trip_inputs["hotel_settings"] = {
            **existing_hotel,
            **detected_settings["hotel_settings"],
        }

    if "flight_settings" in detected_settings:
        existing_flight = trip_inputs.get("flight_settings", {})
        trip_inputs["flight_settings"] = {
            **existing_flight,
            **detected_settings["flight_settings"],
        }
        # Keep routing/logistics in sync within the same turn.
        trip_inputs.setdefault("booking_types", {})["flights"] = "on"
        state.metadata["explicit_flights_toggle"] = "on"

    state.metadata["trip_inputs"] = trip_inputs
    state.metadata.pop("trip_settings", None)
    state.metadata["trip_settings"] = get_trip_settings(state).model_dump()

    # Populate extracted_settings for frontend persistence
    ext = state.metadata.setdefault("extracted_settings", {})
    if "hotel_settings" in detected_settings:
        hs = detected_settings["hotel_settings"]
        if "min_stars" in hs:
            ext["hotel_min_stars"] = hs["min_stars"]
    if "flight_settings" in detected_settings:
        fs = detected_settings["flight_settings"]
        if fs.get("direct_only") is not None:
            ext["flights_toggle"] = "on"
            ext["flight_direct_only"] = fs["direct_only"]
        if "cabin_class" in fs:
            ext["flight_cabin_class"] = fs["cabin_class"]

    # Mark for frontend + downstream (architect skips duplicate settings extraction)
    state.metadata["settings_just_updated"] = True
    state.metadata["updated_settings"] = list(detected_settings.keys())
    state.metadata["router_detected_settings_change"] = True

    # ROUTE TO LOGISTICS
    state.metadata["origin_only_logistics"] = True
    state.metadata["skip_architect"] = True
    state.metadata["skip_specialists"] = True
    state.metadata["tier2_prefetch_intent"] = "settings"

    # Build response message
    changes = []
    if "budget" in detected_settings:
        changes.append(f"budget of **${detected_settings['budget']:,}**")
    if "adults" in detected_settings or "children" in detected_settings:
        adults = detected_settings.get("adults", state.trip_plan.adults or 1)
        children = detected_settings.get("children", state.trip_plan.children or 0)
        traveler_str = f"{adults} adult{'s' if adults > 1 else ''}"
        if children:
            traveler_str += f" and {children} child{'ren' if children > 1 else ''}"
        changes.append(traveler_str)
    if "hotel_settings" in detected_settings:
        hotel = detected_settings["hotel_settings"]
        if "min_stars" in hotel:
            changes.append(f"{hotel['min_stars']}-star hotels")
        elif "style" in hotel:
            changes.append(f"{hotel['style']} hotels")
    if "flight_settings" in detected_settings:
        flight = detected_settings["flight_settings"]
        if flight.get("direct_only"):
            changes.append("direct flights")
        if "cabin_class" in flight:
            changes.append(f"{flight['cabin_class']} class")

    change_str = ", ".join(changes)
    state.last_summary = f"Got it - updating your trip for {change_str}. Refreshing options..."
    state.suggested_replies = ["Show me more options", "Change budget", "Update travelers"]

    _debug_node_end(
        "router",
        "🧭",
        intent="SETTINGS_TO_LOGISTICS",
        settings=list(detected_settings.keys()),
    )


def _apply_modifications_to_state(
    state: GraphState, mods: dict, user_text: str, _clog
) -> Optional[GraphState]:
    """
    Apply trip modifications: add/remove categories, skill level, resets.

    Returns state if caller should early-return (routing handled),
    or None if fall-through needed (mixed Tier1+Tier2).
    """
    from app.debug_utils import _debug_node_end, log

    trip_inputs = state.metadata.get("trip_inputs", {})
    activity_settings = trip_inputs.get("activity_settings", {})
    existing_cats = set(activity_settings.get("categories", []))

    # Apply additions
    if "add_categories" in mods:
        existing_cats |= mods["add_categories"]

    # Apply removals
    if "remove_categories" in mods:
        existing_cats -= mods["remove_categories"]
        # Clear strategy sections for removed Tier 1 specialists
        for cat in mods["remove_categories"]:
            if cat in TIER1_SPECIALIST_NAMES:
                sections = state.metadata.get("strategy_sections", [])
                state.metadata["strategy_sections"] = [
                    s for s in sections if s.get("specialist_type") != cat
                ]

    # Apply skill level
    if "skill_level" in mods:
        activity_settings["skill_level"] = mods["skill_level"]

    # Apply setting resets
    if "reset_budget" in mods:
        trip_inputs["budget"] = None
        state.trip_plan.budget = None
    if "reset_hotel" in mods:
        trip_inputs["hotel_settings"] = {}

    # Write back categories
    activity_settings["categories"] = sorted(existing_cats)
    trip_inputs["activity_settings"] = activity_settings
    state.metadata["trip_inputs"] = trip_inputs
    state.metadata.pop("trip_settings", None)
    state.metadata["trip_settings"] = get_trip_settings(state).model_dump()

    # Check if message ALSO contains Tier 1 keywords
    has_tier1 = any(
        any(kw in user_text.lower() for kw in kws) for kws in ALL_SPECIALIST_KEYWORDS.values()
    )
    removing_tier1 = bool(mods.get("remove_categories", set()) & TIER1_SPECIALIST_NAMES)

    # Tier 2 prefetch: fire regardless of Tier1 presence so mixed inputs
    # like "diving and yoga" prefetch yoga tiles during specialist execution.
    # Uses full category set (not just additions) to match what Logistics computes.
    # Note: prefetch uses current settings, which may lag category removals
    # by one turn. L1/L2 cache makes this a ~0ms overhead, not a bug.
    if state.trip_plan.destination:
        all_cats = set(get_trip_settings(state).activity_settings.categories)
        tier2_to_prefetch = all_cats - TIER1_SPECIALISTS
        if tier2_to_prefetch:
            state.metadata["tier2_prefetch_intent"] = "activity"
            _prefetch_tier2_experiences(state, tier2_to_prefetch)

    if not has_tier1 or removing_tier1:
        # Check for real changes
        has_real_changes = (
            mods.get("add_categories")
            or mods.get("remove_categories")
            or mods.get("skill_level")
            or mods.get("reset_budget")
            or mods.get("reset_hotel")
        )
        if not has_real_changes:
            log(
                "ROUTER",
                "[ACTIONABLE] Nothing resolved — falling through",
            )
            return None

        # Route to logistics
        state.metadata["origin_only_logistics"] = True
        state.metadata["skip_architect"] = True
        state.metadata["skip_specialists"] = True

        # Build confirmation message
        parts = []
        added = mods.get("add_categories", set())
        removed = mods.get("remove_categories", set())
        if added:
            parts.append(f"Added **{', '.join(sorted(added))}**")
        if removed:
            parts.append(f"Removed **{', '.join(sorted(removed))}**")
        if "skill_level" in mods:
            parts.append(f"Skill level: **{mods['skill_level']}**")
        if "reset_budget" in mods:
            parts.append("Budget limit removed")
        if "reset_hotel" in mods:
            parts.append("Hotel preferences reset")

        state.last_summary = f"{'. '.join(parts)}. Refreshing options..."
        state.metadata["actionable_acknowledgment"] = state.last_summary
        state.suggested_replies = []

        state.metadata["settings_just_updated"] = True
        if added:
            state.metadata["added_categories"] = list(added)

        log("ROUTER", f"[ACTIONABLE] {mods}")
        _debug_node_end(
            "router",
            "🧭",
            intent="ACTIONABLE_TO_LOGISTICS",
            changes=list(mods.keys()),
        )
        return state

    # Mixed Tier 1 + Tier 2: fall through to SOFT_TRANSITION
    log(
        "ROUTER",
        f"[ACTIONABLE] Tier 2 categories set, continuing for Tier 1: {mods}",
    )
    return None


# =============================================================================
# Input Gate Validation
# =============================================================================


def _run_input_gates(state: GraphState) -> bool:
    """
    Run input gate validation after extraction populates trip_plan.
    Returns True if blocked (short-circuit to synthesizer).
    Returns False if ok to continue (warnings stashed in metadata).
    """
    blockers, warnings = _gate_registry.run_all(state.trip_plan)

    if warnings:
        state.metadata["input_gate_warnings"] = [
            {
                "code": w.code,
                "message": w.message,
                "field": w.field,
                "suggested_action": w.suggested_action,
            }
            for w in warnings
        ]
        for w in warnings:
            logger.debug(f"[INPUT_GATE] warning {w.code}: {w.message}")

    if blockers:
        state.metadata["input_gate_violations"] = [
            {
                "code": b.code,
                "message": b.message,
                "field": b.field,
                "suggested_action": b.suggested_action,
            }
            for b in blockers
        ]
        state.metadata["short_circuit_response"] = True
        state.metadata["short_circuit_type"] = "gate_blocked"

        msgs = [b.message for b in blockers]
        actions = [b.suggested_action for b in blockers if b.suggested_action]
        fallback = " ".join(msgs)
        if actions:
            fallback += " " + " ".join(actions)
        state.metadata["_gate_blocked_fallback"] = fallback

        for b in blockers:
            logger.debug(f"[INPUT_GATE] BLOCKED {b.code}: {b.message}")

        return True

    return False


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
    import time

    from app.debug_utils import (
        CompactLogger,
        _debug_node_end,
        _debug_node_start,
        _debug_node_timer_end,
        _debug_node_timer_start,
    )

    # Start timing this node execution
    _debug_node_timer_start("router")
    node_start_time = time.time()

    # Initialize compact logger with request metrics
    metrics = state.metadata.get("_metrics")
    clog = CompactLogger("router", metrics=metrics)

    # Get user message from last message
    user_text = ""
    if state.messages:
        last_msg = state.messages[-1]
        if hasattr(last_msg, "content"):
            user_text = last_msg.content

    # Clear stale per-turn flags from previous turn
    state.metadata.pop("settings_just_updated", None)
    state.metadata.pop("actionable_acknowledgment", None)
    state.metadata.pop("_tiles_replaced", None)
    state.metadata.pop("router_detected_settings_change", None)
    state.metadata.pop("updated_settings", None)
    state.metadata.pop("added_categories", None)
    state.metadata.pop("tier2_tiles_generated", None)
    state.metadata.pop("tier2_new_content_generated", None)

    _debug_node_start(
        "router",
        "🧭",
        user_text=user_text[:80] if user_text else "",
        current_specialist=state.active_specialist,
    )

    # Compact logging: node start
    clog.node_start("ROUTER", user_text=user_text[:30] if user_text else "")

    # ==========================================================================
    # DIAGNOSTIC LOGGING - Track origin sync (Issue 6 investigation)
    # ==========================================================================
    from app.debug_utils import _debug_log

    trip_inputs = state.metadata.get("trip_inputs", {})
    trip_inputs_origin = trip_inputs.get("origin")
    _debug_log(f"[ROUTER] trip_plan.origin={state.trip_plan.origin!r}")
    _debug_log(f"[ROUTER] metadata.trip_inputs.origin={trip_inputs_origin!r}")

    # Check for origin mismatch at graph entry point
    if trip_inputs_origin and not state.trip_plan.origin:
        logger.warning(
            f"[ROUTER] ⚠️ ORIGIN MISMATCH: metadata.trip_inputs.origin='{trip_inputs_origin}' "
            f"but trip_plan.origin is empty! State restoration may have failed."
        )
        # FIX: Sync origin from trip_inputs to trip_plan if missing
        state.trip_plan.origin = trip_inputs_origin
        _debug_log(
            f"[ROUTER] ✅ Fixed: Synced origin from trip_inputs "
            f"to trip_plan: '{trip_inputs_origin}'"
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
    # POST-PLAN FAST PATH: When plan is active (S2/S3), LLM extraction runs
    # first. Settings/modifications/origin are read from extraction output
    # instead of regex. Pre-plan messages skip this and use regex below.
    # ==========================================================================
    plan_is_active = _is_plan_active(state)

    if plan_is_active and classification is None:
        from app.debug_utils import log

        log("ROUTER", "[POST-PLAN] LLM-first extraction for active plan...")

        old_start = state.trip_plan.start_date
        old_end = state.trip_plan.end_date
        old_origin = state.trip_plan.origin

        try:
            router_output, token_usage = await _classify_and_extract_with_llm(user_text, state)
            extracted_router_output = router_output.model_dump()

            if token_usage:
                from app.debug_utils import log_tokens

                log_tokens(
                    "ROUTER",
                    token_usage.get("prompt_tokens", 0),
                    token_usage.get("completion_tokens", 0),
                    token_usage.get("total_tokens", 0),
                )
                clog.llm_call(
                    model=settings.router_model,
                    prompt_tokens=token_usage.get("prompt_tokens", 0),
                    completion_tokens=token_usage.get("completion_tokens", 0),
                    purpose="post_plan_extraction",
                )

            destination = _extract_destination_context(user_text, state)

            # Snapshot categories BEFORE _populate writes them — needed for
            # _collect_modifications to detect the delta (Issue #3 fix).
            # Prefer active-plan categories as baseline to avoid stale persisted carryover.
            active_plan_cats = set(state.metadata.get("active_plan_categories", []))
            pre_cats = active_plan_cats or set(
                state.metadata.get("trip_inputs", {})
                .get("activity_settings", {})
                .get("categories", [])
            )
            has_category_intent = has_explicit_category_intent(user_text, extracted_router_output)
            category_merge_mode = detect_category_merge_mode(user_text, extracted_router_output)
            _debug_log(
                "[VERIFY][CATEGORY_MERGE] "
                f"intent={has_category_intent} "
                f"mode={category_merge_mode} "
                f"baseline_source={'active_plan' if active_plan_cats else 'persisted'} "
                f"baseline={sorted(pre_cats)}"
            )

            _populate_trip_plan_from_router_output(
                state,
                router_output,
                destination,
                user_text,
                category_baseline=pre_cats,
                category_merge_mode=category_merge_mode,
                allow_category_updates=has_category_intent,
            )

            # Guard against LLM drifting a date the user didn't change.
            # "Extend to Feb 22" should only change end_date, not start_date.
            text_lower = user_text.lower()
            if old_start and state.trip_plan.start_date != old_start:
                start_signals = ("start", "begin", "from ", "depart", "leave on", "move")
                if not any(sig in text_lower for sig in start_signals):
                    state.trip_plan.start_date = old_start
                    log("ROUTER", f"[POST-PLAN] Reverted start date drift → {old_start}")
            if old_end and state.trip_plan.end_date != old_end:
                end_signals = ("extend", "until", "end ", "through", "shorten", "move")
                if not any(sig in text_lower for sig in end_signals):
                    state.trip_plan.end_date = old_end
                    log("ROUTER", f"[POST-PLAN] Reverted end date drift → {old_end}")

            # Flag extraction BEFORE input gates — even if gates block,
            # the Architect should NOT re-extract the same message.
            state.metadata["router_output"] = extracted_router_output
            state.metadata["router_extracted_fields"] = True

            # === INPUT GATE VALIDATION ===
            if _run_input_gates(state):
                return state

            ro_dict = state.metadata["router_output"]  # reuse from line 1905

            log(
                "ROUTER",
                f"[POST-PLAN] Extracted: dest={state.trip_plan.destination}, "
                f"dates={state.trip_plan.start_date} -> {state.trip_plan.end_date}, "
                f"origin={state.trip_plan.origin}",
            )

            # -- Origin from LLM --
            new_origin = state.trip_plan.origin
            if new_origin and new_origin != old_origin:
                should_return = await _apply_origin_to_state(state, new_origin, clog)
                if should_return:
                    return state

            # -- Collect settings + modifications in one pass --
            # Mods own routing when both present (Tier 1 additions need
            # specialist queue; settings are parameter updates that logistics
            # picks up regardless).
            llm_settings = _collect_settings_from_extraction(ro_dict)
            # Fallback: merge regex-based settings for fields LLM missed
            # (e.g., "5-star hotels only" → LLM may not extract hotel_min_stars)
            regex_settings = _detect_settings_from_message(user_text, state)
            if regex_settings:
                if llm_settings is None:
                    llm_settings = regex_settings
                else:
                    for key, val in regex_settings.items():
                        if key not in llm_settings:
                            llm_settings[key] = val
            llm_settings = _sanitize_settings_from_message(llm_settings, user_text)
            llm_mods = _collect_modifications_from_extraction(
                ro_dict,
                state,
                pre_populate_categories=pre_cats,
                allow_category_modifications=has_category_intent,
            )

            has_settings = bool(llm_settings) and bool(state.trip_plan.destination)
            has_mods = llm_mods is not None

            if has_settings and not has_mods:
                _apply_settings_to_state(state, llm_settings, clog)
                return state

            if has_mods:
                if has_settings:
                    _apply_settings_to_state(state, llm_settings, clog)
                    # Mods take routing priority -- clear settings' skip flags
                    state.metadata.pop("origin_only_logistics", None)
                    state.metadata.pop("skip_specialists", None)
                    state.metadata.pop("skip_architect", None)
                    # Prevent reset_hotel from clobbering hotel_settings we just applied
                    # (LLM may incorrectly flag reset_hotel for "5-star hotels only")
                    if "hotel_settings" in llm_settings and "reset_hotel" in llm_mods:
                        del llm_mods["reset_hotel"]
                    if "budget" in llm_settings and "reset_budget" in llm_mods:
                        del llm_mods["reset_budget"]
                result = _apply_modifications_to_state(state, llm_mods, user_text, clog)
                if result is not None:
                    return result
                if has_settings:
                    # Restore logistics routing flags cleared at line 1879-1881
                    # (mods returned None, so settings should still route to logistics)
                    state.metadata["origin_only_logistics"] = True
                    state.metadata["skip_architect"] = True
                    state.metadata["skip_specialists"] = True
                    return state

            # -- Date change -> upgrade planning_intent later --
            if state.trip_plan.start_date != old_start or state.trip_plan.end_date != old_end:
                state.metadata["_post_plan_date_change"] = True

            # Fall through to planning_intent / exploration
        except Exception as e:
            logger.warning(f"[POST-PLAN] LLM extraction failed: {e}")
            state.metadata["router_extraction_failed"] = True
            # Fall through -- exploration/soft_transition still works

    # ==========================================================================
    # END POST-PLAN FAST PATH
    # ==========================================================================

    # ==========================================================================
    # ORIGIN DETECTION (pre-plan only -- post-plan uses LLM extraction above)
    # ==========================================================================
    if not plan_is_active:
        detected_origin = _detect_origin_from_message(user_text)
        if detected_origin:
            should_return = await _apply_origin_to_state(state, detected_origin, clog)
            if should_return:
                return state
    # ==========================================================================
    # END ORIGIN DETECTION
    # ==========================================================================

    # ==========================================================================
    # EXPLORATION MODE: Check if this is a generic travel question
    # ==========================================================================
    # Before falling through to LLM classification, check if this is an exploration
    # question that we can answer directly using Local Expert knowledge.
    from app.debug_utils import log

    if classification is None:
        # ======================================================================
        # SETTINGS DETECTION (pre-plan only -- post-plan uses LLM extraction)
        # ======================================================================
        if not plan_is_active:
            detected_settings = _detect_settings_from_message(user_text, state)
            if detected_settings and state.trip_plan.destination:
                _apply_settings_to_state(state, detected_settings, clog)
                return state
        # ======================================================================
        # END SETTINGS DETECTION
        # ======================================================================

        # ==================================================================
        # ACTIONABLE INPUT DETECTION (pre-plan only -- post-plan uses LLM)
        # ==================================================================
        if not plan_is_active:
            actionable = _detect_actionable_input(user_text, state)
            if actionable:
                # Pre-plan: resolve unresolved tokens via LLM before applying
                if actionable.get("unresolved_tokens"):
                    log(
                        "ROUTER",
                        f"[ACTIONABLE] Resolving: {actionable['unresolved_tokens']}",
                    )
                    try:
                        router_output, _ = await _classify_and_extract_with_llm(user_text, state)
                        if router_output and router_output.activity_categories:
                            known = TIER1_SPECIALISTS | TIER2_ACTIVITY_KEYWORDS
                            resolved = {
                                c.lower()
                                for c in router_output.activity_categories
                                if c.lower() in known
                            }
                            existing_cats = set(
                                state.metadata.get("trip_inputs", {})
                                .get("activity_settings", {})
                                .get("categories", [])
                            )
                            if resolved - existing_cats:
                                actionable.setdefault("add_categories", set()).update(resolved)
                                log("ROUTER", f"[ACTIONABLE] LLM resolved: {resolved}")
                    except Exception as e:
                        log("ROUTER", f"[ACTIONABLE] LLM resolution failed: {e}")
                        state.metadata["router_extraction_failed"] = True

                result = _apply_modifications_to_state(state, actionable, user_text, clog)
                if result is not None:
                    return result
        # ==================================================================
        # END ACTIONABLE INPUT DETECTION
        # ==================================================================

        # Post-plan: use LLM classification. Pre-plan: keyword fallback.
        router_output_dict = state.metadata.get("router_output")
        if plan_is_active and router_output_dict and router_output_dict.get("planning_intent"):
            llm_intent = router_output_dict["planning_intent"]
            intent_map = {
                "ready": "ready",
                "modifying": "soft_transition",
                "exploring": "exploring",
                "greeting": "exploring",
            }
            planning_intent = intent_map.get(llm_intent, "exploring")
            log("ROUTER", f"[POST-PLAN] planning_intent from LLM: {llm_intent} → {planning_intent}")
        else:
            planning_intent = detect_planning_intent(user_text, state)

        # Pick up post-plan date change from fast path above
        if state.metadata.pop("_post_plan_date_change", False):
            planning_intent = "soft_transition"
            from app.debug_utils import log

            log("ROUTER", "[POST-PLAN] Dates changed, upgrading to soft_transition")

        destination = _extract_destination_context(user_text, state)

        # =====================================================================
        # OPPORTUNISTIC EXTRACTION: Extract dates/fields from EVERY message
        # that contains extractable data, regardless of planning intent.
        # This ensures dates mentioned during exploration are NOT lost.
        # =====================================================================
        # Capture old dates BEFORE extraction so we can detect date changes
        old_start_date = state.trip_plan.start_date
        old_end_date = state.trip_plan.end_date

        text_lower = user_text.lower()
        has_date_in_message = any(re.search(p, text_lower) for p in DATE_INDICATORS)

        if has_date_in_message and not state.metadata.get("router_extracted_fields"):
            log("ROUTER", "[OPPORTUNISTIC] Extracting (dates detected in pre-plan)...")

            try:
                router_output, token_usage = await _classify_and_extract_with_llm(user_text, state)
                extracted_router_output = router_output.model_dump()

                if token_usage:
                    from app.debug_utils import log_tokens

                    log_tokens(
                        "ROUTER",
                        token_usage.get("prompt_tokens", 0),
                        token_usage.get("completion_tokens", 0),
                        token_usage.get("total_tokens", 0),
                    )
                    # Compact logging: LLM call
                    clog.llm_call(
                        model=settings.router_model,
                        prompt_tokens=token_usage.get("prompt_tokens", 0),
                        completion_tokens=token_usage.get("completion_tokens", 0),
                        purpose="opportunistic_extraction",
                    )

                # Immediately persist to state.trip_plan
                has_category_intent = has_explicit_category_intent(
                    user_text,
                    extracted_router_output,
                )
                category_merge_mode = detect_category_merge_mode(
                    user_text,
                    extracted_router_output,
                )
                _populate_trip_plan_from_router_output(
                    state,
                    router_output,
                    destination,
                    user_text,
                    category_merge_mode=category_merge_mode,
                    allow_category_updates=has_category_intent,
                )

                # Flag extraction BEFORE input gates — even if gates block,
                # the Architect should NOT re-extract the same message.
                state.metadata["router_output"] = extracted_router_output
                state.metadata["router_extracted_fields"] = True

                # === INPUT GATE VALIDATION ===
                if _run_input_gates(state):
                    return state

                log(
                    "ROUTER",
                    f"[OPPORTUNISTIC] Extracted: dest={state.trip_plan.destination}, "
                    f"dates={state.trip_plan.start_date} → {state.trip_plan.end_date}",
                )
            except Exception as e:
                logger.warning(f"[OPPORTUNISTIC] Extraction failed: {e}")
                state.metadata["router_extraction_failed"] = True
                # Continue with normal flow even if extraction fails
        # =====================================================================
        # END OPPORTUNISTIC EXTRACTION
        # =====================================================================

        # If extraction changed dates, upgrade intent so soft_transition path
        # handles specialist re-queuing (not the exploring short-circuit)
        if state.trip_plan.start_date != old_start_date or state.trip_plan.end_date != old_end_date:
            planning_intent = "soft_transition"
            log("ROUTER", "[OPPORTUNISTIC] Dates changed, upgrading to soft_transition")

        log(
            "ROUTER",
            f"[EXPLORATION] planning_intent={planning_intent}, destination={destination}",
        )

        # Upgrade exploring → soft_transition when dates already collected
        # from prior turns. Without this, "dates turn 1 + destination turn 2"
        # enters the exploration short-circuit and never routes to planning.
        if (
            planning_intent == "exploring"
            and (destination or state.trip_plan.destination)
            and state.trip_plan.start_date
            and state.trip_plan.end_date
            and not _is_plan_active(state)
        ):
            planning_intent = "soft_transition"
            log("ROUTER", "[EXPLORATION] Upgraded to soft_transition (dates already collected)")

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

                    # Store niche specialists so infeasible ones can be
                    # resurrected when constraints (e.g. dates) change
                    niche = [s for s in all_specialists if s not in ("general", "local_expert")]
                    if niche:
                        state.metadata["requested_specialists"] = niche

                # CRITICAL: Set constraint hash for future change detection
                # This ensures subsequent destination changes trigger tile clearing
                trip_settings = get_trip_settings(state)
                state.last_constraint_hash = _compute_constraint_hash(
                    state.trip_plan, trip_settings
                )
                log("ROUTER", f"[READY] Constraint hash set: {state.last_constraint_hash[:8]}")

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

                # Detect month from user text for contextual date suggestions (SuggestionPool)
                for _ml, _mc in _MONTHS.items():
                    if _ml in user_text.lower():
                        state.metadata["detected_month"] = _mc
                        break

                # Generate context-aware date suggestions based on any month mentioned
                state.suggested_replies = _get_date_suggestions(
                    user_text
                )  # DEPRECATED: replaced by SuggestionPool
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
            has_active_plan = state.trip_plan.destination and _is_plan_active(state)

            if has_active_plan:
                # ── Post-planning: section-specific answer ──
                qtype, section = _classify_question(user_text, state, plan_is_active)
                if qtype != "general":
                    answer, _ = await generate_comprehensive_answer(
                        user_text, destination, qtype, section, state
                    )
                    # Track for question rotation
                    count = state.metadata.get("generic_question_count", 0) + 1
                    state.metadata["generic_question_count"] = count

                    state.last_summary = answer  # No ending ("Ready to plan?")
                    state.metadata["short_circuit_response"] = True
                    state.metadata["short_circuit_type"] = "question_answer"
                    # Don't set suggested_replies — synthesizer's generate_suggestions
                    # produces fresh state-aware chips (falls through PRIORITY 2 logic)

                    log(
                        "ROUTER",
                        f"[QUESTION] Post-plan answer: {qtype}/{section} (#{count})",
                    )
                    _debug_node_end(
                        "router",
                        "🧭",
                        intent="QUESTION_ANSWER",
                        destination=destination,
                        question_type=qtype,
                        question_count=count,
                        short_circuit=True,
                    )
                    return state
                else:
                    # Unrecognized question + active plan → fall through to LLM
                    log(
                        "ROUTER",
                        "[QUESTION] Unrecognized post-plan question, falling through to LLM",
                    )
                    state.metadata["exploration_mode"] = False

            else:
                # ── Pre-planning: exploration short-circuit (existing behavior) ──
                qtype, section = classify_question_type(user_text)
                log("ROUTER", f"[EXPLORATION] Detected question type: {qtype}, section: {section}")

                answer, ending = await generate_comprehensive_answer(
                    user_text, destination, qtype, section, state
                )

                count = state.metadata.get("generic_question_count", 0) + 1
                state.metadata["generic_question_count"] = count
                state.metadata["last_destination_context"] = destination
                state.metadata["exploration_mode"] = True

                # Override ending when trip state makes the generic prompt irrelevant.
                # Chips already suggest dates — response should match.
                if state.trip_plan.origin and not state.trip_plan.start_date:
                    ending = "When are you thinking of going?"
                elif not state.trip_plan.start_date:
                    ending = "When would you like to go?"

                state.last_summary = f"{answer}\n\n{ending}"
                state.suggested_replies = _get_exploration_suggestions(qtype, destination)
                state.metadata["short_circuit_response"] = True
                state.metadata["short_circuit_type"] = "exploration"

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

            # Detect if dates CHANGED (not just exist) - compare to pre-extraction values
            dates_changed = (
                state.trip_plan.start_date != old_start_date
                or state.trip_plan.end_date != old_end_date
            ) and plan_has_dates  # Only if we have valid dates now

            # Get existing specialists from strategy sections
            existing_from_sections = [
                s.get("specialist_type")
                for s in state.metadata.get("strategy_sections", [])
                if s.get("specialist_type") not in ("general", "local_expert")
            ]
            # Include previously requested specialists that may have been
            # infeasible (e.g. diving was too short, now dates extended)
            requested = state.metadata.get("requested_specialists", [])
            existing_specialists = list(
                dict.fromkeys(
                    existing_from_sections
                    + [s for s in requested if s not in ("general", "local_expert")]
                )
            )

            # Detect NEW specialists from the message
            new_specialists = get_new_specialists_from_text(user_text, existing_specialists)

            # Also detect specialists from activity_settings categories (UI pill selection)
            # Without this, categories set via pills are ignored in SOFT_TRANSITION path
            category_specialists = _detect_specialists_from_activity_settings(state)
            for s in category_specialists:
                if s not in new_specialists:
                    new_specialists.append(s)

            # Track all requested specialists (persists across turns so infeasible
            # ones can be resurrected when constraints like dates change)
            if new_specialists:
                prev_requested = state.metadata.get("requested_specialists", [])
                updated = list(dict.fromkeys(prev_requested + new_specialists))
                state.metadata["requested_specialists"] = updated

            # CRITICAL: Route to planning immediately when user provides actionable input:
            # 1. dates + destination (e.g., "bali Mar 1-9")
            # 2. destination + activities (e.g., "bali diving")
            # Input parameters have highest priority - don't ask exploration questions
            if plan_has_dates or new_specialists:
                # ── Clear stale fast-path flags from previous turns ──
                # Without this, "from rome" sets origin_only_logistics=True,
                # and the next message ("I want hiking") skips specialists entirely.
                state.metadata.pop("origin_only_logistics", None)
                state.metadata.pop("skip_specialists", None)
                state.metadata.pop("skip_architect", None)

                # CRITICAL FIX: Persist destination to state so route_after_router
                # can dispatch specialists (it checks has_destination before routing)
                if destination and not state.trip_plan.destination:
                    state.trip_plan.destination = destination

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

                # DATE CHANGE: Re-queue existing specialists only when the month
                # changed (seasonal shift). Same-month date tweaks (extend/shorten)
                # don't affect specialist content — the builder adapts to variable
                # trip lengths. This avoids a 15s specialist LLM re-run on date edits.
                old_month = (old_start_date or "")[:7]
                new_month = (state.trip_plan.start_date or "")[:7]
                month_changed = old_month != new_month
                if dates_changed and existing_specialists and month_changed:
                    log(
                        "ROUTER",
                        f"[SOFT_TRANSITION] Dates changed, re-queuing: {existing_specialists}",
                    )

                    # Merge new specialists with existing (preserving order, deduping)
                    all_specialists = list(dict.fromkeys(new_specialists + existing_specialists))

                    # Clear stale content from re-queued specialists
                    # (strategy_sections is stored in metadata, not trip_plan)
                    current_sections = state.metadata.get("strategy_sections", [])
                    state.metadata["strategy_sections"] = [
                        s
                        for s in current_sections
                        if s.get("specialist_type") not in existing_specialists
                    ]

                    # Clear constraint hash so guard re-validates
                    state.metadata["constraint_hash"] = None

                    # Clear stale itinerary_blocks from previous build so guard
                    # doesn't read old activity placements (prevents false
                    # ALTITUDE_AFTER_DIVE on date changes)
                    state.trip_plan.itinerary_blocks = []

                    # CRITICAL: Clear in-memory specialist cache so LLM re-runs with new dates
                    # Without this, specialists return stale 8-day content for 4-day trips
                    state.metadata.pop("parallel_llm_results", None)

                    # CRITICAL: Clear fast-path flags so route_after_router
                    # picks up active_specialist instead of jumping to logistics
                    state.metadata.pop("origin_only_logistics", None)
                    state.metadata.pop("skip_specialists", None)

                    # Clear infeasibility flags so re-queued specialists
                    # get a fresh evaluation with new dates
                    state.metadata.pop("specialist_infeasible", None)
                    state.metadata.pop("specialist_infeasible_reason", None)
                    state.metadata.pop("specialist_alternative", None)

                    # Persist merged list so infeasible specialists survive
                    niche = [s for s in all_specialists if s not in ("general", "local_expert")]
                    if niche:
                        state.metadata["requested_specialists"] = niche

                    # Queue all specialists (existing + new)
                    state.pending_specialists = (
                        all_specialists[1:] if len(all_specialists) > 1 else []
                    )
                    state.active_specialist = all_specialists[0]
                    state.active_agent_id = all_specialists[0]

                elif dates_changed and existing_specialists and not month_changed:
                    # Same-month date change: skip specialist LLM, just rebuild itinerary.
                    # Builder adapts activity count to new trip length automatically.
                    log(
                        "ROUTER",
                        f"[SOFT_TRANSITION] Same-month date change, skipping specialist re-run "
                        f"(old={old_start_date}→{old_end_date}, "
                        f"new={state.trip_plan.start_date}→{state.trip_plan.end_date})",
                    )
                    state.trip_plan.itinerary_blocks = []
                    # Queue new specialists only (if any), don't re-queue existing
                    if new_specialists:
                        state.pending_specialists = (
                            new_specialists[1:] if len(new_specialists) > 1 else []
                        )
                        state.active_specialist = new_specialists[0]
                        state.active_agent_id = new_specialists[0]
                    else:
                        # No specialists to run — route to architect for itinerary rebuild
                        state.pending_specialists = []
                        state.active_specialist = None
                        state.active_agent_id = None

                elif has_local_expert and new_specialists:
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

                # SYNC: Write detected specialists to activity_settings.categories
                # Without this, logistics sees categories=[] and suppresses all tiles
                if new_specialists:
                    _ti = state.metadata.get("trip_inputs", {})
                    _as = _ti.get("activity_settings", {})
                    _cats = set(_as.get("categories", []))
                    _merged = sorted(_cats | set(new_specialists))
                    _as["categories"] = _merged
                    _ti["activity_settings"] = _as
                    state.metadata["trip_inputs"] = _ti
                    state.metadata.pop("trip_settings", None)
                    state.metadata["trip_settings"] = get_trip_settings(state).model_dump()

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

            qtype, section = _classify_question(user_text, state, plan_is_active)
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
                f"I specialize in {_SPECIALIST_NAMES_CSV} trips."
            )
            if has_date:
                # Has date, needs activity
                # Check if dates were actually extracted and acknowledge them
                if state.trip_plan.start_date and state.trip_plan.end_date:
                    start = state.trip_plan.start_date
                    end = state.trip_plan.end_date
                    ending = f"Great, I've noted your dates ({start} to {end}). {activity_prompt}"
                elif state.trip_plan.start_date:
                    ending = f"Got it, starting {state.trip_plan.start_date}. {activity_prompt}"
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

        try:
            classification, token_usage = await _classify_intent_with_llm(user_text, state)
            if token_usage:
                log_tokens(
                    "ROUTER",
                    token_usage.get("prompt_tokens", 0),
                    token_usage.get("completion_tokens", 0),
                    token_usage.get("total_tokens", 0),
                )
                # Compact logging: LLM call
                clog.llm_call(
                    model=settings.router_model,
                    prompt_tokens=token_usage.get("prompt_tokens", 0),
                    completion_tokens=token_usage.get("completion_tokens", 0),
                    purpose="intent_classification",
                )
            else:
                log("ROUTER", "No LLM call (exact match or error)")
                clog.event("cache_hit", "Intent (exact match)")
            log(
                "ROUTER",
                f"Intent: {classification.intent}",
                data=f"specialist_hints={classification.specialist_hints}",
            )
        except Exception as e:
            logger.error(f"[ROUTER] Intent LLM failed, defaulting to PLANNING: {e}")
            classification = IntentClassification(
                intent="PLANNING",
                confidence=0.3,
                reasoning=f"Intent classification failed: {e}",
                specialist_hints=[],
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
        # FORCE clear tiles on GENERATE_PLAN_NOW (Refresh button)
        # This ensures fresh tile fetch even if hash comparison fails
        state.tiles = {}
        state.metadata["tiles_destination"] = None
        logger.info("[Router] 🔥 GENERATE_PLAN_NOW - forced tile cache clear")
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
    # NOTE: Hash is computed from typed trip_settings which has latest values
    current_hash = _compute_constraint_hash(state.trip_plan, get_trip_settings(state))
    previous_hash = state.last_constraint_hash
    executed = state.metadata.get("executed_strategy_topics", [])
    # Include requested specialists that may have been infeasible
    requested = state.metadata.get("requested_specialists", [])

    # Debug logging - CRITICAL for debugging reactivity
    from app.debug_utils import log

    prev_hash_str = previous_hash[:8] if previous_hash else "None"
    log(
        "ROUTER",
        f"[REACTIVITY] Hash: prev={prev_hash_str} → curr={current_hash[:8]}",
    )
    log("ROUTER", f"[REACTIVITY] executed_strategy_topics={executed}")
    dest = state.trip_plan.destination
    start = state.trip_plan.start_date
    end = state.trip_plan.end_date
    log(
        "ROUTER",
        f"[REACTIVITY] trip_plan: dest={dest}, dates={start} to {end}",
    )
    log("ROUTER", f"[REACTIVITY] is_generate_trigger={is_generate_trigger}")

    # Detect constraint changes (only if we have a previous hash to compare)
    constraints_changed = previous_hash is not None and current_hash != previous_hash

    # Re-run specialists in two cases:
    # 1. Constraints changed (destination, dates, budget, etc. modified)
    # 2. GENERATE_PLAN_NOW + specialists were executed before (ensures fresh run with complete data)
    # NOTE: Use (executed or requested) so infeasible specialists get resurrected
    should_rerun_specialists = (constraints_changed or is_generate_trigger) and (
        executed or requested
    )

    log(
        "ROUTER",
        f"[REACTIVITY] constraints_changed={constraints_changed}, "
        f"should_rerun={should_rerun_specialists}",
    )

    if should_rerun_specialists:
        # Filter to niche specialists only (not local_expert/general which run automatically)
        # Merge executed + requested so infeasible specialists are resurrected
        niche_specialists = [
            t for t in dict.fromkeys(executed + requested) if t not in ("general", "local_expert")
        ]

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

        # Track niche specialists for resurrection if they become infeasible
        niche = [s for s in all_specialists if s not in ("general", "local_expert")]
        if niche:
            prev_requested = state.metadata.get("requested_specialists", [])
            updated = list(dict.fromkeys(prev_requested + niche))
            state.metadata["requested_specialists"] = updated

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

    # Compact logging: node end with timing
    duration_ms = int((time.time() - node_start_time) * 1000)
    clog.node_end(
        "ROUTER",
        duration_ms,
        intent=state.intent,
        dest=state.trip_plan.destination,
        specialist=state.active_specialist,
    )

    return state


# _prefetch_tier2_experiences now imported from router_category_sync.py
