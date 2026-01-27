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

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.planner.state import (
    GraphStateV2,
    ItineraryBlock,
    SpecialistConstraint,
    SpecialistOutput,
)

# =============================================================================
# Specialist Domain Knowledge
# =============================================================================

# Diving domain knowledge
DIVING_KNOWLEDGE = {
    "constraints": [
        SpecialistConstraint(
            type="temporal",
            rule="min_24h_buffer_after_dive",
            applies_to="flights",
            reason="Flying within 24 hours of diving risks decompression sickness",
        ),
        SpecialistConstraint(
            type="temporal",
            rule="min_18h_surface_interval",
            applies_to="flights",
            reason="Minimum 18h recommended before flying after single dive",
        ),
        SpecialistConstraint(
            type="safety",
            rule="advanced_cert_required_for_deep",
            applies_to="activities",
            parameters={"max_depth_without_cert": 18},
            reason="Dives below 18m require Advanced Open Water certification",
        ),
    ],
    "top_destinations": {
        "bali": [
            {
                "title": "USAT Liberty Wreck",
                "description": (
                    "One of the most accessible wrecks in the world, " "perfect for all levels"
                ),
                "type": "activity",
                "skill_level": "beginner",
                "logic_hook": "Shore entry - no boat needed, 5am for best visibility",
            },
            {
                "title": "Manta Point Nusa Penida",
                "description": "High chance of manta ray encounters year-round",
                "type": "activity",
                "skill_level": "intermediate",
                "logic_hook": "Currents can be strong - intermediate+ recommended",
            },
            {
                "title": "Crystal Bay",
                "description": "Famous for Mola Mola (sunfish) sightings July-October",
                "type": "activity",
                "skill_level": "advanced",
                "logic_hook": "Mola season Jul-Oct only - plan timing accordingly",
            },
        ],
        "maldives": [
            {
                "title": "Hanifaru Bay",
                "description": "UNESCO biosphere for manta feeding aggregations",
                "type": "activity",
                "skill_level": "intermediate",
                "logic_hook": "Best Jun-Nov during SW monsoon plankton bloom",
            },
            {
                "title": "Maaya Thila",
                "description": "Night diving with white-tip reef sharks",
                "type": "activity",
                "skill_level": "advanced",
                "logic_hook": "Night dive - bring torch, sharks active after sunset",
            },
        ],
        "egypt": [
            {
                "title": "SS Thistlegorm",
                "description": "World-famous WWII wreck with trucks and motorcycles",
                "type": "activity",
                "skill_level": "intermediate",
                "logic_hook": "Best visited at dawn - fewer divers",
            },
            {
                "title": "Ras Mohammed",
                "description": "Pristine coral walls and big fish action",
                "type": "activity",
                "skill_level": "beginner",
                "logic_hook": "Morning dives best for calm conditions",
            },
        ],
        "dubai": [
            {
                "title": "Deep Dive Dubai",
                "description": (
                    "World's deepest pool at 60m with a sunken city theme. "
                    "Perfect for year-round diving regardless of weather."
                ),
                "type": "activity",
                "skill_level": "intermediate",
                "logic_hook": "Indoor facility - Summer safe, AC controlled",
            },
            {
                "title": "Jumeirah Scuba Diving",
                "description": (
                    "Shore diving at Jumeirah Beach with artificial reefs and marine life."
                ),
                "type": "activity",
                "skill_level": "beginner",
                "logic_hook": "No boat needed - shore entry",
            },
        ],
    },
}

HIKING_KNOWLEDGE = {
    "constraints": [
        SpecialistConstraint(
            type="safety",
            rule="altitude_acclimatization",
            applies_to="activities",
            parameters={"max_daily_elevation_gain": 500},
            reason="Gain no more than 500m per day above 3000m to prevent altitude sickness",
        ),
        SpecialistConstraint(
            type="equipment",
            rule="proper_footwear_required",
            applies_to="activities",
            reason="Hiking boots required for mountain trails",
        ),
    ],
    "top_destinations": {
        "patagonia": [
            {
                "title": "Torres del Paine W Trek",
                "description": "Iconic 5-day trek through glaciers and granite spires",
                "type": "activity",
                "skill_level": "intermediate",
            },
            {
                "title": "Fitz Roy Summit Approach",
                "description": "Day hike to the base of the famous peaks",
                "type": "activity",
                "skill_level": "beginner",
            },
        ],
        "nepal": [
            {
                "title": "Everest Base Camp",
                "description": "Classic 12-14 day trek to the roof of the world",
                "type": "activity",
                "skill_level": "intermediate",
            },
            {
                "title": "Annapurna Circuit",
                "description": "Diverse landscapes from jungle to high desert",
                "type": "activity",
                "skill_level": "advanced",
            },
        ],
    },
}

SKIING_KNOWLEDGE = {
    "constraints": [
        SpecialistConstraint(
            type="temporal",
            rule="check_snow_conditions",
            applies_to="activities",
            reason="Verify snow conditions and avalanche reports before backcountry skiing",
        ),
        SpecialistConstraint(
            type="certification",
            rule="guide_required_offpiste",
            applies_to="activities",
            reason="Certified guide required for off-piste skiing",
        ),
    ],
    "top_destinations": {
        "chamonix": [
            {
                "title": "Vallée Blanche",
                "description": "Legendary 20km off-piste descent from Aiguille du Midi",
                "type": "activity",
                "skill_level": "advanced",
            },
            {
                "title": "Les Grands Montets",
                "description": "Steep terrain with incredible Mont Blanc views",
                "type": "activity",
                "skill_level": "intermediate",
            },
        ],
        "japan": [
            {
                "title": "Niseko Powder",
                "description": "Legendary Japanese powder snow",
                "type": "activity",
                "skill_level": "intermediate",
            },
            {
                "title": "Hakuba Valley",
                "description": "1998 Olympics venue with varied terrain",
                "type": "activity",
                "skill_level": "beginner",
            },
        ],
    },
}

# Map topic to knowledge
SPECIALIST_KNOWLEDGE = {
    "diving": DIVING_KNOWLEDGE,
    "hiking": HIKING_KNOWLEDGE,
    "skiing": SKIING_KNOWLEDGE,
    "cycling": {"constraints": [], "top_destinations": {}},
    "boating": {"constraints": [], "top_destinations": {}},
}


# =============================================================================
# Feasibility Data (Geographic/Physical Constraints)
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


def check_feasibility(
    topic: str,
    destination: str,
) -> tuple:
    """
    Check if activity is feasible at destination.

    Returns:
        (status, reason, alternative_suggestion) tuple where:
        - status: "feasible" | "caveat" | "infeasible"
        - reason: Human-readable explanation (or None)
        - alternative_suggestion: Suggested alternative (or None)
    """

    dest_lower = (destination or "").lower()

    data = FEASIBILITY_DATA.get(topic)
    if not data:
        return ("feasible", None, None)

    # Check infeasible locations
    for location in data.get("infeasible", []):
        if location in dest_lower:
            return (
                "infeasible",
                f"{topic.title()} is not available in {destination}",
                _suggest_alternative(topic),
            )

    # Check caveat locations
    for location, caveat_msg in data.get("caveat", {}).items():
        if location in dest_lower:
            return (
                "caveat",
                caveat_msg,
                None,
            )

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

    Key difference from old architecture:
    - Returns BOTH safety constraints AND itinerary suggestions
    - Runs BEFORE Architect calls tools (Constraint Injector pattern)
    """

    def __init__(self, topic: str):
        self.topic = topic
        self.knowledge = SPECIALIST_KNOWLEDGE.get(
            topic, {"constraints": [], "top_destinations": {}}
        )
        self.debug = bool(os.getenv("DEBUG_PLAN_MESSAGES"))

    def get_constraints(self) -> List[SpecialistConstraint]:
        """Get domain-specific constraints.

        Returns a COPY of the constraints list to avoid mutating
        the original SPECIALIST_KNOWLEDGE when caveats are inserted.
        """
        return list(self.knowledge.get("constraints", []))

    def _calculate_activity_days(self, state: GraphStateV2) -> int:
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

        # DEBUG: Always print to console to trace dates
        print("[SPECIALIST DEBUG] _calculate_activity_days called")
        print(f"[SPECIALIST DEBUG]   topic={self.topic}")
        print(f"[SPECIALIST DEBUG]   start_date={plan.start_date}")
        print(f"[SPECIALIST DEBUG]   end_date={plan.end_date}")

        if not plan.start_date or not plan.end_date:
            print("[SPECIALIST DEBUG]   -> No dates, returning 3 (default)")
            return 3  # Default to 3 activity days if dates unknown

        from datetime import datetime

        try:
            start = datetime.strptime(plan.start_date, "%Y-%m-%d")
            end = datetime.strptime(plan.end_date, "%Y-%m-%d")
            total_days = (end - start).days + 1
            print(f"[SPECIALIST DEBUG]   total_days={total_days}")
        except ValueError as e:
            print(f"[SPECIALIST DEBUG]   -> Date parse error: {e}, returning 3")
            return 3  # Default if date parsing fails

        # Subtract arrival (day 1) and departure (last day)
        available = total_days - 2
        print(f"[SPECIALIST DEBUG]   after arrival/departure: available={available}")

        # Specialist-specific buffers
        if self.topic == "diving":
            # No-fly buffer day before departure
            available -= 1
            print(f"[SPECIALIST DEBUG]   after diving no-fly buffer: available={available}")
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
                print(f"[SPECIALIST DEBUG]   after hiking altitude buffer: available={available}")

        result = max(0, available)
        print(f"[SPECIALIST DEBUG]   -> FINAL: max_activities={result}")
        return result

    def get_content_for_destination(
        self, destination: str, state: Optional[GraphStateV2] = None
    ) -> List[ItineraryBlock]:
        """
        Get suggested activities for a destination.

        This is the S1/S2 content generation.
        Respects trip duration - only generates activities that fit.

        Priority:
        1. Curated content from demo_curation.py (has images for hero destinations)
        2. Hardcoded knowledge (fallback for non-hero destinations)
        """
        from app.debug_utils import _debug_v2

        # Guard: return empty if no destination (prevents false matches)
        if not destination:
            _debug_v2("[SPECIALIST] get_content_for_destination: No destination, returning empty")
            return []

        # Normalize destination name for lookup
        dest_lower = destination.lower().strip()

        # Extra safety: return empty if destination is effectively empty
        if not dest_lower:
            _debug_v2("[SPECIALIST] get_content_for_destination: Empty dest_lower, returning empty")
            return []

        # Calculate available activity days from trip dates
        max_activities = self._calculate_activity_days(state) if state else 3
        print(f"[SPECIALIST DEBUG] get_content_for_destination: max_activities={max_activities}")
        _debug_v2(f"[SPECIALIST] get_content_for_destination: max_activities={max_activities}")

        # For very short trips (no activity days), return empty
        if max_activities <= 0:
            print(
                "[SPECIALIST DEBUG] get_content_for_destination: "
                "TRIP TOO SHORT - returning empty list!"
            )
            _debug_v2("[SPECIALIST] get_content_for_destination: " "Trip too short for activities")
            return []

        # PRIORITY 1: Check for curated content (includes images)
        _debug_v2(
            f"[SPECIALIST] get_content_for_destination: "
            f"Looking up curated content for '{dest_lower}'"
        )
        curated_blocks = self._get_curated_content(dest_lower, max_activities)
        if curated_blocks:
            print(
                f"[SPECIALIST DEBUG] Returning {len(curated_blocks)} "
                f"curated blocks (max was {max_activities})"
            )
            _debug_v2(
                f"[SPECIALIST] get_content_for_destination: "
                f"Found {len(curated_blocks)} curated blocks (limited to {max_activities})"
            )
            return curated_blocks

        # PRIORITY 2: Fall back to hardcoded knowledge
        destinations = self.knowledge.get("top_destinations", {})
        for dest_key, activities in destinations.items():
            # Require meaningful match (not empty string matching everything)
            if len(dest_lower) >= 3 and (dest_key in dest_lower or dest_lower in dest_key):
                blocks = []
                # Limit to available activity days
                for i, activity in enumerate(activities[:max_activities]):
                    blocks.append(
                        ItineraryBlock(
                            day=i + 2,  # Start from day 2 (day 1 is arrival)
                            title=activity["title"],
                            description=activity["description"],
                            type=activity.get("type", "activity"),
                            source_specialist=self.topic,
                            skill_level=activity.get("skill_level"),
                            logic_hook=activity.get("logic_hook"),  # Pro tip for UI
                        )
                    )
                return blocks

        return []

    def _get_curated_content(
        self, destination: str, max_activities: int = 3
    ) -> List[ItineraryBlock]:
        """
        Get curated content from demo_curation.py if available.

        Returns ItineraryBlocks with images for hero destinations.
        Limited to max_activities based on trip duration.
        """
        from app.debug_utils import _debug_v2

        try:
            from app.data.demo_curation import DEMO_MANIFEST, is_hero_destination

            _debug_v2(
                f"[SPECIALIST] _get_curated_content: "
                f"destination='{destination}', topic='{self.topic}', max={max_activities}"
            )

            is_hero = is_hero_destination(destination)
            _debug_v2(f"[SPECIALIST] is_hero_destination('{destination}') = {is_hero}")

            if not is_hero:
                _debug_v2("[SPECIALIST] NOT a hero destination, returning empty")
                return []

            _debug_v2("[SPECIALIST] IS a hero destination, fetching curated content")
            manifest = DEMO_MANIFEST.get(destination.lower().strip(), {})
            specialist_content = manifest.get("specialist_content", {})
            _debug_v2(f"[SPECIALIST] specialist_content keys: {list(specialist_content.keys())}")

            # Get activities for this specialist type
            activities = specialist_content.get(self.topic, [])
            _debug_v2(f"[SPECIALIST] activities for topic '{self.topic}': {len(activities)}")

            if not activities:
                _debug_v2("[SPECIALIST] No activities found, returning empty")
                return []

            blocks = []
            # Limit to max_activities based on trip duration
            for i, activity in enumerate(activities[:max_activities]):
                _debug_v2(
                    f"[SPECIALIST] Creating block: {activity.get('title')}, "
                    f"image={bool(activity.get('image'))}"
                )
                blocks.append(
                    ItineraryBlock(
                        day=i + 2,  # Start from day 2 (day 1 is arrival)
                        title=activity.get("title", ""),
                        description=activity.get("description", ""),
                        type=activity.get("type", "activity"),
                        source_specialist=self.topic,
                        skill_level=activity.get("skill_level"),
                        logic_hook=activity.get("logic_hook"),
                        image_url=activity.get("image"),  # Curated image URL
                    )
                )

            _debug_v2(
                f"[SPECIALIST] Returning {len(blocks)} curated blocks (max was {max_activities})"
            )
            return blocks

        except ImportError:
            return []

    def critique_plan(self, state: GraphStateV2) -> Optional[str]:
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

    def generate_enhancements(self, state: GraphStateV2) -> List[str]:
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

    def generate_bookends(self, state: GraphStateV2) -> List[ItineraryBlock]:
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

    def generate_safety_buffers(self, state: GraphStateV2) -> List[ItineraryBlock]:
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
            # Add no-fly buffer on the day before departure
            no_fly_day = duration - 1
            blocks.append(
                ItineraryBlock(
                    day=no_fly_day,
                    title="No-Fly Interval",
                    description=(
                        "Surface interval before flight. Light activities only - no diving."
                    ),
                    type="buffer",
                    is_buffer=True,
                    buffer_type="no_fly",
                    buffer_reason=(
                        "PADI Standard: 24h surface interval required before flying after diving"
                    ),
                    source_specialist="diving",
                    safety_notes=(
                        "Decompression sickness risk if flying within 24 hours of diving"
                    ),
                )
            )

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

    def generate_output(self, state: GraphStateV2) -> SpecialistOutput:
        """
        Generate the complete specialist output.

        Returns BOTH constraints AND content, including:
        - Feasibility check (can return early if infeasible)
        - Bookend blocks (arrival/departure)
        - Safety buffer blocks (no-fly, acclimatization)
        - Activity content blocks
        """
        from app.debug_utils import _debug_v2

        destination = state.trip_plan.destination or ""

        # DEBUG: Log input state
        _debug_v2(
            f"[SPECIALIST] generate_output called: "
            f"topic={self.topic}, destination='{destination}'"
        )
        _debug_v2(
            f"[SPECIALIST] trip_plan: start_date={state.trip_plan.start_date}, "
            f"end_date={state.trip_plan.end_date}"
        )

        # STEP 1: Check feasibility FIRST (Constraint Engine pattern)
        status, reason, alternative = check_feasibility(self.topic, destination)
        _debug_v2(
            f"[SPECIALIST] feasibility: status={status}, reason={reason[:50] if reason else None}"
        )

        if status == "infeasible":
            # Return empty output with infeasible status - no content generated
            return SpecialistOutput(
                feasibility_status="infeasible",
                feasibility_reason=reason,
                alternative_suggestion=alternative,
                constraints=[],
                content_blocks=[],
                critique=None,
                enhancements=[],
            )

        # STEP 2: Collect all content blocks in order
        all_blocks: List[ItineraryBlock] = []

        # 2a. Bookends (arrival/departure)
        bookends = self.generate_bookends(state)
        _debug_v2(f"[SPECIALIST] bookends: {len(bookends)} blocks")
        all_blocks.extend(bookends)

        # 2b. Safety buffers (no-fly, acclimatization)
        safety_buffers = self.generate_safety_buffers(state)
        _debug_v2(f"[SPECIALIST] safety_buffers: {len(safety_buffers)} blocks")
        all_blocks.extend(safety_buffers)

        # 2c. Activity content (respects trip duration)
        activity_content = self.get_content_for_destination(destination, state)
        _debug_v2(f"[SPECIALIST] activity_content: {len(activity_content)} blocks")
        for block in activity_content:
            _debug_v2(
                f"[SPECIALIST]   - {block.title}, "
                f"is_buffer={block.is_buffer}, image={bool(block.image_url)}"
            )
        all_blocks.extend(activity_content)

        # Sort by day
        all_blocks.sort(key=lambda b: b.day)
        _debug_v2(f"[SPECIALIST] total all_blocks: {len(all_blocks)}")

        # STEP 3: Build constraints list
        constraints = self.get_constraints()

        # If caveat, inject as first constraint (warning)
        if status == "caveat" and reason:
            constraints.insert(
                0,
                SpecialistConstraint(
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


async def vertical_specialist(state: GraphStateV2) -> GraphStateV2:
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
    from app.debug_utils import _debug_v2, _debug_v2_node_end, _debug_v2_node_start, log

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
        _debug_v2("🤿 SPECIALIST skipped (no active specialist)")
        return state

    _debug_v2_node_start(
        "specialist",
        "🤿",
        topic=topic,
        destination=state.trip_plan.destination,
    )

    # DEBUG: Log full trip plan state
    _debug_v2(
        f"[SPECIALIST] FULL STATE: start_date={state.trip_plan.start_date}, "
        f"end_date={state.trip_plan.end_date}"
    )
    _debug_v2(
        f"[SPECIALIST] FULL STATE: adults={state.trip_plan.adults}, "
        f"children={state.trip_plan.children}"
    )
    tiles_count = sum(len(v) for v in state.tiles.values()) if state.tiles else 0
    _debug_v2(f"[SPECIALIST] FULL STATE: tiles_count={tiles_count}")
    existing_sections = [
        s.get("specialist_type") for s in state.metadata.get("strategy_sections", [])
    ]
    _debug_v2(f"[SPECIALIST] FULL STATE: existing_strategy_sections={existing_sections}")

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

    # Create specialist for this topic
    specialist = VerticalSpecialist(topic)

    # Generate output (includes feasibility check)
    output = specialist.generate_output(state)

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

        _debug_v2_node_end(
            "specialist",
            "🤿",
            topic=topic,
            feasibility_status="infeasible",
            reason=output.feasibility_reason,
        )

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
        content_added.append(
            {
                "title": block.title,
                "description": block.description,
                "logic_hook": block.logic_hook,
                "type": block.type,
                "day": block.day,
                "image_url": image_url,
            }
        )

    section: Dict[str, Any] = {
        "id": f"specialist_{topic}",
        "title": f"{topic.title()} Specialist",
        "specialist_type": topic,
        "feasibility_status": output.feasibility_status,
        "feasibility_reason": output.feasibility_reason,
        "alternative_suggestion": output.alternative_suggestion,
        "constraints_applied": [
            {"rule": c.rule, "reason": c.reason, "type": c.type} for c in output.constraints
        ],
        "content_added": content_added,
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

    _debug_v2(f"Strategy section created for {topic} with {len(content_added)} recommendations")
    reason_preview = output.feasibility_reason[:50] if output.feasibility_reason else None
    _debug_v2(
        f"  feasibility_status={output.feasibility_status}, " f"feasibility_reason={reason_preview}"
    )
    _debug_v2(
        f"  constraints_count={len(output.constraints)}, "
        f"content_blocks_count={len(output.content_blocks)}"
    )
    _debug_v2(f"  content_added titles: {[c.get('title') for c in content_added]}")
    _debug_v2(f"  content_added has images: {[bool(c.get('image_url')) for c in content_added]}")

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

    _debug_v2_node_end(
        "specialist",
        "🤿",
        topic=topic,
        constraints_added=len(output.constraints),
        content_blocks_added=len(output.content_blocks),
        critique=output.critique[:50] if output.critique else None,
    )

    # Track for downstream nodes (synthesizer, _v2_result_to_v1_format)
    state.metadata["last_executed_specialist"] = topic

    # CRITICAL: Clear active_specialist after processing
    # This allows the routing function to know we're done with this one.
    # If pending_specialists has more items, routing will send us back here,
    # and we'll pop the next one at the start of the function.
    state.active_specialist = None

    return state
