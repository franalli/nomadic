"""
Strategy Node Orchestrator - Calls relevant strategy nodes for plan generation.

Used by generate_responder to enrich branches with strategy content:
- Detects relevant strategy topics from activity_settings.categories
- Calls strategy nodes for each topic
- Parses LLM responses into structured content (vibe, highlights, flow, notes)
"""

from __future__ import annotations

import asyncio
import json
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
    # General categories (fallback to general strategy)
    "sightseeing": "general",
    "culture": "general",
    "food": "general",
    "relaxation": "general",
    "beach": "general",
    "city": "general",
    "shopping": "general",
    "nightlife": "general",
    "tours": "general",
    "experiences": "general",
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

    Returns list of topic names (hiking, diving, skiing, cycling, boating, general).
    Falls back to 'general' if no specific strategies are detected, ensuring
    all trips get vibe/highlights/flow content.
    """
    topics: set[str] = set()

    activity_settings = state.trip_inputs.activity_settings
    if activity_settings:
        # Handle both dict and object access (activity_settings can be either)
        if isinstance(activity_settings, dict):
            categories = activity_settings.get("categories", []) or []
        else:
            categories = activity_settings.categories or []

        for category in categories:
            category_lower = category.lower().strip()
            if category_lower in CATEGORY_TO_STRATEGY:
                topics.add(CATEGORY_TO_STRATEGY[category_lower])

    # Always include 'general' as fallback if no specific strategies found
    # This ensures all trips get vibe/highlights/flow content
    if not topics:
        topics.add("general")

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
    Call a strategy node to generate content for plan generation (Stage 2 tier).

    Uses FULL tier (1536 tokens) to get rich strategy content for branch population.
    Parses JSON response from LLM, with markdown fallback.
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

        # Build rich context for Stage 2 tier
        ti = state.trip_inputs
        destinations = ti.destinations or []
        dest_str = ", ".join(destinations) if destinations else "their chosen destination"

        # Date and duration context
        dates_str = ""
        duration_str = ""
        if ti.start_date and ti.end_date:
            dates_str = f"Travel dates: {ti.start_date} to {ti.end_date}"
            # Calculate duration
            try:
                from datetime import datetime

                start = datetime.strptime(ti.start_date, "%Y-%m-%d")
                end = datetime.strptime(ti.end_date, "%Y-%m-%d")
                days = (end - start).days + 1
                duration_str = f"Duration: {days} days"
            except (ValueError, TypeError):
                pass

        # Budget context
        budget_str = ""
        if ti.budget:
            currency = ti.currency or "USD"
            budget_str = f"Budget: {ti.budget} {currency}"

        # Travelers context
        travelers_str = ""
        adults = ti.adults or 1
        children = ti.children or 0
        if children > 0:
            travelers_str = f"Travelers: {adults} adult(s), {children} child(ren)"
        else:
            travelers_str = f"Travelers: {adults} adult(s)"

        # Activity preferences context
        activity_prefs = ""
        if ti.activity_settings:
            as_dict = (
                ti.activity_settings
                if isinstance(ti.activity_settings, dict)
                else ti.activity_settings.model_dump()
            )
            categories = as_dict.get("categories", [])
            if categories:
                activity_prefs = f"Activity interests: {', '.join(categories)}"

        # Build comprehensive context for FULL tier (Stage 2)
        context_parts = [
            f"\n\n{'='*40}",
            "CONTEXT FOR PLAN GENERATION (STAGE 2 - FULL DETAIL)",
            f"{'='*40}",
            f"Destination: {dest_str}",
        ]
        if dates_str:
            context_parts.append(dates_str)
        if duration_str:
            context_parts.append(duration_str)
        if budget_str:
            context_parts.append(budget_str)
        if travelers_str:
            context_parts.append(travelers_str)
        if activity_prefs:
            context_parts.append(activity_prefs)

        context_parts.extend(
            [
                "",
                "Generate a DETAILED plan with:",
                "1. A compelling vibe/theme (1 evocative sentence)",
                "2. Focus: What makes this trip special (1-2 sentences)",
                "3. 3-5 specific highlights (actual experiences, not generic activities)",
                "4. Day-by-day flow matching trip duration (be specific about each day)",
                "5. 3-4 practical on-the-ground tips",
                "",
                "IMPORTANT: Output valid JSON with vibe, focus, highlights, flow, notes fields.",
            ]
        )

        context = "\n".join(context_parts)

        system_prompt = prompt + context
        user_message = f"Generate a detailed {topic} plan for {dest_str}"

        # Call LLM with FULL tier token budget (1536)
        response_text = await call_llm_streaming_with_json_field(
            model=settings.llm_specialist_model,
            prompt=system_prompt,
            stream_field="",  # Empty string - no field streaming needed
            max_tokens=1536,  # FULL tier for Stage 2
            user_message=user_message,
            timeout_seconds=settings.llm_timeout_specialist,
        )

        # Parse JSON response (primary path)
        content = _parse_json_strategy_response(response_text, topic)

        _debug(
            "Strategy plan generated",
            topic=topic,
            has_vibe=bool(content.vibe),
            has_focus=bool(content.focus),
            highlights_count=len(content.highlights),
            flow_count=len(content.flow),
            notes_count=len(content.notes),
        )

        return StrategyResult(topic=topic, success=True, content=content)

    except Exception as e:
        _debug(f"Strategy {topic} call failed", error=str(e))
        return StrategyResult(topic=topic, success=False, error=str(e))


def _parse_json_strategy_response(response_text: str, topic: str) -> StrategyContent:
    """
    Parse strategy LLM response, trying JSON first then markdown fallback.

    The strategy prompts output JSON with vibe, focus, highlights, flow, notes fields.
    """
    # Try to extract JSON from response (may be wrapped in markdown code blocks)
    json_text = response_text.strip()

    # Remove markdown code block wrapper if present
    if json_text.startswith("```"):
        # Find the end of the code block
        lines = json_text.split("\n")
        # Skip first line (```json or ```) and find closing ```
        json_lines = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            if line.startswith("```") and in_block:
                break
            if in_block:
                json_lines.append(line)
        json_text = "\n".join(json_lines)

    # Try JSON parsing
    try:
        parsed = json.loads(json_text)

        # Extract fields from JSON response
        content = StrategyContent(
            topic=topic,
            vibe=parsed.get("vibe", "") or "",
            focus=parsed.get("focus", "") or "",
            highlights=parsed.get("highlights", []) or [],
            flow=parsed.get("flow", []) or [],
            notes=parsed.get("notes", []) or [],
        )

        # Ensure lists contain strings
        content.highlights = [str(h) for h in content.highlights if h][:5]
        content.flow = [str(f) for f in content.flow if f][:7]  # Allow up to 7 for longer trips
        content.notes = [str(n) for n in content.notes if n][:4]

        _debug(
            "Strategy JSON parsed successfully",
            topic=topic,
            vibe_preview=content.vibe[:50] if content.vibe else None,
        )

        return content

    except json.JSONDecodeError as e:
        _debug(
            "Strategy JSON parse failed, falling back to markdown parsing",
            topic=topic,
            error=str(e),
            response_preview=response_text[:200],
        )
        # Fallback to markdown parsing
        return parse_strategy_response(response_text, topic)


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
