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
from typing import List, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.planner.state import GraphStateV2

# =============================================================================
# LLM Output Schema (OpenAI Structured Output compatible)
# =============================================================================


class LocalConstraint(BaseModel):
    """A logistical constraint for the destination."""

    type: Literal["opening_hours", "booking_window", "seasonal", "cultural"] = Field(
        description="Type of constraint"
    )
    description: str = Field(description="Short, actionable constraint text")
    severity: Literal["warning", "info"] = Field(default="info", description="Severity level")


class LocalRecommendation(BaseModel):
    """A logistical recommendation for the destination."""

    title: str = Field(description="Name of pass/tip/area")
    description: str = Field(description="What is it?")
    category: Literal["logistics", "attraction", "dining"] = Field(
        default="logistics", description="Category of recommendation"
    )
    logic_hook: str = Field(
        default="", description="The specific logistical advantage (e.g., 'Saves 20% on transit')"
    )


class LocalExpertOutput(BaseModel):
    """Structured output from the Local Expert LLM."""

    constraints: List[LocalConstraint] = Field(
        default_factory=list,
        description="List of logistical constraints (opening hours, booking windows, etc.)",
    )
    recommendations: List[LocalRecommendation] = Field(
        default_factory=list,
        description="List of logistical recommendations (passes, tips, etc.)",
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
                    "Dress modestly in malls and public areas - " "shoulders and knees covered"
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
                    "Broadway shows: book 2+ weeks for popular shows, " "or try TKTS day-of"
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
        return LocalExpertOutput(constraints=[], recommendations=[])

    constraints = [LocalConstraint(**c) for c in knowledge.get("constraints", [])]
    recommendations = [LocalRecommendation(**r) for r in knowledge.get("recommendations", [])]

    return LocalExpertOutput(constraints=constraints, recommendations=recommendations)


# =============================================================================
# Local Expert Node
# =============================================================================


async def local_expert(state: GraphStateV2) -> GraphStateV2:
    """
    The 'Concierge' agent. Adds logistical constraints and city tips.

    Triggered by default when no niche specialist is requested.
    Returns a StrategySection with constraints and recommendations.
    """
    from app.debug_utils import log

    plan = state.trip_plan

    # Skip if no destination
    if not plan.destination:
        log("LOCAL_EXPERT", "Skipped - no destination set")
        return state

    log("LOCAL_EXPERT", f"Activated for {plan.destination}")

    try:
        return await _run_local_expert(state, plan, log)
    except Exception as e:
        # Catch any unexpected errors to prevent graph crash
        from app.debug_utils import _debug_error

        _debug_error(f"LOCAL_EXPERT unexpected error: {e}")
        log("LOCAL_EXPERT", f"Error - returning state unchanged: {type(e).__name__}")
        return state


async def _run_local_expert(state: GraphStateV2, plan, log) -> GraphStateV2:
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
Dates: {plan.start_date or 'Not specified'} to {plan.end_date or 'Not specified'}
Travelers: {plan.adults} adults{f', {plan.children} children' if plan.children else ''}
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

    # Check for empty response
    if not response.constraints and not response.recommendations:
        log("LOCAL_EXPERT", "No content available for this destination")
        return state

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

    # Build the strategy section
    # NOTE: booking_artifacts intentionally omitted - Local Expert does not handle logistics counts
    section = {
        "id": "strategy_local_expert",
        "specialist_type": "local_expert",
        "title": f"{plan.destination} Local Expert",
        "one_liner": f"Local logistics and tips for {plan.destination}",
        "bullets": [c.description for c in response.constraints[:3]],
        "principles": [],
        "must_dos": [r.title for r in response.recommendations[:5]],
        "optional_upgrades": [],
        "logistics_notes": [r.description for r in response.recommendations],
        "constraints_applied": constraints_applied,
        "content_added": content_added,
        "impact_areas": ["Logistics", "Timing", "Culture"],
    }

    # ==========================================================================
    # Update State
    # ==========================================================================

    # Initialize strategy_sections if needed
    if "strategy_sections" not in state.metadata:
        state.metadata["strategy_sections"] = []

    # Remove existing local_expert section (avoid duplicates on re-run)
    state.metadata["strategy_sections"] = [
        s for s in state.metadata["strategy_sections"] if s.get("specialist_type") != "local_expert"
    ]
    state.metadata["strategy_sections"].append(section)

    # Mark as executed
    executed = state.metadata.get("executed_strategy_topics", [])
    if "local_expert" not in executed:
        executed = list(executed)  # Make a copy
        executed.append("local_expert")
        state.metadata["executed_strategy_topics"] = executed

    log(
        "LOCAL_EXPERT",
        f"Added {len(constraints_applied)} constraints, {len(content_added)} tips",
    )

    return state
