"""
Strategy Node Orchestrator - Calls relevant strategy nodes for plan generation.

Used by generate_responder to enrich branches with strategy content:
- Detects relevant strategy topics from activity_settings.categories
- Calls strategy nodes for each topic
- Parses LLM responses into structured content (vibe, highlights, flow, notes)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from app.debug_utils import _debug

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# Map activity categories to strategy topics
CATEGORY_TO_STRATEGY: Dict[str, str] = {
    # Hiking
    "hiking": "hiking",
    "trekking": "hiking",
    "mountains": "hiking",
    "trails": "hiking",
    # Diving
    "diving": "diving",
    "scuba": "diving",
    "snorkeling": "diving",
    "underwater": "diving",
    # Skiing
    "skiing": "skiing",
    "snowboarding": "skiing",
    "winter sports": "skiing",
    # Cycling
    "cycling": "cycling",
    "biking": "cycling",
    "bicycle": "cycling",
    # Boating
    "boating": "boating",
    "sailing": "boating",
    "yachting": "boating",
    "kayaking": "boating",
}


@dataclass
class StrategyContent:
    """Structured content parsed from strategy LLM response."""

    topic: str
    vibe: str = ""
    focus: str = ""
    highlights: List[str] = field(default_factory=list)
    flow: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class StrategyResult:
    """Result from a single strategy node execution."""

    topic: str
    success: bool
    content: Optional[StrategyContent] = None
    error: Optional[str] = None


def detect_relevant_strategies(state: "GraphState") -> List[str]:
    """
    Detect which strategy topics are relevant based on activity_settings.categories.

    Returns list of topic names (hiking, diving, skiing, cycling, boating).
    """
    topics: set[str] = set()

    activity_settings = state.trip_inputs.activity_settings
    if not activity_settings:
        return []

    # Handle both dict and object access (activity_settings can be either)
    if isinstance(activity_settings, dict):
        categories = activity_settings.get("categories", []) or []
    else:
        categories = activity_settings.categories or []

    for category in categories:
        category_lower = category.lower().strip()
        if category_lower in CATEGORY_TO_STRATEGY:
            topics.add(CATEGORY_TO_STRATEGY[category_lower])

    return list(topics)


def parse_strategy_response(response: str, topic: str) -> StrategyContent:
    """
    Parse strategy LLM response into structured content.

    Extracts vibe, focus, highlights, flow, and notes from markdown response.
    """
    content = StrategyContent(topic=topic)
    lines = response.split("\n")

    current_section: Optional[str] = None
    first_paragraph_captured = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect section headers (markdown ## or ** bold **)
        lower = stripped.lower()
        if "itinerary" in lower or "day-by-day" in lower or "schedule" in lower:
            current_section = "flow"
            continue
        if "highlight" in lower or "experience" in lower or "must-" in lower:
            current_section = "highlights"
            continue
        if "tip" in lower or "note" in lower or "consider" in lower or "practical" in lower:
            current_section = "notes"
            continue
        if "overview" in lower or "vibe" in lower or "theme" in lower:
            current_section = "vibe"
            continue

        # Extract list items
        list_match = re.match(r"^[-•*]\s*(.+)$", stripped)
        numbered_match = re.match(r"^\d+[.)]\s*(.+)$", stripped)
        item_text = None

        if list_match:
            item_text = list_match.group(1).strip()
        elif numbered_match:
            item_text = numbered_match.group(1).strip()

        if item_text:
            if current_section == "flow":
                content.flow.append(item_text)
            elif current_section == "highlights":
                content.highlights.append(item_text)
            elif current_section == "notes":
                content.notes.append(item_text)
        elif current_section == "vibe" and not content.vibe:
            # Capture first non-header line as vibe
            content.vibe = stripped[:100]
        elif not first_paragraph_captured and len(stripped) > 30:
            # Capture first substantive paragraph as vibe/focus
            if not content.vibe:
                content.vibe = stripped[:100]
            elif not content.focus:
                content.focus = stripped[:150]
            first_paragraph_captured = True

    # Limit items
    content.highlights = content.highlights[:5]
    content.flow = content.flow[:5]
    content.notes = content.notes[:4]

    return content


async def call_strategy_for_plan(
    state: "GraphState",
    topic: str,
) -> StrategyResult:
    """
    Call a strategy node to generate content for plan generation.

    Uses a simplified LLM call to get strategy content without full stage logic.
    """
    from app.config import settings
    from app.plan_graph import STRATEGY_REGISTRY, load_prompt
    from app.planner.streaming import call_llm_streaming_with_json_field

    try:
        # Get prompt for this topic
        prompt_name = STRATEGY_REGISTRY.get(topic)
        if not prompt_name:
            return StrategyResult(topic=topic, success=False, error=f"Unknown topic: {topic}")

        prompt = load_prompt(prompt_name)

        # Build minimal context
        destinations = state.trip_inputs.destinations or []
        dest_str = ", ".join(destinations) if destinations else "their chosen destination"
        dates_str = ""
        if state.trip_inputs.start_date and state.trip_inputs.end_date:
            dates_str = f" from {state.trip_inputs.start_date} to {state.trip_inputs.end_date}"

        # Add destination context to prompt
        context = (
            f"\n\nCONTEXT FOR PLAN GENERATION:\n"
            f"Destination: {dest_str}{dates_str}\n"
            f"Generate a {topic} plan with:\n"
            f"1. A short vibe/theme (1 sentence)\n"
            f"2. 3-5 key highlights\n"
            f"3. Day-by-day flow (3-5 days)\n"
            f"4. 3-4 practical tips/notes\n"
        )

        messages = [
            {"role": "system", "content": prompt + context},
            {"role": "user", "content": f"Generate a {topic} plan for {dest_str}"},
        ]

        # Call LLM
        response_text = ""
        async for chunk in call_llm_streaming_with_json_field(
            messages=messages,
            model=settings.llm_specialist_model,
            max_tokens=768,
            json_field=None,  # Plain text response
            timeout=settings.llm_timeout_specialist,
        ):
            if isinstance(chunk, str):
                response_text += chunk

        # Parse response
        content = parse_strategy_response(response_text, topic)

        return StrategyResult(topic=topic, success=True, content=content)

    except Exception as e:
        _debug(f"Strategy {topic} call failed", error=str(e))
        return StrategyResult(topic=topic, success=False, error=str(e))


async def orchestrate_strategies(state: "GraphState") -> Dict[str, StrategyResult]:
    """
    Orchestrate strategy node calls for plan generation.

    Detects relevant topics from activity_settings and calls strategies in parallel.
    Returns dict of topic -> StrategyResult.
    """
    topics = detect_relevant_strategies(state)

    if not topics:
        _debug("No relevant strategies detected for trip inputs")
        return {}

    _debug(f"Orchestrating strategies for topics: {topics}")

    # Call strategies in parallel
    tasks = [call_strategy_for_plan(state, topic) for topic in topics]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build results dict
    output: Dict[str, StrategyResult] = {}
    for topic, result in zip(topics, results, strict=True):
        if isinstance(result, Exception):
            output[topic] = StrategyResult(topic=topic, success=False, error=str(result))
        else:
            output[topic] = result

    return output


def merge_strategy_results(results: Dict[str, StrategyResult]) -> StrategyContent:
    """
    Merge multiple strategy results into a single content object.

    Uses first successful result for vibe/focus, combines highlights/flow/notes.
    """
    merged = StrategyContent(topic="combined")

    for _topic, result in results.items():
        if not result.success or not result.content:
            continue

        content = result.content

        # Use first non-empty vibe/focus
        if not merged.vibe and content.vibe:
            merged.vibe = content.vibe
        if not merged.focus and content.focus:
            merged.focus = content.focus

        # Combine lists (limit to avoid overflow)
        for highlight in content.highlights[:2]:
            if len(merged.highlights) < 5:
                merged.highlights.append(highlight)

        for flow_item in content.flow:
            if len(merged.flow) < 5:
                merged.flow.append(flow_item)

        for note in content.notes[:2]:
            if len(merged.notes) < 4:
                merged.notes.append(note)

    return merged
