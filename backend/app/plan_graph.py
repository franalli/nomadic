# plan_graph.py — Minimalist LangGraph with strategy modules + monolith fallback
from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from jsonschema import Draft7Validator
from jsonschema import validate as jsonschema_validate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.config import settings


# -----------------------
# Models & schema
# -----------------------
class TripInputs(BaseModel):
    destinations: List[str] = []
    origin: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    requires_assistance: Optional[bool] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    multi_city_intent: Optional[Literal["multi_city", "separate"]] = None
    booking_types: Dict[str, bool] = Field(default_factory=dict)
    flight_settings: Dict[str, Any] = Field(default_factory=dict)
    hotel_settings: Dict[str, Any] = Field(default_factory=dict)
    activity_settings: Dict[str, Any] = Field(default_factory=lambda: {"categories": []})
    transport_settings: Dict[str, Any] = Field(default_factory=dict)
    # Strategy-specific persisted preferences (per topic)
    strategy_settings: Dict[str, Any] = Field(default_factory=dict)


class GraphState(BaseModel):
    user_text: str
    trip_inputs: TripInputs = Field(default_factory=TripInputs)
    parsed_inputs: Dict[str, Any] = Field(default_factory=dict)
    ready_to_generate: bool = False
    branches: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_responses: List[str] = Field(default_factory=list)
    intent: Optional[str] = (
        None  # required_fields|flights|hotels|transport|activities|correction_needed|strategy
    )
    strategy_topic: Optional[str] = None  # boating|hiking|diving|...
    active_category: Optional[str] = None
    last_summary: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    flags: Dict[str, Any] = Field(default_factory=dict)


TRIP_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "destinations": {"type": "array", "items": {"type": "string"}},
        "origin": {"type": ["string", "null"]},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "adults": {"type": ["integer", "null"], "minimum": 1},
        "children": {"type": ["integer", "null"], "minimum": 0},
        "requires_assistance": {"type": ["boolean", "null"]},
        "budget": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}
TRIP_VALIDATOR = Draft7Validator(TRIP_JSON_SCHEMA)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROMPTS_DIR = Path(__file__).parent / "prompts"
INVALID_JSON_HINT = (
    "\n\nIMPORTANT: Your previous response was not valid JSON. "
    "Please respond with ONLY valid JSON."
)

# -----------------------
# Strategy registry (plug-in)
# -----------------------
STRATEGY_REGISTRY: Dict[str, str] = {}  # topic -> prompt filename (without .txt)


def register_strategy(topic: str, prompt_name: str):
    STRATEGY_REGISTRY[topic] = prompt_name


# Example registrations (create corresponding prompts/*.txt files)
register_strategy("boating", "strategy_boating")
register_strategy("hiking", "strategy_hiking")
register_strategy("diving", "strategy_diving")
register_strategy("skiing", "strategy_skiing")
register_strategy("cycling", "strategy_cycling")


# -----------------------
# Prompt & LLM helpers
# -----------------------
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def call_llm(model: str, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> str:
    """
    Call the LLM provider. Must return a string (JSON text).

    IMPORTANT: This is a stub that must be replaced with your actual LLM provider.
    Implement this function to call OpenAI, Anthropic, or your preferred provider.

    Example implementation:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content
    """
    raise RuntimeError(
        "LLM provider not configured. Implement call_llm() in plan_graph.py "
        "to connect to your LLM provider (OpenAI, Anthropic, etc.)"
    )


def call_llm_with_timeout(
    model: str,
    prompt: str,
    timeout_seconds: float,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    """
    Call LLM with a timeout. Raises TimeoutError if the call takes too long.

    Args:
        model: Model identifier.
        prompt: The prompt to send.
        timeout_seconds: Maximum time to wait for response.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.

    Returns:
        str: LLM response text.

    Raises:
        TimeoutError: If the call exceeds timeout_seconds.
        Exception: Any exception from the underlying LLM call.
    """
    result = {"response": None, "error": None}

    def target():
        try:
            result["response"] = call_llm(model, prompt, max_tokens, temperature)
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # Thread still running - timeout occurred
        raise TimeoutError(f"LLM call timed out after {timeout_seconds}s")

    if result["error"]:
        raise result["error"]

    return result["response"]


def jloads_safe(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start : end + 1])
        raise


def ti_short(ti: TripInputs) -> Dict[str, Any]:
    return ti.model_dump(exclude_none=True)


def _record_llm_failure(state: GraphState, reason: str) -> GraphState:
    state.metadata["validator_failures"] = state.metadata.get("validator_failures", 0) + 1
    state.flags["force_monolith"] = True
    state.errors.append(reason)
    state.last_summary = "Switching to full planner due to inconsistent responses; continue?"
    state.suggested_responses = []
    state.branches = []
    state.ready_to_generate = False
    return state


# -----------------------
# Cheap extractor (code)
# -----------------------
def extractor(state: GraphState) -> GraphState:
    text = state.user_text
    parsed: Dict[str, Any] = {}

    # budget + currency
    m = re.search(r"(?P<cur>[$€£]|USD|EUR|GBP)\s*(?P<amt>\d[\d,\.]*)", text, re.I)
    if m:
        cur = m.group("cur")
        amt = float(m.group("amt").replace(",", ""))
        parsed["budget_delta"] = {
            "budget": amt,
            "currency": {"$": "USD", "€": "EUR", "£": "GBP"}.get(cur, cur.upper()),
        }

    # origin/destinations (very basic)
    m = re.search(r"from\s+(?P<o>[A-Za-z\s\-]+)\s+to\s+(?P<d>[A-Za-z\s,\-and]+)", text, re.I)
    if m:
        parsed["origin_delta"] = m.group("o").strip()
        parsed["destinations_delta"] = [
            x.strip() for x in re.split(r",|and", m.group("d")) if x.strip()
        ]

    # category activation
    cats = []
    if re.search(r"flight|cabin|nonstop|direct|one[-\s]?way", text, re.I):
        cats.append("flights")
    if re.search(r"hotel|amenit|star", text, re.I):
        cats.append("hotels")
    if re.search(r"\btrain|car rental|rent car|bus\b", text, re.I):
        cats.append("transport")
    if re.search(r"activity|tour|museum|beach|hike|dive|nightlife", text, re.I):
        cats.append("activities")
    if cats:
        parsed["category_activation"] = cats

    # strategy detection heuristic (router will finalize)
    if re.search(r"boat|boating|sail|yacht|kayak|canoe|marina", text, re.I):
        parsed["strategy_hint"] = "boating"
    if re.search(r"hike|trek|trail|alpine|mountain", text, re.I):
        parsed["strategy_hint"] = parsed.get("strategy_hint") or "hiking"

    state.parsed_inputs = parsed
    return state


# -----------------------
# Router (small LLM) - no retry, uses timeout
# -----------------------
def router(state: GraphState) -> GraphState:
    """
    Router node to determine intent. Uses timeout but NO retry (router should be fast and reliable).
    """
    try:
        prompt = load_prompt("router")
        tpl = prompt.replace("{parsed_inputs}", json.dumps(state.parsed_inputs)).replace(
            "{trip_inputs}", json.dumps(ti_short(state.trip_inputs))
        )
        out = call_llm_with_timeout(
            model="small-router",
            prompt=tpl,
            timeout_seconds=settings.llm_timeout_router,
            max_tokens=200,
        )
        j = jloads_safe(out)
        state.intent = j.get("intent") or "required_fields"
        topic = j.get("topic") or state.parsed_inputs.get("strategy_hint")
        state.strategy_topic = topic if state.intent == "strategy" else None
        state.metadata["router_notes"] = j.get("notes", "")
        state.metadata["router_confidence"] = j.get("confidence", 1.0)

        prev_intent = state.metadata.get("last_intent")
        no_progress_turns = state.metadata.get("no_progress_turns", 0)
        if state.intent == "required_fields" and prev_intent == "required_fields":
            no_progress_turns += 1
        else:
            no_progress_turns = 0
        state.metadata["no_progress_turns"] = no_progress_turns
        state.metadata["last_intent"] = state.intent
        return state
    except Exception as exc:
        return _record_llm_failure(state, f"router failed: {exc}")


# -----------------------
# Specialists (shared handler)
# -----------------------
def _specialist(
    name: str, state: GraphState, model: str = "medium", retry_on_json_error: bool = True
) -> GraphState:
    """
    Shared handler for specialist nodes with JSON retry logic.

    Args:
        name: Prompt name to load.
        state: Current graph state.
        model: LLM model to use.
        retry_on_json_error: If True, attempt one repair retry on JSON parse failure.
    """
    prompt = load_prompt(name)
    tpl = prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs))).replace(
        "{parsed_inputs}", json.dumps(state.parsed_inputs)
    )

    # Determine timeout based on model type
    timeout = settings.llm_timeout_specialist

    attempts = 2 if retry_on_json_error else 1
    last_error = None

    for attempt in range(attempts):
        try:
            out = call_llm_with_timeout(
                model=model, prompt=tpl, timeout_seconds=timeout, max_tokens=550
            )
            j = jloads_safe(out)

            ti = state.trip_inputs.model_copy(deep=True)
            delta = j.get("trip_inputs", {}) or {}
            for k, v in delta.items():
                if k == "destinations" and isinstance(v, list):
                    for d in v:
                        if d not in ti.destinations:
                            ti.destinations.append(d)
                elif v is None:
                    continue
                else:
                    setattr(ti, k, v)

            jsonschema_validate(ti.model_dump(), TRIP_JSON_SCHEMA)
            state.trip_inputs = ti
            state.last_summary = j.get("assistant_message", "")
            state.suggested_responses = (j.get("suggested_responses", []) or [])[:3]
            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )
            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                state.branches = j.get("branches", []) or []
            state.metadata["model_used"] = model
            return state
        except json.JSONDecodeError as e:
            last_error = e
            if attempt < attempts - 1:
                # Add repair hint to prompt for retry
                tpl += INVALID_JSON_HINT
                continue
            break
        except TimeoutError as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            break

    reason = f"{name} node produced invalid output after {attempts} attempt(s): {last_error}"
    return _record_llm_failure(state, reason)


def required_fields_node(s: GraphState) -> GraphState:
    return _specialist("required_fields", s, model="small")


def flights_node(s: GraphState) -> GraphState:
    s.active_category = "flights"
    return _specialist("flights", s, model="medium")


def hotels_node(s: GraphState) -> GraphState:
    s.active_category = "hotels"
    return _specialist("hotels", s, model="medium")


def transport_node(s: GraphState) -> GraphState:
    s.active_category = "transport"
    return _specialist("transport", s, model="small")


def activities_node(s: GraphState) -> GraphState:
    s.active_category = "activities"
    return _specialist("activities", s, model="small")


def correction_node(s: GraphState) -> GraphState:
    return _specialist("correction", s, model="medium")


# -----------------------
# Strategy node (loads module by topic from registry)
# -----------------------
def _is_strategy_enabled(topic: str) -> bool:
    """Check if a strategy is enabled via feature flags."""
    flag_map = {
        "boating": settings.enable_strategy_boating,
        "hiking": settings.enable_strategy_hiking,
        "diving": settings.enable_strategy_diving,
        "skiing": settings.enable_strategy_skiing,
        "cycling": settings.enable_strategy_cycling,
    }
    return flag_map.get(topic, True)  # Default to enabled for unknown topics


def strategy_node(state: GraphState) -> GraphState:
    topic = state.strategy_topic or "boating"

    # Check feature flag - if disabled, fallback to activities-lite
    if not _is_strategy_enabled(topic):
        state.last_summary = (
            f"The {topic} planning module is currently unavailable. "
            "I can help with general activity planning instead."
        )
        state.active_category = "activities"
        return _specialist("activities", state, model="small")

    prompt_name = STRATEGY_REGISTRY.get(topic)
    if not prompt_name:
        # Fallback: gentle notice; no state changes
        state.last_summary = (
            f"I can draft a detailed {topic} plan soon. For now, which preferences matter most?"
        )
        state.suggested_responses = [
            "Beginner skill level",
            "Prefer skippered",
            "Max 4 hours daily",
        ]
        return state

    # Use timeout and retry logic
    timeout = settings.llm_timeout_specialist
    attempts = 2
    last_error = None

    prompt = load_prompt(prompt_name)
    tpl = (
        prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{topic}", topic)
    )

    for attempt in range(attempts):
        try:
            out = call_llm_with_timeout(
                model="medium-large",
                prompt=tpl,
                timeout_seconds=timeout,
                max_tokens=700,
                temperature=0.2,
            )
            j = jloads_safe(out)

            ti = state.trip_inputs.model_copy(deep=True)
            ss = dict(ti.strategy_settings)
            ss[topic] = j.get("strategy_settings", ss.get(topic, {}))
            ti.strategy_settings = ss

            for k, v in (j.get("trip_inputs", {}) or {}).items():
                if k in {"strategy_settings"}:
                    continue
                if k == "destinations" and isinstance(v, list):
                    for d in v:
                        if d not in ti.destinations:
                            ti.destinations.append(d)
                elif v is None:
                    continue
                else:
                    setattr(ti, k, v)

            jsonschema_validate(ti.model_dump(), TRIP_JSON_SCHEMA)
            state.trip_inputs = ti
            state.last_summary = j.get("assistant_message", "")
            state.suggested_responses = (j.get("suggested_responses", []) or [])[:3]
            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )
            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                state.branches = j.get("branches", []) or []
            state.metadata["model_used"] = "medium-large"
            return state
        except json.JSONDecodeError as e:
            last_error = e
            if attempt < attempts - 1:
                tpl += INVALID_JSON_HINT
                continue
            break
        except Exception as e:
            last_error = e
            break

    reason = (
        f"strategy node for {topic} produced invalid output after {attempts} attempt(s): "
        f"{last_error}"
    )
    return _record_llm_failure(state, reason)


# -----------------------
# Monolith fallback (full prompt)
# -----------------------
def monolith_node(state: GraphState) -> GraphState:
    """
    Monolith fallback node with timeout and JSON retry logic.

    Used when router confidence is low or specialists fail repeatedly.
    """
    prompt = load_prompt("monolith")
    # Use today_iso from metadata (injected by route) or fall back to current date
    today_iso = state.metadata.get("today_iso") or date.today().isoformat()
    tpl = (
        prompt.replace("{trip_inputs}", json.dumps(ti_short(state.trip_inputs)))
        .replace("{parsed_inputs}", json.dumps(state.parsed_inputs))
        .replace("{conversation_summary}", state.last_summary or "")
        .replace("{errors}", json.dumps(state.errors))
        .replace("{today}", today_iso)
        .replace(
            "{current_state_json}", json.dumps(ti_short(state.trip_inputs))
        )  # reuse compact state
    )

    timeout = settings.llm_timeout_monolith
    attempts = 2
    last_error = None

    for attempt in range(attempts):
        try:
            out = call_llm_with_timeout(
                model="large", prompt=tpl, timeout_seconds=timeout, max_tokens=700, temperature=0.2
            )
            j = jloads_safe(out)

            ti = state.trip_inputs.model_copy(deep=True)
            for k, v in (j.get("trip_inputs", {}) or {}).items():
                if k == "destinations" and isinstance(v, list):
                    for d in v:
                        if d not in ti.destinations:
                            ti.destinations.append(d)
                elif v is None:
                    continue
                else:
                    setattr(ti, k, v)

            jsonschema_validate(ti.model_dump(), TRIP_JSON_SCHEMA)
            state.trip_inputs = ti
            state.last_summary = j.get("assistant_message", "")
            state.suggested_responses = (j.get("suggested_responses", []) or [])[:3]
            # Only set ready_to_generate if explicitly triggered
            state.ready_to_generate = bool(j.get("ready_to_generate", False)) and state.flags.get(
                "generate_requested", False
            )
            # Only emit branches if generate was explicitly requested
            if state.flags.get("generate_requested", False):
                state.branches = j.get("branches", []) or []
            state.metadata["model_used"] = "large"
            state.metadata["monolith_used"] = True
            return state
        except json.JSONDecodeError as e:
            last_error = e
            if attempt < attempts - 1:
                tpl += INVALID_JSON_HINT
                continue
            break
        except Exception as e:
            last_error = e
            break

    reason = f"monolith node failed after {attempts} attempt(s): {last_error}"
    return _record_llm_failure(state, reason)


# -----------------------
# Validation & summarization
# -----------------------
def validate_and_merge(s: GraphState) -> GraphState:
    ti = s.trip_inputs
    if ti.start_date and not ISO.match(ti.start_date):
        s.errors.append("Invalid start_date")
    if ti.end_date and not ISO.match(ti.end_date):
        s.errors.append("Invalid end_date")
    if ti.start_date and ti.end_date and ISO.match(ti.start_date) and ISO.match(ti.end_date):
        if ti.start_date > ti.end_date:
            s.errors.append("Start date after end date")
    s.ready_to_generate = bool(
        not s.errors and all([ti.destinations, ti.origin, ti.start_date, ti.end_date])
    )
    return s


def summarize(s: GraphState) -> GraphState:
    return s  # optional micro-summarizer


# -----------------------
# Monolith routing policy
# -----------------------
def should_use_monolith(state: GraphState) -> bool:
    return any(
        [
            state.intent is None,
            state.intent == "unknown",
            state.metadata.get("router_confidence", 1.0) < 0.45,
            state.metadata.get("no_progress_turns", 0) >= 2,
            state.metadata.get("validator_failures", 0) >= 2,
            state.flags.get("force_monolith", False),
            state.flags.get("generate_plan", False),
        ]
    )


# -----------------------
# Graph assembly
# -----------------------
_graph = StateGraph(GraphState)
_graph.add_node("extractor", extractor)
_graph.add_node("router", router)
_graph.add_node("required_fields_node", required_fields_node)
_graph.add_node("flights_node", flights_node)
_graph.add_node("hotels_node", hotels_node)
_graph.add_node("transport_node", transport_node)
_graph.add_node("activities_node", activities_node)
_graph.add_node("strategy_node", strategy_node)
_graph.add_node("correction_node", correction_node)
_graph.add_node("monolith_node", monolith_node)
_graph.add_node("validate_and_merge", validate_and_merge)
_graph.add_node("summarize", summarize)

_graph.add_edge(START, "extractor")
_graph.add_edge("extractor", "router")


def route_after_router(s: GraphState) -> str:
    if should_use_monolith(s):
        return "monolith_node"
    if s.intent == "strategy":
        return "strategy_node"
    return {
        "required_fields": "required_fields_node",
        "flights": "flights_node",
        "hotels": "hotels_node",
        "transport": "transport_node",
        "activities": "activities_node",
        "correction_needed": "correction_node",
    }.get(s.intent, "required_fields_node")


_graph.add_conditional_edges(
    "router",
    route_after_router,
    {
        "monolith_node": "monolith_node",
        "strategy_node": "strategy_node",
        "required_fields_node": "required_fields_node",
        "flights_node": "flights_node",
        "hotels_node": "hotels_node",
        "transport_node": "transport_node",
        "activities_node": "activities_node",
        "correction_node": "correction_node",
    },
)

# From any worker → validate → summarize → END
for n in [
    "required_fields_node",
    "flights_node",
    "hotels_node",
    "transport_node",
    "activities_node",
    "strategy_node",
    "correction_node",
    "monolith_node",
]:
    _graph.add_edge(n, "validate_and_merge")
_graph.add_edge("validate_and_merge", "summarize")
_graph.add_edge("summarize", END)

app = _graph.compile(checkpointer=MemorySaver())


# -----------------------
# Public entrypoint
# -----------------------


def _required_done(ti: TripInputs) -> bool:
    # Match your READY STATE rule (destinations, origin, start_date)
    return bool(ti.destinations and ti.origin and ti.start_date)


def _progress_signal(before: TripInputs, after: TripInputs) -> bool:
    # Register progress if any required field newly completed or any field changed
    if _required_done(before) != _required_done(after):
        return True
    # Shallow diff on a few high-signal keys
    keys = [
        "destinations",
        "origin",
        "start_date",
        "end_date",
        "budget",
        "currency",
        "activity_settings",
        "strategy_settings",
        "booking_types",
        "flight_settings",
        "hotel_settings",
        "transport_settings",
    ]
    b = before.model_dump(exclude_none=True)
    a = after.model_dump(exclude_none=True)
    return any(b.get(k) != a.get(k) for k in keys)


def run_turn(user_text: str, session_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    session_state = session_state or {}
    thread_id = session_state.get("thread_id") or str(uuid4())

    # Previous state snapshot for progress heuristics
    prev_ti = TripInputs(**session_state.get("trip_inputs", {}))

    # Build metadata with today_iso from session_state (defaults to current date)
    metadata = deepcopy(session_state.get("metadata", {}))
    if "today_iso" in session_state:
        metadata["today_iso"] = session_state["today_iso"]
    elif "today_iso" not in metadata:
        metadata["today_iso"] = date.today().isoformat()

    # Build input state
    state = GraphState(
        user_text=user_text,
        trip_inputs=TripInputs(**session_state.get("trip_inputs", {})),
        metadata=metadata,
        flags=deepcopy(session_state.get("flags", {})),
        last_summary=session_state.get("last_summary"),
        branches=deepcopy(session_state.get("branches", [])),
        suggested_responses=deepcopy(session_state.get("suggested_responses", [])),
        errors=deepcopy(session_state.get("errors", [])),
    )

    # Invoke graph with a stable thread for LangGraph checkpointing
    result: GraphState = app.invoke(state, config={"configurable": {"thread_id": thread_id}})

    # Update simple “no progress” metric used by should_use_monolith()
    try:
        made_progress = _progress_signal(prev_ti, result.trip_inputs)
        meta = result.metadata or {}
        if made_progress:
            meta["no_progress_turns"] = 0
        else:
            meta["no_progress_turns"] = int(meta.get("no_progress_turns", 0)) + 1
        result.metadata = meta
    except Exception:
        # Do not let metrics break the turn
        pass

    # Assemble response
    resp = {
        "assistant_message": result.last_summary or "",
        "trip_inputs": result.trip_inputs.model_dump(exclude_none=True),
        "ready_to_generate": result.ready_to_generate,
        "branches": result.branches,
        "suggested_responses": result.suggested_responses,
        "errors": result.errors,
        "session_state": {
            "trip_inputs": result.trip_inputs.model_dump(),
            "metadata": result.metadata,
            "flags": result.flags,
            "last_summary": result.last_summary,
            "branches": result.branches,
            "suggested_responses": result.suggested_responses,
            "errors": result.errors,
            "thread_id": thread_id,
            # Optional: expose for debugging/analytics if your nodes set them
            "router_intent": getattr(result, "intent", None),
            "strategy_topic": getattr(result, "strategy_topic", None),
        },
    }
    return resp
