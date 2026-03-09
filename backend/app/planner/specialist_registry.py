"""
Specialist Registry — Single source of truth for all specialist configuration.

Every specialist's keywords, constraints, enhancements, feasibility flags,
and domain principles live here. Consumer files import derived constants
instead of maintaining their own copies.

Adding a new specialist = 1 registry entry + 1 .txt prompt file.
"""

from __future__ import annotations

import re
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
    geographic_rule: str = ""  # human-readable rule for LLM feasibility prompt
    has_nofly_buffer: bool = False  # diving: 24h no-fly
    has_altitude_buffer: bool = False  # hiking/climbing: acclimatization

    # --- Trip duration ---
    min_days_needed: int = 3

    # --- Strategy section ---
    domain_default_principles: list[str] = field(default_factory=list)

    # --- Constraint canonicalization ---
    constraint_aliases: dict[str, list[str]] = field(default_factory=dict)

    # --- Pricing ---
    default_price_estimate: float = 50.0  # per-person baseline when GP returns no priceLevel

    # --- Backfill affinity (used by mock_provider to sort supplemental activities) ---
    backfill_affinity_tags: list[str] = field(default_factory=list)


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
        geographic_rule="Diving requires coastline, large lakes, or dedicated dive facilities. Landlocked cities cannot have diving.",
        has_nofly_buffer=True,
        min_days_needed=4,  # arrival + dive + no-fly buffer + departure
        domain_default_principles=[
            "24-hour no-fly buffer after dives",
            "Depth and time limits for safe diving",
            "Equipment and certification requirements",
        ],
        default_price_estimate=85.0,
        backfill_affinity_tags=["water", "outdoors"],
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
        default_price_estimate=45.0,
        backfill_affinity_tags=["outdoors", "culture"],
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
        default_price_estimate=120.0,
        backfill_affinity_tags=["outdoors", "culture"],
        has_geographic_constraint=True,
        geographic_rule="Skiing requires mountains with reliable snow or indoor ski facilities. Tropical destinations without mountains cannot have skiing.",
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
        default_price_estimate=55.0,
        backfill_affinity_tags=["outdoors", "culture"],
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
        default_price_estimate=65.0,
        backfill_affinity_tags=["water", "outdoors"],
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
        default_price_estimate=75.0,
        backfill_affinity_tags=["outdoors", "culture"],
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
        default_price_estimate=95.0,
        backfill_affinity_tags=["water", "outdoors"],
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
        default_price_estimate=110.0,
        backfill_affinity_tags=["outdoors", "culture"],
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

TIER2_COMMON_HINTS: frozenset[str] = frozenset(
    {
        "yoga",
        "cooking",
        "nightlife",
        "temples",
        "beach",
        "shopping",
        "photography",
        "sailing",
        "wellness",
        "cultural",
        "music",
        "wine",
        "food",
    }
)

# Backward-compat alias — consumers being migrated
TIER2_ACTIVITY_KEYWORDS = TIER2_COMMON_HINTS

ALL_SPECIALIST_KEYWORDS: dict[str, list[str]] = {
    cfg.topic: cfg.keywords for cfg in SPECIALIST_REGISTRY.values() if cfg.keywords
}

ALL_CATEGORY_TO_SPECIALIST: dict[str, str] = {}
for _cfg in SPECIALIST_REGISTRY.values():
    ALL_CATEGORY_TO_SPECIALIST.update(_cfg.category_mappings)

# Tier 2 display aliases (for synthesizer output normalization)
# Covers informal/plural forms that aren't in Tier 1 category_mappings.
TIER2_CATEGORY_ALIASES: dict[str, str] = {
    "party": "nightlife",
    "parties": "nightlife",
    "club": "nightlife",
    "clubs": "nightlife",
    "clubbing": "nightlife",
    "night out": "nightlife",
    "night outs": "nightlife",
    "hike": "hiking",
    "hikes": "hiking",
    "trek": "hiking",
    "treks": "hiking",
    "trekking": "hiking",
    "surf": "surfing",
    "surfs": "surfing",
    "dive": "diving",
    "dives": "diving",
    "scuba": "diving",
    "snorkel": "diving",
    "snorkeling": "diving",
    "spa": "wellness",
    "spas": "wellness",
    "culture": "cultural",
    "cuisine": "food",
}

# Merged view: Tier 1 category_mappings + Tier 2 display aliases
ALL_DISPLAY_ALIASES: dict[str, str] = {
    **ALL_CATEGORY_TO_SPECIALIST,
    **TIER2_CATEGORY_ALIASES,
}

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
    """Look up a specialist config by topic name.

    Returns None for Tier 2 / novel categories (yoga, nightlife, cooking, etc.)
    that have no dedicated specialist pipeline. None is the correct signal —
    callers MUST None-guard before accessing config attributes:
        if config and config.has_nofly_buffer: ...
    Do NOT substitute a default SpecialistConfig — that would imply Tier 2
    categories have specialist semantics (safety buffers, certifications, etc.)
    that they don't have.
    """
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


def get_nofly_buffer_days(topic: str) -> int:
    """Return no-fly buffer in whole days (ceil of buffer_hours / 24), or 0 if none."""
    hours = get_nofly_buffer_hours(topic)
    if hours is None:
        return 0
    return max(1, -(-hours // 24))  # ceiling division


def get_cross_domain_target_specialists(source_topic: str) -> list[str]:
    """Return list of specialists blocked by cross-domain constraints from source_topic.

    E.g., for diving this returns ["skiing", "hiking", "climbing"] — the altitude
    specialists that require a buffer after diving.
    """
    cfg = SPECIALIST_REGISTRY.get(source_topic)
    if not cfg:
        return []
    targets: list[str] = []
    for xd in cfg.cross_domain_blocks:
        targets.extend(xd.target_specialists)
    return targets


def get_cross_domain_buffer_days(source_topic: str) -> int:
    """Return the cross-domain buffer in whole days for source_topic, or 0 if none.

    Reads from the first cross_domain_block entry. For diving this is 24h -> 1 day.
    """
    cfg = SPECIALIST_REGISTRY.get(source_topic)
    if not cfg or not cfg.cross_domain_blocks:
        return 0
    hours = cfg.cross_domain_blocks[0].buffer_hours
    return max(1, -(-hours // 24))  # ceiling division


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
# Fill-day constraint validation (lightweight, no LLM)
# =============================================================================


@dataclass(frozen=True)
class FillDayRejection:
    """Structured rejection when fill-day placement violates a safety constraint."""

    code: str  # e.g. "NOFLY_BUFFER_VIOLATED", "ALTITUDE_AFTER_DIVE"
    reason: str  # Human-readable, shown to user
    suggestion: str | None = None  # Optional alternative


def validate_fill_day_placement(
    target_day: int,
    specialist_type: str,
    day_cards: list,
    total_days: int,
    has_departure_flight: bool = True,
) -> FillDayRejection | None:
    """Lightweight Tier 1 constraint check for fill-day placement.

    Checks:
      1. No-fly buffer — specialist with has_nofly_buffer too close to departure
      2. Cross-domain forward — placing specialist adjacent to its blocked targets
      3. Cross-domain reverse — adjacent specialist lists placement as target

    Surface interval (back-to-back dives) is NOT a rejection — handled by
    itinerary_builder Phase 6.5 tagging.

    Returns None when placement is safe, FillDayRejection when blocked.
    """
    config = SPECIALIST_REGISTRY.get(specialist_type)
    if not config:
        return None

    # ── Check 1: No-fly buffer (departure proximity) ──────────────────
    if config.has_nofly_buffer and has_departure_flight:
        buffer_hrs = get_nofly_buffer_hours(specialist_type) or 24
        buffer_days = buffer_hrs // 24
        departure_day = total_days  # last day is departure
        latest_safe_day = departure_day - 1 - buffer_days
        if target_day > latest_safe_day:
            return FillDayRejection(
                code="NOFLY_BUFFER_VIOLATED",
                reason=(
                    f"{specialist_type.title()} requires a {buffer_hrs}h buffer "
                    f"before your departure day"
                ),
                suggestion=(
                    f"Place {specialist_type} on Day {latest_safe_day} or earlier"
                    if latest_safe_day >= 1
                    else None
                ),
            )

    def _text_or_empty(value: object) -> str:
        return value.strip().lower() if isinstance(value, str) else ""

    def _is_reliably_diving_block(block: object) -> bool:
        """Best-effort guard against mis-labeled generic blocks as `diving`."""
        activity_type = _text_or_empty(getattr(block, "activity_type", None))
        summary = _text_or_empty(getattr(block, "summary", None))
        if not activity_type and not summary:
            # Legacy/mock blocks often only carry specialist_type.
            return True

        text_blob = f"{activity_type} {summary}"
        diving_markers = ("dive", "diving", "scuba", "snorkel", "freedive", "wreck")
        if any(marker in text_blob for marker in diving_markers):
            return True

        constraints = getattr(block, "constraints", None) or []
        for item in constraints:
            if isinstance(item, str):
                if canonicalize_rule(item) in ("surface_interval", "min_24h_buffer_after_dive"):
                    return True
            elif isinstance(item, dict):
                rule = item.get("id") or item.get("rule")
                if isinstance(rule, str) and canonicalize_rule(rule) in (
                    "surface_interval",
                    "min_24h_buffer_after_dive",
                ):
                    return True
        return False

    # ── Collect specialist types on adjacent days ─────────────────────
    adjacent_specialists: set[str] = set()
    for dc in day_cards:
        if abs(dc.day_number - target_day) == 1:
            for block in dc.blocks:
                st = (getattr(block, "specialist_type", None) or "").lower()
                if st:
                    if st == "diving" and not _is_reliably_diving_block(block):
                        continue
                    adjacent_specialists.add(st)

    # ── Check 2: Cross-domain forward ─────────────────────────────────
    # Placing specialist_type whose cross_domain_blocks target an adjacent specialist
    for xd in config.cross_domain_blocks:
        conflicts = adjacent_specialists & set(xd.target_specialists)
        if conflicts:
            return FillDayRejection(
                code=xd.violation_code,
                reason=xd.reason,
                suggestion=f"Avoid placing {specialist_type} adjacent to {', '.join(conflicts)}",
            )

    # ── Check 3: Cross-domain reverse ─────────────────────────────────
    # Adjacent specialist lists specialist_type as one of its blocked targets
    for adj_spec in adjacent_specialists:
        adj_config = SPECIALIST_REGISTRY.get(adj_spec)
        if not adj_config:
            continue
        for xd in adj_config.cross_domain_blocks:
            if specialist_type in xd.target_specialists:
                return FillDayRejection(
                    code=xd.violation_code,
                    reason=xd.reason,
                    suggestion=f"Avoid placing {specialist_type} adjacent to {adj_spec}",
                )

    return None


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


# =============================================================================
# Category intent detection
# =============================================================================

_CATEGORY_INTENT_PATTERNS = (
    re.compile(r"\b(add|include|with|plus|also)\b"),
    re.compile(r"\b(remove|drop|skip|without)\b"),
    re.compile(r"\b(only|instead of|rather than|replace|swap)\b"),
    re.compile(r"\b(more|another|extra)\b"),
)


def has_explicit_category_intent(
    user_text: str,
    router_output: Optional[dict] = None,
) -> bool:
    """Return True when this turn explicitly intends to mutate activity categories."""
    text = (user_text or "").lower().strip()
    if not text:
        return False

    # Check Tier 1 by registry, Tier 2 by common hints + aliases (fast path)
    all_hints = TIER2_COMMON_HINTS | TIER1_SPECIALIST_NAMES | frozenset(TIER2_CATEGORY_ALIASES)
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
