"""
Expert Constraints — Pydantic models and static knowledge data for Local Expert.

This module holds:
- All Pydantic schema classes used by the Local Expert LLM structured output
- The LOCAL_EXPERT_KNOWLEDGE static fallback dict
- The _get_static_local_knowledge() lookup function

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


class TippingInfo(BaseModel):
    """Tipping culture details."""

    restaurants: str = Field(default="", description="Restaurant tipping norm")
    taxis: str = Field(default="", description="Taxi tipping norm")
    hotels: str = Field(default="", description="Hotel tipping norm")


class TypicalCosts(BaseModel):
    """Typical costs for common items."""

    budget_meal: str = Field(default="", description="Budget meal cost")
    mid_range_meal: str = Field(default="", description="Mid-range meal cost")
    beer: str = Field(default="", description="Beer cost")
    taxi_per_km: str = Field(default="", description="Taxi cost per km")
    attraction_entry: str = Field(default="", description="Typical attraction entry")


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
    tipping: TippingInfo = Field(default_factory=TippingInfo)
    typical_costs: TypicalCosts = Field(default_factory=TypicalCosts)
    daily_budget: DailyBudget = Field(default_factory=DailyBudget)
    haggling: str = Field(default="", description="Haggling norm (Expected/Acceptable/Not done)")


class AirportTransfer(BaseModel):
    """Airport transfer option."""

    method: str = Field(description="Transfer method (Taxi, Bus, Train, etc.)")
    price: str = Field(default="", description="Price estimate")
    time: str = Field(default="", description="Duration")
    tip: str = Field(default="", description="Booking/usage tip")


class PublicTransit(BaseModel):
    """Public transit information."""

    has_metro: bool = Field(default=False)
    has_bus: bool = Field(default=True)
    transit_card: str = Field(default="", description="Name of transit card if exists")
    cost_per_ride: str = Field(default="", description="Cost per ride")


class ScooterRental(BaseModel):
    """Scooter/bike rental info."""

    available: bool = Field(default=False)
    daily_rate: str = Field(default="", description="Daily rental rate")
    license_required: bool = Field(default=True, description="International license required?")
    recommendation: str = Field(default="", description="Safety recommendation")


class Transportation(BaseModel):
    """Transportation information."""

    airport_to_city: List[AirportTransfer] = Field(default_factory=list)
    public_transit: PublicTransit = Field(default_factory=PublicTransit)
    ride_apps: List[str] = Field(default_factory=list, description="Available ride-hailing apps")
    scooter_rental: ScooterRental = Field(default_factory=ScooterRental)
    traffic_note: str = Field(default="", description="Traffic considerations")


class DressCode(BaseModel):
    """Dress code requirements."""

    temples: str = Field(default="", description="Temple dress requirements")
    beaches: str = Field(default="", description="Beach dress norms")
    restaurants: str = Field(default="", description="Restaurant dress expectations")


class CulturalNorms(BaseModel):
    """Cultural norms and etiquette."""

    dress_code: DressCode = Field(default_factory=DressCode)
    religious_notes: str = Field(default="", description="Key religious considerations")
    greetings: str = Field(default="", description="How locals greet")
    photo_etiquette: str = Field(default="", description="Photography rules")
    dining_etiquette: List[str] = Field(default_factory=list)
    lgbtq_friendly: str = Field(default="", description="LGBTQ+ friendliness")
    important_taboos: List[str] = Field(default_factory=list)


class SafetyHealth(BaseModel):
    """Safety and health information."""

    overall_safety: str = Field(default="Safe", description="Overall safety rating")
    tap_water_safe: bool = Field(default=False)
    street_food_safe: bool = Field(default=True)
    common_concerns: List[str] = Field(default_factory=list)
    emergency_number: str = Field(default="", description="Emergency contact")
    nearest_hospital: str = Field(default="", description="Tourist-friendly hospital")
    vaccinations: List[str] = Field(default_factory=list)
    areas_to_avoid: List[str] = Field(default_factory=list)


class VisaEntry(BaseModel):
    """Visa and entry requirements."""

    visa_free_for: List[str] = Field(
        default_factory=list, description="Countries with visa-free entry"
    )
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
    wifi_quality: str = Field(default="Good")
    essential_apps: List[str] = Field(default_factory=list)
    vpn_needed: bool = Field(default=False)


class Festival(BaseModel):
    """Festival or event info."""

    name: str = Field(description="Festival name")
    when: str = Field(default="", description="Date or month")
    impact: str = Field(default="", description="Impact on travelers")


class Seasonality(BaseModel):
    """Seasonal information."""

    best_months: List[str] = Field(default_factory=list)
    avoid_months: List[str] = Field(default_factory=list)
    high_season: str = Field(default="", description="High season period and implications")
    rainy_season: str = Field(default="", description="Rainy season details")
    major_festivals: List[Festival] = Field(default_factory=list)
    current_season_tip: str = Field(default="", description="Tip for travel dates")


class MustDoExperience(BaseModel):
    """A must-do experience."""

    name: str = Field(description="Experience name")
    why: str = Field(default="", description="Why it's special")
    booking: str = Field(default="", description="Booking requirement")
    best_time: str = Field(default="", description="Best time to visit")
    cost: str = Field(default="", description="Cost estimate")


class DayTrip(BaseModel):
    """Day trip destination."""

    destination: str = Field(description="Destination name")
    distance: str = Field(default="", description="Distance/travel time")
    highlight: str = Field(default="", description="Main highlight")


class HiddenGem(BaseModel):
    """Local hidden gem."""

    name: str = Field(description="Place name")
    why: str = Field(default="", description="Why tourists miss it")
    tip: str = Field(default="", description="How to experience it")


class ThingsToDo(BaseModel):
    """Things to do information."""

    must_do: List[MustDoExperience] = Field(default_factory=list)
    day_trips: List[DayTrip] = Field(default_factory=list)
    hidden_gems: List[HiddenGem] = Field(default_factory=list)
    skip_these: List[str] = Field(default_factory=list, description="Overrated tourist traps")


class Neighborhood(BaseModel):
    """Neighborhood information."""

    name: str = Field(description="Area name")
    vibe: str = Field(default="", description="Area vibe/description")
    best_for: List[str] = Field(default_factory=list)
    price_range: str = Field(default="", description="Price range (Budget/Mid-range/Luxury)")
    walkability: str = Field(default="", description="Walkability (High/Medium/Need transport)")


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

    types_available: List[str] = Field(default_factory=list)
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
    tourist_traps: List[str] = Field(default_factory=list)
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
    buy_locally: List[str] = Field(default_factory=list)
    electrical: ElectricalInfo = Field(default_factory=ElectricalInfo)
    clothing_tips: List[str] = Field(default_factory=list)


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
# Static Local Expert Knowledge (Fallback when LLM unavailable)
# =============================================================================
# This dict provides STABLE constraints (cultural norms, safety, seasonality)
# as fallback data when the LLM is unavailable. Volatile venue-specific data
# (prices, opening hours, transport costs) is NOT included — the LLM path
# generates those dynamically.
#
# Adding cities here is optional — the LLM handles any destination.
# Only add entries when specific safety/cultural constraints are critical
# and must survive LLM failures.

LOCAL_EXPERT_KNOWLEDGE = {
    "dubai": {
        "constraints": [
            {
                "type": "cultural",
                "description": (
                    "Dress modestly in malls and public areas - shoulders and knees covered"
                ),
                "severity": "warning",
            },
            {
                "type": "seasonal",
                "description": "Summer (Jun-Aug) can exceed 45°C - plan indoor activities",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "description": "Alcohol only in licensed venues (hotels, restaurants)",
                "severity": "info",
            },
        ],
    },
    "paris": {
        "constraints": [
            {
                "type": "opening_hours",
                "description": "Louvre closed on Tuesdays",
                "severity": "warning",
            },
            {
                "type": "opening_hours",
                "description": "Most museums closed Mondays or Tuesdays - check before visiting",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "description": "Eiffel Tower requires booking 2-3 weeks ahead for summit access",
                "severity": "warning",
            },
        ],
    },
    "rome": {
        "constraints": [
            {
                "type": "booking_window",
                "description": "Vatican Museums require advance tickets - same-day often sold out",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "description": "Colosseum timed entry tickets sell out days in advance",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "description": "Dress code for churches: covered shoulders and knees required",
                "severity": "info",
            },
        ],
    },
    "london": {
        "constraints": [
            {
                "type": "booking_window",
                "description": "West End shows sell out weeks ahead for popular productions",
                "severity": "info",
            },
            {
                "type": "opening_hours",
                "description": "Tube runs until ~midnight (24h on weekends on some lines)",
                "severity": "info",
            },
            {
                "type": "seasonal",
                "description": "Rain likely year-round - pack layers and waterproof jacket",
                "severity": "info",
            },
        ],
    },
    "amsterdam": {
        "constraints": [
            {
                "type": "booking_window",
                "description": "Anne Frank House requires booking 6+ weeks ahead",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "description": "Van Gogh Museum timed tickets sell out - book 2 weeks ahead",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "description": "Cycling rules: stay in bike lanes, signal turns",
                "severity": "info",
            },
        ],
    },
    "tokyo": {
        "constraints": [
            {
                "type": "cultural",
                "description": "Many restaurants don't accept credit cards - carry cash",
                "severity": "warning",
            },
            {
                "type": "cultural",
                "description": "No tipping in Japan - considered rude",
                "severity": "info",
            },
            {
                "type": "booking_window",
                "description": "teamLab exhibitions require advance booking",
                "severity": "warning",
            },
        ],
    },
    "new york": {
        "constraints": [
            {
                "type": "booking_window",
                "description": "Statue of Liberty crown access books out 3+ months ahead",
                "severity": "warning",
            },
            {
                "type": "booking_window",
                "description": (
                    "Broadway shows: book 2+ weeks for popular shows, or try TKTS day-of"
                ),
                "severity": "info",
            },
            {
                "type": "cultural",
                "description": "Tipping expected: 18-20% at restaurants",
                "severity": "info",
            },
        ],
    },
    "bali": {
        # Comprehensive 12-category knowledge for Bali
        "destination_overview": {
            "tagline": "Island of the Gods where ancient traditions meet surf culture",
            "best_for": [
                "Beach lovers",
                "Divers",
                "Culture seekers",
                "Digital nomads",
                "Honeymooners",
            ],
            "vibe": "Relaxed",
        },
        "visa_entry": {
            "visa_free_for": ["US", "UK", "EU", "AU", "CA", "NZ", "JP", "KR", "SG"],
            "visa_on_arrival": True,
            "max_stay_days": 30,
            "passport_validity_months": 6,
            "key_requirements": ["Return ticket", "Proof of accommodation"],
            "immigration_tip": (
                "Have your hotel address ready - they always ask. "
                "E-VOA available online to skip queues."
            ),
        },
        "safety_health": {
            "overall_safety": "Safe",
            "tap_water_safe": False,
            "street_food_safe": True,
            "common_concerns": [
                "Mosquitoes - bring DEET repellent",
                "Strong sun - SPF 50+ essential",
                "Bali belly - stick to busy warungs, avoid ice in small places",
                "Monkeys at temples - hide shiny items, they snatch glasses",
            ],
            "emergency_number": "112 (general), 118 (ambulance)",
            "nearest_hospital": (
                "BIMC Hospital Kuta - 24/7 English-speaking staff, accepts travel insurance"
            ),
            "vaccinations": ["Hepatitis A recommended", "Typhoid for adventurous eaters"],
            "areas_to_avoid": ["Kuta after midnight if solo - drunk tourists attract trouble"],
        },
        "cultural_norms": {
            "dress_code": {
                "temples": (
                    "Cover shoulders and knees - sarongs provided at entrance "
                    "(free or small donation)"
                ),
                "beaches": "Swimwear OK at beach clubs",
                "restaurants": "Smart casual for upscale places in Seminyak",
            },
            "religious_notes": (
                "Bali is Hindu in Muslim Indonesia. Daily offerings (canang sari) "
                "everywhere - step over, not on them."
            ),
            "greetings": "Namaste-style hands together greeting. Right hand for giving/receiving.",
            "photo_etiquette": (
                "Ask before photographing ceremonies. Never climb sacred trees or statues."
            ),
            "dining_etiquette": [
                "Remove shoes if entering someone's home",
                "Don't point with your finger - use your thumb",
                "Left hand considered unclean - use right for eating",
            ],
            "lgbtq_friendly": "Legal but discreet - PDA uncommon even for straight couples",
            "important_taboos": [
                "Never touch someone's head (sacred)",
                "Don't point feet at shrines or people",
                "Don't step on offerings",
            ],
        },
        "seasonality": {
            "best_months": ["Apr", "May", "Jun", "Jul", "Aug", "Sep"],
            "avoid_months": ["Dec-Feb if you hate rain, Jan for extreme crowds"],
            "high_season": (
                "Jul-Aug and Dec-Jan - book hotels 2-3 months ahead, prices 30-50% higher"
            ),
            "rainy_season": (
                "Nov-Mar - afternoon thunderstorms, mornings usually clear. "
                "Best time for rice terrace greenery."
            ),
            "major_festivals": [
                {
                    "name": "Nyepi (Day of Silence)",
                    "when": "March (varies)",
                    "impact": (
                        "Everything closes 24h - no flights, no leaving hotel. "
                        "Unique experience if you plan for it."
                    ),
                },
                {
                    "name": "Galungan",
                    "when": "Every 210 days",
                    "impact": (
                        "Temples decorated, ceremonies everywhere. Beautiful but some closures."
                    ),
                },
            ],
            "current_season_tip": "",  # Filled dynamically based on travel dates
        },
        "packing": {
            "must_pack": [
                "Reef-safe sunscreen (protect the coral!)",
                "Mosquito repellent with DEET",
                "Light rain jacket or poncho",
                "Quick-dry clothing",
                "Sarong (or buy one - $5-10)",
                "Water shoes for rocky beaches",
                "Power bank (long days out)",
            ],
            "dont_bring": [
                "Formal clothes (hardly needed)",
                "Heavy jackets (only for Kintamani highlands)",
                "Too many toiletries (everything available cheap)",
            ],
            "buy_locally": [
                "Sarongs - $5-10, better quality and patterns",
                "Bintang tank tops - the Bali souvenir",
                "Mosquito coils - 50 cents at any Indomaret",
                "Snorkel gear - rent for $5/day vs buying",
            ],
            "electrical": {
                "plug_type": "Type C and F (European 2-pin)",
                "voltage": "230V",
                "adapter_needed": True,
            },
            "clothing_tips": [
                "Light, breathable fabrics - it's humid",
                "Cover-ups for temple visits",
                "One nice outfit for upscale Seminyak restaurants",
                "Flip flops for beach, closed shoes for volcano trek",
            ],
        },
        # Legacy format for backward compatibility
        "constraints": [
            {
                "type": "cultural",
                "description": (
                    "Cover shoulders and knees when visiting temples - "
                    "sarongs available at entrances"
                ),
                "severity": "warning",
            },
            {
                "type": "seasonal",
                "description": (
                    "Rainy season (Nov-Mar) brings afternoon showers - mornings are best for diving"
                ),
                "severity": "info",
            },
            {
                "type": "safety",
                "description": "Strong currents at some beaches - swim only at patrolled areas",
                "severity": "warning",
            },
            {
                "type": "safety",
                "description": "Tap water not safe - drink bottled water only",
                "severity": "warning",
            },
            {
                "type": "transport",
                "description": (
                    "International Driving Permit required for scooter rental - "
                    "police checkpoints common"
                ),
                "severity": "warning",
            },
        ],
    },
}


def _get_static_local_knowledge(destination: str) -> LocalExpertOutput:
    """Get static local expert knowledge for common destinations."""
    dest_lower = destination.lower().strip()

    # Check for exact match or partial match
    knowledge = None
    for key in LOCAL_EXPERT_KNOWLEDGE:
        if key in dest_lower or dest_lower in key:
            knowledge = LOCAL_EXPERT_KNOWLEDGE[key]
            break

    if not knowledge:
        return LocalExpertOutput()

    # Check if this is the new comprehensive format (has destination_overview)
    if "destination_overview" in knowledge:
        # Comprehensive format — only parse stable categories
        # Volatile venue/price data (money_costs, transportation, connectivity,
        # things_to_do, neighborhoods, accommodation, scams_traps, recommendations)
        # has been removed from static data; the LLM path supplies those.
        return LocalExpertOutput(
            destination_overview=DestinationOverview(**knowledge.get("destination_overview", {})),
            visa_entry=VisaEntry(**knowledge.get("visa_entry", {})),
            safety_health=SafetyHealth(**knowledge.get("safety_health", {})),
            cultural_norms=CulturalNorms(
                dress_code=DressCode(**knowledge.get("cultural_norms", {}).get("dress_code", {})),
                religious_notes=knowledge.get("cultural_norms", {}).get("religious_notes", ""),
                greetings=knowledge.get("cultural_norms", {}).get("greetings", ""),
                photo_etiquette=knowledge.get("cultural_norms", {}).get("photo_etiquette", ""),
                dining_etiquette=knowledge.get("cultural_norms", {}).get("dining_etiquette", []),
                lgbtq_friendly=knowledge.get("cultural_norms", {}).get("lgbtq_friendly", ""),
                important_taboos=knowledge.get("cultural_norms", {}).get("important_taboos", []),
            ),
            seasonality=Seasonality(
                best_months=knowledge.get("seasonality", {}).get("best_months", []),
                avoid_months=knowledge.get("seasonality", {}).get("avoid_months", []),
                high_season=knowledge.get("seasonality", {}).get("high_season", ""),
                rainy_season=knowledge.get("seasonality", {}).get("rainy_season", ""),
                major_festivals=[
                    Festival(**f)
                    for f in knowledge.get("seasonality", {}).get("major_festivals", [])
                ],
                current_season_tip=knowledge.get("seasonality", {}).get("current_season_tip", ""),
            ),
            packing=Packing(
                must_pack=knowledge.get("packing", {}).get("must_pack", []),
                dont_bring=knowledge.get("packing", {}).get("dont_bring", []),
                buy_locally=knowledge.get("packing", {}).get("buy_locally", []),
                electrical=ElectricalInfo(**knowledge.get("packing", {}).get("electrical", {})),
                clothing_tips=knowledge.get("packing", {}).get("clothing_tips", []),
            ),
            constraints=[LocalConstraint(**c) for c in knowledge.get("constraints", [])],
        )
    else:
        # Legacy format - constraints only (recommendations removed as volatile)
        constraints = [LocalConstraint(**c) for c in knowledge.get("constraints", [])]
        return LocalExpertOutput(constraints=constraints)
