# Plan Graph Architecture

> **Source**: `backend/app/planner/plan_graph.py` (streaming), `backend/app/planner/agent.py` (factory)
> **Planner Package**: `backend/app/planner/`
> **Prompt Files**: `backend/app/planner/prompts/`, `backend/app/prompts/specialists/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Package Structure](#package-structure)
3. [Agent Architecture Diagram](#agent-architecture-diagram)
4. [Agent Tools Reference](#agent-tools-reference)
5. [Middleware Stack](#middleware-stack)
6. [Library Modules (Surviving Node Code)](#library-modules-surviving-node-code)
7. [Itinerary Builder Service](#itinerary-builder-service)
8. [Structured Output Usage](#structured-output-usage)
9. [State Models](#state-models)
10. [Specialist Domain Knowledge](#specialist-domain-knowledge)
11. [Constraint Validation](#constraint-validation)
12. [Caching Architecture](#caching-architecture)
13. [Selective Regeneration](#selective-regeneration)
14. [Prompt File Mapping](#prompt-file-mapping)
15. [Streaming Architecture](#streaming-architecture)
16. [Tile Service Architecture](#tile-service-architecture)
17. [Booking Provider Interface](#booking-provider-interface-scaffolding)
18. [Key Exports](#key-exports)
19. [Admin Cache Management Endpoints](#admin-cache-management-endpoints)
20. [View States](#view-states)
21. [UI Events](#ui-events)
22. [Result Format](#result-format)

---

## Architecture Overview

Single-agent trip planning system built on LangChain's `create_agent` with **6 tools** and **4 middleware**.

The agent dynamically decides tool order based on conversation context -- there is no fixed node graph or routing logic. The old 7-node LangGraph DAG (router, architect, specialist, local_expert, logistics, guard, synthesizer) has been replaced.

| Category            | Count | Description                                                                                                                 |
| ------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------- |
| Agent Tools         | 6     | extract_trip_fields, get_specialist_advice, search_tiles, get_local_intel, validate_plan, build_itinerary                   |
| Middleware           | 4     | ModelSelectionMiddleware, DynamicPromptMiddleware, TurnLifecycleMiddleware, SuggestionChipMiddleware                         |
| Library Modules      | 5     | router_extraction.py, vertical_specialist.py, local_expert.py, logistics_node.py, constraint_guard.py (now wrapped by tools, no longer standalone graph nodes) |

> **Note:** `ItineraryBuilder` is a pure Python **service** (not a tool or node). It is called by the `build_itinerary` tool and from both `_build_complete_envelope()` (graph shadow mode) and the `/api/expand-itinerary` endpoint.

### Design Principles

1. **Single Agent Architecture** -- One `create_agent` planner with 6 tools replaces the old 7-node DAG. The agent decides tool order dynamically.
2. **"Flights/Hotels are Data"** -- They are fetched via `search_tiles` tool (LogisticsNode + TileService), not agents
3. **"Diving IS an Agent"** -- Domain experts (Tier 1) use `get_specialist_advice` tool (VerticalSpecialist)
4. **TripPlan is the SSoT** -- Single Source of Truth for trip state
5. **Middleware over Nodes** -- State mutation, model upgrades, prompt injection, and chip generation happen in `AgentMiddleware` hooks, not standalone nodes
6. **One Voice** -- The planner agent generates responses directly; no separate synthesizer node
7. **Centralized LLM Factory** -- `get_llm_by_model()` handles provider detection (OpenAI/Gemini), model-specific params. Models configured via `settings.*_model` env vars.
8. **Safe Routing** -- LLM-based intent classification via `extract_trip_fields` tool and `settings.router_model`
9. **Itinerary Synthesis** -- ItineraryBuilder is pure Python (no LLM) for deterministic scheduling

### Deleted Components (replaced by agent + tools)

| Old Component | Replacement |
|---------------|-------------|
| IntentRouter node (`intent_router.py`) | `extract_trip_fields` tool wrapping `router_extraction.py` |
| TripArchitect node (`trip_architect.py`) | Planner agent direct reasoning |
| Synthesizer node (`synthesizer.py`) | Planner agent generates responses directly |
| `router_utils.py` | Deleted (logic absorbed into agent prompt / tools) |
| `router_category_sync.py` | Deleted (logic absorbed into middleware / tools) |
| `backend/app/plan_graph.py` (old location) | Replaced by `backend/app/planner/plan_graph.py` (new streaming core) |
| Routing functions (`route_after_*`) | Agent decides tool order dynamically |

---

## Package Structure

```
backend/app/planner/
├── __init__.py              # Facade exports (stable public API)
├── agent.py                 # Agent factory: create_planner_agent() using create_agent
├── agent_constants.py       # Shared constants: AGENT_MAX_TOKENS=4000, AGENT_TEMPERATURE=0.4
├── hashing.py               # Stable hashing utilities (make_cache_key, field_hash)
├── llm_factory.py           # Provider-agnostic LLM factory (OpenAI/Gemini auto-routing) + extract_token_usage(), resolve_schema_refs(), extract_json_content()
├── middleware.py             # 4 AgentMiddleware classes (model selection, dynamic prompt, turn lifecycle, suggestion chips)
├── patterns_registry.py     # Shared regex/keyword patterns (BUDGET_PATTERNS, TRAVELER_PATTERNS, SETTINGS_KEYWORDS)
├── plan_graph.py             # Streaming core: run_turn_streaming() using astream_events(version="v2")
├── test_mode.py             # Test mode detection
├── specialist_registry.py   # Specialist config SSoT (keywords, constraints, enhancements, flags)
#   Frontend mirror: frontend/lib/specialists.ts (colors, icons, keywords, display names)
├── nodes/                   # Library modules (wrapped by tools, no longer standalone graph nodes)
│   ├── __init__.py          # Exports surviving library code
│   ├── constraint_guard.py  # Mostly deterministic validation (one LLM-backed check: validate_place_exists)
│   ├── expert_constraints.py # Pydantic models + constraint data for LocalExpert LLM output
│   ├── input_gate_config.py # Input gate threshold constants (dates, travelers, budget)
│   ├── input_gates.py       # Pre-routing input validation (6 gates: Date, Duration, Traveler, Budget, Destination, MessageLength)
│   ├── local_expert.py      # City logistics concierge (Phase A/B architecture)
│   ├── logistics_node.py    # Flight/hotel/activity fetching + safety logic
│   ├── router_extraction.py # LLM-based intent classification + field extraction (RouterOutput schema)
│   ├── specialist_schemas.py # Specialist Pydantic schemas
│   └── vertical_specialist.py # Domain specialist (8 specialists, registry-driven)
├── prompts/
│   └── planner.py           # Dynamic system prompt builder: build_planner_system_prompt()
├── services/
│   ├── __init__.py          # Services package
│   ├── admin_utils.py       # Cache management, debugging, observability, startup validation
│   ├── agent_runner.py      # Turn execution wrapper: run_agent_turn() with cached agent singleton
│   ├── feasibility_service.py # Specialist feasibility checks
│   ├── iata_resolver.py     # IATA airport code resolver (LLM-backed with state caching)
│   ├── itinerary_adapter.py # Thin bridge: GraphState -> ItineraryBuilder
│   ├── section_builder.py   # Strategy section CRUD (upsert, anchor sort, builders)
│   └── state_serde.py       # State serialization: GraphState <-> session_state + NomadicAgentState <-> agent state
├── state/
│   ├── __init__.py          # State exports
│   ├── agent_state.py       # NomadicAgentState (extends AgentState with trip planning context)
│   ├── graph_state.py       # Legacy state models (GraphState, TripPlan, TripSettings, SpecialistConstraint, etc.)
│   └── typed_meta.py        # Typed metadata bridge (TurnMeta, PersistentMeta, get_trip_settings)
└── tools/                   # 6 agent tools
    ├── __init__.py          # Exports all tools
    ├── _parsing.py          # Shared JSON parsing helpers (parse_tiles_json, parse_constraints_json)
    ├── build_itinerary.py   # Wraps ItineraryBuilder.build()
    ├── extract_trip_fields.py # Wraps router_extraction._classify_and_extract_with_llm()
    ├── get_local_intel.py   # Wraps local_expert Phase A (instant skeleton)
    ├── get_specialist_advice.py # Wraps vertical_specialist.generate_specialist_output_llm()
    ├── search_tiles.py      # Wraps logistics_node helpers (flights/hotels/activities)
    └── validate_plan.py     # Wraps constraint_guard checks + input_gates
```

---

## Agent Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PLANNER AGENT (create_agent)                         │
│                                                                              │
│  Created by: create_planner_agent() in agent.py                             │
│  Model: settings.router_model (default gemini-2.5-flash)                    │
│  State: NomadicAgentState (extends AgentState)                              │
│  Streaming: astream_events(version="v2") in plan_graph.py                   │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    MIDDLEWARE STACK (4 layers)                          │ │
│  │                                                                        │ │
│  │  1. ModelSelectionMiddleware  -- upgrades LLM for complex turns        │ │
│  │  2. DynamicPromptMiddleware   -- injects live state into system prompt │ │
│  │  3. TurnLifecycleMiddleware   -- resets turn_meta; merges tool results │ │
│  │  4. SuggestionChipMiddleware  -- template-based chips after response   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         6 AGENT TOOLS                                  │ │
│  │                                                                        │ │
│  │  extract_trip_fields ─── Parse intent + trip fields from user message  │ │
│  │  get_specialist_advice ── Domain strategy (diving, hiking, etc.)       │ │
│  │  search_tiles ─────────── Flights, hotels, activities via providers    │ │
│  │  get_local_intel ──────── Trip Overview card + Phase B enrichment      │ │
│  │  validate_plan ────────── Budget/temporal/safety constraint checks     │ │
│  │  build_itinerary ──────── Day-by-day schedule from tiles + constraints │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Agent decides tool order dynamically based on conversation context.         │
│  No fixed routing graph -- the LLM chooses which tools to call and when.    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Agent Factory (`agent.py`)

```python
def create_planner_agent(
    *,
    model: str | BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Factory: build and return the compiled planner agent graph."""
    # Defaults to settings.router_model (gemini-2.5-flash)
    resolved_model = get_llm_by_model(
        settings.router_model,
        temperature=AGENT_TEMPERATURE,   # 0.4
        max_tokens=AGENT_MAX_TOKENS,     # 4000
    )

    tools = [
        extract_trip_fields,
        get_specialist_advice,
        search_tiles,
        get_local_intel,
        validate_plan,
        build_itinerary,
    ]

    middleware = [
        ModelSelectionMiddleware(),
        DynamicPromptMiddleware(),
        TurnLifecycleMiddleware(),
        SuggestionChipMiddleware(),
    ]

    agent = create_agent(
        model=resolved_model,
        tools=tools,
        system_prompt=initial_prompt,
        middleware=middleware,
        state_schema=NomadicAgentState,
        checkpointer=checkpointer,
        name="nomadic_planner",
    )
    return agent
```

### Turn Execution (`agent_runner.py`)

```python
async def run_agent_turn(
    user_message: str,
    session_state: dict,
    session_id: str,
) -> dict:
    """Execute one agent turn. Restores state, appends HumanMessage, invokes agent."""
    agent = _get_agent()  # Cached singleton via _cached_agent module-level
    state = restore_agent_state(session_state)
    state["messages"].append(HumanMessage(content=user_message))
    result = await agent.ainvoke(state, config={"configurable": {"thread_id": session_id}})
    return serialize_agent_state(result)
```

---

## Agent Tools Reference

| Tool | Wraps | Purpose | Uses InjectedState |
|------|-------|---------|-------------------|
| `extract_trip_fields` | `router_extraction.py` | Parse intent + trip fields from user message | Yes |
| `get_specialist_advice` | `vertical_specialist.py` | Domain-specific strategy (diving, hiking, etc.) | No (explicit params) |
| `search_tiles` | `logistics_node.py` | Flights, hotels, activities via provider cascade | Yes |
| `get_local_intel` | `local_expert.py` | Trip Overview card + Phase B enrichment | No (explicit params) |
| `validate_plan` | `constraint_guard.py` + `input_gates.py` | Budget/temporal/safety constraint checks | Yes |
| `build_itinerary` | `itinerary_builder.py` | Day-by-day schedule from tiles + constraints | Yes |

### Tool Details

**`extract_trip_fields`** (`tools/extract_trip_fields.py`)

Wraps `_classify_and_extract_with_llm()` from `router_extraction.py`. Uses `InjectedState` for auto-populating current trip context. Returns `TripFieldsResult` model_dump(). Tracks `fields_changed` by comparing extracted vs current values.

**`get_specialist_advice`** (`tools/get_specialist_advice.py`)

Wraps `generate_specialist_output_llm()` from `vertical_specialist.py`. Runs feasibility check, LLM generation for Tier 1 specialists, builds strategy section. Returns `SpecialistAdviceResult` model_dump(). 8 specialists: diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari.

**`search_tiles`** (`tools/search_tiles.py`)

Wraps logistics_node.py helpers. Fetches flights/hotels/activities from provider cascade (Google Places -> Mock). Applies no-fly buffer. Uses `_NOFLY_CATEGORIES` frozenset from registry. Hotels and activities fetched in parallel via `asyncio.gather()`.

**`get_local_intel`** (`tools/get_local_intel.py`)

Wraps local_expert Phase A (instant skeleton). Builds Trip Overview card from static constraint data. Stashes Phase B enrichment closure in `_pending_enrichments` dict for fire-and-forget after DB commit. `session_id` is resolved from explicit tool args first, then from `runtime.config.configurable.thread_id` so Phase B enrichments key by real session token when the LLM omits `session_id`. Returns section + constraints + gallery_images + enrichment_status.
Prompt policy should keep this tool explicit: it is intended for user-visible local-info questions (food, safety, transport, culture), not routine planning steps.

**`validate_plan`** (`tools/validate_plan.py`)

Wraps constraint_guard checks + input_gates. Uses `InjectedState` for auto-populating trip fields and tiles/constraints. Runs 6 gate checks (Date, Duration, Traveler, Budget, Destination, MessageLength) + 4 guard checks (budget, temporal, specialist, route). Returns valid/violations/warnings/blocking_count.
Also runs day-preference capacity checks from `trip_settings.activity_settings.day_preferences` and returns blocking `DAY_PREFERENCE_EXCEEDS_CAPACITY` when user-requested activity days exceed available trip days after no-fly-buffer adjustments.

**`build_itinerary`** (`tools/build_itinerary.py`)

Wraps `ItineraryBuilder.build()`. Uses `InjectedState`. Parses tiles/constraints JSON via shared `_parsing.py` helpers, builds strategy sections from tiles, constructs `ItineraryBuilderInput`, delegates to builder. Returns success/day_cards/conflicts/activities_placed/dropped.
When the user message already contains destination, dates, and activity intent, planner routing expects an automatic chain through extract/specialist/tiles/validation/build in a single turn (unless validation blocks completion).

### InjectedState Pattern

Tools that need access to current trip context use `Annotated[Optional[dict], InjectedState]` to auto-populate from the agent's state. The injected dict contains trip_plan, tiles, constraints, and other state fields.

```python
@tool
async def validate_plan(
    state: Annotated[Optional[dict], InjectedState] = None,
) -> dict:
    """Validate the current plan against constraints."""
    trip_plan = state.get("trip_plan", {}) if state else {}
    # ... run checks ...
```

---

## Middleware Stack

Middleware is applied outermost-first: ModelSelection > DynamicPrompt > TurnLifecycle > SuggestionChip.

### ModelSelectionMiddleware (`awrap_model_call`)

Upgrades the LLM from the fast model (`settings.router_model`) to the planning model (`settings.synthesizer_planning_model`) for complex turns.

**Upgrade triggers:**
- `S0_BOOTSTRAP` phase with >4 messages (indicates initial full planning)
- 3+ tool calls in the current turn (complex multi-tool turn)

```python
def _should_upgrade(self, state: dict, messages: list) -> bool:
    persistent_meta = state.get("persistent_meta", {})
    turn_meta = state.get("turn_meta", {})
    # Condition 1: bootstrap phase with enough context
    if persistent_meta.get("plan_view_state") == "S0_BOOTSTRAP" and len(messages) > 4:
        return True
    # Condition 2: many tool calls in this turn (from turn_meta counter)
    if turn_meta.get("tool_call_count", 0) >= 3:
        return True
    return False
```

### DynamicPromptMiddleware (`awrap_model_call`)

Rebuilds the system prompt from live state on every model call. Uses `build_planner_system_prompt(state_dict)` from `prompts/planner.py`.

The prompt template includes:
- `{specialist_list}`: Rendered from `SPECIALIST_REGISTRY` + `TIER2_COMMON_HINTS`
- `{trip_state_summary}`: Rendered from current agent state (destination, dates, tiles, strategy sections, etc.)

### TurnLifecycleMiddleware (`abefore_agent`, `awrap_tool_call`)

**`abefore_agent`:** Resets turn_meta at the start of each agent turn.

**`awrap_tool_call`:** After each tool call completes:
1. Increments tool call counter
2. Merges tool results into agent state via `_TOOL_MERGERS` dispatch table
3. Wraps result in `Command(update=...)` for state update

**Merge dispatch table:**
```python
_TOOL_MERGERS = {
    "extract_trip_fields": _merge_trip_fields,
    "search_tiles": _merge_tiles,
    "get_specialist_advice": _merge_specialist,
    "get_local_intel": _merge_local_intel,
    "validate_plan": _merge_validation,
    "build_itinerary": _merge_itinerary,
}
```

`_merge_trip_fields` applies both additive updates and explicit clear/remove intents:
- `removal_targets` removes categories/hints case-insensitively from existing `trip_plan` state.
- `reset_budget` clears `trip_plan.budget`.
- `reset_hotel` clears hotel constraints (`min_stars=0`, `amenities=[]`).
- Extracted preference fields persist to nested `trip_settings` sub-dicts (`flight_settings`, `hotel_settings`, `activity_settings`) instead of legacy flat keys.
- `_merge_trip_fields` now auto-derives `trip_plan.end_date` when missing from `start_date + duration_days`.
- Activity day preferences from `activity_day_preferences` are JSON-parsed into `trip_settings.activity_settings.day_preferences`.
- Setting `origin` automatically flips `trip_settings.booking_types.flights` from `off` to `suggested`.
- `_merge_trip_fields` also runs a capacity pre-check for `day_preferences` and writes blocking violations to `turn_meta.validation_result` so constraints surface before a build attempt can complete.
- `_merge_*` mergers append structured `turn_steps` summaries into `turn_meta` (`trip_update`, `preference`, `tiles`, `specialist`, `local_intel`, `validation`, `itinerary`). `_build_complete_envelope()` uses these `turn_steps` for per-turn `ack_updates`.

### SuggestionChipMiddleware (`aafter_model`)

Generates template-based suggestion chips (no LLM) after the final model response (when last message is AIMessage with no tool_calls).

Uses `_generate_chips_from_state()` which inspects current state to produce contextually relevant chips.
`SuggestionChipMiddleware` stores chip payloads in `persistent_meta["suggestion_chips"]`, which `_build_complete_envelope()` mirrors into the complete event.

---

## Library Modules (Surviving Node Code)

These modules survived the architecture migration. They are no longer standalone LangGraph nodes -- they are library code wrapped by the agent tools. They retain their internal logic and can still be called directly for testing.

### RouterExtraction (`router_extraction.py`)

LLM-based intent classification + field extraction. Single LLM call produces `RouterOutput` schema.

**Key functions:**
- `_classify_and_extract_with_llm()` -- Core extraction (wrapped by `extract_trip_fields` tool)
- `_validate_extraction()` -- Post-extraction validation
- `_populate_trip_plan_from_router_output()` -- Applies extracted fields to TripPlan

**RouterOutput Schema:**

```python
class RouterOutput(BaseModel):
    """Combined intent classification + field extraction."""
    # Intent classification
    intent: Literal["GREETING", "RESET", "PLANNING"]
    confidence: float  # 0.0-1.0
    reasoning: str

    # Specialist & activity detection
    specialist_hints: List[str] = []
    activity_categories: List[str] = []
    activity_day_preferences: Optional[str] = None  # JSON string

    # Core trip fields
    destination: Optional[str] = None
    origin: Optional[str] = None
    origin_iata: Optional[str] = None
    destination_iata: Optional[str] = None
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None
    duration_days: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    budget: Optional[float] = None

    # Flags
    has_dates_in_message: bool = False
    has_activity_in_message: bool = False
    planning_ready: bool = False

    # Modification intents
    removal_targets: List[str] = []
    skill_level: Optional[str] = None
    reset_budget: bool = False
    reset_hotel: bool = False

    # Settings extraction
    hotel_min_stars: Optional[int] = None
    hotel_style: Optional[str] = None
    hotel_amenities: List[str] = []
    hotel_location: Optional[str] = None
    flight_direct_only: Optional[bool] = None
    flight_cabin_class: Optional[str] = None

    # Intent classification
    planning_intent: Optional[str] = None
    question_type: Optional[str] = None
```

### VerticalSpecialist (`vertical_specialist.py`)

Domain specialist with LLM-first architecture. 8 specialists (diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari).

**Key functions:**
- `generate_specialist_output_llm()` -- Core LLM generation (wrapped by `get_specialist_advice` tool)
- `generate_all_specialists_parallel()` -- Batch parallel execution with caching

**LLM-first architecture:** Single LLM call generates feasibility + activities + constraints. Falls back to minimal safety constraints if LLM fails (parse error, timeout).

Uses `_SPECIALIST_FLAT_SCHEMA` (inlined `$defs` via `resolve_schema_refs()`) for Gemini function calling compatibility.

### LocalExpert (`local_expert.py`)

City logistics concierge with Phase A/B architecture.

**Phase A (instant):** Static skeleton from constraint data. Returns Trip Overview card immediately. Stashes Phase B enrichment closure in `_pending_enrichments` dict.

**Phase B (background):** LLM enrichment fired after DB commit in `streaming.py`. Uses `build_enrichment_closure()`, with module-level `_pending_enrichments` dict, `_pending_lock`, and `_active_destination_enrichments` set for dedupe.

### LogisticsNode (`logistics_node.py`)

Flight/hotel/activity fetching with safety logic. ~1764 lines.

**Provider cascade:** Google Places -> Mock in logistics_node; Curated -> Google Places -> Mock in tile_service/service.py.

**Key features:**
- Separate cache key hashes for hotels/activities/flights
- Two-tier activity system (Tier 1 specialist + Tier 2 experience)
- No-fly safety logic (registry-driven via `_NOFLY_CATEGORIES`)
- Hotels and activities fetched in parallel via `asyncio.gather()`

### ConstraintGuard (`constraint_guard.py`)

Mostly deterministic validation. One LLM exception: `check_route_constraint()` calls `validate_place_exists()` (via `validation_cache.py`, LLM-backed with TTL caching).

**Checks:**
- `check_budget_constraint()` -- Total cost vs budget allocation (30/40/30 split)
- `check_temporal_constraints()` -- Date validity, duration limits
- `check_specialist_constraints()` -- Registry-driven departure buffer + cross-domain
- `check_route_constraint()` -- Same-city error + unknown destination (LLM-backed)
- `_check_cross_domain_from_sections()` -- Stateless section-driven cross-domain check

**ConstraintGuard class** still exists and provides `check_all()` for the validate_plan tool.

**Arrangement validation** (`validate_block_arrangement()`) for drag-and-drop reordering is also in this file.

### InputGates (`input_gates.py`)

Pre-routing input validation. 6 gates with fail-open exception handling.

| Gate | Severity | Checks |
|------|----------|--------|
| DateGate | blocking | Past dates, too far future, invalid format |
| DurationGate | blocking/warning | Too short (<1d), too long (>max), long warning |
| TravelerGate | blocking | Children without adult, too many travelers |
| BudgetGate | blocking/warning | Too low, extreme, high warning |
| DestinationGate | warning | Multi-destination detection |
| MessageLengthGate | blocking | Message length (placeholder, defense-in-depth) |

---

## Itinerary Builder Service

**Location:** `backend/app/services/itinerary_builder.py`

**Purpose:** Pure Python service that transforms specialist outputs into chronological, constraint-validated timeline. Supports multi-specialist trips with conflict resolution.

**NOT an agent tool directly** -- called by the `build_itinerary` tool, from `format_result()` shadow mode, and from `/api/expand-itinerary`.

### Algorithm Phases

```
┌─────────────────────────────────────────────────────────────────┐
│  ItineraryBuilder.build() Algorithm                             │
│                                                                  │
│  1.    Day Skeleton - DayCard[] from dates                      │
│  2.    Extract Specialist Content - Activities + constraints    │
│  2a.   Constraint Merge - Priority resolution (BLOCKING>STRONG) │
│  2b.   Early Conflict Detection - Irreconcilable check         │
│  3.    Anchor Placement - Arrival/departure from flights       │
│  4.    Buffer Injection - Safety blocks by severity            │
│  5.    Activity Distribution - Round-robin interleaving        │
│  5.24  Day Preference Capping - User activity count limits     │
│  5.25  Preferred Activity Placement - Hearted tiles (2-pass)   │
│  5.5   Free Day Placeholders - Empty day handling              │
│  5.55  Restore Browse-Pinned Tiles - User-added Google Places  │
│  5.6   Experience Tile Placement - Tier 2 on free/spare days   │
│  6.    Tile Matching - Hotels span all days, preferences weighted│
│  6.5   Constraint Tagging - Inline constraints for frontend      │
│  6.75  Chronological Sort - Final block ordering                 │
│  7.    Temporal Conflict Detection - Post-placement overflow     │
│                                                                  │
│  Called from: build_itinerary tool + format_result() (shadow     │
│              at S2) + /api/expand-itinerary                      │
└─────────────────────────────────────────────────────────────────┘
```

**Early Conflict Detection (Pre-Phase Validation)**

Before running phases, the builder validates capacity to detect irreconcilable conflicts early:

```python
# Per-specialist capacity check (NOT global buffer subtraction)
usable_days = total_days - 2  # Arrival/departure days

# Diving: must finish 24h before departure if no-fly constraint
diving_slots = usable_days - buffer_days if nofly_constraint else usable_days
if len(diving_activities) > diving_slots:
    auto_truncate(diving_activities, diving_slots)  # Silent trim, no conflict

# Cross-domain (diving + altitude): trim-before-conflict
# Only raises BLOCKING conflict when available_after_buffer < 2
# (can't fit even 1 dive + 1 hike). Otherwise trims evenly.
available_after_buffer = usable_days - altitude_buffer
if available_after_buffer >= 2:
    dive_slots = (available_after_buffer + 1) // 2  # ceiling -- diving gets remainder
    altitude_slots = available_after_buffer - dive_slots
    trim(diving, dive_slots); trim(altitude, altitude_slots)
else:
    conflict("Cannot fit diving + buffer + altitude in trip")

# Total capacity: activities can share days via interleaving
max_capacity = usable_days * MAX_BLOCKS_PER_DAY  # 3 blocks/day
if total_activity_days > max_capacity:
    auto_truncate_proportionally()  # Silent trim, no conflict
```

**Key Insight:** The no-fly buffer only restricts DIVING placement, not total capacity. Day 7 of an 8-day trip can have hiking activities even though diving is blocked (24h before flight). The buffer doesn't reduce total trip capacity -- it restricts which activities can go where.

**Cross-Domain Trim Math:** For a trip with diving + altitude activities and a 24h buffer:

| Trip | Usable | After buffer | Dive slots | Altitude slots | Result        |
| ---- | ------ | ------------ | ---------- | -------------- | ------------- |
| 5d   | 3      | 2            | 1          | 1              | Trimmed       |
| 7d   | 5      | 4            | 2          | 2              | Trimmed       |
| 9d   | 7      | 6            | 3          | 3              | Trimmed       |
| 3-4d | 1-2    | 0-1          | --         | --             | Real conflict |

**Two-Layer No-Fly Enforcement:**

1. **Phase 2b (Count):** Truncates diving activity count to fit available slots (`diving_slots = usable_days - buffer_days`)
2. **Phase 6.5 (Inline Display):** Tags the last dive block with a `no_fly_buffer` inline constraint badge when within 2 days of departure. Phase 4 (`_inject_safety_buffers`) no longer inserts standalone "No-Fly Day" buffer cards -- the constraint is shown as an inline badge on the relevant dive activity instead.

**Cross-Domain Clustering (Phase 4 -- `no_altitude_after_dive`):**

When the `no_altitude_after_dive` constraint is present and both diving and altitude activities (hiking, trekking, mountaineering, skiing, climbing) exist, `_distribute_activities` bypasses round-robin and uses ordered clustering:

1. **Phase A:** All diving activities placed on earliest available days
2. **Phase B:** One buffer/rest day inserted after last dive day
3. **Phase C:** All altitude activities placed after the buffer
4. **Phase D:** Co-schedule remaining specialists onto existing days using capacity-based scoring (replaces slot_ptr). Scores each candidate day: `headroom * 0.6 + complement * 0.4`. Buffer days only block altitude specialists (not e.g. surfing). Max 1 activity per specialist per day. When Tier 2 categories exist, reserves 1 block + 2h per day so Phase 5.6 has room for experience tiles. Unplaced activities defer to round-robin fallback.

This ensures the 24h decompression gap is respected in the schedule layout. The constraint is detected via `_find_constraint(constraints, "no_altitude_after_dive")` and the `constraints` parameter is now passed from the call site at Phase 5.

```
Example: 9-day Bali trip with diving + hiking
Day 1: Arrival
Day 2: Dive 1 (Tulamben)
Day 3: Dive 2 (Nusa Penida)
Day 4: Dive 3 (Menjangan)
Day 5: REST -- decompression buffer
Day 6: Hike 1 (Mt Batur)
Day 7: Hike 2 (Campuhan Ridge)
Day 8: Hike 3 (Sekumpul)
Day 9: Departure
```

**Phase 5.24: Day Preference Capping**

**Hallucination Guard:** `_parse_day_preferences(raw, user_text)` rejects LLM-inferred day counts when the user message contains no digits -- the LLM is hallucinating counts from trip duration. Only explicit user statements like "3 days diving" produce valid preferences. Additionally, parsed preferences are scoped to categories mentioned this turn (`activity_categories + specialist_hints`) to prevent the LLM from hallucinating day counts for categories the user didn't reference.

When `activity_day_preferences` are set (e.g., `{"diving": 3, "hiking": 2}`), the builder caps each specialist's activity list to the user-requested count BEFORE cross-domain clustering or round-robin. The cap is a maximum -- if only 2 diving activities exist but user asked for 3, all 2 are placed. Remaining specialists (without day preferences) fill leftover days via the existing distribution logic.

**Phase 5.25: Preferred Activity Placement (Two-Pass)**

After creating free day placeholders, the builder populates days with user-preferred activities (hearted tiles). Uses a two-pass strategy:

1. **Pass 1 (Unified Slot Model):** Collects preferred tiles from `preferences.preferred_activity_ids`. **D3 category filter:** Before collecting, each tile is checked against `self._active_categories` (derived from `input_data.activity_categories`, set at `ItineraryBuilder.__init__`). If the user has explicitly set categories (`activity_categories is not None`) and a tile's category is not in the active set, it is skipped. Builds slot map (3 periods per day), places via round-robin on least-loaded days.
2. **Pass 2 (Co-Schedule Fallback):** Tiles that couldn't fit in Pass 1 are deferred. Re-scans using `_day_remaining_capacity()` + `_time_slot_score()` for hour-based placement on specialist days with spare capacity.

Activity blocks created this way have `preference_status: "user_preferred"` for UI attribution.

**Phase 6: Constraint Tagging (Inline Display)**

After distributing activities, the builder tags blocks with relevant constraints for inline UI display.

Each specialist type has its own constraint generator:

**Constraint Types:**
| ID | Severity | Specialist | Description |
|----|----------|------------|-------------|
| `no_fly_buffer` | warning | diving | 24h before departure flight |
| `surface_interval` | info | diving | General dive safety intervals |
| `fitness_required` | info | hiking | Intermediate+ fitness level |
| `early_start_recommended` | info | hiking | Morning departure recommended |
| `avalanche_awareness` | warning | skiing | Off-piste/backcountry safety |
| `advanced_terrain` | info | skiing | Black diamond skill level |
| `tide_timing` | info | surfing | Check swell/tide forecast |
| `altitude_acclimatization` | warning | climbing | Above 3000m elevation. Only fires when specialist sets `requires_acclimatization=True`. Skipped on cross-domain diving trips. Placed on first free interior day before first altitude-activity; fallback to first free interior day (>=4-day trips only) |
| `gear_inspection` | info | climbing | Equipment safety check |
| `weather_window` | info | sailing | Check weather conditions |
| `guide_required` | info | wildlife_safari | Professional guide for game drives |
| `proximity_optimized` | success | hotel | Location optimized for activities |

**Result Metrics:**

- `total_activities_input`: Activities fed into distribution
- `total_activities_placed`: Activities actually placed on timeline (excludes buffers, logistics, free days)
- Drop ratio (`1 - placed/input`) is captured in `turn_meta['builder_result']` (via `success`, `placed`, and `dropped` counters) for guard suppression and suggestion-chip telemetry

**Preference Weighting:**

- User heart preferences passed via `PreferenceOverrideInput`
- Preferred hotels get 1.5x score multiplier
- Preference attribution badges: "user_preferred", "ai_selected", "ai_override"

**Conflict Detection:**

- Temporal capacity (>11h activities per day)
- Constraint clash (diving + high-altitude hiking same day)
- Cross-domain constraint clash (diving + hiking within 24h buffer via `no_altitude_after_dive`)
- Insufficient days for planned activities

**Cross-Domain Constraints:** Declarative `CrossDomainBlock` entries on the specialist registry enforce temporal buffers between specialists. Diving's `ALTITUDE_AFTER_DIVE` block prevents scheduling hiking/skiing/climbing within 24h.

Two enforcement layers in the guard:

1. **Block-level** (`check_specialist_constraints()`): Reads `plan.itinerary_blocks` for day-level scheduling conflicts. Only effective when blocks are populated. **Capacity gate:** if the trip has enough days (`available_after_buffer >= 2`), the violation is skipped (builder handles sequencing).
2. **Section-level** (`_check_cross_domain_from_sections(start_date, end_date)`): Reads `persistent.strategy_sections` to detect specialist co-existence. **Capacity-aware:** only emits a violation when the trip is too short for minimum viable (available_after_buffer < 2). **Suppressed on subsequent turns** when the corresponding builder constraint is already persisted in `existing_rules`. Mapping: `_violation_to_constraint_rule = {"ALTITUDE_AFTER_DIVE": "no_altitude_after_dive"}`.

**Violation lifecycle:** Turn N (first co-existence, trip long enough): no violation -> builder trims -> constraint injected. Turn N (trip too short): violation fires -> constraint injected -> user informed with suggestion chips. Turn N+1+: constraint already in `existing_rules` -> section-level violation suppressed.

**Constraint Injection (decoupled from violations):** The guard injects `SpecialistConstraint` (e.g. `rule="no_altitude_after_dive"`) whenever specialists co-exist, **regardless of whether a violation was emitted**. This ensures the builder has the constraint for sequencing even when the trip is long enough that no violation fires. Injection iterates over `persistent.executed_strategy_topics` and checks registry `cross_domain_blocks` directly (idempotent via `existing_rules` check).

Data flow: `registry (CrossDomainBlock) -> guard (co-existence check) -> SpecialistConstraint injection -> builder (_find_constraint)`

#### Constraint Alias Normalization

LLMs generate constraint names with natural variation (e.g., `"no_altitude_24h"`, `"altitude_buffer"`, `"no-altitude-after-diving"`). The builder normalizes these via **alias mapping** to ensure robust constraint detection regardless of LLM phrasing.

**Location:** Defined in `backend/app/planner/specialist_registry.py` per specialist, aggregated into `ALL_CONSTRAINT_ALIASES`. Used directly by `itinerary_builder.py`.

```python
# In specialist_registry.py (per specialist config):
constraint_aliases={
    "no_altitude_after_dive": [
        "no_altitude_24h", "altitude_buffer", "no_altitude_after_diving",
        "altitude_restriction_after_dive",
    ],
    "min_24h_buffer_after_dive": [
        "no_fly_24h", "flight_buffer_24h", "no_fly_after_diving",
        "24h_no_fly_after_diving", "no_fly_buffer",
    ],
    "surface_interval": ["min_18h_surface_interval", "dive_surface_interval"],
}

def _find_constraint(
    constraints: List["MergedConstraint"],
    canonical_rule: str,
) -> Optional["MergedConstraint"]:
    """Find constraint by canonical rule name or any of its aliases."""
    aliases = ALL_CONSTRAINT_ALIASES.get(canonical_rule, [])
    all_names = [canonical_rule] + aliases
    for c in constraints:
        rule_lower = c.rule.lower().replace("-", "_").replace(" ", "_")
        for name in all_names:
            if rule_lower == name.lower() or name.lower() in rule_lower:
                return c
    return None
```

**Design Principle:** Builder defines canonical IDs -> LLM outputs flexible natural language -> Builder normalizes for detection. This inverts the typical approach where LLM must match exact constraint names.

### Partial Timeline (Conflict Visualization)

When conflicts are detected, the builder returns a **partial schedule** showing what CAN be scheduled, with unschedulable activities marked.

```python
class DayBlockOutput(BaseModel):
    # ... existing fields
    unschedulable: bool = False
    unschedulable_reason: Optional[str] = None
    unschedulable_days_needed: Optional[int] = None
```

**Frontend Rendering:**

- Unschedulable blocks show with `opacity-60`, dashed amber border
- "Cannot schedule" warning badge with AlertTriangle icon
- Activity title shown with strikethrough
- `unschedulable_reason` displayed as italic amber text

**UX Flow:** Partial timeline auto-renders when `conflicts.length > 0 && day_cards.length > 0`. No extra "Show partial" click needed.

### Post-Arrangement Constraint Recomputation

**Location:** `recompute_constraints_after_arrangement()` in `itinerary_builder.py`

Called by `apply_arrangement` endpoint between `_apply_moves_to_cards` and `save_document_data`. Pure Python, no LLM, <50ms.

**Pass 1: `_recompute_nofly_tags()`** -- Strips and reapplies `no_fly_buffer` tags based on new block positions.

**Pass 2: `_detect_stale_buffers()`** -- Detects orphaned or missing cross-domain buffers after rearrangement.

---

## Structured Output Usage

Pydantic structured output is used for LLM calls that need **guaranteed schema extraction**.

### Tool-by-Tool Status

| Tool / Module | Uses Structured Output? | LLM Used? | Schema(s) | Purpose |
| --- | --- | --- | --- | --- |
| **extract_trip_fields** (via `router_extraction.py`) | Yes | `settings.router_model` (via `llm_factory`) | `RouterOutput` | Intent + field extraction in one call |
| **get_specialist_advice** (via `vertical_specialist.py`) | Yes (function_calling, flattened schema) | `settings.specialist_model` (via `llm_factory`) | `LLMSpecialistOutput` via `_SPECIALIST_FLAT_SCHEMA` | LLM-first with fallback |
| **get_local_intel** (via `local_expert.py`) | Yes (prompt-based) | `settings.local_expert_model` (via `llm_factory`) | `LocalExpertOutput` | Prompt-based JSON; no function_calling |
| **search_tiles** (via `logistics_node.py`) | No | N/A | N/A | API/provider calls only (Curated, Google Places, Mock) |
| **validate_plan** (via `constraint_guard.py`) | No | `settings.guard_model` (place validation only) | N/A | Mostly deterministic |
| **build_itinerary** (via `itinerary_builder.py`) | No | N/A | N/A | Pure Python scheduling |
| **Planner Agent** | No | `settings.router_model` / `settings.synthesizer_planning_model` | N/A | Free-form natural language responses |

### Design Principle

**Rule of thumb:**

- **LLM extracts structured information** -> Use `.with_structured_output(Schema, include_raw=True, method="function_calling")`
- **LLM generates natural language** -> Don't use structured output
- **No LLM (static data, APIs, validation)** -> N/A

**Structured output conventions:**

1. **`include_raw=True`** -- All structured output calls pass `include_raw=True` to access the raw `AIMessage` for token tracking and error diagnostics. The result is a `{"parsed": T | None, "raw": AIMessage}` dict.
2. **`method="function_calling"`** -- Explicit `method="function_calling"` is used for cross-provider compatibility (OpenAI + Gemini).
3. **`parsed is None` guard** -- Every call site checks `if parsed is None: raise ValueError(...)`. No silent fallback to empty data.
4. **`extract_token_usage()`** -- Centralized in `llm_factory.py`. Handles `include_raw=True` dict unwrapping, LangChain 0.2+ `usage_metadata`, and `response_metadata["token_usage"]` fallback.
5. **`resolve_schema_refs(schema)`** -- Inlines `$defs` pointers for Gemini function calling. Used for schemas with few `$defs` (e.g., `LLMSpecialistOutput`: 2). Do NOT use for deeply nested schemas.
6. **`extract_json_content(response)`** -- Extracts JSON string from AIMessage. Handles OpenAI string content, Gemini multi-part list content, and markdown code fence stripping.
7. **`patterns_registry.py`** -- Shared regex/keyword lists used by multiple planner modules. Centralizes `BUDGET_PATTERNS`, `TRAVELER_PATTERNS`, and `SETTINGS_KEYWORDS`.

---

## State Models

### NomadicAgentState (Runtime State)

The agent's runtime state, extending LangChain's `AgentState` with trip planning context.

```python
class NomadicAgentState(AgentState):
    """Agent state with trip planning extensions."""
    # Fields with possible parallel updates use Annotated reducers.
    # Dict/list fields merge by reducer; scalar metadata follows last-write rules.
    trip_plan: Annotated[dict, _merge_dicts]           # TripPlan as dict
    trip_settings: Annotated[dict, _merge_dicts]       # TripSettings as dict
    tiles: Annotated[dict, _merge_dicts]               # {"flights": [], "hotels": [], "activities": []}
    strategy_sections: Annotated[list, _merge_strategy_sections]  # Strategy section dicts
    day_cards: NotRequired[list]          # Itinerary day card dicts
    constraints: Annotated[list, _merge_constraints]    # Constraint dicts
    turn_meta: Annotated[dict, _merge_turn_meta]       # Per-turn metadata (reset each turn)
    persistent_meta: Annotated[dict, _merge_dicts]      # Cross-turn metadata
```

### GraphState (Legacy, used by library modules)

The old unified state model. Still used internally by surviving library modules (constraint_guard, vertical_specialist, etc.) during service migrations.

```python
class GraphState(BaseModel):
    messages: List[BaseMessage]
    trip_plan: TripPlan           # The Single Source of Truth
    intent: Optional[Literal["general", "booking", "specialist"]]
    active_specialist: Optional[str]
    active_agent_id: Optional[str]
    pending_specialists: List[str]
    tiles: Dict[str, List[Dict]]  # {"flights": [], "hotels": [], "activities": []}
    constraints_violated: List[str]
    guard_retry_count: int = 0
    ui_events: List[str]
    last_summary: Optional[str]
    suggested_replies: List[str]
    metadata: Dict[str, Any]
    last_constraint_hash: Optional[str]
```

### TripPlan (SSoT)

Single Source of Truth for the trip's **core dimensions** (who, where, when, budget).

Settings fields (`activity_settings`, `hotel_settings`, `flight_settings`, `transport_settings`, `booking_types`) are typed via the `TripSettings` model (using `get_trip_settings(state)` accessor). The typed settings live in `metadata["trip_settings"]`.

```python
class TripPlan(BaseModel):
    destination: Optional[str]
    origin: Optional[str]
    origin_iata: Optional[str]
    destination_iata: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    travelers: int = 1
    adults: int = 1
    children: int = 0
    budget: Optional[float]
    currency: str = "USD"
    status: Literal["draft", "planning", "ready", "booked"]
    segments: List[TripSegment]
    itinerary_blocks: List[ItineraryBlock]  # DEPRECATED: content now on strategy_sections
    constraints: List[SpecialistConstraint]
    trip_type: Optional[str]
    vibe: Optional[str]
```

### SpecialistConstraint

```python
class SpecialistConstraint(BaseModel):
    constraint_id: str = ""
    type: Literal["temporal", "safety", "equipment", "certification", "budget"]
    rule: str
    severity: ConstraintSeverity = ConstraintSeverity.STRONG
    applies_to: Optional[str]  # DEPRECATED
    applies_to_categories: List[str] = []
    parameters: Dict[str, Any]
    reason: Optional[str]
    label: Optional[str] = None
    icon: Optional[str] = None
    buffer_hours: Optional[int] = None

class ConstraintSeverity(str, Enum):
    BLOCKING = "blocking"  # Safety/Legal - always wins
    STRONG = "strong"      # Optimization - negotiates
    SOFT = "soft"          # Preference - defers
```

### State Serialization (`state_serde.py`)

Two parallel serialization paths:

**Legacy path (GraphState):**
- `state_to_session_state(state)` -- GraphState -> session dict
- `restore_graph_state(session_state)` -- session dict -> GraphState
- `trip_plan_to_trip_inputs(plan)` -- TripPlan -> trip_inputs dict

**Agent path (NomadicAgentState):**
- `serialize_agent_state(state)` -- Agent state dict -> serializable dict (uses `messages_to_dict` for full-fidelity message serde)
- `restore_agent_state(session_state)` -- Serialized dict -> agent state dict (uses `messages_from_dict` + legacy migration for `trip_inputs`/`metadata.tiles`/`metadata.strategy_sections` and flat `trip_settings` normalization)
- `_trim_messages(messages, keep_last=20)` -- Keeps first 2 + last N messages for context window management

---

## Specialist Domain Knowledge

> **SSoT:** All specialist configuration (keywords, constraints, enhancements, flags, backfill affinity) lives in `backend/app/planner/specialist_registry.py`. Top destinations and activities are LLM-generated per prompt file -- no hardcoded destination lists. Tier 2 is open-ended (no fixed validation set). `display_name(category)` provides canonical display names. `backfill_affinity_tags` drives complementary category selection for free-day backfill. Adding a specialist requires only: 1) add entry to `SPECIALIST_REGISTRY`, 2) create `prompts/specialists/{topic}.txt`.

**Fill-Day Validation:** `validate_fill_day_placement(target_day, specialist_type, day_cards, total_days, has_departure_flight)` checks placement against registry constraints: cross-domain buffers on adjacent days, no-fly buffer proximity to departure, arrival/departure day restrictions, and `min_days_needed`. Returns `FillDayRejection(code, reason, suggestion)` or `None` if valid.

### Diving

**Constraints (from registry):**
| Rule | Type | Severity | Cross-Domain |
|------|------|----------|--------------|
| `no_fly_24h` | temporal | blocking | flights |
| `no_altitude_after_dive` | safety | blocking | hiking, trekking, mountaineering, skiing, climbing |

**Registry flags:** `has_geographic_constraint=True`, `has_nofly_buffer=True`, `min_days_needed=4`, `backfill_affinity_tags=["water", "outdoors"]`
**Cross-domain blocks:** `ALTITUDE_AFTER_DIVE` -> skiing, hiking, climbing (24h buffer, blocking)

### Hiking

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `morning_start_recommended` | temporal | soft |
| `proper_footwear_required` | equipment | soft |
| `altitude_acclimatization` | safety | strong |

**Registry flags:** `has_altitude_buffer=True`

### Skiing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `check_snow_conditions` | safety | blocking |

**Registry flags:** `has_geographic_constraint=True`

### Cycling

No hardcoded constraints (LLM-generated only)

### Surfing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `tide_and_swell_check` | safety | soft |
| `reef_awareness` | safety | strong |
| `skill_appropriate_breaks` | equipment | soft |

### Climbing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `altitude_acclimatization` | safety | strong |
| `gear_check_required` | equipment | strong |

**Registry flags:** `has_altitude_buffer=True`, `min_days_needed=3`

### Sailing

No hardcoded constraints (LLM-generated only)

**Backward compat:** Keywords include old "boating" terms; `category_mappings` maps `"boating" -> "sailing"`.

### Wildlife Safari

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `guide_required` | safety | strong |

**Registry flags:** `min_days_needed=3`

---

## Constraint Validation

### Validation Categories

| Category   | Check                                                                              | Severity     | Note                                                                           |
| ---------- | ---------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------ |
| **Route**  | `origin == destination`                                                            | **blocking** | Triggers `SAME_CITY_ERROR`                                                     |
| **Route**  | `validate_place_exists(dest)`                                                      | **blocking** | Triggers `UNKNOWN_DESTINATION_ERROR`                                           |
| Budget     | `total_cost > budget`                                                              | blocking     | `suggested_action="Reduce total spend by $N or increase budget"` |
| Budget     | `category_cost > allocation`                                                       | warning      | `suggested_action="Look for more affordable {category} options"` |
| Temporal   | `end_date < start_date`                                                            | blocking     |                                 |
| Temporal   | `duration > 30 days`                                                               | info         |                                                                                |
| Temporal   | `duration < 1 day`                                                                 | warning      |                                                                                |
| Specialist | Departure buffer (registry: `has_nofly_buffer`)                                    | blocking     | Unfixable                                                                      |
| Specialist | Cross-domain via blocks (registry: `cross_domain_blocks`)                          | blocking     | Unfixable                                                                      |
| Specialist | Cross-domain via sections (stateless fallback)                                     | blocking     | Unfixable                                                                      |
| Capacity   | Activity count > available days                                                    | blocking     |                                 |
| Capacity   | Day preference count > effective days (`DAY_PREFERENCE_EXCEEDS_CAPACITY`)          | blocking     |                                 |
| Capacity   | Multi-specialist aggregate exceeds capacity (`MULTI_SPECIALIST_CAPACITY_EXCEEDED`) | warning      |                                 |

`DAY_PREFERENCE_EXCEEDS_CAPACITY` is now computed by `check_day_preference_capacity()` and considers:
- requested totals from `day_preferences`
- usable trip days as `max(0, total_days - 2)` (arrival/departure removed)
- active no-fly buffers from strategy sections (or activity category fallback)
- effective capacity as `max(0, usable_days - max_buffer)`

This check is executed in both `validate_plan` and `_merge_trip_fields()` so blocking preference-capacity issues can surface before user-visible itinerary build completion.

**Multi-Specialist Aggregate Capacity Check:** Sums activity counts across ALL active specialists. Individual specialist checks may pass, but combined they can exceed timeline capacity (`effective_days * 2` specialist activities max, since specialist activities are 3-5h each). Accounts for cross-domain buffer days. Fires when `len(active_specialists) >= 2` and `total_activities > max_capacity`.

**Builder-Aware Suppression:**
When the ItineraryBuilder persists a constraint rule (e.g., `no_fly_buffer`) and succeeds (`turn_meta["builder_result"]["success"] == True`) with acceptable drop ratio (from `builder_result`), the guard suppresses duplicate violations on the next turn — the builder is already enforcing the constraint via clustering. If the builder **failed** or dropped too much volume, the violation is re-surfaced so the agent can generate resolution chips.

**Deleted checks (handled by specialist LLM feasibility):**

- ~~Geographic: Diving in landlocked country~~ -> specialist `check_feasibility()` returns `infeasible`
- ~~Seasonal: Hiking in winter / Skiing in summer~~ -> specialist LLM prompt includes seasonality
- ~~season.py~~ -> deleted entirely

---

## Caching Architecture

### Cache Implementations

**Two-Tier LLM/API Caches (Cross-Session):**

All caches share a common `MemoryCache` primitive from `backend/app/services/cache_core.py` -- thread-safe `TTLCache` wrapper with `RLock` for cache ops and separate `_stats_lock` for hit/miss counters. Each service instantiates its own `MemoryCache` with domain-specific config (maxsize, TTL, stat keys). L2 writes use the shared `l2_upsert()` function in `cache_core.py` -- a `pg_insert().on_conflict_do_update()` pattern that commits internally.

| Cache | Service File | L1 Size | L1 TTL | L2 TTL | Key Format | Purpose |
|-------|-------------|---------|--------|--------|------------|---------|
| Specialist | `specialist_cache.py` | 128 | 1h | 168h (env: SPECIALIST_CACHE_TTL_HOURS) | `specialist::v2::{topic}::{dest}::{month}::{bucket}::{skill}::{dpref}::{phash}` | LLM outputs |
| Experience | `experience_generator.py` | 128 | 1h | 72h (env: EXPERIENCE_CACHE_TTL_HOURS) | `experience::v2::{dest}::{sorted_cats}::{month}::n{tiles_per_category}` | Tier 2 tiles |
| Tile | `tile_cache.py` | 256 | 24h | 72h (env: TILE_CACHE_TTL_HOURS) | `tile::v2::{provider}::{type}::{dest}::{start_date}::{end_date}[::{variant}]` | Provider API data |
| Browse | `activity_browser.py` | 256 | 6h | 72h (env: TILE_CACHE_TTL_HOURS) | `browse::v2::{dest}::{sorted_cats}::{month}::{center_bucket}` | On-demand Browse Activities tiles |
| Places Enrichment | `google_places_provider.py` | 2048 | 24h | 168h (env: GOOGLE_PLACES_ENRICHMENT_CACHE_TTL_HOURS) | `places::enrich::v2::{dest}::{title}::q{sig}` | Google Places enrich-by-title lookups |
| Router | `router_cache.py` | 500 | 1h | N/A | `router::v2::SHA256({text}:{date})[:32]` | NL extraction |

**Database Table:** `response_cache` with `cache_type` column for filtering (values: `'specialist'`, `'experience'`, `'experience_single'`, `'tiles'`). Browse and Places enrichment L2 entries use `cache_type='tiles'`.

### Cache Invalidation Triggers

| Trigger                  | Caches Invalidated               |
| ------------------------ | -------------------------------- |
| Core fields change       | response, tile                   |
| `end_date` change        | tile                             |
| `adults/children` change | tile                             |
| Strategy topic switch    | response                         |
| Destination change       | `parallel_llm_results` (session) |
| Month change             | `parallel_llm_results` (session) |
| Session timeout          | All                              |

### Validation Cache (Origin/Destination Verification)

Cache infrastructure in `backend/app/validation_cache.py`, validation logic in `backend/app/validation.py`. Stores LLM-verified place names.

| Parameter               | Value           | Purpose                         |
| ----------------------- | --------------- | ------------------------------- |
| `validation_cache_size` | 5000            | Max entries before LRU eviction |
| `validation_cache_ttl`  | 604800 (7 days) | Time before entries expire      |

**Cache Layers:**

| Cache               | Purpose                     | TTL        |
| ------------------- | --------------------------- | ---------- |
| `_validation_cache` | Positive validation results | 7 days     |
| `_negative_cache`   | Invalid locations           | 15 minutes |
| `_split_cache`      | Multi-destination splits    | 7 days     |

### Image Cache (Unsplash)

Two-tier cache for destination images.

**Tier 1: In-Memory Cache**

- Storage: Python dict `_memory_cache` with `asyncio.Lock` for thread safety
- Key format: `"destination:variant"` or `"destination:activity:variant"` (activity-aware)
- Max variants: 6 per destination

**Tier 2: Database Cache**

- Table: `unsplash_image_cache`
- TTL: Permanent
- Primary Key: `(destination, variant)` -- destination key is activity-aware

**Lookup Order:**

1. In-memory cache (async lock, fastest)
2. Database cache (persistent, activity-aware key)
3. Unsplash API (retry + timeout, fresh fetch)
4. Unsplash placeholder fallback (deterministic seed-based)

### Specialist LLM Cache

Two-tier cache for VerticalSpecialist LLM outputs. Reduces LLM calls by ~86% for repeated destination/activity queries.

**Service:** `backend/app/services/specialist_cache.py`

**Cache Key Components:**
| Component | Example | Purpose |
|-----------|---------|---------|
| topic | `diving` | Specialist type |
| destination | `bali` | Normalized lowercase |
| month | `2025-02` | YYYY-MM from start_date (seasonal bucketing) |
| bucket | `week` | Duration bucket: weekend(1-3d), short(4-5d), week(6-8d), extended(9-11d), twoweek(12-15d), long(16d+) |
| skill | `advanced` / `any` | User skill level |
| dpref | `dp5` / `dpany` | Day preference count for this topic |
| phash | `9c22ff5f` | 8-char blake2s hash of prompt file (auto-invalidates on edit) |

**Lookup Order:**

1. L1 in-memory (thread-safe) -> ~1ms
2. L2 PostgreSQL -> ~50ms (promotes to L1 on hit)
3. LLM API call -> ~5s (writes to both layers)

### Router Extraction Cache

L1-only cache for NL extraction results. Only caches self-contained queries to prevent cross-conversation pollution.

**Service:** `backend/app/services/router_cache.py`

**CRITICAL: Context-Dependency Detection** -- Queries that reference conversation context are NOT cached:

| Query                                  | Cacheable | Reason                     |
| -------------------------------------- | --------- | -------------------------- |
| "I want to go diving in Bali Feb 1-14" | Yes       | Self-contained             |
| "Show me diving there"                 | No        | "there" depends on context |
| "Same dates as before"                 | No        | "same" depends on context  |

---

## Selective Regeneration

Selective regeneration minimizes LLM calls when trip inputs change by computing the minimum required execution path based on which fields changed.

### Strategy Tiers (Lowest to Highest Cost)

| Strategy        | Trigger Fields                                                                              | Execution Path                    | Est. Time | LLM Calls             |
| --------------- | ------------------------------------------------------------------------------------------- | --------------------------------- | --------- | --------------------- |
| **BUILDER**     | `preferred_tile_ids` / `preferences`, `origin`                                              | ItineraryBuilder only             | ~100ms    | None                  |
| **LOGISTICS**   | `adults`, `children`, `budget`, `flight_settings`, `hotel_settings`, `activity_skill_level` | Tile fetching + Builder           | ~500ms    | None (API calls only) |
| **SPECIALISTS** | `start_date`, `end_date`, `activity_categories`                                             | Specialists + Tiles + Builder     | ~3-8s     | Yes                   |
| **FULL**        | `destination`                                                                               | Full re-execution                 | ~10-15s   | Yes                   |

### Field-to-Strategy Mapping

```python
# backend/app/services/regen_strategy.py
FIELD_IMPACT: Dict[str, RegenStrategy] = {
    "destination": RegenStrategy.FULL,
    "dates": RegenStrategy.SPECIALISTS,
    "activity_categories": RegenStrategy.SPECIALISTS,
    "travelers": RegenStrategy.LOGISTICS,
    "budget": RegenStrategy.LOGISTICS,
    "flight_settings": RegenStrategy.LOGISTICS,
    "hotel_settings": RegenStrategy.LOGISTICS,
    "activity_skill_level": RegenStrategy.LOGISTICS,
    "origin": RegenStrategy.BUILDER,
    "preferences": RegenStrategy.BUILDER,
}
```

### Settings Ownership & Document Merge

User-configurable settings (`activity_settings`, `hotel_settings`, `flight_settings`, `transport_settings`, `booking_types`) follow a strict ownership model to prevent stale graph state from overwriting user intent.

**Ownership Rule:** The document (written by `PATCH /api/document`) is the SSoT for these fields.

**Three-layer defense:**

| Layer          | File                                                 | What it does                                                                                                                                                                                 |
| -------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Emission       | `state_serde.py` `trip_plan_to_trip_inputs()`        | Settings fields **omitted** from TripPlan conversion                                                                                                                                         |
| Restoration    | `state_serde.py` + `plan_graph.py` complete envelope assembly | Reads typed `TripSettings` via `get_trip_settings(state)` and serializes sub-models into output `trip_inputs`                                                                                |
| Input merge    | `streaming.py` (SSE endpoint)                        | `_USER_OWNED_SETTINGS` guard -- document baseline wins for settings fields                                                                                                                   |
| Output persist | `crud_document.py` `apply_planner_update()`          | Strips settings from graph output before `merge_trip_inputs()`                                                                                                                               |

---

## Prompt File Mapping

### Prompts

```
backend/app/planner/prompts/
└── planner.py                 # Dynamic system prompt builder (build_planner_system_prompt)

backend/app/prompts/
└── specialists/
    ├── climbing.txt               # VerticalSpecialist - climbing domain
    ├── cycling.txt                # VerticalSpecialist - cycling domain
    ├── diving.txt                 # VerticalSpecialist - diving domain
    ├── generic_activity.txt       # VerticalSpecialist - fallback for unmatched categories
    ├── hiking.txt                 # VerticalSpecialist - hiking domain
    ├── local_expert.txt           # LocalExpert - city logistics prompt
    ├── sailing.txt                # VerticalSpecialist - sailing domain
    ├── skiing.txt                 # VerticalSpecialist - skiing domain
    ├── surfing.txt                # VerticalSpecialist - surfing domain
    └── wildlife_safari.txt        # VerticalSpecialist - wildlife safari domain
```

### Prompt Purpose Summary

| File                              | Used By            | Purpose                                                   |
| --------------------------------- | ------------------ | --------------------------------------------------------- |
| `planner/prompts/planner.py`      | Planner Agent      | Dynamic system prompt with `{specialist_list}` and `{trip_state_summary}` placeholders. Rebuilt from live state each model call via `DynamicPromptMiddleware`. |
| `specialists/climbing.txt`        | VerticalSpecialist | Climbing domain knowledge                                 |
| `specialists/cycling.txt`         | VerticalSpecialist | Cycling domain knowledge                                  |
| `specialists/diving.txt`          | VerticalSpecialist | Diving domain knowledge                                   |
| `specialists/generic_activity.txt` | VerticalSpecialist | Fallback prompt for unmatched activity categories          |
| `specialists/hiking.txt`          | VerticalSpecialist | Hiking domain knowledge                                   |
| `specialists/local_expert.txt`    | LocalExpert        | City logistics prompt                                     |
| `specialists/sailing.txt`         | VerticalSpecialist | Sailing domain knowledge                                  |
| `specialists/skiing.txt`          | VerticalSpecialist | Skiing domain knowledge                                   |
| `specialists/surfing.txt`         | VerticalSpecialist | Surfing domain knowledge                                  |
| `specialists/wildlife_safari.txt` | VerticalSpecialist | Wildlife safari domain knowledge                          |

### Deleted Prompts

| File | Was Used By | Status |
|------|-------------|--------|
| `synthesizer.txt` | Synthesizer node | Deleted -- agent generates responses directly |

---

## Streaming Architecture

### Current Implementation: Agent Streaming via astream_events

Uses `astream_events(version="v2")` for real-time token streaming from the planner agent.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STREAMING FLOW (plan_graph.py)                                             │
│  ──────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  1. User sends message                                                       │
│  2. run_turn_streaming() restores state, invokes agent.astream_events()     │
│  3. Events emitted:                                                          │
│     - on_chat_model_stream: LLM tokens -> token events                      │
│       (filtered: tool-calling reasoning not streamed)                        │
│     - Tool completions: partial events (trip_inputs, tiles, strategy)        │
│     - Final: complete event with full result envelope                        │
│  4. "complete" event with full result                                        │
│                                                                              │
│  Intermediate reasoning filter: _current_invocation_has_tools flag           │
│  prevents streaming tool-calling reasoning text to frontend                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Streaming Events

| Event Type     | Data                              | Description                                                    |
| -------------- | --------------------------------- | -------------------------------------------------------------- |
| `node_status`  | `{node, status, label, icon_key, estimated_duration_ms}` | Tool progress tracking (from `_TOOL_STATUS_MAP`)              |
| `token`        | `string`                          | Response text (from agent LLM, filtered for tool-calling)      |
| `partial`      | `{kind: "strategy_sections"\|"tiles"\|"trip_inputs", payload: any}` | Progressive render -- emitted when a tool completes with partial data. `extract_trip_fields` -> `trip_inputs`; `get_specialist_advice`/`get_local_intel` -> `strategy_sections`; `search_tiles` -> `tiles` (payload is ID-keyed tile map, same shape as `document.tiles`). |
| `complete`     | `{...result}`                     | Full result object (from `_build_complete_envelope()`)         |
| `error`        | `{message}`                       | Error information                                              |

### Tool Status Map (`_TOOL_STATUS_MAP`)

Maps tool names to UI labels, icons, and estimated durations for frontend progress tracking.

### Tool Partial Kinds (`_TOOL_PARTIAL_KIND`)

Maps tools to partial event kinds:
- `extract_trip_fields` -> `trip_inputs`
- `search_tiles` -> `tiles`
- `get_specialist_advice` / `get_local_intel` -> `strategy_sections`

### Complete Envelope (`_build_complete_envelope()`)

Builds the final complete event with document dict including `plan_view_state`, `tiles`, `strategy_sections`, `itinerary_day_cards`, `constraint_violations`, `constraints_validated`, `suggested_responses`, etc.

When `destination`, `start_date`, and `end_date` are present and there are both strategy sections and tiles, `_build_complete_envelope()` auto-runs the builder if `build_itinerary` was not explicitly called in the turn and no blocking validation errors exist. This allows auto-expansion into `itinerary_day_cards` and populates `turn_meta.builder_result` with placement/conflict metrics.

### DB Session Ownership

`generate_sse()` in `streaming.py` creates and owns its own DB session via `_get_async_session_factory()` (not injected by caller). The streaming generator is fully self-contained.

---

## Tile Service Architecture

### Provider Architecture

```
tile_service/
├── __init__.py               # Exports: search_tiles + booking types
├── models.py                 # SearchContext, TileSearchRequest
├── service.py                # search_tiles() orchestrator
├── provider_base.py          # Provider ABC + BookableProvider ABC
├── mock_provider.py          # Mock providers for development
├── google_places_provider.py # Google Places API (hotels + activities; async-first)
└── curated_provider.py       # Curated content for hero destinations
```

### Provider Routing Consistency

The `search_tiles` tool (via logistics_node) and `tile_service/service.py` both use a 3-tier cascade:

**`search_tiles` tool routing (3-tier via logistics_node):**

| Priority | Condition                            | Hotels                    | Activities                    |
| -------- | ------------------------------------ | ------------------------- | ----------------------------- |
| 1        | `USE_GOOGLE_PLACES_PROVIDER=true`    | GooglePlacesHotelProvider | GooglePlacesActivityProvider  |
| 2        | Fallback (offline/dev)               | MockHotelProvider         | MockActivityProvider          |

**`tile_service/service.py` routing (3-tier):**

| Priority | Condition                            | Hotels                    | Activities                    |
| -------- | ------------------------------------ | ------------------------- | ----------------------------- |
| 1        | Curated destination                  | CuratedProvider           | CuratedProvider               |
| 2        | `USE_GOOGLE_PLACES_PROVIDER=true`    | GooglePlacesHotelProvider | GooglePlacesActivityProvider  |
| 3        | Fallback (offline/dev)               | MockHotelProvider         | MockActivityProvider          |

### Settings-Aware Tile Filtering

| Setting Type                    | Filter Applied                                      | Budget Allocation |
| ------------------------------- | --------------------------------------------------- | ----------------- |
| `budget` (hotels)               | `tile.price_estimate <= budget * 0.40`              | 40%               |
| `budget` (activities)           | `tile.price_estimate <= budget * 0.30`              | 30%               |
| `budget` (flights)              | `tile.price_estimate <= budget * 0.30`              | 30%               |
| `hotel_settings.min_stars`      | `tile.rating >= min_stars`                          | -                 |
| `flight_settings.direct_only`   | `tile.meta.stops == 0`                              | -                 |
| `activity_settings.skill_level` | `tile_skill_level <= user_skill_level`              | -                 |

---

## Booking Provider Interface (Scaffolding)

> **Status:** Interface defined, real provider implementation deferred until API access.

### Design Decision

**Booking = REST endpoints, NOT agent tools**

| Reason           | Detail                                        |
| ---------------- | --------------------------------------------- |
| Explicit consent | Financial transactions need user confirmation |
| No LLM reasoning | Simple CRUD operations                        |
| Audit trail      | Different error handling requirements         |
| PCI compliance   | Payment data handling considerations          |

### Booking Flow Types

```python
class BookingFlowType(Enum):
    REDIRECT = "redirect"   # User sent to partner checkout
    EMBEDDED = "embedded"   # Booking within our app
    HYBRID = "hybrid"       # API hold, redirect for payment
```

### Booking Status States

```
INITIATED -> PENDING_PAYMENT -> HOLD -> CONFIRMED
                 |              |
              FAILED         EXPIRED
                 |
            CANCELLED
```

---

## Key Exports

| Module              | Exports                                                                                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `planner`           | `create_planner_agent`, `run_turn_streaming`, `NomadicAgentState`                                                                                              |
| `planner.state`     | `GraphState`, `TripPlan`, `TripSegment`, `ItineraryBlock`, `SpecialistConstraint`, `SpecialistStateOutput`                                                     |
| `planner.state.agent_state` | `NomadicAgentState`                                                                                                                                   |
| `planner.hashing`   | `stable_hash`, `stable_hash_short`, `canonicalize_destinations`, `make_cache_key`                                                                              |
| `planner.nodes`     | `VerticalSpecialist`, `vertical_specialist`, `ConstraintGuard`, `constraint_guard`, `local_expert`, `logistics_node`                                           |
| `planner.tools`     | `extract_trip_fields`, `get_specialist_advice`, `search_tiles`, `get_local_intel`, `validate_plan`, `build_itinerary`                                          |
| `planner.middleware` | `ModelSelectionMiddleware`, `DynamicPromptMiddleware`, `TurnLifecycleMiddleware`, `SuggestionChipMiddleware`                                                   |

---

## Admin Cache Management Endpoints

| Endpoint                            | Method | Purpose                                                                         |
| ----------------------------------- | ------ | ------------------------------------------------------------------------------- |
| `/api/admin/cache-stats`            | GET    | Unified stats for all caches (specialist, tile, router)                         |
| `/api/admin/specialist-cache-stats` | GET    | Specialist cache hit/miss statistics                                            |
| `/api/admin/tile-cache-stats`       | GET    | Tile cache hit/miss statistics                                                  |
| `/api/admin/router-cache-stats`     | GET    | Router cache hit/miss/skipped statistics                                        |
| `/api/admin/clear-specialist-cache` | POST   | Clear specialist L1 + L2                                                        |
| `/api/admin/clear-tile-cache`       | POST   | Clear tile L1 + L2                                                              |
| `/api/admin/clear-router-cache`     | POST   | Clear router L1 only                                                            |
| `/api/admin/clear-l1-l2-caches`     | POST   | Force-clear L1 memory caches + L2 response_cache/unsplash cache rows only      |
| `/api/admin/clear-validation-cache` | POST   | Clear validation caches                                                         |
| `/api/admin/fresh-start`            | POST   | Clear validation + response caches                                              |
| `/api/admin/clear-all-checkpoints`  | POST   | Clear ALL LangGraph checkpoints                                                 |
| `/api/admin/clear-all-caches`       | POST   | Comprehensive clear of ALL caches                                               |

---

## View States

The response envelope computes `plan_view_state` based on data richness:

| View State            | Condition                                                                          | Data Richness                                |
| --------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------- |
| `S0_BOOTSTRAP`        | No tiles and no specialist content                                                 | Setup checklist, blank slate                 |
| `S2_STRATEGY_READY`   | Has tiles OR has specialist strategy sections                                      | Strategy preview or full logistics dashboard |
| `S3_ITINERARY_READY`  | Builder succeeded -- day_cards exist and conflict count is 0                       | Full timeline with scheduled activities      |
| `S3_EDITING`          | Builder succeeded -- day_cards exist and conflicts remain                          | Timeline visible with non-blocking conflicts |
| `S3_PARTIAL_CONFLICT` | Builder failed with conflicts but returned partial day_cards                       | Partial timeline with unschedulable blocks   |

---

## UI Events

Events emitted to frontend for UI updates.

| Event                 | Trigger                       | Frontend Action         |
| --------------------- | ----------------------------- | ----------------------- |
| `UI_RESET`            | RESET intent or panic button  | Clear chat, reset state |
| `SPECIALIST_ACTIVE`   | Specialist detected           | Show specialist badge   |
| `SPECIALIST_DONE`     | Specialist finished           | Update UI               |
| `TILES_LOADING`       | Fetching tiles                | Show loading state      |
| `TILES_READY`         | Tiles fetched                 | Display tile cards      |
| `CONSTRAINT_VIOLATED` | Validation failed             | Show warning banner     |
| `MISSING_FIELDS`      | Core fields missing           | Trigger Setup Modal     |
| `PLAN_READY`          | Plan complete                 | Enable booking          |
| `PLAN_UPDATE`         | Plan updated but not complete | Update plan display     |

---

## Result Format

Built by `_build_complete_envelope()` in `plan_graph.py` for the agent architecture.

```python
{
    "assistant_message": "...",
    "suggested_responses": ["...", "...", "..."],
    "session_state": {...},
    "trip_inputs": {...},
    "ready_to_generate": bool,
    "document": {
        "plan_view_state": "S0_BOOTSTRAP" | "S2_STRATEGY_READY" | "S3_ITINERARY_READY" | "S3_EDITING" | "S3_PARTIAL_CONFLICT",
        "tiles": {...},           # Flattened ID-based map
        "strategy_sections": [...], # Agent cards data
        "itinerary_day_cards": [...] | null,  # ItineraryBuilder output (null until S2_STRATEGY_READY)
        "constraints_validated": [...] | null,
        "constraint_violations": [...] | null,
        "ack_status": "applied" | "rejected" | "no_change",
        "ack_updates": [{"field": str, "to": str}],
        "applied_updates": [...],
    },
}
```
