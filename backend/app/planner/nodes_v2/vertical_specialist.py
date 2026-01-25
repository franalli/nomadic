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
from typing import List, Optional

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
            },
            {
                "title": "Manta Point Nusa Penida",
                "description": "High chance of manta ray encounters year-round",
                "type": "activity",
                "skill_level": "intermediate",
            },
            {
                "title": "Crystal Bay",
                "description": "Famous for Mola Mola (sunfish) sightings July-October",
                "type": "activity",
                "skill_level": "advanced",
            },
        ],
        "maldives": [
            {
                "title": "Hanifaru Bay",
                "description": "UNESCO biosphere for manta feeding aggregations",
                "type": "activity",
                "skill_level": "intermediate",
            },
            {
                "title": "Maaya Thila",
                "description": "Night diving with white-tip reef sharks",
                "type": "activity",
                "skill_level": "advanced",
            },
        ],
        "egypt": [
            {
                "title": "SS Thistlegorm",
                "description": "World-famous WWII wreck with trucks and motorcycles",
                "type": "activity",
                "skill_level": "intermediate",
            },
            {
                "title": "Ras Mohammed",
                "description": "Pristine coral walls and big fish action",
                "type": "activity",
                "skill_level": "beginner",
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
    # Caveat - pool/aquarium only
    "caveat": {
        "london": "Pool diving at NDAC or London Aquarium experiences",
        "amsterdam": "Pool diving at Duikvaker centers",
        "paris": "Pool diving at Aqua 92 or Nemo 33 (Belgium, 3h)",
        "berlin": "Pool diving at Dive4Life or aquarium experiences",
        "madrid": "Pool diving available; nearest sea diving in Valencia (3h)",
        "munich": "Pool diving; nearest sea diving in Croatia (5h)",
        "vienna": "Pool diving available; landlocked country",
    },
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
        """Get domain-specific constraints."""
        return self.knowledge.get("constraints", [])

    def get_content_for_destination(self, destination: str) -> List[ItineraryBlock]:
        """
        Get suggested activities for a destination.

        This is the S1/S2 content generation.
        """
        destinations = self.knowledge.get("top_destinations", {})

        # Normalize destination name for lookup
        dest_lower = destination.lower() if destination else ""

        # Find matching destination
        for dest_key, activities in destinations.items():
            if dest_key in dest_lower or dest_lower in dest_key:
                blocks = []
                for i, activity in enumerate(activities):
                    blocks.append(
                        ItineraryBlock(
                            day=i + 2,  # Start from day 2 (day 1 is arrival)
                            title=activity["title"],
                            description=activity["description"],
                            type=activity.get("type", "activity"),
                            source_specialist=self.topic,
                            skill_level=activity.get("skill_level"),
                        )
                    )
                return blocks

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
        destination = state.trip_plan.destination or ""

        # STEP 1: Check feasibility FIRST (Constraint Engine pattern)
        status, reason, alternative = check_feasibility(self.topic, destination)

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
        all_blocks.extend(self.generate_bookends(state))

        # 2b. Safety buffers (no-fly, acclimatization)
        all_blocks.extend(self.generate_safety_buffers(state))

        # 2c. Activity content
        all_blocks.extend(self.get_content_for_destination(destination))

        # Sort by day
        all_blocks.sort(key=lambda b: b.day)

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
# Node Function (for graph registration)
# =============================================================================


async def vertical_specialist(state: GraphStateV2) -> GraphStateV2:
    """
    VerticalSpecialist node function for LangGraph.

    The "Diving Agent" / "Hiking Agent" that injects domain expertise.
    """
    from app.debug_utils import _debug_v2, _debug_v2_node_end, _debug_v2_node_start

    topic = state.active_specialist

    if not topic:
        # No specialist needed - pass through
        _debug_v2("🤿 SPECIALIST skipped (no active specialist)")
        return state

    from app.debug_utils import log

    _debug_v2_node_start(
        "specialist",
        "🤿",
        topic=topic,
        destination=state.trip_plan.destination,
    )

    log("SPECIALIST", f"{topic.title()} Specialist activated")

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

    return state
