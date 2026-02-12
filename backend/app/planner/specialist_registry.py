"""
Specialist Registry — Single source of truth for all specialist configuration.

Every specialist's keywords, constraints, enhancements, feasibility flags,
and domain principles live here. Consumer files import derived constants
instead of maintaining their own copies.

Adding a new specialist = 1 registry entry + 1 .txt prompt file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class CrossDomainBlock:
    """Declarative cross-domain constraint.

    Source specialist's activity blocks cannot be scheduled within
    buffer_hours of target specialist's activity blocks.
    Guard enforces the TEMPORAL relationship — no geographic knowledge needed.
    """

    target_specialists: tuple[str, ...]  # ("skiing", "hiking", "climbing")
    buffer_hours: int  # 24
    severity: str  # "blocking"
    reason: str
    violation_code: str  # "ALTITUDE_AFTER_DIVE"


@dataclass(frozen=True)
class SpecialistConfig:
    """All data-driven configuration for a single specialist."""

    topic: str
    tier: int  # 1 = full LLM specialist, 2 = lightweight
    display_name: str = ""  # human-readable label for receipts/UI

    # --- Detection ---
    keywords: list[str] = field(default_factory=list)
    category_mappings: dict[str, str] = field(default_factory=dict)

    # --- Constraints (stored as dicts, hydrated to SpecialistConstraint at call site) ---
    hardcoded_constraints: list[dict] = field(default_factory=list)

    # --- Cross-domain constraints ---
    cross_domain_blocks: tuple[CrossDomainBlock, ...] = ()

    # --- Enhancements ---
    enhancements: list[str] = field(default_factory=list)

    # --- Feasibility flags ---
    has_geographic_constraint: bool = False  # triggers LLM feasibility check
    has_nofly_buffer: bool = False  # diving: 24h no-fly
    has_altitude_buffer: bool = False  # hiking/climbing: acclimatization

    # --- Trip duration ---
    min_days_needed: int = 3

    # --- Strategy section ---
    domain_default_principles: list[str] = field(default_factory=list)

    # --- Constraint canonicalization ---
    constraint_aliases: dict[str, list[str]] = field(default_factory=dict)


# =============================================================================
# Registry: 8 specialists
# =============================================================================

SPECIALIST_REGISTRY: dict[str, SpecialistConfig] = {
    # -----------------------------------------------------------------
    # DIVING
    # -----------------------------------------------------------------
    "diving": SpecialistConfig(
        topic="diving",
        tier=1,
        display_name="Diving Safety",
        keywords=[
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
            # Common typos (demo safety)
            "divng",
            "diveing",
            "snorkle",
            "snorkeling",
            "scubba",
        ],
        category_mappings={
            "diving": "diving",
            "scuba": "diving",
            "scuba diving": "diving",
            "freediving": "diving",
        },
        hardcoded_constraints=[
            {
                "constraint_id": "no_fly_24h",
                "type": "temporal",
                "rule": "min_24h_buffer_after_dive",
                "severity": "blocking",
                "applies_to_categories": ["flights"],
                "buffer_hours": 24,
                "reason": "Flying within 24h of diving risks decompression sickness",
                "label": "24h No-Fly Buffer",
                "icon": "🚫",
            },
        ],
        cross_domain_blocks=(
            CrossDomainBlock(
                target_specialists=("skiing", "hiking", "climbing"),
                buffer_hours=24,
                severity="blocking",
                reason="No high-altitude activities within 24h of diving — decompression risk",
                violation_code="ALTITUDE_AFTER_DIVE",
            ),
        ),
        enhancements=[
            "Book a dive shop for equipment rental in advance",
        ],
        has_geographic_constraint=True,
        has_nofly_buffer=True,
        min_days_needed=4,  # arrival + dive + no-fly buffer + departure
        domain_default_principles=[
            "24-hour no-fly buffer after dives",
            "Depth and time limits for safe diving",
            "Equipment and certification requirements",
        ],
        constraint_aliases={
            "min_24h_buffer_after_dive": [
                "no_fly_24h",
                "24h_no_fly",
                "diving_no_fly_buffer",
                "no_fly_after_dive",
                "24h_buffer_after_dive",
                "flight_buffer_24h",
                "no_fly_after_diving",
                "24h_no_fly_after_diving",
                "no_fly_buffer",
            ],
            "no_altitude_after_dive": [
                "no_altitude_24h",
                "altitude_buffer",
                "no_altitude_after_diving",
                "altitude_restriction_after_dive",
                "altitude_after_dive",
            ],
            "surface_interval": [
                "min_18h_surface_interval",
                "dive_surface_interval",
            ],
        },
    ),
    # -----------------------------------------------------------------
    # HIKING
    # -----------------------------------------------------------------
    "hiking": SpecialistConfig(
        topic="hiking",
        tier=1,
        display_name="Altitude Safety",
        keywords=[
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
            # Common typos (demo safety)
            "hikeing",
            "hikng",
            "trekk",
            "treking",
        ],
        category_mappings={
            "hiking": "hiking",
            "trekking": "hiking",
            "mountaineering": "hiking",
            "camping": "hiking",
            "backpacking": "hiking",
        },
        hardcoded_constraints=[
            {
                "constraint_id": "morning_start_recommended",
                "type": "temporal",
                "rule": "morning_start_recommended",
                "severity": "soft",
                "applies_to_categories": ["activities"],
                "reason": (
                    "Morning starts recommended for mountain hikes to avoid afternoon weather"
                ),
                "label": "Morning Start",
                "icon": "🌅",
            },
            {
                "constraint_id": "proper_footwear_required",
                "type": "equipment",
                "rule": "proper_footwear_required",
                "severity": "soft",
                "applies_to_categories": ["activities"],
                "reason": "Proper footwear required for steep terrain",
                "label": "Proper Footwear",
                "icon": "🥾",
            },
            {
                "constraint_id": "altitude_acclimatization",
                "type": "safety",
                "rule": "altitude_acclimatization",
                "severity": "strong",
                "applies_to_categories": ["activities"],
                "reason": "Max 500m elevation gain per day above 3000m",
                "label": "Altitude Acclimatization",
                "icon": "🏔️",
            },
        ],
        enhancements=[
            "Check weather forecasts before departure",
            "Download offline maps for the trails",
        ],
        has_altitude_buffer=True,
        min_days_needed=3,
        domain_default_principles=[
            "Altitude acclimatization schedule",
            "Daily elevation gain limits",
            "Rest day planning",
        ],
        constraint_aliases={
            "morning_start_recommended": [
                "early_start",
                "morning_activity",
                "am_start",
            ],
        },
    ),
    # -----------------------------------------------------------------
    # SKIING
    # -----------------------------------------------------------------
    "skiing": SpecialistConfig(
        topic="skiing",
        tier=1,
        display_name="Snow Safety",
        keywords=[
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
            # Common typos (demo safety)
            "skii",
            "skiig",
            "skking",
            "sking",
            "snowbord",
        ],
        category_mappings={
            "skiing": "skiing",
            "snowboarding": "skiing",
            "snow sports": "skiing",
            "winter sports": "skiing",
        },
        hardcoded_constraints=[
            {
                "constraint_id": "avalanche_check",
                "type": "safety",
                "rule": "check_snow_conditions",
                "severity": "blocking",
                "applies_to_categories": ["activities"],
                "reason": "Check avalanche bulletin before off-piste skiing",
                "label": "Avalanche Check Required",
                "icon": "🏔️",
            },
        ],
        enhancements=[
            "Book ski passes in advance for better rates",
            "Consider private lessons for the first day",
        ],
        has_geographic_constraint=True,
        min_days_needed=3,
        domain_default_principles=[
            "Slope difficulty progression",
            "Weather window optimization",
            "Equipment rental coordination",
        ],
    ),
    # -----------------------------------------------------------------
    # CYCLING
    # -----------------------------------------------------------------
    "cycling": SpecialistConfig(
        topic="cycling",
        tier=1,
        display_name="Cycling",
        keywords=[
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
        category_mappings={
            "cycling": "cycling",
            "biking": "cycling",
            "mountain biking": "cycling",
            "road cycling": "cycling",
        },
        enhancements=[
            "Rent a quality bike from a reputable local shop",
            "Bring or purchase padded cycling shorts",
        ],
        domain_default_principles=[
            "Route difficulty progression",
            "Hydration and nutrition planning",
            "Equipment and bike fit",
        ],
    ),
    # -----------------------------------------------------------------
    # SURFING
    # -----------------------------------------------------------------
    "surfing": SpecialistConfig(
        topic="surfing",
        tier=1,
        display_name="Surfing",
        keywords=[
            "surf",
            "surfing",
            "wave",
            "swell",
            "barrel",
            "longboard",
            "shortboard",
            "bodyboard",
            "reef break",
            "point break",
            "beach break",
            "wetsuit",
            "lineup",
        ],
        category_mappings={
            "surfing": "surfing",
            "surf": "surfing",
        },
        hardcoded_constraints=[
            {
                "constraint_id": "tide_and_swell_check",
                "type": "safety",
                "rule": "tide_and_swell_check",
                "severity": "soft",
                "applies_to_categories": ["activities"],
                "reason": "Check tide charts and swell forecasts before each session",
                "label": "Tide & Swell Check",
                "icon": "🌊",
            },
            {
                "constraint_id": "reef_awareness",
                "type": "safety",
                "rule": "reef_awareness",
                "severity": "strong",
                "applies_to_categories": ["activities"],
                "reason": (
                    "Shallow reef breaks require booties and awareness of"
                    " tide-dependent depth — avoid surfing reef breaks at low tide"
                    " without experience"
                ),
                "label": "Reef Safety",
                "icon": "🪸",
            },
            {
                "constraint_id": "skill_appropriate_breaks",
                "type": "equipment",
                "rule": "skill_appropriate_breaks",
                "severity": "soft",
                "applies_to_categories": ["activities"],
                "reason": (
                    "Match surf spot difficulty to skill level — beginners"
                    " should avoid heavy reef breaks like Uluwatu or Padang Padang"
                ),
                "label": "Skill-Appropriate Breaks",
                "icon": "🏄",
            },
        ],
        enhancements=[
            "Check swell forecast and tide charts before each session",
            "Book a surf lesson if visiting a new break",
        ],
        domain_default_principles=[
            "Wave and swell forecast planning",
            "Skill-appropriate break selection",
            "Tide and safety awareness",
        ],
    ),
    # -----------------------------------------------------------------
    # CLIMBING (NEW)
    # -----------------------------------------------------------------
    "climbing": SpecialistConfig(
        topic="climbing",
        tier=1,
        display_name="Altitude Safety",
        keywords=[
            "climb",
            "climbing",
            "rock climbing",
            "bouldering",
            "crag",
            "belay",
            "rappel",
            "abseil",
            "via ferrata",
            "sport climbing",
            "trad climbing",
            "top rope",
            "lead climbing",
            "carabiner",
            "harness",
            "ascent",
        ],
        category_mappings={
            "climbing": "climbing",
            "rock climbing": "climbing",
            "bouldering": "climbing",
        },
        hardcoded_constraints=[
            {
                "constraint_id": "altitude_acclimatization",
                "type": "safety",
                "rule": "altitude_acclimatization",
                "severity": "strong",
                "applies_to_categories": ["activities"],
                "reason": "Max 500m elevation gain per day above 3000m",
                "label": "Altitude Acclimatization",
                "icon": "🏔️",
            },
            {
                "constraint_id": "gear_check_required",
                "type": "equipment",
                "rule": "gear_check_required",
                "severity": "strong",
                "applies_to_categories": ["activities"],
                "reason": "All climbing gear must be inspected before each climb",
                "label": "Gear Inspection",
                "icon": "🧗",
            },
        ],
        enhancements=[
            "Hire a local climbing guide for unfamiliar crags",
            "Check route conditions and recent beta online",
        ],
        has_altitude_buffer=True,
        min_days_needed=3,
        domain_default_principles=[
            "Route difficulty progression",
            "Altitude acclimatization schedule",
            "Gear inspection and safety protocols",
        ],
    ),
    # -----------------------------------------------------------------
    # SAILING (NEW — replaces "boating")
    # -----------------------------------------------------------------
    "sailing": SpecialistConfig(
        topic="sailing",
        tier=1,
        display_name="Sailing",
        keywords=[
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
            "ketch",
            "sloop",
            "dinghy",
            "windward",
        ],
        category_mappings={
            "sailing": "sailing",
            "boating": "sailing",  # backward compat
            "yacht": "sailing",
            "charter": "sailing",
        },
        enhancements=[
            "Check marine weather forecast before departure",
            "Book marina berths in advance during peak season",
        ],
        domain_default_principles=[
            "Weather window planning",
            "Route and harbor logistics",
            "Safety equipment checks",
        ],
    ),
    # -----------------------------------------------------------------
    # WILDLIFE SAFARI (NEW)
    # -----------------------------------------------------------------
    "wildlife_safari": SpecialistConfig(
        topic="wildlife_safari",
        tier=1,
        display_name="Wildlife Safari",
        keywords=[
            "safari",
            "wildlife",
            "game drive",
            "big five",
            "savanna",
            "bush",
            "lodge",
            "conservation",
            "migration",
            "national park",
            "game reserve",
            "wildlife photography",
            "bird watching",
            "birding",
            "jungle trek",
        ],
        category_mappings={
            "safari": "wildlife_safari",
            "wildlife safari": "wildlife_safari",
            "game drive": "wildlife_safari",
            "wildlife": "wildlife_safari",
        },
        hardcoded_constraints=[
            {
                "constraint_id": "guide_required_reserves",
                "type": "safety",
                "rule": "guide_required",
                "severity": "strong",
                "applies_to_categories": ["activities"],
                "reason": "Professional guide required in big five reserves",
                "label": "Guide Required",
                "icon": "🦁",
            },
        ],
        enhancements=[
            "Book game drives at dawn and dusk for best sightings",
            "Pack neutral-colored clothing and binoculars",
        ],
        domain_default_principles=[
            "Seasonal migration awareness",
            "Guide and reserve logistics",
            "Wildlife-safe behavior protocols",
        ],
        constraint_aliases={
            "guide_required": [
                "requires_guide",
                "guided_activity",
                "professional_guide",
            ],
        },
    ),
}


# =============================================================================
# Derived constants (computed once at import time)
# =============================================================================

TIER1_SPECIALIST_NAMES: frozenset[str] = frozenset(
    topic for topic, cfg in SPECIALIST_REGISTRY.items() if cfg.tier == 1
)

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

ALL_SPECIALIST_KEYWORDS: dict[str, list[str]] = {
    cfg.topic: cfg.keywords for cfg in SPECIALIST_REGISTRY.values() if cfg.keywords
}

ALL_CATEGORY_TO_SPECIALIST: dict[str, str] = {}
for _cfg in SPECIALIST_REGISTRY.values():
    ALL_CATEGORY_TO_SPECIALIST.update(_cfg.category_mappings)

ALL_CONSTRAINT_ALIASES: dict[str, list[str]] = {}
for _cfg in SPECIALIST_REGISTRY.values():
    for _canonical, _aliases in _cfg.constraint_aliases.items():
        if _canonical in ALL_CONSTRAINT_ALIASES:
            # Merge without duplicates
            existing = set(ALL_CONSTRAINT_ALIASES[_canonical])
            existing.update(_aliases)
            ALL_CONSTRAINT_ALIASES[_canonical] = sorted(existing)
        else:
            ALL_CONSTRAINT_ALIASES[_canonical] = list(_aliases)

ALL_DOMAIN_DEFAULT_PRINCIPLES: dict[str, list[str]] = {
    cfg.topic: cfg.domain_default_principles
    for cfg in SPECIALIST_REGISTRY.values()
    if cfg.domain_default_principles
}

DOMAIN_DEFAULT_FALLBACK: list[str] = [
    "{specialist_type} safety protocols active",
    "Expert recommendations applied",
    "Optimized scheduling",
]


# =============================================================================
# Helper functions
# =============================================================================


def get(topic: str) -> Optional[SpecialistConfig]:
    """Look up a specialist config by topic name."""
    return SPECIALIST_REGISTRY.get(topic)


def load_prompt(topic: str) -> Optional[str]:
    """Load specialist prompt from .txt file. Returns None if not found."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "specialists"
    prompt_file = prompts_dir / f"{topic}.txt"
    if prompt_file.exists():
        return prompt_file.read_text()
    return None


def get_nofly_buffer_hours(topic: str) -> int | None:
    """Return buffer hours if specialist has nofly constraint, else None."""
    cfg = SPECIALIST_REGISTRY.get(topic)
    if not cfg or not cfg.has_nofly_buffer:
        return None
    for c in cfg.hardcoded_constraints:
        if c.get("buffer_hours"):
            return c["buffer_hours"]
    return 24  # default fallback


def prompt_hash(topic: str) -> str:
    """8-char stable hash of prompt file content for cache key versioning.

    Returns 'noprompt' if file missing (fallback specialists).
    """
    from app.planner.hashing import stable_hash_short

    content = load_prompt(topic)
    return stable_hash_short(content) if content else "noprompt"


def canonicalize_rule(rule: str) -> str:
    """Normalize a constraint rule name to its canonical form."""
    if not rule:
        return rule
    normalized = rule.lower().replace("-", "_").replace(" ", "_")
    for canonical, aliases in ALL_CONSTRAINT_ALIASES.items():
        if normalized == canonical or any(normalized == a.lower() for a in aliases):
            return canonical
    return normalized


# =============================================================================
# Import-time validation
# =============================================================================

_EXPECTED_SPECIALISTS = {
    "diving",
    "hiking",
    "skiing",
    "cycling",
    "surfing",
    "climbing",
    "sailing",
    "wildlife_safari",
}
assert set(SPECIALIST_REGISTRY.keys()) == _EXPECTED_SPECIALISTS, (
    f"Registry mismatch: expected {_EXPECTED_SPECIALISTS}, got {set(SPECIALIST_REGISTRY.keys())}"
)
