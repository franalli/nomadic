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

    def generate_output(self, state: GraphStateV2) -> SpecialistOutput:
        """
        Generate the complete specialist output.

        Returns BOTH constraints AND content.
        """
        destination = state.trip_plan.destination or ""

        return SpecialistOutput(
            constraints=self.get_constraints(),
            content_blocks=self.get_content_for_destination(destination),
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

    _debug_v2_node_start(
        "specialist",
        "🤿",
        topic=topic,
        destination=state.trip_plan.destination,
    )

    # Create specialist for this topic
    specialist = VerticalSpecialist(topic)

    # Generate output
    output = specialist.generate_output(state)

    # Inject constraints into trip plan
    for constraint in output.constraints:
        if constraint not in state.trip_plan.constraints:
            state.trip_plan.constraints.append(constraint)

    # Add content blocks to trip plan
    for block in output.content_blocks:
        if block not in state.trip_plan.itinerary_blocks:
            state.trip_plan.itinerary_blocks.append(block)

    # Store specialist output in metadata
    state.metadata["specialist_output"] = output.model_dump()

    # Update UI state
    state.active_agent_id = topic
    state.ui_events.append("SPECIALIST_DONE")

    # Generate specialist message for UI
    if output.content_blocks:
        block_titles = [b.title for b in output.content_blocks[:3]]
        state.metadata["specialist_message"] = (
            f"I've added some {topic} experiences: {', '.join(block_titles)}. "
            f"I've also noted {len(output.constraints)} safety considerations."
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
