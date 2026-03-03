"""
Conversationalist -- generates the assistant response via a single streaming LLM call.

The conversationalist is the final step in the coordinator pipeline. It receives
the full trip state (including specialist plans, tiles, day_cards) and the
classifier output, then produces a natural-language response streamed token by
token.

The system prompt encodes trip context, specialist findings, turn context,
itinerary status, and conversational quality rules so the LLM responds like
a knowledgeable travel agent rather than a generic chatbot.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.planner.llm_factory import get_llm_by_model

if TYPE_CHECKING:
    from app.planner.schemas.coordinator_schemas import ClassifierOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RESPONSE_TEMPERATURE: float = 0.6
_RESPONSE_MAX_TOKENS: int = 600


# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------


def _build_trip_context_block(state: Dict[str, Any]) -> str:
    """Build the current-trip-context section of the system prompt."""
    trip_plan: Dict[str, Any] = state.get("trip_plan", {})
    trip_settings: Dict[str, Any] = state.get("trip_settings", {})

    parts: List[str] = []

    destination = trip_plan.get("destination")
    if destination:
        parts.append(f"Destination: {destination}")

    start = trip_plan.get("start_date")
    end = trip_plan.get("end_date")
    if start and end:
        parts.append(f"Dates: {start} to {end}")
        try:
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
            duration = (e - s).days + 1
            parts.append(f"Trip duration: {duration} days (ends {e.strftime('%B %d')})")
        except ValueError:
            pass
    elif start:
        parts.append(f"Start date: {start}")

    if start:
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d").date()
            days_until = (start_dt - date.today()).days
            if days_until > 0:
                if days_until <= 14:
                    parts.append(f"Trip is in {days_until} days — booking urgency is HIGH")
                elif days_until <= 30:
                    parts.append(f"Trip is {days_until} days away — moderate planning window")
                parts.append(f"Start day: {start_dt.strftime('%A')}")
        except ValueError:
            pass

    adults = trip_plan.get("adults")
    children = trip_plan.get("children")
    if adults:
        traveler_str = f"{adults} adult{'s' if adults != 1 else ''}"
        if children:
            traveler_str += f", {children} child{'ren' if children != 1 else ''}"
        parts.append(f"Travelers: {traveler_str}")

    budget = trip_plan.get("budget")
    currency = trip_plan.get("currency", "USD")
    if budget:
        parts.append(f"Budget: {currency} {budget:,.0f}")

    origin = trip_plan.get("origin")
    if origin:
        parts.append(f"Origin: {origin}")

    vibe = trip_plan.get("vibe")
    if vibe:
        parts.append(f"Trip vibe: {vibe}")

    # Activity pacing / skill / accommodation preferences
    activity_settings = trip_settings.get("activity_settings", {})
    apd = activity_settings.get("activities_per_day")
    if apd:
        pace_label = {1: "relaxed", 2: "moderate", 3: "packed"}.get(apd, f"{apd}/day")
        parts.append(f"Pace: {pace_label} ({apd} activities/day)")

    skill_level = activity_settings.get("skill_level")
    if skill_level and skill_level != "beginner":
        parts.append(f"Skill level: {skill_level}")

    hotel_settings = trip_settings.get("hotel_settings", {})
    hotel_style = hotel_settings.get("style")
    hotel_stars = hotel_settings.get("min_stars")
    if hotel_style:
        parts.append(f"Hotel preference: {hotel_style}")
    elif hotel_stars and hotel_stars > 0:
        parts.append(f"Hotel preference: {hotel_stars}+ stars")

    flight_settings = trip_settings.get("flight_settings", {})
    cabin_class = flight_settings.get("cabin_class")
    if cabin_class and cabin_class != "economy":
        parts.append(f"Flight class: {cabin_class.replace('_', ' ')}")

    # Activity categories
    categories: List[str] = activity_settings.get("categories", [])
    if categories:
        parts.append(f"Activities: {', '.join(c.title() for c in categories)}")

    booking_types = trip_settings.get("booking_types", {})
    disabled = [k for k in ("flights", "hotels", "activities") if booking_types.get(k) == "off"]
    if disabled:
        parts.append(f"Disabled: {', '.join(disabled)} (user turned off)")

    day_prefs = activity_settings.get("day_preferences", {})
    if day_prefs:
        pref_parts = [f"{k}: {v} day{'s' if v != 1 else ''}" for k, v in day_prefs.items()]
        parts.append(f"Day allocation: {', '.join(pref_parts)}")

    if not parts:
        return ""

    return "## Current Trip\n" + "\n".join(f"- {p}" for p in parts)


def _build_specialist_findings_block(
    state: Dict[str, Any],
    classifier: ClassifierOutput | None = None,
) -> str:
    """Build the specialist findings section.

    Tries the coordinator path (``strategy_sections``) first, then falls
    back to the legacy agent path (``specialist_plans``).
    """
    strategy_sections: List[Any] = state.get("strategy_sections", [])
    if strategy_sections:
        return _build_from_strategy_sections(strategy_sections, classifier)

    specialist_plans: Dict[str, Any] = state.get("specialist_plans", {})
    if specialist_plans:
        return _build_from_specialist_plans(specialist_plans)

    return ""


def _build_from_strategy_sections(
    sections: List[Any],
    classifier: ClassifierOutput | None = None,
) -> str:
    """Build specialist findings from coordinator strategy_sections."""
    affected_set = set(classifier.affects) if classifier and classifier.affects else set()
    blocks: List[str] = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        topic = s.get("specialist_type", "unknown")
        # Handle local_expert separately — destination-level, not specialist-scoped
        if topic == "local_expert":
            lines: List[str] = []
            # Constraints from local expert
            constraints = s.get("constraints_applied", [])
            if constraints:
                lines.append("**Local Expert Warnings**")
                for c in constraints[:3]:
                    if isinstance(c, dict):
                        lines.append(f"  - {c.get('rule', '')}")
            # Travel intelligence (visa, weather, safety, transport)
            ti = s.get("travel_intelligence", {})
            if isinstance(ti, dict) and ti:
                if not lines:
                    lines.append("**Local Expert Intel**")
                for category, items in ti.items():
                    if isinstance(items, list) and items:
                        lines.append(f"  - {category.replace('_', ' ').title()}: {items[0]}")
            if lines:
                blocks.append("\n".join(lines))
            continue

        parts: List[str] = [f"**{topic.replace('_', ' ').title()}**"]

        feasibility = s.get("feasibility_status")
        if feasibility and feasibility != "feasible":
            parts.append(f"  - Status: {feasibility}")
            reason = s.get("feasibility_reason", "")
            if reason:
                parts.append(f"  - Why: {reason}")
        elif feasibility == "feasible" and s.get("feasibility_reason"):
            parts.append(f"  - Note: {s['feasibility_reason']}")

        # Constraints — richest signal for voice
        constraints = s.get("constraints_applied", [])
        for c in constraints[:3]:
            if isinstance(c, dict):
                rule = c.get("rule", "")
                severity = c.get("severity", "")
                prefix = "\u26d4" if severity == "blocking" else "\u26a0\ufe0f"
                relevant = topic in affected_set
                marker = " [RELEVANT to this turn]" if relevant else ""
                parts.append(f"  - {prefix} {rule}{marker}")

        # Activities placed on itinerary
        content = s.get("content_added", [])
        for item in content[:3]:
            if isinstance(item, dict):
                title = item.get("title", "")
                desc = (item.get("description") or "")[:150]
                duration = item.get("duration_hours")
                dur_str = f" ({duration}h)" if duration else ""
                parts.append(f"  - Activity: {title}{dur_str} — {desc}")

        # Travel intelligence (visa, weather, safety, transport)
        ti = s.get("travel_intelligence", {})
        if isinstance(ti, dict) and ti:
            for category, items in ti.items():
                if isinstance(items, list) and items:
                    parts.append(f"  - {category.replace('_', ' ').title()}: {items[0]}")

        blocks.append("\n".join(parts))

    return "## Specialist Findings\n" + "\n\n".join(blocks) if blocks else ""


def _build_from_specialist_plans(specialist_plans: Dict[str, Any]) -> str:
    """Build specialist findings from legacy agent-path specialist_plans."""
    blocks: List[str] = []
    for topic, plan_dict in specialist_plans.items():
        if not plan_dict or not isinstance(plan_dict, dict):
            continue

        feasibility = plan_dict.get("feasibility_status", "feasible")
        day_plans = plan_dict.get("day_plans", [])
        activity_count = len(day_plans)
        editorial = plan_dict.get("editorial", "")

        parts: List[str] = [f"**{topic.title()}**"]
        parts.append(f"  - Status: {feasibility}")
        if activity_count:
            parts.append(f"  - Activities planned: {activity_count}")

        # Extract key locations from day plans
        locations: List[str] = []
        for dp in day_plans[:5]:
            loc = dp.get("location") or dp.get("title")
            if loc and loc not in locations:
                locations.append(loc)
        if locations:
            parts.append(f"  - Key locations: {', '.join(locations[:3])}")

        # Constraints
        constraints = plan_dict.get("constraints", [])
        if constraints:
            constraint_labels = [
                c.get("label") or c.get("reason", "")
                for c in constraints[:2]
                if isinstance(c, dict)
            ]
            constraint_labels = [c for c in constraint_labels if c]
            if constraint_labels:
                parts.append(f"  - Constraints: {'; '.join(constraint_labels)}")

        if editorial:
            parts.append(f"  - Insight: {editorial}")

        # Feasibility reason for conditional/infeasible
        if feasibility != "feasible":
            reason = plan_dict.get("feasibility_reason", "")
            if reason:
                parts.append(f"  - Reason: {reason}")

        blocks.append("\n".join(parts))

    if not blocks:
        return ""

    return "## Specialist Findings\n" + "\n\n".join(blocks)


def _detect_user_energy(user_message: str) -> str:
    """Classify user energy from keywords. No LLM call.

    Uncertain is checked first so ``"maybe!"`` resolves to uncertain,
    not enthusiastic.  Word-boundary checks avoid false positives like
    ``"gloves"`` matching ``"love"``.
    """
    lower = user_message.lower()
    # Strip trailing punctuation from each word for accurate set matching
    words = {w.strip("!?.,:;") for w in lower.split()}
    # Check uncertain first — hedging signals outweigh punctuation enthusiasm
    _UNCERTAIN = {"confused", "complicated", "ugh", "hmm", "maybe"}
    _UNCERTAIN_PHRASES = ("too many", "not sure")
    if words & _UNCERTAIN or any(p in lower for p in _UNCERTAIN_PHRASES):
        return "uncertain"
    _ENTHUSIASTIC = {"love", "perfect", "awesome", "yes", "amazing", "definitely"}
    if words & _ENTHUSIASTIC or "!" in lower:
        return "enthusiastic"
    if len(words) <= 4:
        return "terse"
    return ""


def _build_turn_context_block(
    classifier: ClassifierOutput,
    user_message: str = "",
) -> str:
    """Build the turn context section from the classifier output."""
    parts: List[str] = []

    parts.append(f"Intent: {classifier.intent}")
    parts.append(f"Change type: {classifier.change_type.value}")

    if classifier.affects:
        parts.append(f"Affected specialists: {', '.join(classifier.affects)}")

    if classifier.preserves:
        parts.append(f"Preserved specialists: {', '.join(classifier.preserves)}")

    if classifier.fields_changed:
        parts.append(f"Fields changed: {', '.join(classifier.fields_changed)}")

    if user_message:
        energy = _detect_user_energy(user_message)
        if energy:
            parts.append(f"User energy: {energy}")

    return "## This Turn\n" + "\n".join(f"- {p}" for p in parts)


def _build_outcome_block(state: Dict[str, Any]) -> str:
    """What the system did this turn — so the LLM can confirm or caveat honestly."""
    day_cards: List[Any] = state.get("day_cards", [])
    if not day_cards:
        return ""

    parts: List[str] = []

    # Count real activities (exclude arrival/departure/free_day/buffer)
    total_activities = 0
    free_days = 0
    for dc in day_cards:
        dc_dict = (
            dc if isinstance(dc, dict) else (dc.model_dump() if hasattr(dc, "model_dump") else {})
        )
        blocks = dc_dict.get("blocks", [])
        day_has_activity = False
        for b in blocks:
            b_dict = (
                b if isinstance(b, dict) else (b.model_dump() if hasattr(b, "model_dump") else {})
            )
            if b_dict.get("is_buffer"):
                continue
            name = (b_dict.get("summary") or b_dict.get("activity_type") or "").lower()
            if name not in ("arrival", "departure", "free day", ""):
                total_activities += 1
                day_has_activity = True
        if not day_has_activity:
            free_days += 1

    parts.append(
        f"Itinerary: {len(day_cards)} days, {total_activities} activities placed, "
        f"{free_days} empty days"
    )

    # Density (skip for very short trips where the metric is misleading)
    if total_activities and len(day_cards) > 3:
        usable_days = max(1, len(day_cards) - 2)  # minus arrival/departure
        apd = round(total_activities / usable_days, 1)
        parts.append(f"Density: ~{apd} activities/day")

    # Hotel selection — tiles are category-keyed: {"hotels": [...], ...}
    tiles = state.get("tiles", {})
    if isinstance(tiles, dict):
        hotel_tiles = tiles.get("hotels", [])
        if isinstance(hotel_tiles, list):
            for tile in hotel_tiles:
                t = (
                    tile
                    if isinstance(tile, dict)
                    else (tile.model_dump() if hasattr(tile, "model_dump") else {})
                )
                if t.get("selected"):
                    name = t.get("title", "Unknown")
                    stars = t.get("stars") or t.get("meta", {}).get("stars")
                    star_str = f" ({stars}★)" if stars else ""
                    parts.append(f"Hotel: {name}{star_str}")
                    break

    # Hotel filter fallback — warn the LLM so it can inform the user
    turn_meta: Dict[str, Any] = state.get("turn_meta", {})
    if turn_meta.get("hotel_filter_empty"):
        min_stars = turn_meta.get("hotel_filter_min_stars", "?")
        cascade = turn_meta.get("hotel_filter_cascaded")
        actual_stars = cascade.get("actual", 0) if isinstance(cascade, dict) else 0
        if actual_stars and actual_stars > 0:
            parts.append(
                f"REQUIRED: Tell the user no {min_stars}-star hotels were found, "
                f"so you're showing {actual_stars}+ star hotels instead. "
                "Suggest they try adjusting their star rating."
            )
        else:
            parts.append(
                f"REQUIRED: Tell the user their {min_stars}-star hotel filter "
                "matched no results, so you're showing all available hotels. "
                "Suggest they try a lower star rating."
            )

    return "## Outcome (what the system just did)\n" + "\n".join(f"- {p}" for p in parts)


def _build_itinerary_status_block(state: Dict[str, Any]) -> str:
    """Build itinerary summary with actual day highlights."""
    day_cards: List[Any] = state.get("day_cards", [])

    if not day_cards:
        strategy_sections = state.get("strategy_sections", [])
        if strategy_sections:
            topics = [
                s.get("specialist_type", "").title()
                for s in strategy_sections
                if isinstance(s, dict) and s.get("specialist_type")
            ]
            return f"## Itinerary\n- Not yet built. Strategy ready for: {', '.join(topics)}."
        return ""

    lines: List[str] = [f"## Itinerary ({len(day_cards)} days)"]
    free_count = 0

    for dc in day_cards:
        if not isinstance(dc, dict):
            if hasattr(dc, "model_dump"):
                dc = dc.model_dump()
            else:
                continue
        day_num = dc.get("day_number", "?")
        blocks = dc.get("blocks", [])

        activity_names: List[str] = []
        for b in blocks:
            if not isinstance(b, dict):
                if hasattr(b, "model_dump"):
                    b = b.model_dump()
                else:
                    continue
            if b.get("is_buffer"):
                continue
            name = b.get("summary") or b.get("activity_type") or ""
            specialist = b.get("specialist_type")
            if name and name.lower() not in ("arrival", "departure", "free day"):
                tag = f" [{specialist}]" if specialist else ""
                activity_names.append(f"{name}{tag}")

        if activity_names:
            lines.append(f"  Day {day_num}: {', '.join(activity_names[:2])}")
        else:
            free_count += 1

    if free_count:
        lines.append(f"  ({free_count} free days available to fill)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Voice architecture: intent-keyed response rules
# ---------------------------------------------------------------------------

_VOICE_BASE: str = """\
## Hard Rules (NEVER violate)
- NEVER say "Excellent choice", "Great choice", "Wonderful", "Fantastic".
- NEVER narrate system actions: "I've updated", "I've put together", "I'll start looking".
- NEVER promise future work: "I'll make sure to", "I'll also begin planning".
- NEVER end with "How does that sound?" or "Shall we...?" or any rhetorical question.
- NEVER list all days. Pick 1-2 highlights max.
- NEVER use bullet points or markdown formatting.
- NEVER generate markdown links [text](url). Write ALL text as plain text.
- NEVER hyperlink entity names. Mention them naturally in prose.
- NEVER repeat back information the user just typed.
- NEVER repeat any content shown in 'Already Said'. Find a NEW angle, constraint, or highlight.
- Use natural, confident language. You are an expert, not an assistant.
- Match the user's energy level. Enthusiastic users get vivid language. Uncertain users get reassurance and clarity. Terse users get equally terse responses.
- Reference SPECIFIC names, places, and constraints from the specialist data above.
- If specialist data is empty, be brief and direct — don't fabricate details.
- COUNT YOUR SENTENCES. If the voice rule says "2 MAX", write exactly 2 or fewer.
- NEVER repeat a constraint or warning you already mentioned in a previous message.\
"""

_VOICE_DESTINATION_SET: str = """\
## Voice: Destination Set
Sentence count: 1-2 MAX.
Lead with the single most distinctive thing about this destination.
If local expert constraints exist, weave in the most important one naturally.
Do NOT list activities. Do NOT promise what you'll do next.
Tone: confident local who knows the place.\
"""

_VOICE_DATES_SET: str = """\
## Voice: Dates Confirmed
Sentence count: 1-2 MAX.
Acknowledge dates in passing (not as the main event), then immediately surface
the #1 insight or constraint relevant to those specific dates.
The user can see the itinerary panel — don't describe it.
Tone: efficient expert confirming and adding value.\
"""

_VOICE_PLAN_GENERATED: str = """\
## Voice: Plan Generated / Rebuilt
Sentence count: 2 MAX. Target 30 words total.
1. Lead with the single boldest highlight or editorial opinion.
2. One actionable nudge — what to tweak, explore, or watch out for.
CRITICAL: Constraints, gear warnings, weather alerts, and booking reminders
are ALREADY displayed as tags on each day card. Do NOT repeat them.
Never list days. Never describe the plan. It's visible in the panel.
Tone: opinionated travel editor. Terse.\
"""

_VOICE_ACTIVITY_CHANGE: str = """\
## Voice: Activity Added/Removed/Swapped
Sentence count: 2 MAX. Target 25 words total.
Name what changed, then one implication or connection.
Constraints are shown as tags on day cards — do NOT repeat them.
Tone: collaborator adjusting together.\
"""

_VOICE_PREFERENCE_CHANGE: str = """\
## Voice: Preference / Settings Change
Sentence count: 1-2 MAX.
Acknowledge the change factually, then state any consequence.
Tone: concise confirmation.\
"""

_VOICE_QUESTION: str = """\
## Voice: Answering a Question
Answer the question directly and specifically using specialist data.
Then give one actionable follow-up or recommendation.
Never deflect with "it depends" without a concrete suggestion.
Sentence count: 2-3 depending on complexity.
Tone: knowledgeable friend who's been there.\
"""

_VOICE_GREETING: str = """\
## Voice: Greeting / Casual
Sentence count: 1 MAX.
Be warm but don't waste words. Move toward planning.
Example: "Hey! Where are we headed?"\
"""

_VOICE_FALLBACK: str = """\
## Voice: General
Sentence count: 2 MAX.
Be specific. Reference actual plan content. Have a point of view.
Never be generic. If you don't have specialist data, be brief and honest.\
"""

_VOICE_INFEASIBLE_ACTIVITY: str = """\
## Voice: Infeasible Activity
Sentence count: 2-3 MAX.
1. Lead with what's NOT possible and why, in one direct sentence.
2. Immediately pivot to the best alternative activity or destination.
3. If the rest of the plan is solid, end with a quick nudge toward it.
Do NOT apologize. Do NOT say "unfortunately". State the fact and redirect.
Tone: matter-of-fact expert redirecting to something better.\
"""

# Sentence limits per voice block — hard-enforced during streaming.
# These mirror the "Sentence count: X MAX" declarations in each voice block
# so the system never relies solely on the LLM to self-regulate.
# Keys MUST be the exact module-level _VOICE_* constants (looked up by identity).
_SENTENCE_LIMIT: Dict[str, int] = {
    _VOICE_DESTINATION_SET: 2,
    _VOICE_DATES_SET: 2,
    _VOICE_PLAN_GENERATED: 2,
    _VOICE_ACTIVITY_CHANGE: 2,
    _VOICE_PREFERENCE_CHANGE: 2,
    _VOICE_QUESTION: 3,
    _VOICE_GREETING: 1,
    _VOICE_FALLBACK: 2,
    _VOICE_INFEASIBLE_ACTIVITY: 3,
}
_DEFAULT_SENTENCE_LIMIT: int = 3

# Map ChangeType enum values -> voice block
_VOICE_BY_CHANGE_TYPE: Dict[str, str] = {
    # Initial planning
    "initial_plan": _VOICE_DESTINATION_SET,
    "destination_change": _VOICE_DESTINATION_SET,
    # Dates
    "date_change": _VOICE_DATES_SET,
    # Plan generation / rebuild
    "add_activity": _VOICE_PLAN_GENERATED,
    "remove_activity": _VOICE_ACTIVITY_CHANGE,
    "swap_activity": _VOICE_ACTIVITY_CHANGE,
    "day_count": _VOICE_ACTIVITY_CHANGE,
    "spatial": _VOICE_ACTIVITY_CHANGE,
    # Preferences & settings
    "preference": _VOICE_PREFERENCE_CHANGE,
    "logistics": _VOICE_PREFERENCE_CHANGE,
    "settings": _VOICE_PREFERENCE_CHANGE,
    # Questions & social
    "question": _VOICE_QUESTION,
    "greeting": _VOICE_GREETING,
    "reset": _VOICE_GREETING,
}


def _resolve_voice_block(
    classifier: ClassifierOutput,
    state: Dict[str, Any],
    user_message: str,
) -> str:
    """Resolve the voice block for the current turn."""
    # Check if ANY specialist is newly infeasible this turn
    prechecks = state.get("turn_meta", {}).get("feasibility_prechecks", {})
    has_infeasible_this_turn = (
        any(
            isinstance(v, tuple) and len(v) >= 1 and v[0] == "infeasible"
            for v in prechecks.values()
        )
        if prechecks
        else False
    )

    if not has_infeasible_this_turn:
        affected = set(classifier.affects) if classifier.affects else set()
        has_infeasible_this_turn = any(
            isinstance(s, dict)
            and s.get("feasibility_status") == "infeasible"
            and s.get("specialist_type") in affected
            for s in state.get("strategy_sections", [])
        )

    if has_infeasible_this_turn:
        return _VOICE_INFEASIBLE_ACTIVITY

    change_key = classifier.change_type.value
    day_cards = state.get("day_cards", [])

    # swap_activity intentionally stays at ACTIVITY_CHANGE — a swap is a
    # minor tweak, not a full rebuild, so 2-3 sentences (not 3-4) is right.
    if day_cards and change_key in ("add_activity", "remove_activity", "day_count"):
        voice_block = _VOICE_PLAN_GENERATED
    else:
        voice_block = _VOICE_BY_CHANGE_TYPE.get(change_key, _VOICE_FALLBACK)

    if user_message.strip().upper() in ("GENERATE_PLAN_NOW", "GENERATE_PLAN_TRIGGER"):
        voice_block = _VOICE_PLAN_GENERATED
    elif classifier.reasoning and "GENERATE_PLAN_NOW" in classifier.reasoning:
        voice_block = _VOICE_PLAN_GENERATED

    return voice_block


_ABBREVIATIONS = frozenset(
    {
        "st",
        "mt",
        "ft",
        "dr",
        "mr",
        "mrs",
        "ms",
        "sr",
        "jr",
        "pt",
        "no",
        "rd",
        "ave",
        "blvd",
        "sq",
        "dept",
        "govt",
        "approx",
        "est",
        "vol",
        "gen",
        "col",
        "lt",
        "sgt",
        "cpl",
        "pvt",
        "prof",
        "rev",
        "fr",
    }
)


def _enforce_sentence_limit(text: str, limit: int) -> str:
    """Return *text* trimmed to at most *limit* sentences.

    A sentence boundary is a group of ``.``, ``!``, or ``?`` characters
    (so ``...`` and ``!!`` each count as one ending) that is followed by
    either **end-of-text** or **whitespace + an uppercase letter**.

    This avoids false positives on abbreviations (``U.S.``, ``Dr.``),
    decimal numbers (``14.5``), mid-sentence ellipsis (``Wait... really?``),
    and known abbreviations that precede proper nouns (``St. Peter's``).
    """
    count = 0
    i = 0
    while i < len(text):
        if text[i] in ".!?":
            # consume consecutive punctuation (e.g. "..." or "!?")
            while i + 1 < len(text) and text[i + 1] in ".!?":
                i += 1
            # Only count as a sentence boundary when followed by EOT or
            # whitespace + uppercase (skips "U.S.", "14.5", "e.g." etc.)
            rest = text[i + 1 :]
            stripped = rest.lstrip()
            if not stripped or (rest and rest[0].isspace() and stripped and stripped[0].isupper()):
                # Skip known abbreviations (St. Peter's, Mt. Fuji, Dr. Smith)
                word_start = i
                while word_start > 0 and text[word_start - 1].isalpha():
                    word_start -= 1
                preceding_word = text[word_start:i].lower()
                if preceding_word in _ABBREVIATIONS:
                    i += 1
                    continue
                count += 1
                if count >= limit:
                    return text[: i + 1].rstrip()
        i += 1
    return text


def build_response_context(
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    user_message: str,
    *,
    voice_block: str | None = None,
) -> List[Dict[str, str]]:
    """Build the message list for the conversationalist LLM call."""

    if voice_block is None:
        voice_block = _resolve_voice_block(classifier, state, user_message)
    change_key = classifier.change_type.value

    # ── Assemble system prompt ────────────────────────────────────
    destination = state.get("trip_plan", {}).get("destination")
    if destination:
        persona = (
            f"You are the user's personal travel architect. "
            f"You know {destination} well — the neighborhoods, the timing, "
            f"the places locals actually go. You have strong opinions based "
            f"on the specialist data below. Respond like a well-traveled "
            f"friend, not a concierge reading from a binder. "
            f"Follow the voice rules exactly."
        )
    else:
        persona = (
            "You are a sharp, opinionated travel planning expert. "
            "Respond to the user based on the trip state and specialist "
            "findings below. Follow the voice rules exactly."
        )
    system_parts: List[str] = [persona]

    # 1. Trip context
    trip_block = _build_trip_context_block(state)
    if trip_block:
        system_parts.append(trip_block)

    # 2. What the user sees (UI awareness — only when plan content exists)
    if state.get("day_cards") or state.get("strategy_sections"):
        system_parts.append(
            "## What the User Sees Right Now\n"
            "The user sees a timeline with day cards, a map with pins, "
            "and trip pills at the top. NEVER describe what's visible. "
            "Add editorial value, not description."
        )

    # 3. Specialist findings (now reads strategy_sections)
    specialist_block = _build_specialist_findings_block(state, classifier)
    if specialist_block:
        system_parts.append(specialist_block)

    # 4. Itinerary highlights (now includes day-by-day content)
    itinerary_block = _build_itinerary_status_block(state)
    if itinerary_block:
        system_parts.append(itinerary_block)

    # 5. Outcome — what the system actually did (only for plan mutations)
    plan_mutation_types = {
        "add_activity",
        "remove_activity",
        "swap_activity",
        "day_count",
        "date_change",
        "spatial",
        "preference",
        "logistics",
        "settings",
    }
    if change_key in plan_mutation_types:
        outcome_block = _build_outcome_block(state)
        if outcome_block:
            system_parts.append(outcome_block)

    # 6. Turn context (what changed)
    turn_block = _build_turn_context_block(classifier, user_message)
    system_parts.append(turn_block)

    # 7. Dedup: show the LLM what it already said (so it doesn't repeat)
    recent_assistant_msgs = [
        str(msg.content)[:300]
        for msg in (state.get("messages", []) or [])[-6:]
        if isinstance(msg, AIMessage)
    ]
    if recent_assistant_msgs:
        dedup_block = "## Already Said (NEVER repeat these — find something NEW to say)\n"
        dedup_block += "\n".join(f'- "{m}"' for m in recent_assistant_msgs[-3:])
        system_parts.append(dedup_block)

    # 8. Hard rules + intent-specific voice
    system_parts.append(_VOICE_BASE)
    system_parts.append(voice_block)

    system_prompt = "\n\n".join(system_parts)

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

    # Recent history (last 4 turns, truncated)
    for msg in (state.get("messages", []) or [])[-8:]:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": str(msg.content)[:500]})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": str(msg.content)[:500]})

    messages.append({"role": "user", "content": user_message})
    return messages


# ---------------------------------------------------------------------------
# Streaming response generation
# ---------------------------------------------------------------------------


async def generate_response_streaming(
    state: Dict[str, Any],
    classifier: ClassifierOutput,
    user_message: str,
) -> AsyncGenerator[str, None]:
    """Stream the assistant response token by token.

    Uses ``settings.synthesizer_planning_model`` via ``get_llm_by_model()``
    with temperature 0.6 and max 600 tokens.  Enforces a hard sentence
    limit derived from the active voice block so the response never
    exceeds the declared maximum even if the LLM overshoots.
    """
    # Resolve voice block once — used for both prompt assembly and sentence enforcement
    voice_block = _resolve_voice_block(classifier, state, user_message)
    messages = build_response_context(
        state,
        classifier,
        user_message,
        voice_block=voice_block,
    )
    sentence_limit = _SENTENCE_LIMIT.get(voice_block, _DEFAULT_SENTENCE_LIMIT)

    model = settings.synthesizer_planning_model
    llm = get_llm_by_model(
        model,
        temperature=_RESPONSE_TEMPERATURE,
        max_tokens=_RESPONSE_MAX_TOKENS,
    )

    logger.info(
        "[conversationalist] Streaming response (model=%s, intent=%s, change_type=%s, "
        "sentence_limit=%d)",
        model,
        classifier.intent,
        classifier.change_type.value,
        sentence_limit,
    )

    # Convert message dicts to LangChain message objects
    lc_messages = []
    for msg in messages:
        if msg["role"] == "system":
            lc_messages.append(SystemMessage(content=msg["content"]))
        elif msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_messages.append(AIMessage(content=msg["content"]))

    # Stream with sentence enforcement: accumulate text, yield chunks,
    # and cut off cleanly once the sentence limit is reached.
    accumulated = ""
    yielded = 0

    async for chunk in llm.astream(lc_messages):
        content = getattr(chunk, "content", "")
        # Gemini may return list-of-parts instead of a plain string
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, str):
                    parts.append(p)
                elif isinstance(p, dict):
                    parts.append(p.get("text", ""))
                elif hasattr(p, "text"):
                    parts.append(p.text)
            content = "".join(parts)
        if not content:
            continue

        accumulated += content
        trimmed = _enforce_sentence_limit(accumulated, sentence_limit)

        if len(trimmed) < len(accumulated):
            # Hit the limit — yield remaining safe text and stop
            new_text = trimmed[yielded:]
            if new_text:
                yield new_text
            return

        new_text = accumulated[yielded:]
        if new_text:
            yield new_text
            yielded = len(accumulated)
