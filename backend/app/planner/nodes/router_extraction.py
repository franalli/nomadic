"""
Router Extraction Core — LLM-based intent classification and field extraction.

Handles:
- RouterOutput schema (intent + extracted fields)
- LLM prompts for classification and extraction
- Unified extraction with L1 caching
- Field normalization and validation
- State population from extraction results
"""

import asyncio
import hashlib
import json
import logging
import re
from calendar import monthrange
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.planner.llm_factory import (
    gemini_safe_schema,
    get_llm_by_model,
    resolve_schema_refs,
    strip_unsupported_schema_keys,
)
from app.planner.specialist_registry import (
    ALL_SPECIALIST_KEYWORDS,
    TIER1_SPECIALIST_NAMES,
    TIER2_COMMON_HINTS,
)
from app.planner.state import GraphState

if TYPE_CHECKING:
    from app.planner.schemas.coordinator_schemas import (
        ChangeClassification,
        ClassifierOutput,
    )

logger = logging.getLogger(__name__)

# Derived prompt fragments — single source of truth from registry
_SPECIALIST_NAMES_CSV = ", ".join(sorted(TIER1_SPECIALIST_NAMES))
_SPECIALIST_HINTS_JSON = json.dumps(sorted(TIER1_SPECIALIST_NAMES))
_TIER2_EXAMPLES_CSV = ", ".join(sorted(TIER2_COMMON_HINTS))


def _build_specialist_keyword_prompt() -> str:
    lines = []
    for topic in sorted(ALL_SPECIALIST_KEYWORDS):
        aliases = ALL_SPECIALIST_KEYWORDS[topic][:5]
        quoted = ", ".join(f'"{a}"' for a in aliases)
        lines.append(f'- {quoted} -> "{topic}"')
    return "\n".join(lines)


_SPECIALIST_KEYWORD_PROMPT = _build_specialist_keyword_prompt()


def _sanitize_user_message(text: str) -> str:
    """Escape prompt template metacharacters in user input.

    Prevents user-supplied text from being interpreted as format-string
    variables (``{}``) or fenced code blocks (triple backticks) when
    interpolated into LLM prompt templates.
    """
    return text.replace("{", "{{").replace("}", "}}").replace("```", "` ` `")


# =============================================================================
# Schemas
# =============================================================================


class IntentClassification(BaseModel):
    """LLM-structured output for intent classification."""

    intent: Literal["GREETING", "RESET", "PLANNING"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str = Field(description="Brief explanation of classification")
    # Multiple specialist hints (e.g., "diving and hiking trip")
    specialist_hints: List[str] = Field(
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
    specialist_hints: List[str] = Field(
        default_factory=list, description="List of detected specialist activities"
    )

    # Tier 2 activity categories — any recreational activity (open-ended)
    activity_categories: List[str] = Field(
        default_factory=list,
        description="Activity categories mentioned. Common: "
        + _TIER2_EXAMPLES_CSV
        + ". But accept ANY activity the user mentions.",
    )

    # Activity day preferences as JSON string (gpt-4o-mini handles str better than Dict)
    activity_day_preferences: Optional[str] = Field(
        None,
        description=(
            "JSON string of day counts per activity when user explicitly states numbers. "
            'E.g., "3 days diving" -> \'{"diving": 3}\'. null if not specified.'
        ),
    )

    # Activities per day (density preference)
    activities_per_day: Optional[int] = Field(
        None,
        description=(
            "Target activities per day if user specifies density. "
            "E.g., '2 activities a day' -> 2. Only set when explicitly stated."
        ),
    )

    # Extracted trip fields (populated when intent=PLANNING)
    destination: Optional[str] = Field(None, description="Destination city/country if mentioned")
    origin: Optional[str] = Field(None, description="Origin city if mentioned")
    origin_iata: Optional[str] = Field(
        None,
        description=(
            "IATA airport code for origin city. Leave null — resolved downstream by iata_resolver."
        ),
    )
    destination_iata: Optional[str] = Field(
        None,
        description=(
            "IATA airport code for destination. Leave null — resolved downstream by iata_resolver."
        ),
    )
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
            "True if user provided any date info in this message (month, dates, 'next week', etc.)"
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

    # ── Modification intents (Phase 2) ──
    removal_targets: List[str] = Field(
        default_factory=list,
        description=(
            "Activities/categories user wants to REMOVE from their plan. "
            'E.g., "skip hiking" -> ["hiking"], "remove yoga and diving" -> ["yoga", "diving"]. '
            "Empty list if no removal."
        ),
    )
    skill_level: Optional[str] = Field(
        None,
        description=(
            "Skill/experience level if mentioned: "
            "'beginner', 'intermediate', or 'advanced'. "
            "Map synonyms: novice/first time -> beginner, "
            "expert -> advanced. null if not mentioned."
        ),
    )
    traveler_style: Optional[str] = Field(
        None,
        description=(
            "Overall trip style/vibe if inferable from the message. One of: "
            "'adventure', 'relaxed', 'cultural', 'family', 'luxury', 'budget', 'romantic'. "
            "null if not inferable. Only set when the user's language clearly implies a style."
        ),
    )
    reset_budget: bool = Field(
        default=False,
        description=(
            "True ONLY if user wants to REMOVE/CLEAR their budget constraint. "
            "E.g., 'no budget limit', 'remove budget'. "
            "NOT true when user sets a new budget amount (that goes in budget field)."
        ),
    )
    multi_destination_detected: bool = Field(
        default=False,
        description=(
            "True if user mentioned MULTIPLE separate destinations "
            "(e.g., 'Rome and Switzerland', 'Paris then Tokyo'). "
            "NOT true for compound place names like 'Trinidad and Tobago'."
        ),
    )
    reset_hotel: bool = Field(
        default=False,
        description=(
            "True ONLY if user wants to CLEAR hotel preferences. "
            "E.g., 'any hotel is fine', 'reset hotel preferences'. "
            "NOT true when user sets new hotel prefs."
        ),
    )

    # ── Settings extraction (Phase 2) ──
    hotel_min_stars: Optional[int] = Field(
        None,
        description="Minimum hotel star rating (1-5) if mentioned. E.g., '4-star hotel' -> 4.",
    )
    hotel_style: Optional[str] = Field(
        None,
        description=(
            "Hotel style if mentioned: 'luxury', 'boutique', "
            "'budget', 'mid-range'. null if not mentioned."
        ),
    )
    hotel_amenities: List[str] = Field(
        default_factory=list,
        description=(
            "Requested hotel amenities: pool, spa, gym, "
            "breakfast, parking, wifi. Empty if none mentioned."
        ),
    )
    hotel_location: Optional[str] = Field(
        None,
        description=(
            "Hotel location preference: 'beachfront', "
            "'city_center', 'airport'. null if not mentioned."
        ),
    )
    flight_direct_only: Optional[bool] = Field(
        None,
        description=(
            "True if user wants direct/non-stop flights. "
            "False if explicitly wants connections. "
            "null if not mentioned."
        ),
    )
    flight_cabin_class: Optional[str] = Field(
        None,
        description=(
            "Cabin class if mentioned: 'economy', "
            "'premium_economy', 'business', 'first'. "
            "null if not mentioned."
        ),
    )

    # ── Intent classification (Phase 3) ──
    planning_intent: Optional[str] = Field(
        None,
        description=(
            "User's planning readiness. One of: "
            "'ready' (explicitly wants to plan/build: 'plan my trip', 'let's go'), "
            "'modifying' (changing existing plan: "
            "'extend to Feb 17', 'skip hiking', '4-star hotel'), "
            "'exploring' (asking questions: 'is Bali safe?', 'what's the weather?'), "
            "'greeting' (trivial: 'hi', 'thanks'). "
            "null if unclear."
        ),
    )
    question_type: Optional[str] = Field(
        None,
        description=(
            "If user asks a question about the destination, classify: "
            "weather, safety, costs, visa, transport, cultural, activities, "
            "accommodation, scams, packing, connectivity, money, couples, family. "
            "null if not a destination question."
        ),
    )
    date_auto_adjustments: List[Dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Any date corrections applied by backend validation. "
            "Each item has field/from/to/reason."
        ),
    )


# Pre-resolved flat schemas for Gemini-compatible structured output.
# Passing dicts (not classes) avoids LangChain's OpenAI function-calling
# wrapper which adds a top-level "parameters" key Gemini doesn't support.
_ROUTER_FLAT_SCHEMA: dict = gemini_safe_schema(
    strip_unsupported_schema_keys(resolve_schema_refs(RouterOutput.model_json_schema()))
)


# =============================================================================
# Prompts
# =============================================================================

# DEPRECATED: Unused — classification is handled by _classify_and_extract_with_llm().
# Retained as reference only. Do NOT call .format() on this without _sanitize_user_message().
CLASSIFICATION_PROMPT = (
    """You are an intent classifier for a travel planning assistant.

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
   - Activity mentions: """
    + _SPECIALIST_NAMES_CSV
    + """, etc.

## CRITICAL RULES

- If the user says "No" or "Yes" followed by ANY trip content, classify as PLANNING
- If unsure, default to PLANNING (let the architect handle it)
- Do NOT classify based on sentiment, only on intent
- "Stop in Rome" = PLANNING (layover), "Stop" alone = RESET

## Specialist Detection

If the message mentions activities like """
    + _SPECIALIST_NAMES_CSV
    + """,
include ALL matching specialists in the specialist_hints array.
For example, "diving and hiking trip" should return ["diving", "hiking"].

## User Message
"{user_message}"

Respond with valid JSON matching this schema:
{{
  "intent": "GREETING" | "RESET" | "PLANNING",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "specialist_hints": """
    + _SPECIALIST_HINTS_JSON
    + """
}}"""
)  # specialist_hints: array of matching activities, empty if none


# Extended prompt for full field extraction (used when we need dates/destination too)
# Extraction prompt — uses generic structural instructions only (Hard Rule 11).
# IATA resolution is handled downstream by iata_resolver.py.
ROUTER_EXTRACTION_PROMPT = (
    """You are an intent classifier AND field extractor \
for a travel planning assistant.
Today's date is {today_date}.
{current_trip_context}

## Task 1: Intent Classification

Classify the user message into ONE of:

1. **GREETING** - Simple greetings or thanks with NO planning content
2. **RESET** - Explicit requests to start over
3. **PLANNING** - Everything else related to trip planning

## Task 2: Field Extraction (for PLANNING intent)

Extract ANY trip-related fields mentioned:
- **destination**: Extract the PRIMARY CITY NAME ONLY, without country/region qualifiers
  - Remove country suffixes (keep only the city name)
  - Remove state/province qualifiers
  - Normalize to English (translate non-English city names to their common English form)
  - Expand common city abbreviations to full names
  - For country-only queries, let downstream resolution handle city selection
  - Keep compound city names that are official place names (e.g. cities with "City" in the name)
  - MULTI-DESTINATION: If user mentions MULTIPLE separate destinations,
    extract ONLY the first as destination. Set multi_destination_detected: true.
    Do NOT flag compound sovereign state names (e.g. "Trinidad and Tobago").
- **origin**: Same normalization rules as destination
- **origin_iata**: Leave null — IATA resolution is handled downstream
- **destination_iata**: Leave null — IATA resolution is handled downstream
- **start_date**: Convert to YYYY-MM-DD format. Examples:
  - "March 1" → "{current_year}-03-01"
  - "next Friday" → calculate from today
  - "February 15-22" → start_date = "{current_year}-02-15"
- **end_date**: Convert to YYYY-MM-DD format
  - "March 1-8" → end_date = "{current_year}-03-08"
  - IMPORTANT: When current trip context is provided and user says \
"extend by X days" or "add X more days": \
New end_date = current end_date + X days. \
Example: current trip Feb 15–25, "extend by 5 days" → end_date: {current_year}-03-02
  - "shorten to 5 days" → end_date = start_date + 4 days
  - "make it 2 weeks" → end_date = start_date + 13 days
- **duration_days**: If they say "for a week" = 7, "5 days" = 5
  - "weekend trip" / "weekend getaway" → duration_days = 3 (Fri-Sun or Sat-Mon)
  - "long weekend" → duration_days = 4
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

Include all matching specialists (use CANONICAL lowercase names):
"""
    + _SPECIALIST_KEYWORD_PROMPT
    + """

## Task 4: Activity Categories

Extract any activity categories the user mentions or implies.
Tier 2 is OPEN-ENDED — accept ANY recreational activity, not just a fixed list.
Use short canonical lowercase forms (e.g., "horseback riding" not "horseback riding lessons").
IMPORTANT: Use "cultural" (not "culture"), "food" (not "cuisine"), "tours" (not "tourist_attraction").

Common categories: """
    + _TIER2_EXAMPLES_CSV
    + """
But also accept: pottery, meditation, birdwatching, fishing, paragliding, horseback riding, etc.

Examples:
- "I want to party" → ["nightlife"]
- "explore local cuisine" → ["food", "cooking"]
- "relaxing trip with spa" → ["yoga", "wellness"]
- "diving and cooking" → ["cooking"] (diving goes in specialist_hints, not here)
- "temple tours and wine tasting" → ["tours", "wine"]
- "horseback riding and pottery class" → ["horseback riding", "pottery"]
- "local food and culture in Rome" → ["food", "cultural"]

Do NOT include Tier 1 specialist activities ("""
    + _SPECIALIST_NAMES_CSV
    + """) here — \
those go in specialist_hints.

## Task 5: Activity Day Preferences

If the user specifies day counts for activities, return a JSON STRING (not object):
- "3 days diving, 2 days hiking" → '{{"diving": 3, "hiking": 2}}'
- "mostly diving with a bit of hiking" → null (no explicit counts)
- "a week of surfing" → '{{"surfing": 7}}'
Only populate when user explicitly states numbers. null otherwise.

## Task 5b: Activities Per Day (Density Preference)

If the user specifies how many activities they want per day, return the number:
- "2 activities per day" -> 2
- "pack the days with stuff" -> null (no explicit count)
- "keep it to one thing a day" -> 1
- "I want 3 things to do each day" -> 3

Only populate when user explicitly states a number. null otherwise.

## Task 6: Modification Detection

If the user wants to REMOVE activities from their plan, populate removal_targets:
- "skip hiking" -> removal_targets: ["hiking"]
- "remove yoga and diving" -> removal_targets: ["yoga", "diving"]
- "I changed my mind about cycling" -> removal_targets: ["cycling"]

If the user specifies skill/experience level, populate skill_level:
- "I'm a beginner" -> "beginner"
- "expert level" -> "advanced"
- "first time diving" -> "beginner"

If the user wants to CLEAR constraints (not set new ones), use reset flags:
- "no budget limit" -> reset_budget: true
- "any hotel is fine" -> reset_hotel: true
- "budget of $3000" -> reset_budget: false, budget: 3000

## Task 6b: Traveler Style Detection

If the user's message implies a travel style, set traveler_style:
- "we're adventure junkies" → "adventure"
- "chill beach vacation" → "relaxed"
- "exploring temples and history" → "cultural"
- "traveling with my kids" → "family"
- "five-star all the way" → "luxury"
- "on a shoestring budget" → "budget"
- "honeymoon trip" → "romantic"

CRITICAL: Only set when the USER explicitly signals a style. Do NOT infer from destination alone, activities alone, or budget alone. null if unclear.

## Task 7: Settings Extraction

Extract hotel/flight preferences ONLY when explicitly stated:
- "4-star hotel" -> hotel_min_stars: 4
- "luxury resort with pool" -> hotel_style: "luxury", hotel_amenities: ["pool"]
- "beachfront hotel" -> hotel_location: "beachfront"
- "direct flights only" -> flight_direct_only: true
- "business class" -> flight_cabin_class: "business"

Never infer settings that aren't stated. "Nice hotel" != hotel_min_stars: 4.

## Task 8: Planning Intent Classification

Assess the user's readiness to plan:
- "ready": User explicitly wants to start/build/execute ("plan my trip", "let's do it", "book it",
  "build the itinerary"). Also when user provides BOTH dates AND activities.
- "modifying": User is changing parameters of an existing plan ("extend to Feb 17",
  "skip hiking", "make it 4-star", "budget $3000", "add yoga", "from Rome")
- "exploring": User is asking questions without committing ("is Bali safe?",
  "what's the weather like?", "tell me about temples")
- "greeting": Trivial social input ("hi", "thanks", "bye")

If user provides dates OR activities (but not both), use "modifying" — they're refining.

## Task 9: Question Classification

If the user is asking about a destination, classify the topic:
- weather/climate/rain/season/temperature → "weather"
- safe/dangerous/crime/security → "safety"
- cost/expensive/cheap/budget/afford/price → "costs"
- visa/passport/entry/immigration → "visa"
- transport/taxi/uber/scooter/getting around → "transport"
- wear/dress/clothes/cultural/customs → "cultural"
- must see/attractions/things to do → "activities"
- stay/hotel/neighborhood/area/resort → "accommodation"
- scam/rip off/tourist trap → "scams"
- pack/bring/luggage → "packing"
- sim/wifi/internet/phone → "connectivity"
- tip/tipping/currency/money/atm → "money"
- couples/romantic/honeymoon → "couples"
- family/kids/children → "family"
null if not a destination question.

## User Message
"{user_message}"

Respond with valid JSON. Only include fields that are explicitly mentioned."""
)


# =============================================================================
# LLM Factories
# =============================================================================


def _get_router_extraction_llm():
    """Get the LLM for full Router extraction (intent + fields)."""
    return get_llm_by_model(
        settings.router_model,
        temperature=0,  # Deterministic extraction
        max_tokens=700,  # Need more tokens for field extraction + activity_categories
    )


# =============================================================================
# Normalization & Validation
# =============================================================================


def _normalize_city_name(city: str) -> str:
    """
    Fallback normalization for city names extracted by LLM.

    Ensures consistent cache keys by:
    - Removing country/state suffixes (", USA", ", Indonesia", etc.)

    The LLM prompt instructs extraction without qualifiers and handles
    abbreviation expansion (NYC → New York, etc.).
    """
    if not city:
        return city

    city = city.strip()

    # Remove common country/state suffixes (case-insensitive)
    suffixes = [
        ", USA",
        ", US",
        ", United States",
        ", America",
        ", Indonesia",
        ", ID",
        ", France",
        ", FR",
        ", Italy",
        ", IT",
        ", Thailand",
        ", TH",
        ", UK",
        ", United Kingdom",
        ", England",
        ", Spain",
        ", ES",
        ", Japan",
        ", JP",
        ", Australia",
        ", AU",
        ", Mexico",
        ", MX",
        ", Canada",
        ", CA",
        ", Germany",
        ", DE",
        ", UAE",
        ", United Arab Emirates",
        ", NY",
        ", CA",
        ", TX",
        ", FL",  # US states
    ]

    for suffix in suffixes:
        if city.lower().endswith(suffix.lower()):
            city = city[: -len(suffix)].strip()
            break

    return city


def _validate_extraction(extracted: dict, today_date: str, user_message: str = "") -> dict:
    """
    Validate and clean LLM-extracted trip data.

    Ensures:
    - Dates are valid ISO 8601 format (YYYY-MM-DD)
    - Date range is logical (end >= start)
    - Activity categories are lowercase
    - Traveler counts are positive integers
    - Destinations/origins are normalized

    Args:
        extracted: Raw extraction from LLM
        today_date: Current date for context

    Returns:
        Cleaned/validated extraction dict
    """
    # Validate date format (must be YYYY-MM-DD)
    for date_field in ["start_date", "end_date"]:
        if extracted.get(date_field):
            try:
                datetime.strptime(extracted[date_field], "%Y-%m-%d")
            except ValueError:
                logger.warning(f"Invalid {date_field} format: {extracted[date_field]}")
                extracted[date_field] = None

    # Parse valid date objects once for range normalization.
    start_date_obj: Optional[datetime.date] = None
    end_date_obj: Optional[datetime.date] = None
    date_auto_adjustments: list[dict[str, str]] = []
    if extracted.get("start_date"):
        start_date_obj = datetime.strptime(extracted["start_date"], "%Y-%m-%d").date()
    if extracted.get("end_date"):
        end_date_obj = datetime.strptime(extracted["end_date"], "%Y-%m-%d").date()

    # Validate initial date logic (end >= start)
    if start_date_obj and end_date_obj and end_date_obj < start_date_obj:
        logger.warning("end_date before start_date, swapping")
        start_date_obj, end_date_obj = end_date_obj, start_date_obj
        extracted["start_date"] = start_date_obj.isoformat()
        extracted["end_date"] = end_date_obj.isoformat()

    def _bump_year_safe(date_value: datetime.date) -> datetime.date:
        """Always bump +1 year (used for end_date cross-year adjustment)."""
        target_year = date_value.year + 1
        max_day = monthrange(target_year, date_value.month)[1]
        return date_value.replace(year=target_year, day=min(date_value.day, max_day))

    def _bump_to_next_occurrence(date_value: datetime.date, today: datetime.date) -> datetime.date:
        """Try same-year first (date may still be upcoming), otherwise next year."""
        max_day_same = monthrange(today.year, date_value.month)[1]
        same_year = date_value.replace(year=today.year, day=min(date_value.day, max_day_same))
        if same_year >= today:
            return same_year
        target_year = today.year + 1
        max_day_next = monthrange(target_year, date_value.month)[1]
        return date_value.replace(year=target_year, day=min(date_value.day, max_day_next))

    def _auto_bump_past_date(
        *,
        field_name: str,
        date_value: Optional[datetime.date],
        today: datetime.date,
    ) -> tuple[Optional[datetime.date], bool]:
        if date_value is None or date_value >= today:
            return date_value, False
        # Tolerance: dates within the past 7 days are likely intentional
        days_past = (today - date_value).days
        if days_past <= 7:
            return date_value, False
        bumped = _bump_to_next_occurrence(date_value, today)
        logger.warning(
            f"Past {field_name}: {date_value.isoformat()} → {bumped.isoformat()} "
            f"(auto-bumped to next occurrence, today={today_date})"
        )
        extracted[field_name] = bumped.isoformat()
        date_auto_adjustments.append(
            {
                "field": field_name,
                "from": date_value.isoformat(),
                "to": bumped.isoformat(),
                "reason": "past_date_auto_bumped",
            }
        )
        return bumped, True

    # Auto-correct past dates — LLM sometimes picks wrong year for NL input
    # "Feb 15" in the past almost certainly means next Feb 15.
    today = datetime.strptime(today_date, "%Y-%m-%d").date()

    start_bumped = False
    end_bumped = False
    start_date_obj, start_bumped = _auto_bump_past_date(
        field_name="start_date",
        date_value=start_date_obj,
        today=today,
    )
    end_date_obj, end_bumped = _auto_bump_past_date(
        field_name="end_date",
        date_value=end_date_obj,
        today=today,
    )

    # If start_date moved to next year but end_date did not, keep the intended range
    # by bumping end_date as well when needed.
    if (
        start_bumped
        and not end_bumped
        and start_date_obj is not None
        and end_date_obj is not None
        and end_date_obj < start_date_obj
    ):
        previous_end = end_date_obj
        adjusted_end = _bump_year_safe(previous_end)
        if adjusted_end >= start_date_obj:
            logger.warning(
                f"Adjusted end_date year to preserve range: {previous_end.isoformat()} → "
                f"{adjusted_end.isoformat()} (start_date={start_date_obj.isoformat()})"
            )
            end_date_obj = adjusted_end
            extracted["end_date"] = adjusted_end.isoformat()
            date_auto_adjustments.append(
                {
                    "field": "end_date",
                    "from": previous_end.isoformat(),
                    "to": adjusted_end.isoformat(),
                    "reason": "preserve_range_after_start_bump",
                }
            )

    # Final safety guard after all normalization.
    if start_date_obj and end_date_obj and end_date_obj < start_date_obj:
        logger.warning("end_date before start_date after normalization, swapping")
        start_date_obj, end_date_obj = end_date_obj, start_date_obj
        extracted["start_date"] = start_date_obj.isoformat()
        extracted["end_date"] = end_date_obj.isoformat()

    lowered_message = user_message.lower()
    if extracted.get("duration_days") is None and lowered_message:
        if re.search(r"\blong\s+weekend\b", lowered_message):
            extracted["duration_days"] = 4
        elif re.search(r"\bweekend(?:\s+(?:trip|getaway|break))?\b", lowered_message):
            extracted["duration_days"] = 3

    # Normalize activity categories to lowercase
    if extracted.get("activity_categories"):
        extracted["activity_categories"] = [
            cat.lower().strip() for cat in extracted["activity_categories"]
        ]

    # Normalize specialist_hints to lowercase (if present)
    if extracted.get("specialist_hints"):
        extracted["specialist_hints"] = [
            hint.lower().strip() for hint in extracted["specialist_hints"]
        ]

    # Ensure traveler counts are positive integers
    if extracted.get("adults") is not None:
        extracted["adults"] = max(1, int(extracted.get("adults") or 1))
    if extracted.get("children") is not None:
        extracted["children"] = max(0, int(extracted.get("children") or 0))

    # Normalize destination/origin (safety net for LLM variations)
    for field in ["destination", "origin"]:
        if extracted.get(field):
            extracted[field] = _normalize_city_name(extracted[field])

    extracted["date_auto_adjustments"] = date_auto_adjustments

    return extracted


def _build_current_trip_context(state: "GraphState") -> str:
    """Build prompt context used for relative-date extraction."""
    tp = state.trip_plan
    if not tp or not tp.destination or not tp.start_date or not tp.end_date:
        return ""

    try:
        start = datetime.strptime(tp.start_date, "%Y-%m-%d")
        end = datetime.strptime(tp.end_date, "%Y-%m-%d")
    except ValueError:
        return ""

    duration = (end - start).days + 1
    context = f"Current trip: {tp.destination}, {tp.start_date} to {tp.end_date} ({duration} days)"

    # Include current activities so LLM can infer removal from implicit switch language
    categories = (
        state.metadata.get("trip_settings", {}).get("activity_settings", {}).get("categories", [])
    )
    if categories:
        context += f"\nCurrent activities: {', '.join(categories)}"
    return context


def _build_context_fingerprint(current_trip_context: str) -> str:
    """Stable hash of prompt-level context dimensions that affect extraction."""
    if not current_trip_context:
        return ""
    return hashlib.sha256(current_trip_context.encode()).hexdigest()[:16]


# =============================================================================
# LLM Extraction
# =============================================================================


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
    - Key includes today_date + current_trip_context fingerprint
    - 1h TTL (conversational context is short-lived)

    Returns tuple of (RouterOutput, token_usage_dict).
    """
    from app.services.router_cache import get_cached_extraction, set_cached_extraction

    today = datetime.now()
    today_date = today.strftime("%Y-%m-%d")
    current_trip_context = _build_current_trip_context(state)
    context_fingerprint = _build_context_fingerprint(current_trip_context)

    # =========================================================================
    # CACHE CHECK
    # =========================================================================
    cached = get_cached_extraction(
        user_text,
        today_date,
        context_fingerprint=context_fingerprint,
    )
    if cached is not None:
        try:
            output = RouterOutput.model_validate(cached)
            logger.debug(f"[ROUTER] Cache HIT: intent={output.intent}, dest={output.destination}")
            return output, {}  # Empty token_usage for cache hit
        except Exception as e:
            logger.debug(f"[ROUTER] Cache deserialize failed: {e}")

    # =========================================================================
    # CACHE MISS - LLM CALL (with retry)
    # =========================================================================
    MAX_RETRIES = 1
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            llm = _get_router_extraction_llm()

            # Use pre-resolved flat schema (dict, not class) to avoid
            # LangChain wrapping it with a "parameters" key Gemini rejects.
            structured_llm = llm.with_structured_output(
                dict(_ROUTER_FLAT_SCHEMA), include_raw=True, method="function_calling"
            )

            # Format prompt with current date context
            current_year = today.year
            prompt = ROUTER_EXTRACTION_PROMPT.format(
                user_message=_sanitize_user_message(user_text),
                today_date=today_date,
                current_year=current_year,
                current_trip_context=current_trip_context,
            )

            result = await structured_llm.ainvoke([HumanMessage(content=prompt)])

            # Extract parsed result and token usage
            parsed = result["parsed"]
            if parsed is None:
                raise ValueError("Structured output returned None (likely ambiguous short input)")
            raw = result["raw"]
            from app.planner.llm_factory import extract_token_usage

            token_usage = extract_token_usage(raw, model=settings.router_model)

            # =================================================================
            # VALIDATE & NORMALIZE EXTRACTED FIELDS
            # Ensures consistent cache keys (e.g., "Bali, Indonesia" → "Bali")
            # =================================================================
            parsed_dict = parsed if isinstance(parsed, dict) else parsed.model_dump()
            validated_dict = _validate_extraction(parsed_dict, today_date, user_text)
            parsed = RouterOutput.model_validate(validated_dict)

            if attempt > 0:
                logger.warning(f"[ROUTER] Extraction succeeded on retry {attempt + 1}")

            logger.debug(
                f"Router extraction: intent={parsed.intent}, "
                f"dest={parsed.destination}, dates={parsed.start_date}->{parsed.end_date}, "
                f"has_dates={parsed.has_dates_in_message}, planning_ready={parsed.planning_ready}"
            )

            # =================================================================
            # CACHE WRITE (only if self-contained query)
            # =================================================================
            set_cached_extraction(
                user_text,
                today_date,
                parsed.model_dump(),
                context_fingerprint=context_fingerprint,
            )

            return parsed, token_usage

        except Exception as e:
            last_exc = e
            raw_text = getattr(e, "response", None) or str(e)
            logger.error(
                f"[ROUTER] Extraction attempt {attempt + 1}/{MAX_RETRIES + 1} FAILED: {raw_text}"
            )
            if attempt < MAX_RETRIES:
                continue

    # All retries exhausted — raise, let caller handle
    logger.error("[ROUTER] ALL extraction attempts failed — raising to caller")
    raise last_exc  # type: ignore[misc]


# =============================================================================
# Lightweight Change Type Classification (small schema for Gemini)
# =============================================================================

_CHANGE_TYPE_PROMPT = (
    """You are a change classifier for a travel planning system.

## Current Trip State
{trip_state_json}

## Extracted Fields From This Message
{extracted_fields_json}

## Existing Specialist Plans
{existing_specialists_json}

## Task
Classify how the user message changes the existing trip plan.

### intent (MUST be one of):
- "GREETING" — social/greeting input
- "RESET" — user wants to start over
- "QUESTION" — user is asking a question, not changing the plan
- "PLANNING" — user is building or modifying the plan

### change_type (MUST be one of):
- "initial_plan" — first planning message, no existing plan
- "day_count" — changed day counts for an activity ("3 dive days not 4")
- "spatial" — changed spatial arrangement ("move hiking near dives")
- "swap_activity" — replace one activity with another
- "add_activity" — add a new activity to existing plan
- "remove_activity" — remove an activity from the plan
- "date_change" — dates changed
- "destination_change" — destination changed (invalidates ALL specialists)
- "preference" — general preference ("more relaxed pace")
- "logistics" — logistics preference ("direct flights only")
- "settings" — hotel/flight settings ("5-star hotels")
- "question" — asking a question (not changing plan)
- "greeting" — social greeting
- "reset" — explicit reset

### affects / preserves / informs:
- **affects**: Specialist domains that need re-dispatch (lowercase canonical names)
- **preserves**: Domains whose cached results stay valid
- **informs**: Domains that should know about the change but don't re-run

Rules:
- affects values must be Tier 1 specialist names only ("""
    + _SPECIALIST_NAMES_CSV
    + """). Never include "local_expert", "logistics", or infrastructure keys.
- GREETING → change_type="greeting", empty affects/preserves/informs
- RESET → change_type="reset", empty affects/preserves/informs
- QUESTION → change_type="question", empty affects/preserves/informs
- No existing plan → change_type="initial_plan"
- destination_change → affects=ALL existing specialists
- If removal_targets is non-empty AND (activity_categories or specialist_hints is non-empty) → change_type="swap_activity"
- If only removal_targets is non-empty → change_type="remove_activity"
- "switch to X", "replace X with Y", "X instead of Y" → swap_activity
- day_count/swap/add/remove/spatial → affects=only relevant specialists

## User Message
"{user_message}"

Respond with valid JSON matching the schema exactly."""
)


async def _classify_change_type(
    user_message: str,
    router_output: "RouterOutput",
    trip_state_summary: Dict[str, Any],
    *,
    model: Optional[str] = None,
) -> "ChangeClassification":
    """Lightweight change classification using a small 6-field schema.

    This schema is small enough for Gemini function calling (~6 fields, 1 enum)
    whereas the full ClassifierOutput (~40 fields, 14-value enum) triggers
    Gemini's "too much branching" rejection.

    Args:
        user_message: Raw user input text.
        router_output: Already-extracted RouterOutput from step 1.
        trip_state_summary: Compact trip state from build_trip_state_summary().
        model: Optional model override.

    Returns:
        ChangeClassification with intent, change_type, affects, preserves, informs.
    """
    from app.planner.llm_factory import extract_token_usage
    from app.planner.schemas.coordinator_schemas import ChangeClassification

    resolved_model = model or settings.router_model

    # Build compact extracted fields summary for the prompt
    extracted_fields = {
        k: v
        for k, v in {
            "destination": router_output.destination,
            "origin": router_output.origin,
            "start_date": router_output.start_date,
            "end_date": router_output.end_date,
            "duration_days": router_output.duration_days,
            "budget": router_output.budget,
            "specialist_hints": router_output.specialist_hints,
            "activity_categories": router_output.activity_categories,
            "removal_targets": router_output.removal_targets,
            "intent": router_output.intent,
            "planning_ready": router_output.planning_ready,
            "skill_level": router_output.skill_level,
            "activity_day_preferences": router_output.activity_day_preferences,
        }.items()
        if v is not None and v != [] and v != ""
    }

    existing_specialists = sorted(
        str(k).lower() for k in (trip_state_summary.get("specialist_plans", {}) or {}).keys() if k
    )

    trip_state_json = json.dumps(trip_state_summary, indent=2) if trip_state_summary else "{}"

    prompt = _CHANGE_TYPE_PROMPT.format(
        trip_state_json=trip_state_json,
        extracted_fields_json=json.dumps(extracted_fields, indent=2),
        existing_specialists_json=json.dumps(existing_specialists),
        user_message=_sanitize_user_message(user_message),
    )

    llm = get_llm_by_model(resolved_model, temperature=0, max_tokens=400)

    # ChangeClassification is 6 fields — well within Gemini's limits
    classifier_schema = gemini_safe_schema(
        strip_unsupported_schema_keys(resolve_schema_refs(ChangeClassification.model_json_schema()))
    )
    structured_llm = llm.with_structured_output(
        dict(classifier_schema),
        include_raw=True,
        method="function_calling",
    )

    for _attempt in range(2):
        try:
            result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
            break
        except Exception:
            if _attempt == 0:
                await asyncio.sleep(1)
                continue
            raise

    parsed_payload = result["parsed"] if isinstance(result, dict) else result
    if parsed_payload is None:
        raise ValueError("Structured output returned None for _classify_change_type")

    if isinstance(parsed_payload, ChangeClassification):
        parsed_dict = parsed_payload.model_dump()
    elif isinstance(parsed_payload, dict):
        parsed_dict = parsed_payload
    elif hasattr(parsed_payload, "model_dump"):
        parsed_dict = parsed_payload.model_dump()
    else:
        raise ValueError(
            f"Unexpected payload type for _classify_change_type: {type(parsed_payload).__name__}"
        )

    raw = result.get("raw") if isinstance(result, dict) else None
    token_usage = extract_token_usage(raw, model=resolved_model)

    parsed = ChangeClassification.model_validate(parsed_dict)

    logger.info(
        "[CLASSIFIER] change_type=%s affects=%s preserves=%s informs=%s (tokens=%s)",
        parsed.change_type,
        parsed.affects,
        parsed.preserves,
        parsed.informs,
        token_usage,
    )

    return parsed


def _heuristic_change_classification(
    router_output: "RouterOutput",
    trip_state_summary: Dict[str, Any],
) -> "ChangeClassification":
    """Heuristic fallback: derive change classification from RouterOutput fields.

    Called when the lightweight LLM classification also fails (double safety net).
    This is the same logic that was previously inline in classify_change()'s
    fallback path, extracted into a reusable helper.
    """
    from app.planner.schemas.coordinator_schemas import (
        ChangeClassification,
        ChangeType,
    )

    summary = trip_state_summary or {}
    existing_topics = {
        str(k).lower() for k in (summary.get("specialist_plans", {}) or {}).keys() if k
    }

    intent = router_output.intent  # RouterOutput has 3 intents: GREETING/RESET/PLANNING
    # Promote to QUESTION if RouterOutput says PLANNING but no plan fields extracted
    has_plan_fields = bool(
        router_output.destination
        or router_output.start_date
        or router_output.end_date
        or router_output.specialist_hints
        or router_output.activity_categories
        or router_output.removal_targets
        or router_output.planning_ready
        or router_output.budget
    )
    if intent == "PLANNING" and not has_plan_fields and router_output.question_type:
        intent = "QUESTION"

    affects = sorted(
        {
            t.lower()
            for t in router_output.specialist_hints
            if isinstance(t, str) and t.lower() in TIER1_SPECIALIST_NAMES
        }
    )
    preserves = sorted([t for t in existing_topics if t not in set(affects)])

    fields_changed: List[str] = []
    for field in (
        "destination",
        "origin",
        "start_date",
        "end_date",
        "budget",
        "adults",
        "children",
    ):
        if getattr(router_output, field, None) is not None:
            fields_changed.append(field)
    if router_output.activity_categories:
        fields_changed.append("activity_categories")

    has_existing_plan = bool(existing_topics or summary.get("has_itinerary"))

    if intent == "GREETING":
        change_type = ChangeType.GREETING
    elif intent == "RESET":
        change_type = ChangeType.RESET
    elif intent == "QUESTION":
        change_type = ChangeType.QUESTION
    elif (
        router_output.destination
        and summary.get("destination")
        and str(router_output.destination).strip().lower()
        != str(summary.get("destination")).strip().lower()
    ):
        change_type = ChangeType.DESTINATION_CHANGE
        # Force-reset: stale specialist_hints from prior destination are invalid.
        # Coordinator re-derives specialists from active categories on next plan.
        affects = []
        preserves = list(existing_topics)
    elif router_output.start_date or router_output.end_date:
        change_type = ChangeType.DATE_CHANGE if has_existing_plan else ChangeType.INITIAL_PLAN
    elif (
        router_output.removal_targets
        and (router_output.activity_categories or router_output.specialist_hints)
        and has_existing_plan
    ):
        change_type = ChangeType.SWAP_ACTIVITY
    elif router_output.removal_targets and has_existing_plan:
        change_type = ChangeType.REMOVE_ACTIVITY
    elif router_output.activity_categories or affects:
        change_type = ChangeType.ADD_ACTIVITY if has_existing_plan else ChangeType.INITIAL_PLAN
    else:
        change_type = ChangeType.INITIAL_PLAN if not has_existing_plan else ChangeType.PREFERENCE

    return ChangeClassification(
        intent=intent,  # type: ignore[arg-type]  # str reassigned from Literal; runtime values always valid
        change_type=change_type,
        fields_changed=fields_changed,
        affects=affects,
        preserves=preserves,
        informs=[],
    )


async def classify_change(
    user_message: str,
    trip_state_summary: Dict[str, Any],
    *,
    model: Optional[str] = None,
) -> "ClassifierOutput":
    """Classify user intent AND analyze what changed relative to current trip state.

    Two-step approach that works with Gemini:
      1. Proven ``_classify_and_extract_with_llm()`` → RouterOutput (~27 fields)
      2. Lightweight ``_classify_change_type()``       → ChangeClassification (6 fields)
      3. Merge both into ``ClassifierOutput``

    The full ClassifierOutput (~40 fields, 14-value enum) triggers Gemini's
    ``400 INVALID_ARGUMENT: too much branching`` rejection on every call.
    Splitting into two small schemas avoids this entirely while producing
    the same (richer) output.

    Args:
        user_message: Raw user input text.
        trip_state_summary: Compact trip state dict from ``build_trip_state_summary()``.
        model: Optional model override (defaults to ``settings.router_model``).

    Returns:
        ClassifierOutput with both extraction fields and change classification.

    Raises:
        ValueError: If both router extraction and heuristic fallback fail.
    """
    from app.planner.schemas.coordinator_schemas import ChangeType, ClassifierOutput

    # =========================================================================
    # Short-circuit: empty/whitespace messages → GREETING (W9)
    # Avoids wasting an LLM call on no-content input.
    # =========================================================================
    if not user_message or not user_message.strip():
        return ClassifierOutput(
            intent="GREETING",
            change_type=ChangeType.GREETING,
            reasoning="Empty message — treated as greeting",
            confidence=1.0,
        )

    # =========================================================================
    # Short-circuit: GENERATE_PLAN_NOW / GENERATE_PLAN_TRIGGER
    # Saves one LLM call and ensures consistent full-rebuild behavior.
    # =========================================================================
    if user_message.strip().upper() in ("GENERATE_PLAN_NOW", "GENERATE_PLAN_TRIGGER"):
        return ClassifierOutput(
            intent="PLANNING",
            change_type=ChangeType.INITIAL_PLAN,
            reasoning="GENERATE_PLAN_NOW trigger — full rebuild",
            fields_changed=[],
            affects=[],
        )

    # =========================================================================
    # Step 1: Proven router extraction (RouterOutput, ~27 fields — works with Gemini)
    # =========================================================================
    summary = trip_state_summary or {}
    dates = summary.get("dates", {}) if isinstance(summary.get("dates"), dict) else {}
    from app.planner.state.graph_state import TripPlan

    fallback_state = GraphState(
        trip_plan=TripPlan(
            destination=summary.get("destination"),
            origin=summary.get("origin"),
            start_date=dates.get("start"),
            end_date=dates.get("end"),
            adults=summary.get("adults", 1) or 1,
            children=summary.get("children", 0) or 0,
            budget=summary.get("budget"),
        ),
        metadata={
            "trip_settings": {
                "activity_settings": {
                    "categories": summary.get("categories", []),
                },
            },
        },
    )

    router_output, _ = await _classify_and_extract_with_llm(user_message, fallback_state)
    # _classify_and_extract_with_llm already validates/normalizes internally (line 871)

    # =========================================================================
    # Step 2: Lightweight change classification (6 fields — works with Gemini)
    # =========================================================================
    try:
        change_cls = await _classify_change_type(
            user_message,
            router_output,
            summary,
            model=model,
        )
        logger.info(
            "[CLASSIFIER] LLM change classification succeeded: "
            "intent=%s change_type=%s affects=%s preserves=%s",
            change_cls.intent,
            change_cls.change_type,
            change_cls.affects,
            change_cls.preserves,
        )
    except Exception as e:
        logger.warning(
            "[CLASSIFIER] Lightweight change classification failed (%s), using heuristic fallback",
            str(e),
        )
        change_cls = _heuristic_change_classification(router_output, summary)
        logger.info(
            "[CLASSIFIER] Heuristic fallback: intent=%s change_type=%s affects=%s preserves=%s",
            change_cls.intent,
            change_cls.change_type,
            change_cls.affects,
            change_cls.preserves,
        )

    # =========================================================================
    # Step 3: Merge RouterOutput + ChangeClassification → ClassifierOutput
    # =========================================================================
    merged = router_output.model_dump()
    merged.update(
        {
            "intent": change_cls.intent,
            "change_type": change_cls.change_type,
            "fields_changed": change_cls.fields_changed,
            "affects": change_cls.affects,
            "preserves": change_cls.preserves,
            "informs": change_cls.informs,
        }
    )
    result = ClassifierOutput.model_validate(merged)

    logger.info(
        "[CLASSIFIER] change_type=%s fields_changed=%s affects=%s preserves=%s",
        result.change_type,
        result.fields_changed,
        result.affects,
        result.preserves,
    )
    logger.debug(
        "[CLASSIFIER] intent=%s dest=%s dates=%s->%s",
        result.intent,
        result.destination,
        result.start_date,
        result.end_date,
    )

    return result


# =============================================================================
# State Population
# =============================================================================


def _clamp_date_str(date_str: str) -> str | None:
    """Parse YYYY-MM-DD, clamping day to last valid day of month. None if unparseable."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if month < 1 or month > 12:
        return None
    max_day = monthrange(year, month)[1]
    clamped_day = min(day, max_day)
    clamped = f"{year:04d}-{month:02d}-{clamped_day:02d}"
    logger.info(f"Clamped date {date_str} -> {clamped} (month has {max_day} days)")
    return clamped
