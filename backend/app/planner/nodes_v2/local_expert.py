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
    description: str = Field(description="Why this is logistically smart")
    category: Literal["logistics", "attraction", "dining"] = Field(
        default="logistics", description="Category of recommendation"
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

    # ==========================================================================
    # Load Prompt
    # ==========================================================================
    prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "specialists"
    prompt_file = prompts_dir / "local_expert.txt"

    if prompt_file.exists():
        system_prompt = prompt_file.read_text()
    else:
        log("LOCAL_EXPERT", "Prompt file not found, using fallback")
        system_prompt = """You are a local logistics expert. Provide:
1. Constraints: Opening hours, booking requirements, seasonal considerations
2. Recommendations: Transit passes, efficiency tips, cultural notes
Output as JSON with "constraints" and "recommendations" arrays."""

    # Build user context
    user_context = f"""
Destination: {plan.destination}
Dates: {plan.start_date or 'Not specified'} to {plan.end_date or 'Not specified'}
Travelers: {plan.adults} adults{f', {plan.children} children' if plan.children else ''}
"""

    # ==========================================================================
    # Call LLM
    # ==========================================================================
    model = os.getenv("EXTRACTION_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(model=model, temperature=0.3)
    structured_llm = llm.with_structured_output(LocalExpertOutput)

    try:
        response = await structured_llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_context),
            ]
        )
    except Exception as e:
        # Only log errors in full mode (hide from demo videos)
        from app.debug_utils import _debug_error

        _debug_error(f"LOCAL_EXPERT LLM Error: {e}")
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
            }
        )

    # Build the strategy section
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
        "booking_artifacts": {
            "activities_count": 0,
            "hotels_count": 0,
            "flights_count": 0,
        },
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
