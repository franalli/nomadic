"""
Expert Constraints — Pydantic models and constraint data for Local Expert.

This module holds:
- All Pydantic schema classes used by the Local Expert LLM structured output
- LOCAL_EXPERT_CONSTRAINTS: stable constraint facts injected into LLM prompt
- _get_constraint_context(): formats constraints as prompt text for LLM grounding

Separated from local_expert.py to keep node logic focused (~200 lines).
"""

from typing import List

from pydantic import BaseModel, Field

# =============================================================================
# LLM Output Schema (OpenAI Structured Output compatible)
# =============================================================================


class LocalConstraint(BaseModel):
    """A logistical constraint for the destination."""

    type: str = Field(
        default="general",
        description=(
            "Type of constraint (visa, safety, cultural, booking, seasonal, transport, general)"
        ),
    )
    description: str = Field(description="Short, actionable constraint text")
    severity: str = Field(default="info", description="Severity level (warning, info)")


class LocalRecommendation(BaseModel):
    """A logistical recommendation for the destination."""

    title: str = Field(description="Name of pass/tip/area")
    description: str = Field(description="What is it?")
    category: str = Field(
        default="logistics",
        description=(
            "Category (logistics, attraction, dining, activity, accommodation, scam_warning)"
        ),
    )
    logic_hook: str = Field(default="", description="The specific logistical advantage")


# --- Comprehensive Category Models ---
# Tier 2 slim: removed unused sub-models (TippingInfo, TypicalCosts, PublicTransit,
# ScooterRental, DayTrip, HiddenGem) and unused fields within kept models.
# Frontend field-access audit confirmed these are never rendered.


class DailyBudget(BaseModel):
    """Daily budget estimates by travel style."""

    backpacker: str = Field(default="", description="Backpacker daily budget")
    mid_range: str = Field(default="", description="Mid-range daily budget")
    luxury: str = Field(default="", description="Luxury daily budget")


class MoneyCosts(BaseModel):
    """Money and costs information."""

    currency: str = Field(default="", description="Currency name and code")
    exchange_tip: str = Field(default="", description="Where/how to exchange")
    atm_note: str = Field(default="", description="ATM fees and card acceptance")
    daily_budget: DailyBudget = Field(default_factory=DailyBudget)
    haggling: str = Field(default="", description="Haggling norm (Expected/Acceptable/Not done)")


class AirportTransfer(BaseModel):
    """Airport transfer option."""

    method: str = Field(description="Transfer method (Taxi, Bus, Train, etc.)")
    price: str = Field(default="", description="Price estimate")
    time: str = Field(default="", description="Duration")


class Transportation(BaseModel):
    """Transportation information."""

    airport_to_city: List[AirportTransfer] = Field(default_factory=list)
    ride_apps: List[str] = Field(default_factory=list, description="Available ride-hailing apps")
    traffic_note: str = Field(default="", description="Traffic considerations")


class DressCode(BaseModel):
    """Dress code requirements."""

    temples: str = Field(default="", description="Temple dress requirements")
    restaurants: str = Field(default="", description="Restaurant dress expectations")


class CulturalNorms(BaseModel):
    """Cultural norms and etiquette."""

    dress_code: DressCode = Field(default_factory=DressCode)
    greetings: str = Field(default="", description="How locals greet")
    lgbtq_friendly: str = Field(default="", description="LGBTQ+ friendliness")
    important_taboos: List[str] = Field(default_factory=list)


class SafetyHealth(BaseModel):
    """Safety and health information."""

    overall_safety: str = Field(default="Safe", description="Overall safety rating")
    tap_water_safe: bool = Field(default=False)
    common_concerns: List[str] = Field(default_factory=list)
    emergency_number: str = Field(default="", description="Emergency contact")
    nearest_hospital: str = Field(default="", description="Tourist-friendly hospital")
    advisory_level: str = Field(default="none", description="none | caution | warning | avoid")
    advisory_reason: str = Field(
        default="", description="Brief reason for advisory if caution or higher"
    )


class VisaEntry(BaseModel):
    """Visa and entry requirements."""

    visa_on_arrival: bool = Field(default=False)
    max_stay_days: int = Field(default=30)
    passport_validity_months: int = Field(default=6)
    key_requirements: List[str] = Field(default_factory=list)
    immigration_tip: str = Field(default="", description="Immigration process tip")


class Connectivity(BaseModel):
    """Internet and connectivity info."""

    best_sim_provider: str = Field(default="")
    sim_cost: str = Field(default="")
    where_to_buy: str = Field(default="")
    esim_works: bool = Field(default=True)
    essential_apps: List[str] = Field(default_factory=list)


class Festival(BaseModel):
    """Festival or event info."""

    name: str = Field(description="Festival name")
    when: str = Field(default="", description="Date or month")
    impact: str = Field(default="", description="Impact on travelers")


class Seasonality(BaseModel):
    """Seasonal information."""

    best_months: List[str] = Field(default_factory=list)
    high_season: str = Field(default="", description="High season period and implications")
    rainy_season: str = Field(default="", description="Rainy season details")
    major_festivals: List[Festival] = Field(default_factory=list)
    current_season_tip: str = Field(default="", description="Tip for travel dates")


class MustDoExperience(BaseModel):
    """A must-do experience."""

    name: str = Field(description="Experience name")
    why: str = Field(default="", description="Why it's special")
    booking: str = Field(default="", description="Booking requirement")
    cost: str = Field(default="", description="Cost estimate")


class ThingsToDo(BaseModel):
    """Things to do information."""

    must_do: List[MustDoExperience] = Field(default_factory=list)
    skip_these: List[str] = Field(default_factory=list, description="Overrated tourist traps")


class Neighborhood(BaseModel):
    """Neighborhood information."""

    name: str = Field(description="Area name")
    vibe: str = Field(default="", description="Area vibe/description")
    best_for: List[str] = Field(default_factory=list)
    price_range: str = Field(default="", description="Price range (Budget/Mid-range/Luxury)")


class Neighborhoods(BaseModel):
    """Neighborhood guide."""

    where_to_stay: List[Neighborhood] = Field(default_factory=list)
    avoid_staying_in: List[str] = Field(default_factory=list)


class AccommodationPrices(BaseModel):
    """Accommodation price ranges."""

    hostel: str = Field(default="")
    budget_hotel: str = Field(default="")
    mid_range: str = Field(default="")
    luxury: str = Field(default="")


class Accommodation(BaseModel):
    """Accommodation information."""

    booking_platforms: List[str] = Field(default_factory=list)
    price_ranges: AccommodationPrices = Field(default_factory=AccommodationPrices)
    book_ahead: str = Field(default="", description="Booking lead time advice")


class Scam(BaseModel):
    """A common scam."""

    name: str = Field(description="Scam name")
    how_it_works: str = Field(default="", description="How the scam works")
    how_to_avoid: str = Field(default="", description="Prevention tip")


class ScamsTraps(BaseModel):
    """Scams and tourist traps information."""

    common_scams: List[Scam] = Field(default_factory=list)
    taxi_scam_tip: str = Field(default="", description="How to avoid taxi scams")
    general_advice: str = Field(default="", description="Overall safety advice")


class ElectricalInfo(BaseModel):
    """Electrical socket info."""

    plug_type: str = Field(default="", description="Plug type (Type A, B, C, etc.)")
    voltage: str = Field(default="", description="Voltage")
    adapter_needed: bool = Field(default=True)


class Packing(BaseModel):
    """Packing recommendations."""

    must_pack: List[str] = Field(default_factory=list)
    dont_bring: List[str] = Field(default_factory=list)
    electrical: ElectricalInfo = Field(default_factory=ElectricalInfo)


class DestinationOverview(BaseModel):
    """Destination overview/summary."""

    tagline: str = Field(default="", description="Evocative one-liner")
    best_for: List[str] = Field(default_factory=list)
    vibe: str = Field(default="", description="Destination vibe")


class LocalExpertOutput(BaseModel):
    """Comprehensive structured output from the Local Expert LLM."""

    # Overview
    destination_overview: DestinationOverview = Field(default_factory=DestinationOverview)

    # The 12 Categories
    visa_entry: VisaEntry = Field(default_factory=VisaEntry)
    safety_health: SafetyHealth = Field(default_factory=SafetyHealth)
    money_costs: MoneyCosts = Field(default_factory=MoneyCosts)
    transportation: Transportation = Field(default_factory=Transportation)
    cultural_norms: CulturalNorms = Field(default_factory=CulturalNorms)
    connectivity: Connectivity = Field(default_factory=Connectivity)
    seasonality: Seasonality = Field(default_factory=Seasonality)
    things_to_do: ThingsToDo = Field(default_factory=ThingsToDo)
    neighborhoods: Neighborhoods = Field(default_factory=Neighborhoods)
    accommodation: Accommodation = Field(default_factory=Accommodation)
    scams_traps: ScamsTraps = Field(default_factory=ScamsTraps)
    packing: Packing = Field(default_factory=Packing)

    # Legacy fields for backward compatibility
    constraints: List[LocalConstraint] = Field(
        default_factory=list,
        description="Aggregated constraints from all categories",
    )
    recommendations: List[LocalRecommendation] = Field(
        default_factory=list,
        description="Aggregated recommendations from all categories",
    )
    quick_tips: List[str] = Field(
        default_factory=list,
        description="Top one-liner tips",
    )


# =============================================================================
# Static Local Expert Constraints (Injected into LLM prompt as grounding)
# =============================================================================
# Stable constraint facts (cultural norms, safety, seasonality, booking windows)
# that rarely change. Injected into the Local Expert LLM system prompt so it
# doesn't hallucinate them.
#
# NOT included: venue names, prices, hours, transport costs, visa specifics,
# packing lists, or any data that drifts. The LLM generates those dynamically.
#
# Adding cities is optional — the LLM handles any destination without hints.
# Only add entries when specific safety/cultural constraints are critical.
#
# Hard Rule 11 exception: These are curated medical/cultural safety constraints
# (dress codes, altitude warnings, decompression buffers). LLM-generated safety
# data introduces hallucination risk. Kept as static data by design.

LOCAL_EXPERT_CONSTRAINTS: dict[str, dict] = {
    "dubai": {
        "constraints": [
            {
                "type": "cultural",
                "desc": "Dress modestly in malls/public areas - shoulders and knees covered",
                "severity": "warning",
            },
            {
                "type": "seasonal",
                "desc": "Summer (Jun-Aug) can exceed 45°C - plan indoor activities",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "desc": "Alcohol only in licensed venues (hotels, restaurants)",
                "severity": "info",
            },
        ],
    },
    "paris": {
        "constraints": [
            {
                "type": "opening_hours",
                "desc": "Louvre closed on Tuesdays",
                "severity": "warning",
            },
            {
                "type": "opening_hours",
                "desc": "Most museums closed Mondays or Tuesdays - check before visiting",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "desc": "Eiffel Tower requires booking 2-3 weeks ahead for summit access",
                "severity": "warning",
            },
        ],
    },
    "rome": {
        "constraints": [
            {
                "type": "booking_window",
                "desc": "Vatican Museums require advance tickets - same-day often sold out",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "desc": "Colosseum timed entry tickets sell out days in advance",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "desc": "Dress code for churches: covered shoulders and knees required",
                "severity": "info",
            },
        ],
    },
    "london": {
        "constraints": [
            {
                "type": "booking_window",
                "desc": "West End shows sell out weeks ahead for popular productions",
                "severity": "info",
            },
            {
                "type": "opening_hours",
                "desc": "Tube runs until ~midnight (24h on weekends on some lines)",
                "severity": "info",
            },
            {
                "type": "seasonal",
                "desc": "Rain likely year-round - pack layers and waterproof jacket",
                "severity": "info",
            },
        ],
    },
    "amsterdam": {
        "constraints": [
            {
                "type": "booking_window",
                "desc": "Anne Frank House requires booking 6+ weeks ahead",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "desc": "Van Gogh Museum timed tickets sell out - book 2 weeks ahead",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "desc": "Cycling rules: stay in bike lanes, signal turns",
                "severity": "info",
            },
        ],
    },
    "tokyo": {
        "constraints": [
            {
                "type": "cultural",
                "desc": "Many restaurants don't accept credit cards - carry cash",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "desc": "No tipping in Japan - considered rude",
                "severity": "info",
            },
            {
                "type": "booking_window",
                "desc": "teamLab exhibitions require advance booking",
                "severity": "warning",
            },
        ],
    },
    "new york": {
        "constraints": [
            {
                "type": "booking_window",
                "desc": "Statue of Liberty crown access books out 3+ months ahead",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "desc": "Broadway: book 2+ weeks for popular shows, or try TKTS day-of",
                "severity": "info",
            },
            {
                "type": "cultural",
                "desc": "Tipping expected: 18-20% at restaurants",
                "severity": "info",
            },
        ],
    },
    "bali": {
        "constraints": [
            {
                "type": "cultural",
                "desc": "Cover shoulders and knees when visiting temples - sarongs at entrances",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "desc": "Hindu island - daily offerings (canang sari) everywhere, step over not on",
                "severity": "info",
            },
            {
                "type": "cultural",
                "desc": "Never touch someone's head (sacred); don't point feet at shrines",
                "severity": "info",
            },
            {
                "type": "seasonal",
                "desc": "Rainy season Nov-Mar brings afternoon showers - mornings best for diving",
                "severity": "info",
            },
            {
                "type": "safety",
                "desc": "Strong currents at some beaches - swim only at patrolled areas",
                "severity": "warning",
            },
            {
                "type": "safety",
                "desc": "Tap water not safe - drink bottled water only",
                "severity": "warning",
            },
            {
                "type": "transport",
                "desc": "International Driving Permit required for scooter - police checkpoints",
                "severity": "warning",
            },
        ],
    },
}


def _get_constraint_context(destination: str) -> str:
    """Format static constraints as LLM prompt context for a destination.

    Returns a string block to inject into the system prompt, or empty string
    if no constraints are known for this destination.
    """
    dest_lower = destination.lower().strip()

    entry = None
    for key in LOCAL_EXPERT_CONSTRAINTS:
        if key in dest_lower or dest_lower in key:
            entry = LOCAL_EXPERT_CONSTRAINTS[key]
            break

    if not entry:
        return ""

    constraints = entry.get("constraints", [])
    if not constraints:
        return ""

    lines = [f"\n## Known constraints for {destination} (verified facts — do not contradict):"]
    for c in constraints:
        severity_tag = "[WARNING]" if c["severity"] == "warning" else "[INFO]"
        lines.append(f"- {severity_tag} ({c['type']}) {c['desc']}")
    return "\n".join(lines)


def _get_constraints_as_list(destination: str) -> list[dict]:
    """Return raw constraint dicts for a destination (no formatting).

    Used by Phase A skeleton to build constraints_applied instantly,
    without any LLM call.
    """
    dest_lower = destination.lower().strip()
    for key in LOCAL_EXPERT_CONSTRAINTS:
        if key in dest_lower or dest_lower in key:
            return LOCAL_EXPERT_CONSTRAINTS[key].get("constraints", [])
    return []


def _get_static_must_dos(destination: str) -> list[str]:
    """Return top must-do activities from static destination data.

    DEPRECATED: must_dos have been removed from LOCAL_EXPERT_CONSTRAINTS.
    Always returns an empty list. Kept for backward compatibility with callers.
    """
    return []
