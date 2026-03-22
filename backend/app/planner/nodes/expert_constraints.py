"""
Expert Constraints — Pydantic models and constraint data for Local Expert.

This module holds:
- All Pydantic schema classes used by the Local Expert LLM structured output
- Reusable local-expert constraint helpers with no destination lookup table

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
