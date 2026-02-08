"""
Specialist LLM Integration

Optional LLM-based constraint generation using structured output.
This module provides an alternative to the hardcoded knowledge dictionaries
in vertical_specialist.py.

Enable with environment variable: USE_SPECIALIST_LLM=true

@see docs/plan_graph_analysis.md Section: VerticalSpecialist Node
"""

import os
from pathlib import Path
from typing import Optional

from app.planner.state import (
    ConstraintSeverity,
    GraphState,
    SpecialistConstraint,
)
from app.planner.state import (
    SpecialistOutput as StateSpecialistOutput,
)

from .specialist_schemas import (
    ConstraintType,
)
from .specialist_schemas import (
    SpecialistOutput as LLMSpecialistOutput,
)

# Environment flag to enable LLM-based specialist generation
USE_SPECIALIST_LLM = os.getenv("USE_SPECIALIST_LLM", "false").lower() == "true"


def get_specialist_prompt(specialist_type: str) -> Optional[str]:
    """Load the specialist prompt template for the given type."""
    prompt_path = (
        Path(__file__).parent.parent.parent / "prompts" / "specialists" / f"{specialist_type}.txt"
    )

    if not prompt_path.exists():
        return None

    return prompt_path.read_text()


def convert_llm_output_to_state(
    llm_output: LLMSpecialistOutput,
    specialist_type: str,
) -> StateSpecialistOutput:
    """
    Convert LLM structured output to the state format used by the existing node.

    Maps:
    - LLM ConstraintOutput → SpecialistConstraint
    - LLM FeasibilityAssessment → feasibility_status/reason/alternative
    """
    # Convert constraints
    constraints = []
    for c in llm_output.constraints:
        severity = {
            ConstraintType.BLOCKING: ConstraintSeverity.BLOCKING,
            ConstraintType.STRONG: ConstraintSeverity.STRONG,
            ConstraintType.SOFT: ConstraintSeverity.SOFT,
        }.get(c.type, ConstraintSeverity.STRONG)

        constraints.append(
            SpecialistConstraint(
                type=c.type.value if hasattr(c.type, "value") else str(c.type),
                rule=c.id,
                applies_to="activities",
                reason=c.description,
                label=c.description[:30] if len(c.description) > 30 else c.description,
                icon=c.icon,
                severity=severity,
                buffer_hours=(
                    c.temporal_requirements.buffer_hours if c.temporal_requirements else None
                ),
            )
        )

    # Convert feasibility
    feasibility = llm_output.feasibility
    if feasibility.is_feasible and not feasibility.blockers:
        status = "feasible"
    elif feasibility.blockers:
        status = "infeasible"
    else:
        status = "caveat"

    reason = None
    if feasibility.concerns:
        reason = "; ".join(feasibility.concerns)
    elif feasibility.blockers:
        reason = "; ".join(feasibility.blockers)

    alternative = None
    if feasibility.recommendations:
        alternative = feasibility.recommendations[0]

    return StateSpecialistOutput(
        feasibility_status=status,
        feasibility_reason=reason,
        alternative_suggestion=alternative,
        constraints=constraints,
        content_blocks=[],  # Content blocks generated separately
        critique=llm_output.critique,
        enhancements=llm_output.suggested_activities[:5],
    )


async def generate_specialist_output_with_llm(
    specialist_type: str,
    state: GraphState,
) -> Optional[LLMSpecialistOutput]:
    """
    Generate specialist output using LLM with structured output.

    This is an alternative to the hardcoded knowledge approach.
    Returns None if LLM call fails (allowing fallback to hardcoded).

    Requires: USE_SPECIALIST_LLM=true environment variable
    """
    if not USE_SPECIALIST_LLM:
        return None

    try:
        from langchain_openai import ChatOpenAI

        # Load prompt template
        prompt_template = get_specialist_prompt(specialist_type)
        if not prompt_template:
            return None

        # Format prompt with trip context
        trip = state.trip_plan
        prompt = prompt_template.format(
            destination=trip.destination or "destination",
            start_date=trip.start_date or "TBD",
            end_date=trip.end_date or "TBD",
            duration=trip.duration_days or 7,
            preferences="",  # Could expand to include user preferences
        )

        # Create LLM with structured output
        llm = ChatOpenAI(model=os.getenv("SPECIALIST_MODEL", "gpt-4o"), temperature=0.1)
        structured_llm = llm.with_structured_output(LLMSpecialistOutput)

        # Generate output
        output = await structured_llm.ainvoke(prompt)

        return output

    except Exception as e:
        # Log error and return None to allow fallback
        from app.debug_utils import _debug_info

        _debug_info("SPECIALIST_LLM", f"Error generating with LLM: {e}")
        return None


def is_llm_specialist_enabled() -> bool:
    """Check if LLM-based specialist generation is enabled."""
    return USE_SPECIALIST_LLM
