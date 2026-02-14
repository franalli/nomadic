"""
Router Extraction Core — LLM-based intent classification and field extraction.

Handles:
- RouterOutput schema (intent + extracted fields)
- LLM prompts for classification and extraction
- Unified extraction with L1 caching
- Field normalization and validation
- State population from extraction results
"""

import json
import logging
import re
from calendar import monthrange
from datetime import datetime, timedelta
from typing import List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.planner.llm_factory import get_llm_by_model
from app.planner.specialist_registry import (
    ALL_SPECIALIST_KEYWORDS,
    TIER1_SPECIALIST_NAMES,
    TIER2_ACTIVITY_KEYWORDS,
)
from app.planner.state import GraphState
from app.planner.state.typed_meta import get_trip_settings

logger = logging.getLogger(__name__)

# Derived prompt fragments — single source of truth from registry
_SPECIALIST_NAMES_CSV = ", ".join(sorted(TIER1_SPECIALIST_NAMES))
_SPECIALIST_HINTS_JSON = json.dumps(sorted(TIER1_SPECIALIST_NAMES))
_TIER2_NAMES_CSV = ", ".join(sorted(TIER2_ACTIVITY_KEYWORDS))


def _build_specialist_keyword_prompt() -> str:
    lines = []
    for topic in sorted(ALL_SPECIALIST_KEYWORDS):
        aliases = ALL_SPECIALIST_KEYWORDS[topic][:5]
        quoted = ", ".join(f'"{a}"' for a in aliases)
        lines.append(f'- {quoted} -> "{topic}"')
    return "\n".join(lines)


_SPECIALIST_KEYWORD_PROMPT = _build_specialist_keyword_prompt()


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

    # Tier 2 activity categories (yoga, cooking, nightlife, etc.)
    activity_categories: List[str] = Field(
        default_factory=list,
        description=f"Activity categories mentioned: {_TIER2_NAMES_CSV}",
    )

    # Activity day preferences as JSON string (gpt-4o-mini handles str better than Dict)
    activity_day_preferences: Optional[str] = Field(
        None,
        description=(
            "JSON string of day counts per activity when user explicitly states numbers. "
            'E.g., "3 days diving" -> \'{"diving": 3}\'. null if not specified.'
        ),
    )

    # Extracted trip fields (populated when intent=PLANNING)
    destination: Optional[str] = Field(None, description="Destination city/country if mentioned")
    origin: Optional[str] = Field(None, description="Origin city if mentioned")
    origin_iata: Optional[str] = Field(
        None,
        description=(
            "IATA airport code for origin city (e.g. SFO, LHR, CDG). "
            "Use primary international airport."
        ),
    )
    destination_iata: Optional[str] = Field(
        None,
        description=(
            "IATA airport code for destination (e.g. DPS, CDG, DXB). "
            "Use primary international airport."
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


# =============================================================================
# Prompts
# =============================================================================

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
- **destination**: Extract PRIMARY CITY NAME ONLY, without country/region qualifiers
  - Remove country suffixes: "Paris, France" → "Paris", "Bali, Indonesia" → "Bali"
  - Remove state/province: "New York, NY" → "New York"
  - Use English names: "Roma" → "Rome", "München" → "Munich"
  - Expand abbreviations: "NYC" → "New York", "LA" → "Los Angeles"
  - For country-only queries, use primary city: "Indonesia" → "Bali", "UAE" → "Dubai"
  - Edge cases to keep as-is: "Mexico City", "Kansas City", "Washington DC"
  - MULTI-DESTINATION: If user mentions MULTIPLE separate destinations
    (e.g., "Rome and Switzerland", "Paris, Tokyo, Bali"),
    extract ONLY the first as destination. Set multi_destination_detected: true.
    Do NOT flag compound place names like "Trinidad and Tobago" or "St. Kitts and Nevis".
- **origin**: Same normalization rules as destination
- **origin_iata**: IATA airport code for origin (e.g. "San Francisco" → "SFO", "London" → "LHR")
  - Use the PRIMARY/closest international airport
  - Mountain resorts use nearest major airport: "Chamonix" → "GVA", "Whistler" → "YVR"
- **destination_iata**: Same rules (e.g. "Bali" → "DPS", "Paris" → "CDG")
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

Extract any activity categories the user mentions or implies. Use these canonical names:
"""
    + _TIER2_NAMES_CSV
    + """

Examples:
- "I want to party" → ["nightlife"]
- "explore local cuisine" → ["cooking", "food"]
- "relaxing trip with spa" → ["yoga", "wellness"]
- "diving and cooking" → ["cooking"] (diving goes in specialist_hints, not here)
- "temple tours and wine tasting" → ["temples", "wine"]

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


def _get_router_llm():
    """Get the fast LLM for intent classification."""
    return get_llm_by_model(
        settings.router_model,
        temperature=0,  # Deterministic classification
        max_tokens=150,  # Classification is short
    )


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
    - Expanding common abbreviations (NYC → New York)

    The LLM prompt also instructs extraction without qualifiers,
    but this provides a safety net for edge cases.
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

    # Handle known abbreviations
    abbreviations = {
        "NYC": "New York",
        "LA": "Los Angeles",
        "SF": "San Francisco",
        "DC": "Washington DC",  # Disambiguate from Washington state
        "PHILLY": "Philadelphia",
    }

    return abbreviations.get(city.upper(), city)


def _validate_extraction(extracted: dict, today_date: str) -> dict:
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

    # Validate date logic (end >= start)
    if extracted.get("start_date") and extracted.get("end_date"):
        start = datetime.strptime(extracted["start_date"], "%Y-%m-%d")
        end = datetime.strptime(extracted["end_date"], "%Y-%m-%d")
        if end < start:
            logger.warning("end_date before start_date, swapping")
            extracted["start_date"], extracted["end_date"] = (
                extracted["end_date"],
                extracted["start_date"],
            )

    # Auto-correct past dates — LLM sometimes picks wrong year for NL input
    # "Feb 15" in the past almost certainly means next Feb 15
    today = datetime.strptime(today_date, "%Y-%m-%d").date()
    for date_field in ["start_date", "end_date"]:
        if extracted.get(date_field):
            try:
                d = datetime.strptime(extracted[date_field], "%Y-%m-%d").date()
                if d < today:
                    bumped = d.replace(year=d.year + 1)
                    # Handle Feb 29 → Feb 28 on non-leap years
                    if d.month == 2 and d.day == 29:
                        max_day = monthrange(bumped.year, bumped.month)[1]
                        bumped = bumped.replace(day=min(bumped.day, max_day))
                    logger.warning(
                        f"Past {date_field}: {extracted[date_field]} → {bumped.isoformat()} "
                        f"(auto-bumped +1yr, today={today_date})"
                    )
                    extracted[date_field] = bumped.isoformat()
            except ValueError:
                pass  # Already handled by format check above

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

    return extracted


def _parse_day_preferences(raw: Optional[str], user_text: str = "") -> dict[str, int]:
    """Parse activity_day_preferences JSON string → dict. Returns {} on failure.

    Guards against LLM hallucination: day preferences require the user to state
    a number (e.g. "3 days diving"). If the user message contains no digits,
    the LLM is inferring counts from trip duration — reject those.
    """
    if not raw:
        return {}
    if user_text and not any(c.isdigit() for c in user_text):
        logger.info(f"[ROUTER] Ignoring hallucinated day_preferences: {raw} (no digits)")
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {k.lower().strip(): int(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning(f"Invalid activity_day_preferences JSON: {raw}")
    return {}


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
    - Key includes today_date for relative date resolution
    - 1h TTL (conversational context is short-lived)

    Returns tuple of (RouterOutput, token_usage_dict).
    """
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
    # CACHE MISS - LLM CALL (with retry)
    # =========================================================================
    MAX_RETRIES = 1
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            llm = _get_router_extraction_llm()

            # Use structured output for reliable JSON parsing
            structured_llm = llm.with_structured_output(RouterOutput, include_raw=True)

            # Build current trip context for relative date expressions
            current_trip_context = ""
            tp = state.trip_plan
            if tp and tp.destination and tp.start_date and tp.end_date:
                try:
                    s = datetime.strptime(tp.start_date, "%Y-%m-%d")
                    e = datetime.strptime(tp.end_date, "%Y-%m-%d")
                    dur = (e - s).days + 1
                    current_trip_context = (
                        f"Current trip: {tp.destination}, "
                        f"{tp.start_date} to {tp.end_date} ({dur} days)"
                    )
                except ValueError:
                    pass

            # Format prompt with current date context
            current_year = today.year
            prompt = ROUTER_EXTRACTION_PROMPT.format(
                user_message=user_text,
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
            token_usage = {}
            if hasattr(raw, "response_metadata"):
                token_usage = raw.response_metadata.get("token_usage", {})

            # =================================================================
            # VALIDATE & NORMALIZE EXTRACTED FIELDS
            # Ensures consistent cache keys (e.g., "Bali, Indonesia" → "Bali")
            # =================================================================
            parsed_dict = parsed.model_dump()
            validated_dict = _validate_extraction(parsed_dict, today_date)
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
            set_cached_extraction(user_text, today_date, parsed.model_dump())

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


def _populate_trip_plan_from_router_output(
    state: "GraphState",
    router_output: RouterOutput,
    fallback_destination: Optional[str],
    user_text: str = "",
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
    # TIER1_SPECIALIST_NAMES already imported at module level
    TIER1_SPECIALISTS = TIER1_SPECIALIST_NAMES

    # Set destination (prefer extracted, fallback to context)
    if router_output.destination:
        state.trip_plan.destination = router_output.destination
    elif fallback_destination and not state.trip_plan.destination:
        state.trip_plan.destination = fallback_destination

    # Multi-destination: stash deferred destinations on trip_plan for DestinationGate
    if router_output.multi_destination_detected:
        state.trip_plan._multi_dest_from_llm = True
        # Parse deferred destinations from original user text
        raw = user_text
        deferred = []
        dest_lower = (router_output.destination or "").lower()
        for sep in [" and ", " then ", ", "]:
            # Don't split if separator is part of the destination itself
            # (handles "Trinidad and Tobago" erroneously flagged as multi-dest)
            if sep.lower() in dest_lower:
                continue
            if sep in raw.lower():
                parts = re.split(re.escape(sep), raw, flags=re.IGNORECASE)
                if len(parts) > 1:
                    deferred = [p.strip() for p in parts[1:] if p.strip()]
                    break
        state.trip_plan._deferred_destinations = deferred
    else:
        state.trip_plan._multi_dest_from_llm = False
        state.trip_plan._deferred_destinations = []

    # Set dates - TripPlan expects strings in YYYY-MM-DD format
    if router_output.start_date:
        clamped = _clamp_date_str(router_output.start_date)
        if clamped:
            state.trip_plan.start_date = clamped
        else:
            logger.warning(f"Invalid start_date format: {router_output.start_date}")

    if router_output.end_date:
        clamped = _clamp_date_str(router_output.end_date)
        if clamped:
            state.trip_plan.end_date = clamped
        else:
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
    # FIX: Use accumulated start_date from previous turns, not just this-turn's extraction
    # This allows "make it 4 days" to work when start_date was set in a prior message
    start_date_to_use = router_output.start_date or state.trip_plan.start_date
    if start_date_to_use and router_output.duration_days and not router_output.end_date:
        try:
            start = datetime.strptime(start_date_to_use, "%Y-%m-%d")
            end = start + timedelta(days=router_output.duration_days - 1)  # Inclusive
            state.trip_plan.end_date = end.strftime("%Y-%m-%d")
            state.trip_plan.duration_days = router_output.duration_days
            logger.debug(f"Calculated end_date from duration: {state.trip_plan.end_date}")
        except ValueError:
            pass  # Skip if date format is invalid

    # Set other extracted fields if present
    if router_output.origin:
        state.trip_plan.origin = router_output.origin

    if router_output.origin_iata:
        state.trip_plan.origin_iata = router_output.origin_iata
    if router_output.destination_iata:
        state.trip_plan.destination_iata = router_output.destination_iata

    if router_output.adults is not None:
        state.trip_plan.adults = router_output.adults

    if router_output.children is not None:
        state.trip_plan.children = router_output.children

    if router_output.budget is not None:
        state.trip_plan.budget = router_output.budget

    # Persist activity categories to activity_settings (Tier 2 pipeline activation)
    if router_output.activity_categories:
        KNOWN_CATEGORIES = TIER1_SPECIALISTS | TIER2_ACTIVITY_KEYWORDS
        validated = [c for c in router_output.activity_categories if c.lower() in KNOWN_CATEGORIES]
        if validated:
            trip_inputs = state.metadata.get("trip_inputs", {})
            activity_settings = trip_inputs.get("activity_settings", {})
            existing = set(activity_settings.get("categories", []))
            # Also include Tier 1 specialists as categories
            from_specialists = set(router_output.specialist_hints)
            merged = sorted(existing | set(validated) | from_specialists)
            activity_settings["categories"] = merged
            trip_inputs["activity_settings"] = activity_settings
            state.metadata["trip_inputs"] = trip_inputs
            state.metadata.pop("trip_settings", None)  # Clear so fallback reads trip_inputs
            state.metadata["trip_settings"] = get_trip_settings(state).model_dump()
            logger.info(f"[ROUTER] Categories: {merged} (from LLM: {validated})")

    # Persist activity day preferences (count-based, parsed from JSON string)
    day_prefs = _parse_day_preferences(router_output.activity_day_preferences, user_text)
    if day_prefs:
        # Scope to categories mentioned this turn — prevents LLM hallucinating
        # day counts for categories the user didn't reference (e.g., surfing: 3
        # when user only said "add 2 days nightlife").
        mentioned = set(router_output.activity_categories) | set(router_output.specialist_hints)
        if mentioned:
            day_prefs = {k: v for k, v in day_prefs.items() if k in mentioned}
        trip_inputs = state.metadata.get("trip_inputs", {})
        activity_settings = trip_inputs.get("activity_settings", {})
        existing_prefs = activity_settings.get("day_preferences", {})
        merged_prefs = {**existing_prefs, **day_prefs}
        activity_settings["day_preferences"] = merged_prefs
        trip_inputs["activity_settings"] = activity_settings
        state.metadata["trip_inputs"] = trip_inputs
        state.metadata.pop("trip_settings", None)
        state.metadata["trip_settings"] = get_trip_settings(state).model_dump()
        logger.info(f"[ROUTER] Day preferences: {merged_prefs}")

    logger.debug(
        f"Populated trip_plan: dest={state.trip_plan.destination}, "
        f"dates={state.trip_plan.start_date} → {state.trip_plan.end_date}"
    )
