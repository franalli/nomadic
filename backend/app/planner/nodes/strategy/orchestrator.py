"""
Strategy Node Orchestrator - Calls relevant strategy nodes for plan generation.

Used by generate_responder to enrich branches with strategy content:
- Detects relevant strategy topics from multiple sources (categories, message intent)
- Calls strategy nodes for each topic (capped to avoid latency/cost overrun)
- Parses LLM responses into structured content for UI cards
- Returns one StrategyResult per topic (no merging)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from app.debug_utils import _debug

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# Topic priority for stable ordering (higher priority = lower index)
TOPIC_PRIORITY: List[str] = ["skiing", "hiking", "diving", "boating", "cycling", "general"]

# Valid specialist topics (excludes "general" which is fallback only)
SPECIALIST_TOPICS: Set[str] = {"skiing", "hiking", "diving", "boating", "cycling"}

# Keywords for detecting topics from user message intent
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "hiking": ["hike", "hiking", "trek", "trekking", "trail", "trails", "mountain", "mountains"],
    "diving": ["dive", "diving", "scuba", "snorkel", "snorkeling", "underwater", "reef"],
    "skiing": ["ski", "skiing", "snowboard", "snowboarding", "slopes", "piste"],
    "boating": ["sail", "sailing", "boat", "boating", "yacht", "kayak", "kayaking"],
    "cycling": ["bike", "biking", "cycle", "cycling", "bicycle"],
}

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
    """Structured content from strategy node - directly populates UI card."""

    topic: str

    # Legacy fields (still used by other consumers)
    vibe: str = ""
    focus: str = ""
    highlights: List[str] = field(default_factory=list)
    flow: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # NEW: UI card fields - populated BY THE NODE, not derived downstream
    one_liner: str = ""  # Single sentence capturing trip essence (max 80 chars)
    principles: List[str] = field(
        default_factory=list
    )  # Core approach chips (2-4 items, max 50 chars each)
    must_dos: List[str] = field(default_factory=list)  # Essential experiences (3-5 items)
    optional_upgrades: List[str] = field(default_factory=list)  # Nice-to-haves (2-3 items)
    logistics_notes: List[str] = field(default_factory=list)  # Practical tips (2-4 items)
    tradeoffs_summary: str = ""  # Why this approach (1 paragraph, max 300 chars)

    # Provenance for debugging (hidden in UI by default)
    strategy_node_id: str = ""  # e.g., "hiking_strategist_v1"
    strategy_version: str = ""  # Prompt/logic version


@dataclass
class StrategyResult:
    """Result from a single strategy node execution."""

    topic: str
    success: bool
    content: Optional[StrategyContent] = None
    error: Optional[str] = None


def _detect_topics_from_message(user_text: str) -> Set[str]:
    """Detect strategy topics from user message intent."""
    topics: Set[str] = set()
    text_lower = user_text.lower()

    for topic, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                topics.add(topic)
                break  # Found this topic, move to next

    return topics


def detect_relevant_strategies(
    state: "GraphState",
    max_inferred: int = 2,
    max_explicit: int = 3,
) -> List[str]:
    """
    Detect which strategy topics are relevant from multiple sources.

    Sources (union with deduplication):
    1. Forced topics from re-orchestration (takes precedence)
    2. Explicit categories from activity_settings.categories (UI selection)
    3. Inferred topics from user message intent
    4. (Future) Activity shortlist contents

    Returns list of topic names sorted by TOPIC_PRIORITY.
    Falls back to 'general' only if no specialist topics detected.

    Topic budget rules:
    - If user explicitly selected categories: allow up to max_explicit (default 3)
    - If inferred only: allow up to max_inferred (default 2)
    - General is never stacked alongside specialists
    """
    # Check for forced topics from re-orchestration (PR1 Step 4)
    # When adding topics to existing plan, force_strategy_topics overrides detection
    forced_topics = state.metadata.get("force_strategy_topics") if state.metadata else None
    if forced_topics:
        _debug("Using forced strategy topics from re-orchestration", topics=forced_topics)
        # Clear the force flag after use to avoid persistence issues
        state.metadata["force_strategy_topics"] = None
        return forced_topics

    explicit_topics: Set[str] = set()
    inferred_topics: Set[str] = set()

    # Source 1: Explicit categories from activity_settings
    activity_settings = state.trip_inputs.activity_settings
    if activity_settings:
        if isinstance(activity_settings, dict):
            categories = activity_settings.get("categories", []) or []
        else:
            categories = activity_settings.categories or []

        for category in categories:
            category_lower = category.lower().strip()
            if category_lower in CATEGORY_TO_STRATEGY:
                mapped = CATEGORY_TO_STRATEGY[category_lower]
                if mapped != "general":  # Don't count general as explicit
                    explicit_topics.add(mapped)

    # Source 2: Inferred from user message
    user_text = state.metadata.get("user_text", "") or ""
    if user_text:
        inferred_topics = _detect_topics_from_message(user_text)

    # Union all topics (explicit takes precedence)
    all_topics = explicit_topics | inferred_topics

    # Filter out "general" - it's only used as fallback
    specialist_topics = {t for t in all_topics if t in SPECIALIST_TOPICS}

    # Apply topic budget
    if explicit_topics:
        # User explicitly selected - allow more
        budget = max_explicit
    else:
        # Inferred only - be conservative
        budget = max_inferred

    # Sort by priority and apply budget
    sorted_topics = sorted(
        specialist_topics,
        key=lambda t: TOPIC_PRIORITY.index(t) if t in TOPIC_PRIORITY else 999,
    )
    final_topics = sorted_topics[:budget]

    # Fallback to general only if no specialists
    if not final_topics:
        final_topics = ["general"]

    _debug(
        "Strategy topics detected",
        explicit=list(explicit_topics),
        inferred=list(inferred_topics),
        final=final_topics,
        budget=budget,
    )

    return final_topics


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


def _validate_strategy_content(content: StrategyContent) -> StrategyContent:
    """
    Quality gates: ensure fields meet minimum requirements and char limits.

    Applies:
    - Character limits per field
    - Minimum count fallbacks
    - Truncation for oversized content
    """
    # Character limits
    if content.one_liner:
        content.one_liner = content.one_liner[:80]
    if content.tradeoffs_summary:
        content.tradeoffs_summary = content.tradeoffs_summary[:300]

    # List field limits
    content.principles = [p[:50] for p in content.principles[:4]]
    content.must_dos = [m[:110] for m in content.must_dos[:5]]
    content.optional_upgrades = [o[:110] for o in content.optional_upgrades[:3]]
    content.logistics_notes = [n[:110] for n in content.logistics_notes[:4]]

    # Legacy field limits
    content.highlights = content.highlights[:5]
    content.flow = content.flow[:7]
    content.notes = content.notes[:4]

    # Quality fallbacks: if new fields are empty, derive from legacy
    if not content.one_liner and content.vibe:
        content.one_liner = content.vibe[:80]

    if len(content.principles) < 2 and content.flow:
        content.principles = [f[:50] for f in content.flow[:3]]

    if len(content.must_dos) < 3 and content.highlights:
        content.must_dos = content.highlights[:5]

    if len(content.logistics_notes) < 2 and content.notes:
        content.logistics_notes = content.notes[:4]

    if not content.tradeoffs_summary and content.focus:
        content.tradeoffs_summary = content.focus[:300]

    return content


def _parse_json_strategy_response(response_text: str, topic: str) -> StrategyContent:
    """
    Parse strategy LLM response, trying JSON first then markdown fallback.

    Extracts both legacy fields (vibe, focus, highlights, flow, notes) and
    new UI card fields (one_liner, principles, must_dos, optional_upgrades,
    logistics_notes, tradeoffs_summary) with fallbacks for backward compatibility.
    """
    # Try to extract JSON from response (may be wrapped in markdown code blocks)
    json_text = response_text.strip()

    # Remove markdown code block wrapper if present
    if json_text.startswith("```"):
        lines = json_text.split("\n")
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

        # Extract legacy fields (always present in old responses)
        vibe = str(parsed.get("vibe", "") or "")
        focus = str(parsed.get("focus", "") or "")
        highlights = [str(h) for h in (parsed.get("highlights") or []) if h]
        flow = [str(f) for f in (parsed.get("flow") or []) if f]
        notes = [str(n) for n in (parsed.get("notes") or []) if n]

        # Extract NEW UI card fields (may not be present in old cached responses)
        one_liner = str(parsed.get("one_liner", "") or "")
        principles = [str(p) for p in (parsed.get("principles") or []) if p]
        must_dos = [str(m) for m in (parsed.get("must_dos") or []) if m]
        optional_upgrades = [str(o) for o in (parsed.get("optional_upgrades") or []) if o]
        logistics_notes = [str(n) for n in (parsed.get("logistics_notes") or []) if n]
        tradeoffs_summary = str(parsed.get("tradeoffs_summary", "") or "")

        content = StrategyContent(
            topic=topic,
            # Legacy fields
            vibe=vibe,
            focus=focus,
            highlights=highlights,
            flow=flow,
            notes=notes,
            # New UI card fields
            one_liner=one_liner,
            principles=principles,
            must_dos=must_dos,
            optional_upgrades=optional_upgrades,
            logistics_notes=logistics_notes,
            tradeoffs_summary=tradeoffs_summary,
            # Provenance
            strategy_node_id=f"{topic}_strategist_v1",
            strategy_version="1.0",
        )

        # Apply quality gates and fallbacks
        content = _validate_strategy_content(content)

        _debug(
            "Strategy JSON parsed successfully",
            topic=topic,
            one_liner_preview=content.one_liner[:40] if content.one_liner else None,
            must_dos_count=len(content.must_dos),
            principles_count=len(content.principles),
        )

        return content

    except json.JSONDecodeError as e:
        _debug(
            "Strategy JSON parse failed, falling back to markdown parsing",
            topic=topic,
            error=str(e),
            response_preview=response_text[:200],
        )
        # Fallback to markdown parsing, then apply validation
        content = parse_strategy_response(response_text, topic)
        content.strategy_node_id = f"{topic}_strategist_v1"
        content.strategy_version = "1.0"
        content = _validate_strategy_content(content)
        return content


async def orchestrate_strategies(state: "GraphState") -> List[StrategyResult]:
    """
    Orchestrate strategy node calls for plan generation.

    Detects relevant topics from multiple sources, applies topic budget,
    and calls strategies in parallel.

    Returns List[StrategyResult] - one per executed topic, NOT merged.
    Failed topics are excluded (no empty cards in UI).
    Results are sorted by TOPIC_PRIORITY for stable ordering.
    """
    topics = detect_relevant_strategies(state)

    if not topics:
        _debug("No relevant strategies detected for trip inputs")
        return []

    _debug(f"Orchestrating strategies for topics: {topics}")

    # Call strategies in parallel
    tasks = [call_strategy_for_plan(state, topic) for topic in topics]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter to successful results only (failed topics = no card in UI)
    successful_results: List[StrategyResult] = []
    for topic, result in zip(topics, raw_results, strict=True):
        if isinstance(result, Exception):
            _debug(f"Strategy {topic} failed with exception", error=str(result))
            continue
        if not result.success:
            _debug(f"Strategy {topic} returned failure", error=result.error)
            continue
        successful_results.append(result)

    # Sort by TOPIC_PRIORITY for stable ordering
    successful_results.sort(
        key=lambda r: TOPIC_PRIORITY.index(r.topic) if r.topic in TOPIC_PRIORITY else 999
    )

    _debug(
        "Strategy orchestration complete",
        requested=topics,
        successful=[r.topic for r in successful_results],
    )

    return successful_results


# Legacy function - kept for backward compatibility with existing code
async def orchestrate_strategies_dict(state: "GraphState") -> Dict[str, StrategyResult]:
    """
    Legacy wrapper that returns dict format for backward compatibility.

    Prefer orchestrate_strategies() which returns List[StrategyResult].
    """
    results = await orchestrate_strategies(state)
    return {r.topic: r for r in results}


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
