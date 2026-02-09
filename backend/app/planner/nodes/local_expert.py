"""
Local Expert Node - The "Logistics Concierge" for city trips.

This specialist activates by default when no niche specialist (diving/hiking/skiing)
is requested. It provides city-specific constraints and tips:
- Opening hours and closed days
- Booking lead times for popular attractions
- Transit passes and efficiency tips
- Cultural considerations (dining hours, tipping, dress codes)

Goal: Ensure the Agent Feed is never empty for generic trips.
"""

import os
from pathlib import Path
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.data.demo_curation import DEMO_MANIFEST
from app.placeholders import get_destination_gallery
from app.planner.services.section_builder import (
    build_local_expert_section,
    mark_topic_executed,
    upsert_section,
)
from app.planner.state import GraphState

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
        "recommendations": [
            {
                "title": "Dubai Metro",
                "description": "Clean, air-conditioned metro connects major attractions",
                "category": "logistics",
                "logic_hook": "Saves 60% vs taxis - Red Line covers most tourist spots",
            },
            {
                "title": "Burj Khalifa Tickets",
                "description": "Book 'At the Top' tickets online in advance",
                "category": "attraction",
                "logic_hook": "Book 2+ weeks ahead for sunset slots - sells out fast",
            },
            {
                "title": "Mall of the Emirates",
                "description": "Indoor shopping and entertainment complex",
                "category": "logistics",
                "logic_hook": "Escape midday heat - has Ski Dubai indoor slope",
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
        "recommendations": [
            {
                "title": "Paris Museum Pass",
                "description": "Skip-the-line access to 50+ museums",
                "category": "logistics",
                "logic_hook": "Saves €40+ and 90min queues at Louvre/Versailles",
            },
            {
                "title": "Navigo Easy Card",
                "description": "Contactless transit card for Metro, RER, buses",
                "category": "logistics",
                "logic_hook": "Saves 20% vs paper tickets - reloadable",
            },
            {
                "title": "Dinner Reservations",
                "description": "Popular restaurants book up fast",
                "category": "dining",
                "logic_hook": "Book 2+ weeks ahead - dinner starts 8-9pm in Paris",
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
        "recommendations": [
            {
                "title": "Roma Pass",
                "description": "Free entry to 2 museums + unlimited transport",
                "category": "logistics",
                "logic_hook": "Includes Colosseum skip-the-line - saves 2hr queue",
            },
            {
                "title": "Vatican Early Entry",
                "description": "Book first entry slot (8am) for Vatican Museums",
                "category": "attraction",
                "logic_hook": "Beat the crowds - Sistine Chapel nearly empty at opening",
            },
            {
                "title": "Trastevere for Dinner",
                "description": "Authentic neighborhood dining across the Tiber",
                "category": "dining",
                "logic_hook": "30% cheaper than tourist center - locals eat here",
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
        "recommendations": [
            {
                "title": "Oyster Card",
                "description": "Contactless transit card for Tube, buses, trains",
                "category": "logistics",
                "logic_hook": "Daily cap at £8.10 - unlimited Zone 1-2 travel",
            },
            {
                "title": "Free Museums",
                "description": "British Museum, Natural History, V&A are free entry",
                "category": "attraction",
                "logic_hook": "No booking needed - just show up (except special exhibitions)",
            },
            {
                "title": "Borough Market",
                "description": "Historic food market under London Bridge",
                "category": "dining",
                "logic_hook": "Best Thurs-Sat - closed Sun/Mon",
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
        "recommendations": [
            {
                "title": "I amsterdam City Card",
                "description": "Free entry to 70+ museums + unlimited GVB transport",
                "category": "logistics",
                "logic_hook": "Saves €50+ if visiting 3+ museums - includes canal cruise",
            },
            {
                "title": "OV-chipkaart",
                "description": "Contactless card for all Dutch public transport",
                "category": "logistics",
                "logic_hook": "Required for trains/trams - paper tickets 60% more expensive",
            },
            {
                "title": "Jordaan Neighborhood",
                "description": "Charming canal district with cafes and galleries",
                "category": "attraction",
                "logic_hook": "Walk or bike - too narrow for tour buses",
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
        "recommendations": [
            {
                "title": "Suica/Pasmo Card",
                "description": "IC card for trains, buses, convenience stores",
                "category": "logistics",
                "logic_hook": "Touch-and-go everywhere - no need to buy paper tickets",
            },
            {
                "title": "JR Pass",
                "description": "Unlimited travel on JR trains including Shinkansen",
                "category": "logistics",
                "logic_hook": "Worth it if taking 2+ Shinkansen trips - buy before arrival",
            },
            {
                "title": "Conveyor Belt Sushi",
                "description": "Affordable sushi on rotating belts",
                "category": "dining",
                "logic_hook": "¥100-300/plate - same quality as sit-down, 1/3 the price",
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
        "recommendations": [
            {
                "title": "OMNY / MetroCard",
                "description": "Contactless payment or MetroCard for subway/buses",
                "category": "logistics",
                "logic_hook": "Unlimited 7-day pass saves money if 13+ rides",
            },
            {
                "title": "TKTS Booth",
                "description": "Same-day Broadway tickets at 20-50% off",
                "category": "attraction",
                "logic_hook": "Times Square booth - arrive 2pm for matinees, 3pm for evening",
            },
            {
                "title": "High Line Walk",
                "description": "Elevated park on former railway",
                "category": "attraction",
                "logic_hook": "Free entry - combine with Chelsea Market for food",
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
        "money_costs": {
            "currency": "Indonesian Rupiah (IDR)",
            "exchange_tip": (
                "Use ATMs (BCA, Mandiri best rates). "
                "Avoid airport and street changers - bad rates and scams."
            ),
            "atm_note": (
                "ATM fees ~$3-5. Visa/Mastercard widely accepted in tourist areas. "
                "Cash needed for warungs."
            ),
            "tipping": {
                "restaurants": "10% if no service charge, round up at warungs",
                "taxis": "Round up to nearest 10k IDR",
                "hotels": "20-50k IDR/day for housekeeping",
            },
            "typical_costs": {
                "budget_meal": "$2-4 (warung)",
                "mid_range_meal": "$10-20 (restaurant)",
                "beer": "$3-5 (Bintang)",
                "taxi_per_km": "$0.50",
                "attraction_entry": "$3-15",
            },
            "daily_budget": {
                "backpacker": "$30-50",
                "mid_range": "$80-150",
                "luxury": "$300+",
            },
            "haggling": "Expected",
        },
        "transportation": {
            "airport_to_city": [
                {
                    "method": "Grab/Gojek",
                    "price": "$8-15",
                    "time": "30-60 mins",
                    "tip": "Order from arrivals pickup - cheaper than taxi",
                },
                {
                    "method": "Official Taxi",
                    "price": "$15-25",
                    "time": "30-60 mins",
                    "tip": "Use prepaid taxi counter - avoid touts",
                },
                {
                    "method": "Hotel Transfer",
                    "price": "$20-40",
                    "time": "30-60 mins",
                    "tip": "Often included with mid-range+ hotels",
                },
            ],
            "public_transit": {
                "has_metro": False,
                "has_bus": True,
                "transit_card": "None - pay cash",
                "cost_per_ride": "$0.50-1 (Kura-Kura bus)",
            },
            "ride_apps": ["Grab", "Gojek", "InDriver"],
            "scooter_rental": {
                "available": True,
                "daily_rate": "$5-8",
                "license_required": True,
                "recommendation": (
                    "IDP technically required. Only if experienced - traffic is chaotic. "
                    "Insurance doesn't cover scooter accidents."
                ),
            },
            "traffic_note": (
                "Avoid Seminyak-Kuta 5-7pm. Use Bypass road for long distances. "
                "Google Maps works well."
            ),
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
        "connectivity": {
            "best_sim_provider": "Telkomsel (best coverage) or XL (cheaper data)",
            "sim_cost": "$5-10 for 10-30GB",
            "where_to_buy": "Official airport counter or Indomaret/Alfamart - avoid beach vendors",
            "esim_works": True,
            "wifi_quality": "Excellent in cafes/hotels, spotty in rural areas",
            "essential_apps": [
                "Grab/Gojek - rides and food delivery",
                "Google Maps - works well offline",
                "WhatsApp - locals prefer it over calls",
                "XE Currency - IDR has lots of zeros",
            ],
            "vpn_needed": False,
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
        "things_to_do": {
            "must_do": [
                {
                    "name": "USAT Liberty Wreck Dive (Tulamben)",
                    "why": "WWII shipwreck 30m from shore - world's most accessible wreck dive",
                    "booking": "Walk-in OK, sunrise dive best",
                    "best_time": "6-8am",
                    "cost": "$70-100 for 2 dives",
                },
                {
                    "name": "Tegallalang Rice Terraces",
                    "why": "Instagram-famous terraces with walking paths",
                    "booking": "No booking needed",
                    "best_time": "7-9am before crowds",
                    "cost": "$2 entrance + $1 per photo spot",
                },
                {
                    "name": "Uluwatu Temple Sunset + Kecak",
                    "why": "Dramatic clifftop temple with fire dance at sunset",
                    "booking": "Buy Kecak tickets on arrival - arrive by 5pm",
                    "best_time": "5-7pm",
                    "cost": "$5 temple + $10 Kecak",
                },
                {
                    "name": "Tirta Empul Purification",
                    "why": "Sacred spring temple - participate in Balinese water blessing ritual",
                    "booking": "No booking",
                    "best_time": "Early morning or late afternoon",
                    "cost": "$3 + sarong rental",
                },
                {
                    "name": "Nusa Penida Day Trip",
                    "why": "Dramatic cliffs, Kelingking Beach viewpoint, manta ray snorkeling",
                    "booking": "Book tour day before",
                    "best_time": "All day - leave early",
                    "cost": "$40-60 including boat",
                },
                {
                    "name": "Mount Batur Sunrise Trek",
                    "why": "Active volcano sunrise hike with breakfast cooked in volcanic steam",
                    "booking": "Book day before via hotel",
                    "best_time": "2am pickup, summit by 6am",
                    "cost": "$35-50 with guide",
                },
                {
                    "name": "Seminyak Beach Club Day",
                    "why": "Bali's best beach clubs - Potato Head, Ku De Ta, La Plancha",
                    "booking": "Potato Head: reserve for sunset",
                    "best_time": "2pm onwards",
                    "cost": "$20-50 for bed + drinks",
                },
                {
                    "name": "Ubud Monkey Forest",
                    "why": "Sacred forest with 1000+ monkeys and ancient temples",
                    "booking": "No booking",
                    "best_time": "8am or 4pm",
                    "cost": "$5",
                },
                {
                    "name": "Balinese Cooking Class",
                    "why": "Market visit + hands-on cooking + feast",
                    "booking": "Book 1-2 days ahead",
                    "best_time": "Morning classes best",
                    "cost": "$30-50",
                },
                {
                    "name": "Gili Islands Overnight",
                    "why": "No cars, clear water, sea turtles, laid-back vibe",
                    "booking": "Book fast boat ahead in high season",
                    "best_time": "2-3 nights ideal",
                    "cost": "$40 fast boat each way",
                },
            ],
            "day_trips": [
                {
                    "destination": "Nusa Penida",
                    "distance": "45 min boat",
                    "highlight": "Kelingking Beach, Crystal Bay, manta rays",
                },
                {
                    "destination": "Sidemen Valley",
                    "distance": "1.5 hours",
                    "highlight": "Untouched rice terraces, Mt Agung views, no crowds",
                },
                {
                    "destination": "Munduk Waterfalls",
                    "distance": "2 hours",
                    "highlight": "Multiple waterfalls, cool climate, coffee plantations",
                },
                {
                    "destination": "Amed",
                    "distance": "2.5 hours",
                    "highlight": "Black sand beaches, snorkeling, Japanese shipwreck",
                },
            ],
            "hidden_gems": [
                {
                    "name": "Tibumana Waterfall",
                    "why": "Less crowded than Tegenungan, just as beautiful",
                    "tip": "Go before 10am for photos without people",
                },
                {
                    "name": "Warung Babi Guling Ibu Oka",
                    "why": "Anthony Bourdain's favorite suckling pig",
                    "tip": "Get there by 11:30am - sells out by 2pm",
                },
                {
                    "name": "Pura Lempuyang (without crowds)",
                    "why": "Gates of Heaven temple",
                    "tip": "Go at 7am or skip - midday queues are 2-3 hours for one photo",
                },
                {
                    "name": "Sanur Beach sunrise",
                    "why": "East-facing beach with calm water, no waves",
                    "tip": "Rent a bike and ride the boardwalk at dawn",
                },
            ],
            "skip_these": [
                "Tanah Lot at sunset (overcrowded, same view from nearby beach cafe)",
                "Kuta Beach (dirty, aggressive vendors)",
                "Waterbom Park (expensive, a whole day for a water park?)",
                "Bali Safari for non-families (zoo with Indonesian animals - skip)",
            ],
        },
        "neighborhoods": {
            "where_to_stay": [
                {
                    "name": "Seminyak",
                    "vibe": "Upscale beach bars, boutique shopping, sunset clubs",
                    "best_for": ["Beach clubs", "Nightlife", "Shopping"],
                    "price_range": "Mid-range to Luxury",
                    "walkability": "High",
                },
                {
                    "name": "Canggu",
                    "vibe": "Surf town turned digital nomad hub, trendy cafes",
                    "best_for": ["Surfers", "Remote workers", "Yoga"],
                    "price_range": "Budget to Mid-range",
                    "walkability": "Medium - scooter helpful",
                },
                {
                    "name": "Ubud",
                    "vibe": "Cultural heart, rice terraces, temples, wellness",
                    "best_for": ["Culture", "Nature", "Wellness", "Art"],
                    "price_range": "All ranges",
                    "walkability": "Medium",
                },
                {
                    "name": "Uluwatu",
                    "vibe": "Clifftop surf breaks, luxury resorts, dramatic coast",
                    "best_for": ["Surfers", "Honeymooners", "Luxury seekers"],
                    "price_range": "Mid-range to Luxury",
                    "walkability": "Low - need transport",
                },
                {
                    "name": "Sanur",
                    "vibe": "Calm, family-friendly, old-school Bali charm",
                    "best_for": ["Families", "Older travelers", "Kitesurfing"],
                    "price_range": "Budget to Mid-range",
                    "walkability": "High",
                },
                {
                    "name": "Nusa Dua",
                    "vibe": "Resort enclave, manicured beaches, water sports",
                    "best_for": ["Families", "All-inclusive seekers"],
                    "price_range": "Luxury",
                    "walkability": "Low - resort-focused",
                },
            ],
            "avoid_staying_in": [
                "Kuta (noisy, touristy, aggressive vendors - unless you want cheap nightlife)",
                "Legian (same issues as Kuta, slightly better)",
            ],
        },
        "accommodation": {
            "types_available": [
                "Luxury resorts",
                "Boutique hotels",
                "Villas with pools",
                "Guesthouses",
                "Hostels",
                "Airbnb",
            ],
            "booking_platforms": [
                "Booking.com",
                "Agoda (often cheaper in Asia)",
                "Airbnb for villas",
                "Hostelworld",
            ],
            "price_ranges": {
                "hostel": "$8-15/night",
                "budget_hotel": "$20-40/night",
                "mid_range": "$60-150/night",
                "luxury": "$200-500+/night",
            },
            "book_ahead": (
                "2-3 weeks for peak season (Jul-Aug, Dec-Jan). Last minute OK in low season."
            ),
        },
        "scams_traps": {
            "common_scams": [
                {
                    "name": "Money Changer Scam",
                    "how_it_works": (
                        "Shows good rate, palms bills during counting or uses rigged calculator"
                    ),
                    "how_to_avoid": (
                        "Use ATMs or official changers (BMC, Central Kuta). "
                        "Count carefully, don't let them recount."
                    ),
                },
                {
                    "name": "Taxi Meter Scam",
                    "how_it_works": "Claims meter is broken, quotes inflated price",
                    "how_to_avoid": (
                        "Use Grab/Gojek or Blue Bird taxis only. Always insist on meter."
                    ),
                },
                {
                    "name": "Temple Guide Scam",
                    "how_it_works": "Unofficial 'guide' demands payment for unsolicited tour",
                    "how_to_avoid": "Politely decline. Official guides have ID cards.",
                },
                {
                    "name": "Broken Rental Damage",
                    "how_it_works": "Claims you damaged scooter/surfboard, demands cash",
                    "how_to_avoid": "Photo everything before renting. Use reputable shops.",
                },
            ],
            "tourist_traps": [
                "Overpriced restaurants on Monkey Forest Road in Ubud",
                "Beach vendors at Kuta - 10x the fair price",
                "Airport taxi counter (use Grab pickup point instead)",
            ],
            "taxi_scam_tip": (
                "ONLY use Grab, Gojek, or Blue Bird (blue cars with bird logo). "
                "Never accept 'my friend has cheaper price' offers at airport."
            ),
            "general_advice": (
                "Be friendly but firm. 'No thank you' and keep walking works. "
                "Most Balinese are genuinely kind."
            ),
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
        "recommendations": [
            {
                "title": "Use Grab/Gojek",
                "description": "Ride-hailing apps for safe, metered transport",
                "category": "logistics",
                "logic_hook": "50% cheaper than taxis, no haggling, tracked rides",
            },
            {
                "title": "USAT Liberty Wreck Dive",
                "description": "World-class WWII shipwreck dive in Tulamben",
                "category": "activity",
                "logic_hook": "30m from shore - accessible to all cert levels. Best 6-8am.",
            },
            {
                "title": "Ubud Rice Terraces",
                "description": "Tegallalang terraces - iconic Instagram spot",
                "category": "attraction",
                "logic_hook": "Arrive before 9am to avoid crowds and heat",
            },
            {
                "title": "Uluwatu Kecak Dance",
                "description": "Sunset fire dance at clifftop temple",
                "category": "attraction",
                "logic_hook": "Arrive by 5pm for good seats - performance at 6pm",
            },
            {
                "title": "Warung Babi Guling Ibu Oka",
                "description": "Famous Ubud suckling pig - Anthony Bourdain's pick",
                "category": "dining",
                "logic_hook": "Get there by 11:30am - sells out daily by 2pm",
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
        # New comprehensive format
        return LocalExpertOutput(
            destination_overview=DestinationOverview(**knowledge.get("destination_overview", {})),
            visa_entry=VisaEntry(**knowledge.get("visa_entry", {})),
            safety_health=SafetyHealth(**knowledge.get("safety_health", {})),
            money_costs=MoneyCosts(
                currency=knowledge.get("money_costs", {}).get("currency", ""),
                exchange_tip=knowledge.get("money_costs", {}).get("exchange_tip", ""),
                atm_note=knowledge.get("money_costs", {}).get("atm_note", ""),
                tipping=TippingInfo(**knowledge.get("money_costs", {}).get("tipping", {})),
                typical_costs=TypicalCosts(
                    **knowledge.get("money_costs", {}).get("typical_costs", {})
                ),
                daily_budget=DailyBudget(
                    **knowledge.get("money_costs", {}).get("daily_budget", {})
                ),
                haggling=knowledge.get("money_costs", {}).get("haggling", ""),
            ),
            transportation=Transportation(
                airport_to_city=[
                    AirportTransfer(**t)
                    for t in knowledge.get("transportation", {}).get("airport_to_city", [])
                ],
                public_transit=PublicTransit(
                    **knowledge.get("transportation", {}).get("public_transit", {})
                ),
                ride_apps=knowledge.get("transportation", {}).get("ride_apps", []),
                scooter_rental=ScooterRental(
                    **knowledge.get("transportation", {}).get("scooter_rental", {})
                ),
                traffic_note=knowledge.get("transportation", {}).get("traffic_note", ""),
            ),
            cultural_norms=CulturalNorms(
                dress_code=DressCode(**knowledge.get("cultural_norms", {}).get("dress_code", {})),
                religious_notes=knowledge.get("cultural_norms", {}).get("religious_notes", ""),
                greetings=knowledge.get("cultural_norms", {}).get("greetings", ""),
                photo_etiquette=knowledge.get("cultural_norms", {}).get("photo_etiquette", ""),
                dining_etiquette=knowledge.get("cultural_norms", {}).get("dining_etiquette", []),
                lgbtq_friendly=knowledge.get("cultural_norms", {}).get("lgbtq_friendly", ""),
                important_taboos=knowledge.get("cultural_norms", {}).get("important_taboos", []),
            ),
            connectivity=Connectivity(**knowledge.get("connectivity", {})),
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
            things_to_do=ThingsToDo(
                must_do=[
                    MustDoExperience(**e)
                    for e in knowledge.get("things_to_do", {}).get("must_do", [])
                ],
                day_trips=[
                    DayTrip(**t) for t in knowledge.get("things_to_do", {}).get("day_trips", [])
                ],
                hidden_gems=[
                    HiddenGem(**g) for g in knowledge.get("things_to_do", {}).get("hidden_gems", [])
                ],
                skip_these=knowledge.get("things_to_do", {}).get("skip_these", []),
            ),
            neighborhoods=Neighborhoods(
                where_to_stay=[
                    Neighborhood(**n)
                    for n in knowledge.get("neighborhoods", {}).get("where_to_stay", [])
                ],
                avoid_staying_in=knowledge.get("neighborhoods", {}).get("avoid_staying_in", []),
            ),
            accommodation=Accommodation(
                types_available=knowledge.get("accommodation", {}).get("types_available", []),
                booking_platforms=knowledge.get("accommodation", {}).get("booking_platforms", []),
                price_ranges=AccommodationPrices(
                    **knowledge.get("accommodation", {}).get("price_ranges", {})
                ),
                book_ahead=knowledge.get("accommodation", {}).get("book_ahead", ""),
            ),
            scams_traps=ScamsTraps(
                common_scams=[
                    Scam(**s) for s in knowledge.get("scams_traps", {}).get("common_scams", [])
                ],
                tourist_traps=knowledge.get("scams_traps", {}).get("tourist_traps", []),
                taxi_scam_tip=knowledge.get("scams_traps", {}).get("taxi_scam_tip", ""),
                general_advice=knowledge.get("scams_traps", {}).get("general_advice", ""),
            ),
            packing=Packing(
                must_pack=knowledge.get("packing", {}).get("must_pack", []),
                dont_bring=knowledge.get("packing", {}).get("dont_bring", []),
                buy_locally=knowledge.get("packing", {}).get("buy_locally", []),
                electrical=ElectricalInfo(**knowledge.get("packing", {}).get("electrical", {})),
                clothing_tips=knowledge.get("packing", {}).get("clothing_tips", []),
            ),
            constraints=[LocalConstraint(**c) for c in knowledge.get("constraints", [])],
            recommendations=[
                LocalRecommendation(**r) for r in knowledge.get("recommendations", [])
            ],
            quick_tips=knowledge.get("quick_tips", []),
        )
    else:
        # Legacy format - just constraints and recommendations
        constraints = [LocalConstraint(**c) for c in knowledge.get("constraints", [])]
        recommendations = [LocalRecommendation(**r) for r in knowledge.get("recommendations", [])]
        return LocalExpertOutput(constraints=constraints, recommendations=recommendations)


# =============================================================================
# Local Expert Node
# =============================================================================


async def local_expert(state: GraphState) -> GraphState:
    """
    The 'Concierge' agent. Adds logistical constraints and city tips.

    Triggered by default when no niche specialist is requested.
    Returns a StrategySection with constraints and recommendations.

    CRITICAL: Multi-specialist support - same pattern as vertical_specialist.
    """
    from app.debug_utils import log

    # MULTI-SPECIALIST SUPPORT: Pop from pending if active_specialist is not set
    if not state.active_specialist and state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        state.pending_specialists = state.pending_specialists[1:]
        state.active_specialist = next_specialist
        state.active_agent_id = next_specialist
        state.ui_events.append("SPECIALIST_ACTIVE")
        log("LOCAL_EXPERT", f"Multi-specialist loop: popped '{next_specialist}' from queue")
        # If next specialist is not local_expert, we shouldn't be here - but handle gracefully
        if next_specialist != "local_expert":
            log("LOCAL_EXPERT", f"WARNING: Expected local_expert but got {next_specialist}")

    plan = state.trip_plan

    # Skip if no destination
    if not plan.destination:
        log("LOCAL_EXPERT", "Skipped - no destination set")
        state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
        state.active_specialist = None  # Clear for multi-specialist support
        return state

    log("LOCAL_EXPERT", f"Activated for {plan.destination}")

    # ==========================================================================
    # SELECTIVE REGENERATION: Check if cached output can be reused
    # @see docs/plan_graph_analysis.md - Selective Regeneration Strategy
    # ==========================================================================
    existing_sections = state.metadata.get("strategy_sections", [])
    cached_section = next(
        (s for s in existing_sections if s.get("specialist_type") == "local_expert"), None
    )

    if cached_section:
        # Check if destination matches (local_expert caches are destination-specific)
        # The title format is "{destination} Trip Overview"
        cached_title = cached_section.get("title", "")
        current_destination = plan.destination
        if cached_title and current_destination and current_destination in cached_title:
            log("LOCAL_EXPERT", f"Cache HIT: Reusing cached output for {current_destination}")
            state.metadata["last_executed_specialist"] = "local_expert"
            state.active_specialist = None
            return state  # No-op, output already in state from session restore

    try:
        return await _run_local_expert(state, plan, log)
    except Exception as e:
        # Catch any unexpected errors to prevent graph crash
        from app.debug_utils import _debug_error

        _debug_error(f"LOCAL_EXPERT unexpected error: {e}")
        log("LOCAL_EXPERT", f"Error - returning state unchanged: {type(e).__name__}")
        state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
        state.active_specialist = None  # Clear for multi-specialist support
        return state


async def _run_local_expert(state: GraphState, plan, log) -> GraphState:
    """Inner implementation with the actual logic."""

    # ==========================================================================
    # Step 1: Get static knowledge first (guaranteed content)
    # ==========================================================================
    static_knowledge = _get_static_local_knowledge(plan.destination)
    has_static = bool(static_knowledge.constraints or static_knowledge.recommendations)

    if has_static:
        log("LOCAL_EXPERT", f"Found static knowledge for {plan.destination}")

    # ==========================================================================
    # Step 2: Try LLM for additional/dynamic content
    # ==========================================================================
    response = None
    use_llm = os.getenv("LOCAL_EXPERT_USE_LLM", "false").lower() == "true"

    if use_llm:
        prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "specialists"
        prompt_file = prompts_dir / "local_expert.txt"

        if prompt_file.exists():
            system_prompt = prompt_file.read_text()
        else:
            system_prompt = """You are a local logistics expert. Provide:
1. Constraints: Opening hours, booking requirements, seasonal considerations
2. Recommendations: Transit passes, efficiency tips, cultural notes
Output as JSON with "constraints" and "recommendations" arrays."""

        user_context = f"""
Destination: {plan.destination}
Dates: {plan.start_date or "Not specified"} to {plan.end_date or "Not specified"}
Travelers: {plan.adults} adults{f", {plan.children} children" if plan.children else ""}
"""

        model = os.getenv("EXTRACTION_MODEL", "gpt-4o-mini")
        llm = ChatOpenAI(model=model, temperature=0.3, timeout=30, max_retries=1)
        structured_llm = llm.with_structured_output(LocalExpertOutput)

        log("LOCAL_EXPERT", f"Calling LLM ({model})...")

        try:
            response = await structured_llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_context),
                ]
            )
            log("LOCAL_EXPERT", "LLM call completed")
        except Exception as e:
            from app.debug_utils import _debug_error

            _debug_error(f"LOCAL_EXPERT LLM Error: {e}")
            log("LOCAL_EXPERT", f"LLM error, using static knowledge: {type(e).__name__}")
            response = None
    else:
        log("LOCAL_EXPERT", "Using static knowledge only (LLM disabled)")

    # ==========================================================================
    # Step 3: Merge static and LLM content (prefer static for consistency)
    # ==========================================================================
    if response is None:
        response = static_knowledge
    elif has_static:
        # Merge: static first, then LLM additions
        merged_constraints = list(static_knowledge.constraints)
        merged_recommendations = list(static_knowledge.recommendations)

        # Add LLM content that doesn't duplicate static
        static_constraint_descs = {c.description for c in static_knowledge.constraints}
        static_rec_titles = {r.title for r in static_knowledge.recommendations}

        for c in response.constraints:
            if c.description not in static_constraint_descs:
                merged_constraints.append(c)

        for r in response.recommendations:
            if r.title not in static_rec_titles:
                merged_recommendations.append(r)

        response = LocalExpertOutput(
            constraints=merged_constraints[:5],  # Limit to prevent clutter
            recommendations=merged_recommendations[:5],
        )

    # CRITICAL: Always generate a Trip Overview, even without specific knowledge
    # This ensures the UI has an anchor card (Trip DNA) for the destination
    # @see docs/ux_unified_architecture.md Section III.A - "Local Expert Always First"
    if not response.constraints and not response.recommendations:
        log(
            "LOCAL_EXPERT",
            f"No specific knowledge for {plan.destination} - generating Trip Overview",
        )
        # Generate basic Trip Overview with Unsplash images
        response = LocalExpertOutput(
            constraints=[],
            recommendations=[
                LocalRecommendation(
                    title=f"Explore {plan.destination}",
                    description=f"Discover the highlights of {plan.destination}",
                    category="general",
                    logic_hook="Destination Overview",
                ),
            ],
        )

    # ==========================================================================
    # Build Strategy Section
    # ==========================================================================

    # Map constraints to schema format
    constraints_applied = []
    for c in response.constraints:
        constraints_applied.append(
            {
                "rule": c.description,
                "type": c.type,
                "reason": c.severity,
            }
        )

    # Map recommendations to content_added format
    content_added = []
    for r in response.recommendations:
        content_added.append(
            {
                "title": r.title,
                "description": r.description,
                "type": r.category,
                "logic_hook": r.logic_hook,
            }
        )

    # Fetch destination gallery ("Vibe Trio") if available
    dest_key = plan.destination.lower().strip()
    gallery_images = []
    if dest_key in DEMO_MANIFEST:
        gallery_images = DEMO_MANIFEST[dest_key].get("destination_gallery", [])

    # FALLBACK: Generate curated images for destinations without curated gallery
    # This ensures the Magazine Layout always has visual content
    if not gallery_images:
        gallery_images = get_destination_gallery(plan.destination)

    # Build comprehensive travel intelligence data from 12 categories
    travel_intelligence = {
        "destination_overview": (
            response.destination_overview.model_dump() if response.destination_overview else None
        ),
        "visa_entry": response.visa_entry.model_dump() if response.visa_entry else None,
        "safety_health": response.safety_health.model_dump() if response.safety_health else None,
        "money_costs": response.money_costs.model_dump() if response.money_costs else None,
        "transportation": response.transportation.model_dump() if response.transportation else None,
        "cultural_norms": response.cultural_norms.model_dump() if response.cultural_norms else None,
        "connectivity": response.connectivity.model_dump() if response.connectivity else None,
        "seasonality": response.seasonality.model_dump() if response.seasonality else None,
        "things_to_do": response.things_to_do.model_dump() if response.things_to_do else None,
        "neighborhoods": response.neighborhoods.model_dump() if response.neighborhoods else None,
        "accommodation": response.accommodation.model_dump() if response.accommodation else None,
        "scams_traps": response.scams_traps.model_dump() if response.scams_traps else None,
        "packing": response.packing.model_dump() if response.packing else None,
        "quick_tips": response.quick_tips or [],
    }

    # Build the strategy section
    # NOTE: Local Expert uses Magazine Layout (gallery + tips), NOT General Layout (stats grid)
    # trip_summary is intentionally OMITTED - frontend renders different layout for local_expert
    # @see docs/ux_unified_architecture.md Section XII - Magazine Layout for Local Expert
    one_liner = (
        response.destination_overview.tagline
        if response.destination_overview and response.destination_overview.tagline
        else f"Your adventure in {plan.destination}"
    )
    section = build_local_expert_section(
        destination=plan.destination,
        one_liner=one_liner,
        bullets=[c.description for c in response.constraints[:3]],
        must_dos=[r.title for r in response.recommendations[:5]],
        logistics_notes=[r.description for r in response.recommendations],
        constraints_applied=constraints_applied,
        content_added=content_added,
        gallery_images=gallery_images,
        travel_intelligence=travel_intelligence,
    )

    # ==========================================================================
    # Update State
    # ==========================================================================

    # DEBUG: Log incoming strategy_sections
    from app.debug_utils import _debug_log

    incoming_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"local_expert: BEFORE update - {len(incoming_sections)} sections, "
        f"types={[s.get('specialist_type') for s in incoming_sections]}"
    )

    upsert_section(state.metadata, section, mode="appendable")

    # DEBUG: Log outgoing strategy_sections
    outgoing_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"local_expert: AFTER update - {len(outgoing_sections)} sections, "
        f"types={[s.get('specialist_type') for s in outgoing_sections]}"
    )

    mark_topic_executed(state.metadata, "local_expert")

    log(
        "LOCAL_EXPERT",
        f"Added {len(constraints_applied)} constraints, {len(content_added)} tips",
    )

    state.metadata["local_expert_ran"] = True  # Persistent flag to prevent double execution
    state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
    state.active_specialist = None  # Clear for multi-specialist support
    return state
