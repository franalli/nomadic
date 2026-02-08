"""
VerticalSpecialist Node - LLM (Expert) domain specialist.

This is the "Diving Agent" / "Hiking Agent" in the UI.
Key insight: Returns BOTH constraints AND content.

Responsibilities:
- Inject domain constraints (e.g., "Don't fly 24h after diving")
- Generate content blocks (e.g., "Day 2: USAT Liberty Wreck")
- Critique current plan from domain expertise perspective
- Suggest enhancements

Flow: Router → Specialist → Architect
The Specialist runs BEFORE the Architect calls tools.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.placeholders import get_activity_image

# Optional LLM-based constraint generation
from app.planner.state import (
    ConstraintSeverity,
    GraphState,
    ItineraryBlock,
    SpecialistConstraint,
    SpecialistOutput,
)

# =============================================================================
# Activity Coordinates Lookup (for LLM-generated activities)
# Format: [longitude, latitude] per GeoJSON/Mapbox convention
# =============================================================================

ACTIVITY_COORDINATES: Dict[str, List[float]] = {
    # === BALI DIVING ===
    "usat liberty": [115.5931, -8.2762],
    "liberty wreck": [115.5931, -8.2762],
    "tulamben": [115.5931, -8.2762],
    "manta point": [115.5271, -8.7935],
    "crystal bay": [115.4486, -8.7179],
    "padang bai": [115.5088, -8.5331],
    "blue lagoon": [115.5088, -8.5331],
    "amed": [115.6461, -8.3474],
    "jemeluk": [115.6461, -8.3474],
    # === BALI HIKING ===
    "mount batur": [115.3756, -8.2417],
    "batur": [115.3756, -8.2417],
    "campuhan ridge": [115.2580, -8.4952],
    "tegallalang": [115.2791, -8.4343],
    "rice terrace": [115.2791, -8.4343],
    "sekumpul": [115.1847, -8.1768],
    "gitgit": [115.0867, -8.6213],
    "munduk": [115.0867, -8.6213],
    "tirta gangga": [115.5147, -8.4116],
    "mount agung": [115.5079, -8.3427],
    # === DUBAI DIVING ===
    "zainab": [55.3075, 25.1177],
    "anchor barge": [55.1850, 25.2048],
    "mv dara": [55.6000, 25.5700],
    # === CHAMONIX SKIING ===
    "grands montets": [6.9608, 45.9763],
    "vallee blanche": [6.8694, 45.8762],
    "les houches": [6.7983, 45.8908],
    "brevent": [6.8398, 45.9330],
    "flegere": [6.8850, 45.9590],
    # === NISEKO SKIING ===
    "grand hirafu": [140.6892, 42.8636],
    "hirafu": [140.6892, 42.8636],
    "niseko village": [140.6789, 42.8467],
    "annupuri": [140.6458, 42.8556],
    "hanazono": [140.7128, 42.8847],
    # === PATAGONIA HIKING ===
    "torres del paine": [-72.9667, -50.9423],
    "grey glacier": [-73.0486, -50.4967],
    "perito moreno": [-73.0486, -50.4967],
    "fitz roy": [-72.8867, -49.3314],
}


def _lookup_coordinates(title: str) -> Optional[List[float]]:
    """Lookup coordinates by activity title (case-insensitive partial match)."""
    title_lower = title.lower()
    for key, coords in ACTIVITY_COORDINATES.items():
        if key in title_lower:
            return coords
    return None


# =============================================================================
# LLM Specialist System Prompts (Zero-Template Architecture)
# =============================================================================

SPECIALIST_SYSTEM_PROMPTS: Dict[str, str] = {
    "diving": """You are a PADI-certified dive master planning safe dive trips.

ROLE: Generate feasibility assessment, real dive sites, and safety constraints.

CRITICAL SAFETY RULES (BLOCKING - cannot be violated):
1. NO-FLY TIME: 24h minimum after diving before flying
2. NO ALTITUDE: No activities above 2500m within 24h of diving
3. CERTIFICATION: Open Water = 18m max depth, Advanced = 30m max depth
4. SURFACE INTERVALS: Minimum 18h between multi-day diving

CROSS-DOMAIN CONSTRAINTS:
- Diving affects skiing: No high-altitude skiing (>2500m) within 24h after diving
- Same decompression physics as no-fly rule — altitude reduces ambient pressure
- This is a BLOCKING constraint

ACTIVITY GENERATION:
- Generate 2-4 REAL dive sites based on trip duration
- Include depth_meters and certification_required for each dive
- Add logic_hook (practical tip) for each activity
- Consider seasonality and water conditions""",
    "hiking": """You are a certified mountain guide planning hiking expeditions.

ROLE: Generate feasibility assessment, real trails, and safety constraints.

CRITICAL SAFETY RULES:
1. ALTITUDE ACCLIMATIZATION: Max 500m elevation gain per day above 3000m (STRONG)
2. WEATHER WINDOWS: Morning starts recommended for mountain hikes
3. CROSS-DOMAIN: High-altitude hiking (>2500m) requires 24h buffer AFTER diving \
(altitude before dive is safe)

CONSTRAINT SEVERITY LABELS (CRITICAL - always include in output):
- BLOCKING: Trail closed, impassable conditions, permit required but unavailable
- STRONG: Altitude >3000m requires acclimatization day, daily elevation gain >1000m
- SOFT: Prefer morning starts, suggested rest day after 2 consecutive hard days

SEASONALITY (REGIONAL AWARENESS):
- High alpine (Alps, Himalaya): June-September for summer hiking
- Southern Hemisphere (NZ, Patagonia): November-March
- Monsoon regions (Nepal, India): Avoid June-September
- If trip dates fall OUTSIDE hiking season: set feasibility_status="caveat" or "infeasible"
- Exception: Lower-elevation trails may be accessible year-round

ACTIVITY GENERATION:
- Generate 2-4 REAL hiking trails based on trip duration
- Include elevation_meters and distance_km for each hike
- Add difficulty progression (easier trails first)
- Consider fitness requirements and acclimatization needs

OUTPUT FIELD HINTS:
- Always include duration_hours (estimated completion at moderate pace)
- Always include trail_type: "day_hike" | "multi_day" | "summit" | "ridge_walk"
- Severity labels MUST appear in constraints_applied[].type field""",
    "skiing": """You are a certified ski instructor planning ski trips.

ROLE: Generate feasibility assessment, real ski areas, and safety constraints.

CRITICAL SAFETY RULES:
1. AVALANCHE CHECK: Required for off-piste/backcountry (BLOCKING)
2. GUIDE REQUIRED: Certified guide mandatory for off-piste terrain (BLOCKING)
3. SKILL PROGRESSION: Match terrain to skill level

SEASONALITY:
- Northern Hemisphere: December-April
- Southern Hemisphere: June-September
- Indoor facilities: Year-round

CROSS-DOMAIN CONSTRAINTS:
- If trip includes diving: High-altitude skiing (>2500m) requires 24h buffer AFTER diving
- Ski resorts often sit at 2000-3500m elevation — flag altitude conflict for diving combos
- Plan diving activities BEFORE high-altitude skiing days, not after
- This is a BLOCKING constraint (same physiological basis as no-fly rule)

ACTIVITY GENERATION:
- Generate 2-4 REAL ski runs/areas based on trip duration
- Include vertical_meters and run_difficulty for each
- Flag off-piste activities with guide requirement
- Consider snow conditions and resort quality""",
    "surfing": """You are a certified surf coach planning surf trips.

ROLE: Generate feasibility assessment, real surf breaks, and safety constraints.

CRITICAL SAFETY RULES (BLOCKING - cannot be violated):
1. HAZARDOUS CONDITIONS: Do not surf when wave height exceeds skill level thresholds
   - Beginner: max 3ft, Intermediate: max 6ft, Advanced: max 10ft

STRONG RECOMMENDATIONS:
1. TIDE/SWELL CHECK: Required before each session
2. RIP CURRENT AWARENESS: Briefing required for unfamiliar breaks
3. REEF AWARENESS: Booties required for reef breaks
4. BOARD SIZE: Match to skill level

CONSTRAINT SEVERITY LABELS (CRITICAL - always include in output):
- BLOCKING: Hazardous conditions exceeding skill level
- STRONG: Tide check, rip current briefing, reef gear
- SOFT: Board size preferences, optimal session timing

ACTIVITY GENERATION:
- Generate 2-4 REAL surf breaks based on trip duration
- Include wave_height range and best tide conditions
- Add skill level requirements
- Consider seasonal swell patterns""",
    "cycling": """You are a cycling guide planning cycling trips.

ROLE: Generate feasibility assessment, real routes, and safety constraints.

STRONG RECOMMENDATIONS (not blocking - user can override):
1. TRAFFIC SAFETY: Helmet required, high-visibility gear recommended
2. HYDRATION: Water stops every 20-30km in hot climates (500ml/hour)
3. BIKE FIT: Proper sizing essential for multi-day rides

SOFT PREFERENCES:
1. TIMING: Morning starts in hot climates to avoid midday heat
2. REST DAYS: Suggested after 3+ consecutive riding days

CONSTRAINT SEVERITY LABELS (CRITICAL - always include in output):
- BLOCKING: None typical for cycling (no life-threatening constraints like diving)
- STRONG: Helmet, hydration, bike fit
- SOFT: Timing preferences, rest day suggestions

ACTIVITY GENERATION:
- Generate 2-4 REAL cycling routes based on trip duration
- Include distance_km and elevation_meters for each ride
- Add surface type (road, gravel, MTB)
- Consider traffic levels and road quality""",
}


# =============================================================================
# LLM Specialist Output Schema (for structured output)
# =============================================================================


class LLMActivity(BaseModel):
    """Activity generated by LLM specialist."""

    title: str
    description: str = ""
    location: Optional[str] = None
    duration_hours: float = 3.0
    difficulty: str = "beginner"  # beginner, intermediate, advanced
    # Topic-specific
    depth_meters: Optional[int] = None
    elevation_meters: Optional[int] = None
    distance_km: Optional[float] = None
    certification_required: Optional[str] = None
    vertical_meters: Optional[int] = None
    logic_hook: Optional[str] = None


class LLMConstraint(BaseModel):
    """Constraint generated by LLM specialist."""

    constraint_id: str  # e.g., "no_fly_24h"
    constraint_type: str = "blocking"  # blocking, strong, soft
    applies_to_categories: List[str] = []
    buffer_hours: Optional[int] = None
    reason: str = ""
    label: Optional[str] = None
    icon: Optional[str] = None


class LLMSpecialistOutput(BaseModel):
    """Complete output from LLM specialist call."""

    feasibility_status: str = "feasible"  # feasible, infeasible, conditional
    feasibility_reason: Optional[str] = None
    activities: List[LLMActivity] = []
    constraints: List[LLMConstraint] = []


# =============================================================================
# LLM Specialist Generation
# =============================================================================


async def generate_all_specialists_parallel(
    topics: List[str],
    destination: str,
    trip_plan: Any,
    db: Optional[Any] = None,  # AsyncSession for persistent caching
    skill_level: Optional[str] = None,  # User skill from activity_settings
) -> Dict[str, Optional[LLMSpecialistOutput]]:
    """
    Run all specialist LLM calls in parallel.

    Performance optimization: 8-12s sequential → 4-6s parallel.
    Returns dict mapping topic -> LLMSpecialistOutput (or None on failure).

    Args:
        db: Optional AsyncSession for L1+L2 persistent caching.
            If provided, results are cached to PostgreSQL (7-day TTL).

    Note: Cache operations are done BEFORE and AFTER parallel execution to avoid
    SQLAlchemy concurrent session errors. The db session is NOT passed to parallel
    tasks - instead we do batch lookup/write with the session sequentially.
    """
    import asyncio

    from app.debug_utils import _debug_log

    if not topics:
        return {}

    _debug_log(f"[LLM_SPECIALIST] Starting PARALLEL generation for {topics}")

    output: Dict[str, Optional[LLMSpecialistOutput]] = {}
    topics_needing_llm: List[str] = []

    # =========================================================================
    # STEP 1: Batch cache lookup (sequential, single session)
    # =========================================================================
    _debug_log(
        f"[LLM_SPECIALIST] Parallel lookup: topics={topics} "
        f"dest={destination} dates={trip_plan.start_date}→{trip_plan.end_date}"
    )
    if db is not None:
        from app.services.specialist_cache import get_cached_specialist_output

        for topic in topics:
            try:
                cached = await get_cached_specialist_output(
                    db=db,
                    topic=topic,
                    destination=destination,
                    start_date=trip_plan.start_date,
                    end_date=trip_plan.end_date,
                )
                if cached is not None:
                    try:
                        output[topic] = LLMSpecialistOutput.model_validate(cached)
                        status = output[topic].feasibility_status
                        _debug_log(f"[LLM_SPECIALIST] CACHE HIT: {topic} ({status})")
                        continue
                    except Exception as e:
                        _debug_log(f"[LLM_SPECIALIST] Cache deserialize failed for {topic}: {e}")
            except Exception as e:
                _debug_log(f"[LLM_SPECIALIST] Cache lookup failed for {topic}: {e}")

            topics_needing_llm.append(topic)
    else:
        topics_needing_llm = list(topics)

    # =========================================================================
    # STEP 2: Parallel LLM calls (no db passed - avoid concurrent session)
    # =========================================================================
    if topics_needing_llm:
        _debug_log(f"[LLM_SPECIALIST] Cache MISS for {topics_needing_llm}, calling LLM")

        # Create tasks WITHOUT db (cache write happens after)
        tasks = [
            generate_specialist_output_llm(
                topic, destination, trip_plan, db=None, skill_level=skill_level
            )
            for topic in topics_needing_llm
        ]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            _debug_log("[LLM_SPECIALIST] PARALLEL timeout - cancelling remaining tasks")
            # Cancel all tasks that are still running to prevent orphaned coroutines
            for task in tasks:
                if isinstance(task, asyncio.Task) and not task.done():
                    task.cancel()
            # Wait briefly for cancellation to complete
            pending = [t for t in tasks if isinstance(t, asyncio.Task)]
            await asyncio.gather(*pending, return_exceptions=True)
            for topic in topics_needing_llm:
                output[topic] = None
            return output

        # Map results and collect for batch cache write
        llm_results: Dict[str, LLMSpecialistOutput] = {}
        for topic, result in zip(topics_needing_llm, results, strict=False):
            if isinstance(result, Exception):
                _debug_log(f"[LLM_SPECIALIST] {topic} failed in parallel: {result}")
                output[topic] = None
            else:
                output[topic] = result
                if result is not None:
                    llm_results[topic] = result

        # =====================================================================
        # STEP 3: Batch cache write (sequential, single session)
        # =====================================================================
        if db is not None and llm_results:
            from app.services.specialist_cache import set_cached_specialist_output

            for topic, llm_output in llm_results.items():
                try:
                    await set_cached_specialist_output(
                        db=db,
                        topic=topic,
                        destination=destination,
                        start_date=trip_plan.start_date,
                        end_date=trip_plan.end_date,
                        output=llm_output.model_dump(),
                    )
                except Exception as e:
                    _debug_log(f"[LLM_SPECIALIST] Cache write failed for {topic}: {e}")

    success_count = sum(1 for r in output.values() if r is not None)
    _debug_log(f"[LLM_SPECIALIST] PARALLEL complete: {success_count}/{len(topics)} succeeded")

    return output


async def generate_specialist_output_llm(
    topic: str,
    destination: str,
    trip_plan: Any,
    db: Optional[Any] = None,  # AsyncSession for persistent caching
    skill_level: Optional[str] = None,  # User skill from activity_settings
) -> Optional[LLMSpecialistOutput]:
    """
    Single LLM call generates feasibility + activities + constraints.

    Uses topic-aware system prompt from SPECIALIST_SYSTEM_PROMPTS.
    Returns None on failure (caller should use hardcoded fallback).

    Args:
        db: Optional AsyncSession for L1+L2 persistent caching.
            If provided, checks cache before LLM call and writes after success.
    """
    from app.debug_utils import _debug_log

    # =========================================================================
    # CACHE CHECK: L1 (memory) → L2 (PostgreSQL)
    # =========================================================================
    if db is not None:
        try:
            from app.services.specialist_cache import get_cached_specialist_output

            cached = await get_cached_specialist_output(
                db=db,
                topic=topic,
                destination=destination,
                start_date=trip_plan.start_date,
                end_date=trip_plan.end_date,
            )

            if cached is not None:
                try:
                    output = LLMSpecialistOutput.model_validate(cached)
                    _debug_log(
                        f"[LLM_SPECIALIST] CACHE HIT: {topic} in {destination} "
                        f"(status={output.feasibility_status})"
                    )
                    return output
                except Exception as e:
                    _debug_log(f"[LLM_SPECIALIST] Cache deserialize failed: {e}")
        except Exception as e:
            _debug_log(f"[LLM_SPECIALIST] Cache lookup error: {e}")

    system_prompt = load_specialist_prompt(topic) or SPECIALIST_SYSTEM_PROMPTS.get(topic)
    if not system_prompt:
        # Unknown specialist - return None to trigger fallback
        _debug_log(f"[LLM_SPECIALIST] No system prompt for topic '{topic}', using fallback")
        return None

    # Inject user skill level so LLM generates appropriate activities
    if skill_level:
        system_prompt += (
            f"\n\nUSER SKILL LEVEL: {skill_level}. "
            "Generate activities appropriate for this level. "
            "Do NOT suggest activities above this skill level."
        )

    # Calculate trip duration
    duration_days = 5  # Default
    if trip_plan.start_date and trip_plan.end_date:
        from datetime import datetime

        try:
            start = datetime.strptime(str(trip_plan.start_date), "%Y-%m-%d")
            end = datetime.strptime(str(trip_plan.end_date), "%Y-%m-%d")
            duration_days = (end - start).days + 1
        except ValueError:
            pass

    # NOTE: JSON schema is NOT included here - it's handled by .with_structured_output()
    # OpenAI's function calling API receives the Pydantic schema directly.
    # Including redundant JSON instructions wastes ~200-500 tokens per call.
    user_prompt = f"""Plan {topic} activities for {destination}.

TRIP DETAILS:
- Dates: {trip_plan.start_date} to {trip_plan.end_date} ({duration_days} days)
- Travelers: {trip_plan.adults} adults, {trip_plan.children} children
- Activity days available: {max(1, duration_days - 2)} (excluding arrival/departure)

REQUIREMENTS:
- Use REAL sites/trails/runs - no made-up names
- Generate 2-4 activities based on available days
- Include topic-specific fields (depth_meters for diving, elevation_meters for hiking, etc.)
- Include cross-domain constraints explicitly (e.g., diving affects hiking)
- For infeasible destinations (e.g., diving in landlocked areas), \
set feasibility_status to "infeasible" with reason"""

    import time

    llm_start = time.time()
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=os.getenv("SPECIALIST_MODEL", "gpt-4o"), temperature=0.2)
        structured_llm = llm.with_structured_output(LLMSpecialistOutput)

        _debug_log(f"[LLM_SPECIALIST] Calling LLM for {topic} in {destination}")

        from langchain_core.messages import HumanMessage, SystemMessage

        output = await structured_llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

        elapsed = time.time() - llm_start
        _debug_log(
            f"[LLM_SPECIALIST] ✅ Success for {topic} in {elapsed:.1f}s: "
            f"status={output.feasibility_status}, "
            f"activities={len(output.activities)}, constraints={len(output.constraints)}"
        )

        # =====================================================================
        # CACHE WRITE: Store successful LLM output to L1 + L2
        # =====================================================================
        if db is not None:
            try:
                from app.services.specialist_cache import set_cached_specialist_output

                await set_cached_specialist_output(
                    db=db,
                    topic=topic,
                    destination=destination,
                    start_date=trip_plan.start_date,
                    end_date=trip_plan.end_date,
                    output=output.model_dump(),
                )
            except Exception as cache_err:
                _debug_log(f"[LLM_SPECIALIST] Cache write failed (non-fatal): {cache_err}")

        return output

    except Exception as e:
        elapsed = time.time() - llm_start
        # Log exception type to diagnose: OutputParserException = schema mismatch,
        # TimeoutError = LLM slow, ValidationError = Pydantic rejected field
        _debug_log(
            f"[LLM_SPECIALIST] ❌ FAILED for {topic} after {elapsed:.1f}s | "
            f"type={type(e).__name__} | msg={str(e)[:300]}"
        )
        return None


def _get_minimal_safety_constraints(
    topic: str, destination: Optional[str] = None
) -> List[SpecialistConstraint]:
    """
    Get minimal hardcoded safety constraints as fallback.

    Used when LLM generation fails to ensure critical safety rules are present.

    Args:
        topic: The specialist topic (diving, hiking, skiing)
        destination: Optional destination for gating altitude constraints
    """
    if topic == "diving":
        return [
            SpecialistConstraint(
                constraint_id="no_fly_24h",
                type="temporal",
                rule="min_24h_buffer_after_dive",
                severity=ConstraintSeverity.BLOCKING,
                applies_to_categories=["flights"],
                buffer_hours=24,
                reason="Flying within 24h of diving risks decompression sickness",
                label="24h No-Fly Buffer",
                icon="🚫",
            ),
        ]
    elif topic == "hiking":
        # Base constraints that apply to ALL hiking destinations
        # Valid types: 'temporal', 'safety', 'equipment', 'certification', 'budget'
        base_constraints = [
            SpecialistConstraint(
                constraint_id="morning_start_recommended",
                type="temporal",
                rule="morning_start_recommended",
                severity=ConstraintSeverity.SOFT,
                applies_to_categories=["activities"],
                reason="Morning starts recommended for mountain hikes to avoid afternoon weather",
                label="Morning Start",
                icon="🌅",
            ),
            SpecialistConstraint(
                constraint_id="proper_footwear_required",
                type="equipment",
                rule="proper_footwear_required",
                severity=ConstraintSeverity.SOFT,
                applies_to_categories=["activities"],
                reason="Proper footwear required for steep terrain",
                label="Proper Footwear",
                icon="🥾",
            ),
        ]

        base_constraints.append(
            SpecialistConstraint(
                constraint_id="altitude_acclimatization",
                type="safety",
                rule="altitude_acclimatization",
                severity=ConstraintSeverity.STRONG,
                applies_to_categories=["activities"],
                reason="Max 500m elevation gain per day above 3000m",
                label="Altitude Acclimatization",
                icon="🏔️",
            )
        )

        return base_constraints
    elif topic == "skiing":
        return [
            SpecialistConstraint(
                constraint_id="avalanche_check",
                type="safety",
                rule="check_snow_conditions",
                severity=ConstraintSeverity.BLOCKING,
                applies_to_categories=["activities"],
                reason="Check avalanche bulletin before off-piste skiing",
                label="Avalanche Check Required",
                icon="🏔️",
            ),
        ]
    return []


def _migrate_legacy_constraints(
    constraints: List[SpecialistConstraint],
) -> List[SpecialistConstraint]:
    """
    Add constraint_id to legacy constraints from hardcoded system.

    Ensures backward compatibility when mixing old and new constraint formats.
    """
    for c in constraints:
        if not c.constraint_id:
            c.constraint_id = c.rule  # Use rule as fallback ID
    return constraints


def convert_llm_output_to_specialist_output(
    llm_output: LLMSpecialistOutput,
    topic: str,
    destination: str,
) -> SpecialistOutput:
    """
    Convert LLM output to SpecialistOutput format for the graph.

    Maps LLMActivity -> ItineraryBlock and LLMConstraint -> SpecialistConstraint.
    Images are fetched from Unsplash (activity-aware) with Picsum fallback.
    """
    from app.services.unsplash import get_image_url_sync

    # Convert activities to ItineraryBlocks
    content_blocks: List[ItineraryBlock] = []
    for i, activity in enumerate(llm_output.activities):
        # Use Unsplash service with activity context for location-specific images
        # Variant cycles through prefetched images (0-5)
        image_url = get_image_url_sync(destination, variant=i % 6, activities=[topic])
        # Lookup coordinates by activity title
        coordinates = _lookup_coordinates(activity.title)
        content_blocks.append(
            ItineraryBlock(
                day=i + 2,  # Start from day 2 (day 1 is arrival)
                title=activity.title,
                description=activity.description,
                type="activity",
                source_specialist=topic,
                skill_level=activity.difficulty,
                logic_hook=activity.logic_hook,
                image_url=image_url,
                duration_hours=activity.duration_hours,
                location=activity.location,
                coordinates=coordinates,  # [lng, lat] for Mapbox POI pins
            )
        )

    # Convert constraints to SpecialistConstraints
    constraints: List[SpecialistConstraint] = []
    severity_map = {
        "blocking": ConstraintSeverity.BLOCKING,
        "strong": ConstraintSeverity.STRONG,
        "soft": ConstraintSeverity.SOFT,
    }
    for llm_constraint in llm_output.constraints:
        severity = severity_map.get(
            llm_constraint.constraint_type.lower(), ConstraintSeverity.STRONG
        )
        constraints.append(
            SpecialistConstraint(
                constraint_id=llm_constraint.constraint_id,
                type="safety",  # Default type
                rule=llm_constraint.constraint_id,
                severity=severity,
                applies_to_categories=llm_constraint.applies_to_categories,
                buffer_hours=llm_constraint.buffer_hours,
                reason=llm_constraint.reason,
                label=llm_constraint.label,
                icon=llm_constraint.icon,
            )
        )

    return SpecialistOutput(
        feasibility_status=llm_output.feasibility_status,
        feasibility_reason=llm_output.feasibility_reason,
        constraints=constraints,
        content_blocks=content_blocks,
    )


# =============================================================================
# Feasibility Data (Geographic/Physical Constraints)
# Used for fast pre-checks before LLM calls
# =============================================================================

SKIING_FEASIBILITY = {
    # Infeasible - no natural or indoor skiing possible
    "infeasible": [
        "miami",
        "florida",
        "hawaii",
        "caribbean",
        "bahamas",
        "cancun",
        "bali",
        "thailand",
        "singapore",
        "philippines",
        "vietnam",
        "indonesia",
        "malaysia",
        "cambodia",
        "laos",
        "myanmar",
        "india",
        "sri lanka",
        "maldives",
        "seychelles",
        "mauritius",
        "kenya",
        "tanzania",
        "south africa",
        "egypt",
        "morocco",
        "brazil",
        "argentina",
        "mexico",
        "costa rica",
        "panama",
        "cuba",
        "jamaica",
        "dominican republic",
        "puerto rico",
    ],
    # Caveat - indoor only
    "caveat": {
        "amsterdam": "Indoor skiing at SnowWorld Zoetermeer (30min drive)",
        "netherlands": "Indoor skiing at SnowWorld (Zoetermeer or Landgraaf)",
        "london": "Indoor skiing at The Snow Centre Hemel Hempstead (45min)",
        "uk": "Indoor skiing at The Snow Centre or Chill Factore Manchester",
        "dubai": "Indoor skiing at Ski Dubai (Mall of the Emirates)",
        "uae": "Indoor skiing at Ski Dubai in Dubai",
        "madrid": "Indoor skiing at Madrid SnowZone (Xanadú)",
        "berlin": "Indoor skiing at Alpincenter Bottrop (4h drive)",
        "paris": "No indoor ski facilities nearby - consider Alps (3h by TGV)",
    },
}

DIVING_FEASIBILITY = {
    # Caveat - pool/aquarium only, or limited ocean access
    "caveat": {
        "london": "Pool diving at NDAC or London Aquarium experiences",
        "amsterdam": "Pool diving at Duikvaker centers",
        "paris": "Pool diving at Aqua 92 or Nemo 33 (Belgium, 3h)",
        "berlin": "Pool diving at Dive4Life or aquarium experiences",
        "madrid": "Pool diving available; nearest sea diving in Valencia (3h)",
        "munich": "Pool diving; nearest sea diving in Croatia (5h)",
        "vienna": "Pool diving available; landlocked country",
        "dubai": (
            "Ocean diving is limited. Try **Deep Dive Dubai** - "
            "world's deepest pool (60m), sunken city theme, indoor facility."
        ),
    },
    # Infeasible - landlocked, no facilities
    "infeasible": [
        "switzerland",
        "austria",
        "czech",
        "czechia",
        "hungary",
        "luxembourg",
        "liechtenstein",
        "andorra",
        "san marino",
        "mongolia",
        "nepal",
        "bhutan",
        "laos",
        "paraguay",
        "bolivia",
        "rwanda",
        "burundi",
        "uganda",
        "zambia",
        "zimbabwe",
        "botswana",
        "malawi",
        "lesotho",
        "eswatini",
        "ethiopia",
        "chad",
        "niger",
        "mali",
        "burkina faso",
        "central african republic",
        "south sudan",
        "kazakhstan",
        "uzbekistan",
        "turkmenistan",
        "kyrgyzstan",
        "tajikistan",
        "afghanistan",
        "armenia",
        "azerbaijan",
        "belarus",
        "slovakia",
    ],
}

HIKING_FEASIBILITY = {
    # Hiking is generally feasible almost everywhere, but with caveats
    "infeasible": [],  # Very few places where hiking is truly impossible
    "caveat": {
        "maldives": "Flat terrain only - no mountain hiking available",
        "bahamas": "Flat terrain - limited to coastal/nature walks",
        "singapore": "Urban hiking only - MacRitchie Reservoir, Bukit Timah",
        "hong kong": "Urban hiking - Dragon's Back, Lion Rock trails",
        "dubai": "Desert hiking only - no mountain trails nearby",
    },
}

# Map topic to feasibility data
FEASIBILITY_DATA = {
    "skiing": SKIING_FEASIBILITY,
    "diving": DIVING_FEASIBILITY,
    "hiking": HIKING_FEASIBILITY,
}


# =============================================================================
# LLM Feasibility Check (for unknown destinations)
# =============================================================================


class FeasibilityCheck(BaseModel):
    """LLM response for feasibility check."""

    possible: bool
    reason: str


def _check_feasibility_llm(topic: str, destination: str) -> FeasibilityCheck:
    """
    LLM determines if activity is geographically possible.

    Uses GPT-4o-mini for fast, cheap checks (~$0.0001, ~200ms).
    Falls open on error (assumes possible) to avoid false negatives.
    """
    from app.debug_utils import _debug_log

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=os.getenv("ROUTER_MODEL", "gpt-4o-mini"),  # Quick feasibility check
            temperature=0,
            max_tokens=100,
        )

        prompt = f"""Is {topic} activity possible in {destination}?

Rules:
- Diving requires coastline, large lakes, or dedicated dive facilities
- Skiing requires mountains with reliable snow or indoor ski facilities
- Hiking requires terrain suitable for walking trails
- Surfing requires ocean waves

Be strict. Landlocked cities cannot have diving. Alpine towns without coast cannot have diving.

Respond JSON only: {{"possible": true/false, "reason": "brief"}}"""

        response = llm.invoke(prompt)
        content = response.content.strip()

        # Parse JSON response
        # Handle potential markdown code blocks
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = FeasibilityCheck(**json.loads(content))
        _debug_log(
            f"[FEASIBILITY_LLM] {topic} in {destination}: "
            f"possible={result.possible}, reason={result.reason}"
        )
        return result

    except Exception as e:
        _debug_log(f"[FEASIBILITY_LLM] Error checking {topic} in {destination}: {e}")
        # Fail open - assume possible if LLM fails
        return FeasibilityCheck(possible=True, reason="Unknown, proceeding")


@lru_cache(maxsize=1000)
def get_feasibility_llm(topic: str, destination: str) -> Tuple[bool, str]:
    """
    Cached LLM feasibility check.

    Cache key: f"{topic}:{destination}" (implicit via lru_cache)
    Returns: (possible, reason)
    """
    result = _check_feasibility_llm(topic, destination)
    return (result.possible, result.reason)


def check_feasibility(
    topic: str,
    destination: str,
) -> tuple:
    """
    Check if activity is feasible at destination.

    Uses a two-tier approach:
    1. Fast hardcoded checks for known destinations
    2. LLM fallback for unknown destinations (cached)

    Returns:
        (status, reason, alternative_suggestion) tuple where:
        - status: "feasible" | "caveat" | "infeasible"
        - reason: Human-readable explanation (or None)
        - alternative_suggestion: Suggested alternative (or None)
    """
    from app.debug_utils import _debug_log

    dest_lower = (destination or "").lower()

    # Skip empty destinations
    if not dest_lower:
        return ("feasible", None, None)

    data = FEASIBILITY_DATA.get(topic)
    if not data:
        return ("feasible", None, None)

    # TIER 1: Check hardcoded infeasible locations (fast)
    for location in data.get("infeasible", []):
        if location in dest_lower:
            return (
                "infeasible",
                f"{topic.title()} is not available in {destination}",
                _suggest_alternative(topic),
            )

    # TIER 1: Check hardcoded caveat locations (fast)
    for location, caveat_msg in data.get("caveat", {}).items():
        if location in dest_lower:
            return (
                "caveat",
                caveat_msg,
                None,
            )

    # TIER 1: Check hardcoded feasible locations for skiing
    # (Skip LLM for known ski destinations)
    if topic == "skiing" and "feasible" in data:
        for location in data.get("feasible", []):
            if location in dest_lower:
                return ("feasible", None, None)

    # TIER 2: LLM check for unknown destinations
    # Only run for activities with geographic constraints (diving, skiing)
    # Hiking is generally possible everywhere, so skip LLM for it
    if topic in ["diving", "skiing"]:
        _debug_log(f"[FEASIBILITY] LLM check for {topic} in {destination}")
        possible, reason = get_feasibility_llm(topic, destination)

        if not possible:
            return (
                "infeasible",
                f"{topic.title()} is not available in {destination}. {reason}",
                _suggest_alternative(topic),
            )

        # If LLM says possible but with nuance, treat as caveat
        # (e.g., "possible but limited" scenarios)
        if possible and "limited" in reason.lower():
            return ("caveat", reason, None)

    return ("feasible", None, None)


def _suggest_alternative(topic: str) -> str:
    """Get alternative destination suggestion for infeasible activities."""
    alternatives = {
        "skiing": "Consider destinations like Chamonix, Zermatt, Niseko, or Aspen",
        "diving": "Consider destinations like Bali, Red Sea, Maldives, or Great Barrier Reef",
        "hiking": "Consider destinations like Patagonia, Nepal, the Alps, or Yosemite",
    }
    return alternatives.get(topic, "Consider a destination better suited for this activity")


# =============================================================================
# VerticalSpecialist Class
# =============================================================================


class VerticalSpecialist:
    """
    Domain specialist that injects constraints AND content.

    NEW ARCHITECTURE (Zero-Template LLM):
    - Primary: LLM generates activities + constraints via generate_specialist_output_llm()
    - Fallback: _get_minimal_safety_constraints() provides critical safety rules

    Key insight: Returns BOTH safety constraints AND itinerary suggestions.
    Runs BEFORE Architect calls tools (Constraint Injector pattern).
    """

    def __init__(self, topic: str):
        self.topic = topic
        self.debug = bool(os.getenv("DEBUG_PLAN_MESSAGES"))

    def get_constraints(self) -> List[SpecialistConstraint]:
        """Get domain-specific constraints (fallback only).

        In the new LLM architecture, constraints come from generate_specialist_output_llm().
        This method is only used as fallback when LLM fails.
        """
        return _get_minimal_safety_constraints(self.topic)

    def _calculate_activity_days(self, state: GraphState) -> int:
        """
        Calculate how many days are available for activities.

        For a trip:
        - Day 1 = Arrival (no activities)
        - Day N = Departure (no activities)
        - Diving: Day N-1 = No-fly buffer (no diving)
        - Hiking at high altitude: Day 3 = Acclimatization (no strenuous activity)

        Returns the number of days available for specialist activities.
        For very short trips (1-2 days), returns 0 (no activity days).
        """
        plan = state.trip_plan

        from app.debug_utils import _debug_info

        _debug_info("SPECIALIST", "_calculate_activity_days called")
        _debug_info("SPECIALIST", f"  topic={self.topic}")
        _debug_info("SPECIALIST", f"  start_date={plan.start_date}")
        _debug_info("SPECIALIST", f"  end_date={plan.end_date}")

        if not plan.start_date or not plan.end_date:
            _debug_info("SPECIALIST", "  -> No dates, returning 3 (default)")
            return 3  # Default to 3 activity days if dates unknown

        from datetime import datetime

        try:
            start = datetime.strptime(plan.start_date, "%Y-%m-%d")
            end = datetime.strptime(plan.end_date, "%Y-%m-%d")
            total_days = (end - start).days + 1
            _debug_info("SPECIALIST", f"  total_days={total_days}")
        except ValueError as e:
            _debug_info("SPECIALIST", f"  -> Date parse error: {e}, returning 3")
            return 3  # Default if date parsing fails

        # Subtract arrival (day 1) and departure (last day)
        available = total_days - 2
        _debug_info("SPECIALIST", f"  after arrival/departure: available={available}")

        # Specialist-specific buffers
        if self.topic == "diving":
            # No-fly buffer day before departure
            available -= 1
            _debug_info("SPECIALIST", f"  after diving no-fly buffer: available={available}")
        elif self.topic == "hiking":
            # Acclimatization day for high-altitude destinations
            high_altitude_dests = [
                "nepal",
                "everest",
                "kilimanjaro",
                "peru",
                "cusco",
                "tibet",
                "ladakh",
                "bolivia",
                "la paz",
            ]
            dest_lower = (plan.destination or "").lower()
            if any(h in dest_lower for h in high_altitude_dests):
                available -= 1
                _debug_info("SPECIALIST", f"  after hiking altitude buffer: available={available}")

        result = max(0, available)
        _debug_info("SPECIALIST", f"  -> FINAL: max_activities={result}")
        return result

    def get_content_for_destination(
        self, destination: str, state: Optional[GraphState] = None
    ) -> List[ItineraryBlock]:
        """
        Get suggested activities for a destination.

        This is the S1/S2 content generation.
        Respects trip duration - only generates activities that fit.

        Priority:
        1. Curated content from demo_curation.py (has images for hero destinations)
        2. Hardcoded knowledge (fallback for non-hero destinations)
        """
        from app.debug_utils import _debug_info, _debug_log

        # Guard: return empty if no destination (prevents false matches)
        if not destination:
            _debug_log("[SPECIALIST] get_content_for_destination: No destination, returning empty")
            return []

        # Normalize destination name for lookup
        dest_lower = destination.lower().strip()

        # Extra safety: return empty if destination is effectively empty
        if not dest_lower:
            _debug_log(
                "[SPECIALIST] get_content_for_destination: Empty dest_lower, returning empty"
            )
            return []

        # Calculate available activity days from trip dates
        max_activities = self._calculate_activity_days(state) if state else 3
        _debug_info("SPECIALIST", f"get_content_for_destination: max_activities={max_activities}")

        # For very short trips (no activity days), return empty
        if max_activities <= 0:
            message = "get_content_for_destination: TRIP TOO SHORT - returning empty"
            _debug_info("SPECIALIST", message)
            return []

        # Check for curated content (includes images) - used for demo destinations
        # NOTE: In the new LLM architecture, activities primarily come from LLM.
        # This method is called as fallback only when LLM fails.
        _debug_log(
            f"[SPECIALIST] get_content_for_destination: "
            f"Looking up curated content for '{dest_lower}'"
        )
        curated_blocks = self._get_curated_content(dest_lower, max_activities)
        if curated_blocks:
            _debug_info(
                "SPECIALIST",
                f"Returning {len(curated_blocks)} curated blocks (max was {max_activities})",
            )
            return curated_blocks

        # No curated content found - return empty (LLM is primary source now)
        _debug_log(
            f"[SPECIALIST] get_content_for_destination: "
            f"No curated content for '{dest_lower}', returning empty (LLM is primary source)"
        )
        return []

    def _get_curated_content(
        self, destination: str, max_activities: int = 3
    ) -> List[ItineraryBlock]:
        """
        Get curated content from demo_curation.py if available.

        Returns ItineraryBlocks with images for hero destinations.
        Limited to max_activities based on trip duration.
        """
        from app.debug_utils import _debug_log

        try:
            from app.data.demo_curation import DEMO_MANIFEST, is_hero_destination

            _debug_log(
                f"[SPECIALIST] _get_curated_content: "
                f"destination='{destination}', topic='{self.topic}', max={max_activities}"
            )

            is_hero = is_hero_destination(destination)
            _debug_log(f"[SPECIALIST] is_hero_destination('{destination}') = {is_hero}")

            if not is_hero:
                _debug_log("[SPECIALIST] NOT a hero destination, returning empty")
                return []

            _debug_log("[SPECIALIST] IS a hero destination, fetching curated content")
            manifest = DEMO_MANIFEST.get(destination.lower().strip(), {})
            specialist_content = manifest.get("specialist_content", {})
            _debug_log(f"[SPECIALIST] specialist_content keys: {list(specialist_content.keys())}")

            # Get activities for this specialist type
            activities = specialist_content.get(self.topic, [])
            _debug_log(f"[SPECIALIST] activities for topic '{self.topic}': {len(activities)}")

            if not activities:
                _debug_log("[SPECIALIST] No activities found, returning empty")
                return []

            blocks = []
            # Limit to max_activities based on trip duration
            for i, activity in enumerate(activities[:max_activities]):
                _debug_log(
                    f"[SPECIALIST] Creating block: {activity.get('title')}, "
                    f"image={bool(activity.get('image'))}, coords={activity.get('coordinates')}"
                )
                # Default skill_level by specialist type if not in curated data
                default_skill = {
                    "diving": "intermediate",
                    "hiking": "intermediate",
                    "skiing": "advanced",
                    "cycling": "intermediate",
                    "surfing": "intermediate",
                }.get(self.topic, "intermediate")

                blocks.append(
                    ItineraryBlock(
                        day=i + 2,  # Start from day 2 (day 1 is arrival)
                        title=activity.get("title", ""),
                        description=activity.get("description", ""),
                        type=activity.get("type", "activity"),
                        source_specialist=self.topic,
                        skill_level=activity.get("skill_level", default_skill),
                        logic_hook=activity.get("logic_hook"),
                        image_url=activity.get("image"),  # Curated image URL
                        coordinates=activity.get("coordinates"),  # [lng, lat] for Mapbox
                    )
                )

            _debug_log(
                f"[SPECIALIST] Returning {len(blocks)} curated blocks (max was {max_activities})"
            )
            return blocks

        except ImportError:
            return []

    def critique_plan(self, state: GraphState) -> Optional[str]:
        """
        Review current plan from domain expertise perspective.

        Returns critique if issues found, None otherwise.
        """
        plan = state.trip_plan

        # Check for constraint violations
        if self.topic == "diving":
            # Check if there's a flight on the last day
            if plan.segments:
                for segment in plan.segments:
                    if segment.type == "flight":
                        # In real implementation, check dates
                        pass

        return None

    def generate_enhancements(self, state: GraphState) -> List[str]:
        """
        Suggest enhancements to the plan.
        """
        enhancements = []
        plan = state.trip_plan

        if self.topic == "diving":
            if not any("dive" in str(b.title).lower() for b in plan.itinerary_blocks):
                enhancements.append("Consider adding a dive site visit")
            enhancements.append("Book a dive shop for equipment rental in advance")

        elif self.topic == "hiking":
            enhancements.append("Check weather forecasts before departure")
            enhancements.append("Download offline maps for the trails")

        elif self.topic == "skiing":
            enhancements.append("Book ski passes in advance for better rates")
            enhancements.append("Consider private lessons for the first day")

        return enhancements

    def generate_bookends(self, state: GraphState) -> List[ItineraryBlock]:
        """
        Generate arrival/departure bookend blocks.

        Day 1: Arrival + Check-in
        Last Day: Check-out + Departure
        """
        plan = state.trip_plan
        blocks = []

        # Calculate trip duration
        if plan.start_date and plan.end_date:
            from datetime import datetime

            try:
                start = datetime.strptime(plan.start_date, "%Y-%m-%d")
                end = datetime.strptime(plan.end_date, "%Y-%m-%d")
                duration = (end - start).days + 1
            except ValueError:
                duration = 5  # Default
        else:
            duration = 5  # Default

        destination = plan.destination or "your destination"

        # Day 1: Arrival
        blocks.append(
            ItineraryBlock(
                day=1,
                title=f"Arrival in {destination}",
                description="Airport transfer and hotel check-in. Rest and acclimatize.",
                type="buffer",
                is_buffer=True,
                buffer_type="arrival",
                buffer_reason="Travel day - airport transfer and check-in",
                source_specialist=self.topic,
            )
        )

        # Last day: Departure
        blocks.append(
            ItineraryBlock(
                day=duration,
                title=f"Departure from {destination}",
                description="Hotel check-out and transfer to airport.",
                type="buffer",
                is_buffer=True,
                buffer_type="departure",
                buffer_reason="Travel day - check-out and departure",
                source_specialist=self.topic,
            )
        )

        return blocks

    def generate_safety_buffers(self, state: GraphState) -> List[ItineraryBlock]:
        """
        Generate safety buffer blocks based on domain constraints.

        - Diving: No-fly interval (24h before departure flight)
        - Hiking: Acclimatization days at high altitude
        """
        plan = state.trip_plan
        blocks = []

        # Calculate trip duration
        if plan.start_date and plan.end_date:
            from datetime import datetime

            try:
                start = datetime.strptime(plan.start_date, "%Y-%m-%d")
                end = datetime.strptime(plan.end_date, "%Y-%m-%d")
                duration = (end - start).days + 1
            except ValueError:
                duration = 5
        else:
            duration = 5

        if self.topic == "diving" and duration >= 3:
            # No-fly buffer is now shown as INLINE CONSTRAINT on the last dive activity
            # (see itinerary_builder._apply_constraints_to_blocks)
            # No standalone buffer block needed - keeps timeline cleaner while
            # still communicating the safety rule via inline badges.
            pass

        elif self.topic == "hiking":
            # For high-altitude destinations, add acclimatization day
            high_altitude_dests = [
                "nepal",
                "everest",
                "kilimanjaro",
                "peru",
                "cusco",
                "tibet",
                "ladakh",
            ]
            dest_lower = (plan.destination or "").lower()

            if any(h in dest_lower for h in high_altitude_dests) and duration >= 4:
                # Add acclimatization on day 3
                blocks.append(
                    ItineraryBlock(
                        day=3,
                        title="Acclimatization Day",
                        description=(
                            "Rest day to adjust to altitude. Light walks only, stay hydrated."
                        ),
                        type="buffer",
                        is_buffer=True,
                        buffer_type="acclimatization",
                        buffer_reason=(
                            "Altitude sickness prevention: "
                            "max 500m elevation gain per day above 3000m"
                        ),
                        source_specialist="hiking",
                        safety_notes=(
                            "Ascending too fast increases risk of AMS (Acute Mountain Sickness)"
                        ),
                    )
                )

        return blocks

    async def generate_output(self, state: GraphState) -> SpecialistOutput:
        """
        Generate the complete specialist output.

        NEW ARCHITECTURE (Zero-Template LLM):
        1. Check for cached parallel LLM results (from generate_all_specialists_parallel)
        2. If not cached, try LLM generation
        3. If LLM fails, fall back to hardcoded knowledge

        Returns BOTH constraints AND content.
        """
        from app.debug_utils import _debug_log

        destination = state.trip_plan.destination or ""

        # DEBUG: Log input state
        _debug_log(
            f"[SPECIALIST] generate_output called: topic={self.topic}, destination='{destination}'"
        )
        _debug_log(
            f"[SPECIALIST] trip_plan: start_date={state.trip_plan.start_date}, "
            f"end_date={state.trip_plan.end_date}"
        )

        # =====================================================================
        # STEP 0a: Early feasibility check - trip too short for this activity?
        # =====================================================================
        activity_days = self._calculate_activity_days(state)
        if activity_days <= 0:
            # Trip is too short for this specialist's activities
            min_days_needed = {
                "diving": 4,  # arrival + dive + no-fly buffer + departure
                "hiking": 3,  # arrival + hike + departure
                "skiing": 3,  # arrival + ski + departure
            }.get(self.topic, 3)

            reason = (
                f"{self.topic.title()} requires at least {min_days_needed} days "
                f"(your trip is too short). "
            )
            if self.topic == "diving":
                reason += "The 24h no-fly safety buffer leaves no time for diving."

            _debug_log(f"[SPECIALIST] INFEASIBLE: Trip too short for {self.topic}")
            return SpecialistOutput(
                feasibility_status="infeasible",
                feasibility_reason=reason,
                alternative_suggestion=(
                    f"Consider extending your trip to {min_days_needed}+ days, "
                    f"or explore other activities."
                ),
                constraints=[],
                content_blocks=[],
                critique=None,
                enhancements=[],
            )

        # =====================================================================
        # STEP 0b: Check for cached parallel LLM results (PERFORMANCE OPTIMIZATION)
        # =====================================================================
        parallel_results = state.metadata.get("parallel_llm_results", {})
        cached_result = parallel_results.get(self.topic)
        llm_output: Optional[LLMSpecialistOutput] = None

        if cached_result is not None:
            # Deserialize from dict (cached results are stored via model_dump())
            try:
                llm_output = LLMSpecialistOutput.model_validate(cached_result)
                _debug_log(
                    f"[SPECIALIST] Using CACHED parallel result for {self.topic}: "
                    f"status={llm_output.feasibility_status}, "
                    f"activities={len(llm_output.activities)}"
                )
            except Exception as e:
                _debug_log(f"[SPECIALIST] Failed to deserialize cached result: {e}")
                llm_output = None
        else:
            # =====================================================================
            # STEP 1: Try LLM-based generation (fallback if not parallel)
            # =====================================================================
            use_llm = self.topic in SPECIALIST_SYSTEM_PROMPTS

            if use_llm and destination:
                _debug_log(f"[SPECIALIST] Trying LLM generation for {self.topic} in {destination}")
                try:
                    # Native async - no event loop blocking
                    _skill = (
                        state.metadata.get("trip_inputs", {})
                        .get("activity_settings", {})
                        .get("skill_level")
                    )
                    llm_output = await generate_specialist_output_llm(
                        self.topic,
                        destination,
                        state.trip_plan,
                        skill_level=_skill,
                    )
                except Exception as e:
                    _debug_log(f"[SPECIALIST] LLM generation failed: {e}, using hardcoded fallback")

        # =====================================================================
        # STEP 1.5: Process LLM output (cached or fresh)
        # =====================================================================
        if llm_output:
            _debug_log(
                f"[SPECIALIST] LLM SUCCESS: status={llm_output.feasibility_status}, "
                f"activities={len(llm_output.activities)}, "
                f"constraints={len(llm_output.constraints)}"
            )

            # Handle infeasible from LLM
            if llm_output.feasibility_status == "infeasible":
                return SpecialistOutput(
                    feasibility_status="infeasible",
                    feasibility_reason=llm_output.feasibility_reason,
                    alternative_suggestion=_suggest_alternative(self.topic),
                    constraints=[],
                    content_blocks=[],
                    critique=None,
                    enhancements=[],
                )

            # Prefetch activity-specific images from Unsplash BEFORE conversion
            # This populates the memory cache so get_image_url_sync returns Unsplash images
            # MUST await - otherwise cache is empty and fallback shows generic placeholders
            try:
                from app.services.unsplash import prefetch_destination_images

                prefetch_count = await prefetch_destination_images(
                    destination, activities=[self.topic]
                )
                _debug_log(
                    f"[SPECIALIST] Unsplash prefetch completed: {prefetch_count} images "
                    f"for {destination}/{self.topic}"
                )
            except Exception as e:
                _debug_log(f"[SPECIALIST] Unsplash prefetch error (non-fatal): {e}")

            # Convert LLM output to SpecialistOutput format
            converted = convert_llm_output_to_specialist_output(llm_output, self.topic, destination)

            # Add bookends (arrival/departure) - always deterministic
            bookends = self.generate_bookends(state)
            all_blocks = bookends + converted.content_blocks
            all_blocks.sort(key=lambda b: b.day)

            # Add safety buffers
            safety_buffers = self.generate_safety_buffers(state)
            all_blocks.extend(safety_buffers)
            all_blocks.sort(key=lambda b: b.day)

            # Migrate any legacy constraints
            constraints = _migrate_legacy_constraints(converted.constraints)

            # Replace LLM-generated constraints with hardcoded ones (proper IDs/labels)
            # LLM constraints have garbage numeric IDs ("1", "2", "3") - hardcoded are cleaner
            safety_constraints = _get_minimal_safety_constraints(self.topic, destination)
            if safety_constraints:
                constraints = safety_constraints
                _debug_log(
                    f"[SPECIALIST] Replaced LLM constraints with {len(constraints)} hardcoded"
                )

            return SpecialistOutput(
                feasibility_status=llm_output.feasibility_status,
                feasibility_reason=llm_output.feasibility_reason,
                constraints=constraints,
                content_blocks=all_blocks,
                critique=None,
                enhancements=self.generate_enhancements(state),
            )

        # =====================================================================
        # STEP 2: FALLBACK - Use hardcoded knowledge (legacy path)
        # =====================================================================
        _debug_log(f"[SPECIALIST] Using hardcoded fallback for {self.topic}")

        # Check feasibility using hardcoded data
        status, reason, alternative = check_feasibility(self.topic, destination)
        _debug_log(
            f"[SPECIALIST] feasibility: status={status}, reason={reason[:50] if reason else None}"
        )

        if status == "infeasible":
            return SpecialistOutput(
                feasibility_status="infeasible",
                feasibility_reason=reason,
                alternative_suggestion=alternative,
                constraints=[],
                content_blocks=[],
                critique=None,
                enhancements=[],
            )

        # Collect all content blocks
        all_blocks: List[ItineraryBlock] = []

        # Bookends (arrival/departure)
        bookends = self.generate_bookends(state)
        all_blocks.extend(bookends)

        # Safety buffers
        safety_buffers = self.generate_safety_buffers(state)
        all_blocks.extend(safety_buffers)

        # Activity content from hardcoded knowledge
        activity_content = self.get_content_for_destination(destination, state)
        all_blocks.extend(activity_content)

        # Sort by day
        all_blocks.sort(key=lambda b: b.day)

        # Get hardcoded constraints and migrate them
        constraints = _migrate_legacy_constraints(self.get_constraints())

        # If caveat, inject as first constraint (warning)
        if status == "caveat" and reason:
            constraints.insert(
                0,
                SpecialistConstraint(
                    constraint_id="feasibility_caveat",
                    type="safety",
                    rule="feasibility_caveat",
                    applies_to="activities",
                    reason=reason,
                ),
            )

        return SpecialistOutput(
            feasibility_status=status,
            feasibility_reason=reason if status == "caveat" else None,
            alternative_suggestion=alternative,
            constraints=constraints,
            content_blocks=all_blocks,
            critique=self.critique_plan(state),
            enhancements=self.generate_enhancements(state),
        )


# =============================================================================
# Prompt Loading (for future LLM-based specialist)
# =============================================================================


def load_specialist_prompt(topic: str) -> Optional[str]:
    """
    Load specialist prompt from file.

    Looks for prompts/specialists/{topic}.txt
    """
    prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "specialists"
    prompt_file = prompts_dir / f"{topic}.txt"

    if prompt_file.exists():
        return prompt_file.read_text()

    return None


# =============================================================================
# Curated Image Lookup
# =============================================================================


def _get_curated_image(topic: str, destination: str, title: str) -> Optional[str]:
    """
    Get image URL from curated content if available.

    Looks up the demo_curation.py DEMO_MANIFEST for matching activity images.
    Returns None if no match found (graceful fallback for non-demo destinations).
    """
    from app.data.demo_curation import DEMO_MANIFEST

    dest_key = destination.lower().strip() if destination else ""
    manifest = DEMO_MANIFEST.get(dest_key, {})
    specialist_content = manifest.get("specialist_content", {})

    # Check specialist-specific content first
    activities = specialist_content.get(topic, [])
    for activity in activities:
        # Fuzzy match on title (case-insensitive, contains)
        activity_title = activity.get("title", "").lower()
        search_title = title.lower()
        if (
            activity_title == search_title
            or search_title in activity_title
            or activity_title in search_title
        ):
            return activity.get("image")

    # Check general content as fallback
    general = specialist_content.get("general", [])
    for activity in general:
        activity_title = activity.get("title", "").lower()
        search_title = title.lower()
        if (
            activity_title == search_title
            or search_title in activity_title
            or activity_title in search_title
        ):
            return activity.get("image")

    return None


# =============================================================================
# Node Function (for graph registration)
# =============================================================================


async def vertical_specialist(state: GraphState) -> GraphState:
    """
    VerticalSpecialist node function for LangGraph.

    The "Diving Agent" / "Hiking Agent" that injects domain expertise.

    CRITICAL: Multi-specialist support requires state mutations to happen HERE,
    not in routing functions (LangGraph doesn't persist routing function mutations).

    Flow:
    1. First run: Router sets active_specialist, we use it and clear it at end
    2. Routing sees pending_specialists not empty → routes back here
    3. Subsequent runs: active_specialist is None, we pop from pending_specialists
    """
    import time

    from app.debug_utils import (
        CompactLogger,
        _debug_log,
        _debug_node_start,
        _debug_node_timer_end,
        _debug_node_timer_start,
        log,
    )

    # Start timing this node
    node_start_time = time.time()

    # Initialize compact logger with request metrics
    metrics = state.metadata.get("_metrics")
    clog = CompactLogger("specialist", metrics=metrics)

    # =========================================================================
    # FIRST THING: Invalidate stale cache if destination OR month changed
    # Must happen before ANY other logic for multi-specialist loops
    # =========================================================================
    cached_key = state.metadata.get("_last_specialist_key", "")
    current_dest = (state.trip_plan.destination or "").lower().strip()
    # CRITICAL: Use full date range, not just month - dates within same month matter!
    # "Feb 11-18" vs "Feb 11-14" must invalidate cache (different trip durations)
    start_date = state.trip_plan.start_date or "no-start"
    end_date = state.trip_plan.end_date or "no-end"
    current_key = f"{current_dest}:{start_date}:{end_date}"

    if cached_key and cached_key != current_key:
        _debug_log(
            f"[SPECIALIST] Context changed ({cached_key} → {current_key}), "
            "invalidating parallel_llm_results"
        )
        state.metadata.pop("parallel_llm_results", None)
    else:
        _debug_log(f"[SPECIALIST] Context unchanged ({current_key}), preserving cache")

    # Store current key for next comparison
    state.metadata["_last_specialist_key"] = current_key

    # Start timing this node execution
    _debug_node_timer_start("specialist")

    # MULTI-SPECIALIST SUPPORT: Pop from pending if active_specialist is not set
    # On first run, router sets active_specialist. On loop iterations, we pop from pending.
    if not state.active_specialist and state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        state.pending_specialists = state.pending_specialists[1:]
        state.active_specialist = next_specialist
        state.active_agent_id = next_specialist
        state.ui_events.append("SPECIALIST_ACTIVE")
        log("SPECIALIST", f"Multi-specialist loop: popped '{next_specialist}' from queue")

    topic = state.active_specialist

    if not topic:
        # No specialist needed - pass through
        _debug_log("🤿 SPECIALIST skipped (no active specialist)")
        # Compact logging: skipped
        duration_ms = int((time.time() - node_start_time) * 1000)
        clog.node_end("SPECIALIST", duration_ms, status="skipped", reason="no_active_specialist")
        return state

    # Compact logging: node start
    clog.node_start("SPECIALIST", topic=topic, dest=state.trip_plan.destination)

    # =========================================================================
    # SELECTIVE REGENERATION: Check if cached output can be reused
    # =========================================================================
    # If strategy_sections already contains this specialist's output AND
    # destination hasn't changed since last generation, skip LLM call.
    # This is the node-level cache awareness for selective regeneration.
    # @see docs/plan_graph_analysis.md - Selective Regeneration
    #
    existing_sections = state.metadata.get("strategy_sections", [])
    cached_section = next((s for s in existing_sections if s.get("specialist_type") == topic), None)

    if cached_section:
        # Check if destination AND dates match cached section
        # CRITICAL: Dates must match - same destination with different dates = different content
        cached_destination = cached_section.get("subtitle")  # subtitle = destination
        cached_dates = cached_section.get("_cache_dates")  # dates when section was generated
        current_destination = state.trip_plan.destination
        current_dates = f"{state.trip_plan.start_date}:{state.trip_plan.end_date}"

        destination_match = cached_destination and cached_destination == current_destination
        dates_match = cached_dates and cached_dates == current_dates

        if destination_match and dates_match:
            _debug_log(
                f"🤿 SPECIALIST [{topic}] Cache HIT: Reusing cached output "
                f"(destination={current_destination}, dates={current_dates})"
            )

            # Still need to track execution for downstream nodes
            state.metadata["last_executed_specialist"] = topic
            state.active_specialist = None  # Clear for multi-specialist support

            _debug_node_timer_end(
                "specialist",
                "🤿",
                topic=topic,
                cache_hit=True,
            )

            # Compact logging: cache hit
            clog.event("cache_hit", f"Specialist ({topic})", dest=current_destination)
            duration_ms = int((time.time() - node_start_time) * 1000)
            clog.node_end("SPECIALIST", duration_ms, topic=topic, status="cache_hit")
            return state  # No-op, output already in state

        _debug_log(
            f"🤿 SPECIALIST [{topic}] Cache MISS: context changed "
            f"(dest: {cached_destination}->{current_destination}, "
            f"dates: {cached_dates}->{current_dates})"
        )

    _debug_node_start(
        "specialist",
        "🤿",
        topic=topic,
        destination=state.trip_plan.destination,
    )

    # DEBUG: Log full trip plan state
    _debug_log(
        f"[SPECIALIST] FULL STATE: start_date={state.trip_plan.start_date}, "
        f"end_date={state.trip_plan.end_date}"
    )
    _debug_log(
        f"[SPECIALIST] FULL STATE: adults={state.trip_plan.adults}, "
        f"children={state.trip_plan.children}"
    )
    tiles_count = sum(len(v) for v in state.tiles.values()) if state.tiles else 0
    _debug_log(f"[SPECIALIST] FULL STATE: tiles_count={tiles_count}")
    existing_sections = [
        s.get("specialist_type") for s in state.metadata.get("strategy_sections", [])
    ]
    _debug_log(f"[SPECIALIST] FULL STATE: existing_strategy_sections={existing_sections}")

    log("SPECIALIST", f"{topic.title()} Specialist activated")
    log("SPECIALIST", f"Destination from trip_plan: '{state.trip_plan.destination}'")
    dest_from_inputs = state.metadata.get("trip_inputs", {}).get("destination")
    log(
        "SPECIALIST",
        f"Destination from metadata.trip_inputs: '{dest_from_inputs}'",
    )

    # Verify destination is set - critical for correct content
    if not state.trip_plan.destination:
        log("SPECIALIST", "⚠️ WARNING: No destination set in trip_plan!")

    # =========================================================================
    # PARALLEL LLM OPTIMIZATION: Trigger parallel generation on first specialist
    # =========================================================================
    # If this is the first specialist call AND there are multiple specialists,
    # generate all LLM outputs in parallel and cache them for subsequent calls.
    # This reduces wall time from 8-12s (sequential) to 4-6s (parallel).
    #
    # NEW: Pass database session for L1+L2 persistent caching (7-day TTL).
    #
    if "parallel_llm_results" not in state.metadata:
        # Collect all specialists that need processing
        all_specialists = [topic] + list(state.pending_specialists)

        if len(all_specialists) > 1:
            _debug_log(
                f"[SPECIALIST] PARALLEL TRIGGER: {len(all_specialists)} specialists "
                f"detected ({all_specialists}), running in parallel"
            )

            # Get database session for persistent caching
            from app.db import _get_async_session_factory

            async_session_factory = _get_async_session_factory()

            async with async_session_factory() as db:
                # Run all LLM calls in parallel with persistent caching
                _skill = (
                    state.metadata.get("trip_inputs", {})
                    .get("activity_settings", {})
                    .get("skill_level")
                )
                parallel_results = await generate_all_specialists_parallel(
                    topics=all_specialists,
                    destination=state.trip_plan.destination,
                    trip_plan=state.trip_plan,
                    db=db,  # Pass session for L1+L2 caching
                    skill_level=_skill,
                )

            # Cache results for this and subsequent specialist calls
            state.metadata["parallel_llm_results"] = {
                k: v.model_dump() if v else None for k, v in parallel_results.items()
            }

            _debug_log(f"[SPECIALIST] PARALLEL COMPLETE: Cached {len(parallel_results)} results")
        else:
            # Single specialist - use same cache path as parallel for consistency
            _debug_log(f"[SPECIALIST] Single specialist '{topic}' - using cached LLM path")

            from app.db import _get_async_session_factory
            from app.services.specialist_cache import (
                get_cached_specialist_output,
            )

            async_session_factory = _get_async_session_factory()
            cached_result = None
            llm_result = None

            try:
                async with async_session_factory() as db:
                    # STEP 1: Check cache - log dates for debugging stale cache issues
                    _debug_log(
                        f"[SPECIALIST_CACHE] Looking up cache for {topic} "
                        f"in {state.trip_plan.destination} "
                        f"dates={state.trip_plan.start_date}→{state.trip_plan.end_date}"
                    )
                    cached_result = await get_cached_specialist_output(
                        db=db,
                        topic=topic,
                        destination=state.trip_plan.destination,
                        start_date=state.trip_plan.start_date,
                        end_date=state.trip_plan.end_date,
                    )

                    if cached_result:
                        _debug_log(f"[SPECIALIST_CACHE] ✅ HIT for {topic} - skipping LLM")
                        state.metadata["parallel_llm_results"] = {topic: cached_result}
                    else:
                        _debug_log(f"[SPECIALIST_CACHE] ❌ MISS for {topic} - calling LLM")

                        # STEP 2: Call LLM with db session for cache write
                        _skill = (
                            state.metadata.get("trip_inputs", {})
                            .get("activity_settings", {})
                            .get("skill_level")
                        )
                        llm_result = await generate_specialist_output_llm(
                            topic=topic,
                            destination=state.trip_plan.destination,
                            trip_plan=state.trip_plan,
                            db=db,  # Pass db for cache write
                            skill_level=_skill,
                        )

                        if llm_result:
                            _debug_log(
                                f"[SPECIALIST_CACHE] LLM success for {topic}: "
                                f"status={llm_result.feasibility_status}, "
                                f"activities={len(llm_result.activities)}"
                            )
                            state.metadata["parallel_llm_results"] = {
                                topic: llm_result.model_dump()
                            }
                        else:
                            _debug_log(
                                f"[SPECIALIST_CACHE] LLM returned None for {topic} "
                                "- will use fallback"
                            )
                            state.metadata["parallel_llm_results"] = {}

            except Exception as e:
                _debug_log(f"[SPECIALIST_CACHE] Error: {e}")
                state.metadata["parallel_llm_results"] = {}

    # Create specialist for this topic
    specialist = VerticalSpecialist(topic)

    # Generate output (includes feasibility check)
    output = await specialist.generate_output(state)

    # Store specialist output in metadata (always, for UI rendering)
    state.metadata["specialist_output"] = output.model_dump()

    # Handle INFEASIBLE case - activity not possible at destination
    if output.feasibility_status == "infeasible":
        log("SPECIALIST", f"⛔ {topic.title()} INFEASIBLE in {state.trip_plan.destination}")
        log("SPECIALIST", f"   Reason: {output.feasibility_reason}")
        if output.alternative_suggestion:
            log("SPECIALIST", f"   Alternative: {output.alternative_suggestion}")

        # Add as a constraint violation for UI display
        state.constraints_violated.append(
            output.feasibility_reason or f"{topic.title()} not available at this destination"
        )

        # Store infeasibility metadata for frontend
        state.metadata["specialist_infeasible"] = True
        state.metadata["specialist_infeasible_reason"] = output.feasibility_reason
        state.metadata["specialist_alternative"] = output.alternative_suggestion

        # Update UI state
        state.active_agent_id = topic
        state.ui_events.append("SPECIALIST_INFEASIBLE")

        # Generate message for UI
        state.metadata["specialist_message"] = (
            f"{topic.title()} is not available in {state.trip_plan.destination}. "
            f"{output.alternative_suggestion or 'Consider a different destination.'}"
        )

        _debug_node_timer_end(
            "specialist",
            "🤿",
            topic=topic,
            feasibility_status="infeasible",
            reason=output.feasibility_reason,
        )

        # Compact logging: infeasible
        duration_ms = int((time.time() - node_start_time) * 1000)
        clog.node_end("SPECIALIST", duration_ms, topic=topic, status="infeasible")

        state.metadata["last_executed_specialist"] = topic  # Track for downstream nodes
        state.active_specialist = None  # Clear for multi-specialist support
        return state

    # Handle CAVEAT case - activity possible with limitations
    if output.feasibility_status == "caveat":
        log("SPECIALIST", f"⚠️ {topic.title()} CAVEAT: {output.feasibility_reason}")
        state.metadata["specialist_caveat"] = True
        state.metadata["specialist_caveat_reason"] = output.feasibility_reason

    # FEASIBLE or CAVEAT: Inject constraints into trip plan
    for constraint in output.constraints:
        if constraint not in state.trip_plan.constraints:
            state.trip_plan.constraints.append(constraint)

    # Add content blocks to trip plan
    for block in output.content_blocks:
        if block not in state.trip_plan.itinerary_blocks:
            state.trip_plan.itinerary_blocks.append(block)

    # Persist specialist constraints to metadata for cross-turn survival
    # Guard will merge these back if trip_plan.constraints gets cleared on subsequent turns
    if output.constraints:
        specialist_store = state.metadata.setdefault("specialist_constraints", {})
        # Store full model dict for proper reconstruction
        specialist_store[topic] = [c.model_dump() for c in output.constraints]
        log("SPECIALIST", f"Persisted {len(output.constraints)} constraints to metadata['{topic}']")

    # Log constraints and content
    if output.constraints:
        constraint_rules = ", ".join([c.rule for c in output.constraints])
        log("SPECIALIST", "Constraints injected", data=constraint_rules)
    if output.content_blocks:
        log("SPECIALIST", f"Content blocks: {len(output.content_blocks)}")
        for block in output.content_blocks[:3]:
            log("SPECIALIST", f"  Day {block.day}: {block.title}", sleep=0.1)

    # Update UI state
    state.active_agent_id = topic
    state.ui_events.append("SPECIALIST_DONE")

    # Build strategy_section for UI display (with images from curated content)
    # This enables the frontend to render specialist cards with thumbnails
    content_added = []
    for block in output.content_blocks:
        # Skip buffer blocks (arrival/departure/no-fly) - only show activities
        if block.is_buffer:
            continue
        # Use image_url from block if already set (from curated content),
        # otherwise fall back to lookup by title (for hardcoded knowledge)
        image_url = block.image_url or _get_curated_image(
            topic, state.trip_plan.destination, block.title
        )
        # Map skill_level to intensity for frontend display
        # Handles both formats: beginner/intermediate/advanced AND easy/moderate/hard
        skill_to_intensity = {
            "beginner": "light",
            "easy": "light",
            "intermediate": "moderate",
            "moderate": "moderate",
            "advanced": "challenging",
            "hard": "challenging",
            "challenging": "challenging",
        }
        # Default intensity by specialist type if skill_level not set
        default_intensity = {
            "diving": "moderate",
            "hiking": "moderate",
            "skiing": "challenging",
            "cycling": "moderate",
            "surfing": "moderate",
        }
        # Normalize skill_level to lowercase for case-insensitive matching
        skill_key = block.skill_level.lower() if block.skill_level else None
        intensity = (
            skill_to_intensity.get(skill_key)
            if skill_key
            else default_intensity.get(topic, "moderate")
        )

        content_item = {
            "title": block.title,
            "description": block.description,
            "logic_hook": block.logic_hook,
            "type": block.type,
            "day": block.day,
            "image_url": image_url,
            "coordinates": block.coordinates,  # [lng, lat] for Mapbox POI pins
            "intensity": intensity,  # light/moderate/challenging for difficulty badge
            "duration_hours": block.duration_hours,
        }
        content_added.append(content_item)

    # TRIM: Limit activities to what fits in the trip duration.
    # Cached/hardcoded content may have more activities than the current dates allow
    # (e.g. dates shortened from 6 to 4 days but content was generated for 6).
    max_activities = specialist._calculate_activity_days(state)
    if max_activities > 0 and len(content_added) > max_activities:
        original_count = len(content_added)
        content_added = content_added[:max_activities]
        log("SPECIALIST", f"Trimmed activities: {original_count} → {max_activities}")

    # Determine hero_image: use first content image or generate fallback
    hero_image = None
    if content_added:
        hero_image = content_added[0].get("image_url")
    if not hero_image:
        hero_image = get_activity_image(topic, state.trip_plan.destination or "", topic)

    section: Dict[str, Any] = {
        "id": f"specialist_{topic}",
        "title": f"{topic.title()} Specialist",
        "specialist_type": topic,
        "subtitle": state.trip_plan.destination,  # For cache comparison
        # Cache invalidation key: must match destination AND dates
        "_cache_dates": f"{state.trip_plan.start_date}:{state.trip_plan.end_date}",
        "feasibility_status": output.feasibility_status,
        "feasibility_reason": output.feasibility_reason,
        "alternative_suggestion": output.alternative_suggestion,
        "constraints_applied": [
            {"rule": c.rule, "reason": c.reason, "type": c.type} for c in output.constraints
        ],
        "content_added": content_added,
        "hero_image": hero_image,  # Hero banner for niche specialist layout
        "impact_areas": [topic.title(), "Safety", "Activities"],
        # Required fields for StrategySection
        "principles": [],
        "must_dos": [],
        "optional_upgrades": output.enhancements[:3] if output.enhancements else [],
        "logistics_notes": [],
        "bullets": [],
    }

    # Initialize strategy_sections if needed
    if "strategy_sections" not in state.metadata:
        state.metadata["strategy_sections"] = []

    # Remove existing section for this specialist (avoid duplicates on re-run)
    state.metadata["strategy_sections"] = [
        s for s in state.metadata["strategy_sections"] if s.get("specialist_type") != topic
    ]
    state.metadata["strategy_sections"].append(section)

    # Add topic to executed_strategy_topics (for frontend status display)
    executed = state.metadata.get("executed_strategy_topics", [])
    if topic not in executed:
        executed = list(executed)  # Make a copy
        executed.append(topic)
        state.metadata["executed_strategy_topics"] = executed

    _debug_log(f"Strategy section created for {topic} with {len(content_added)} recommendations")
    reason_preview = output.feasibility_reason[:50] if output.feasibility_reason else None
    _debug_log(
        f"  feasibility_status={output.feasibility_status}, feasibility_reason={reason_preview}"
    )
    _debug_log(
        f"  constraints_count={len(output.constraints)}, "
        f"content_blocks_count={len(output.content_blocks)}"
    )
    _debug_log(f"  content_added titles: {[c.get('title') for c in content_added]}")
    _debug_log(f"  content_added has images: {[bool(c.get('image_url')) for c in content_added]}")

    # Generate specialist message for UI
    if output.content_blocks:
        block_titles = [b.title for b in output.content_blocks[:3]]
        caveat_note = (
            f" Note: {output.feasibility_reason}" if output.feasibility_status == "caveat" else ""
        )
        state.metadata["specialist_message"] = (
            f"I've added some {topic} experiences: {', '.join(block_titles)}. "
            f"I've also noted {len(output.constraints)} safety considerations.{caveat_note}"
        )

    _debug_node_timer_end(
        "specialist",
        "🤿",
        topic=topic,
        constraints_added=len(output.constraints),
        content_blocks_added=len(output.content_blocks),
        critique=output.critique[:50] if output.critique else None,
    )

    # Compact logging: success
    duration_ms = int((time.time() - node_start_time) * 1000)
    clog.node_end(
        "SPECIALIST",
        duration_ms,
        topic=topic,
        status=output.feasibility_status,
        constraints=len(output.constraints),
        activities=len(output.content_blocks),
    )

    # Track for downstream nodes (synthesizer, _v2_result_to_v1_format)
    state.metadata["last_executed_specialist"] = topic

    # CRITICAL: Clear active_specialist after processing
    # This allows the routing function to know we're done with this one.
    # If pending_specialists has more items, routing will send us back here,
    # and we'll pop the next one at the start of the function.
    state.active_specialist = None

    return state
