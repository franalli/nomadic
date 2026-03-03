# Plan Graph Architecture

> **Source**: `backend/app/streaming.py` (SSE orchestration), `backend/app/planner/coordinator.py` (turn execution)
> **Planner Package**: `backend/app/planner/`
> **Prompt Files**: `backend/app/prompts/specialists/` (including `local_expert.txt`)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Package Structure](#package-structure)
3. [Coordinator Architecture Diagram](#coordinator-architecture-diagram)
4. [Coordinator Execution Steps](#coordinator-execution-steps)
5. [Envelope and Chip Pipeline](#envelope-and-chip-pipeline)
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

Coordinator-driven trip planning system with deterministic step planning in Python.

`/api/graph_plan/stream` restores state, then calls `coordinator.execute_turn()` directly. The coordinator classifies the message, plans execution steps, runs specialist/logistics/builder phases, streams response tokens, and emits the final envelope.

| Category | Count | Description |
| --- | --- | --- |
| Coordinator step types | 7 | `classify`, `dispatch_specialists`, `search_tiles`, `build_itinerary`, `generate_response`, `local_intel`, `short_circuit` |
| New planner modules | 3 | `coordinator.py`, `conversationalist.py`, `chip_generator.py` |
| Coordinator schemas | 6 | `ChangeType`, `ClassifierOutput`, `TripBrief`, `SpecialistPlan`, `ReplanRequest`, `ExecutionPlan` |

> **Note:** `ItineraryBuilder` remains pure Python (no LLM) and is called from coordinator `_build_itinerary()` and `/api/expand-itinerary`.

### Design Principles

1. **Coordinator-first orchestration** -- `plan_turn()` determines execution order without LLM routing.
2. **TripPlan is the SSoT** -- core trip fields live in `state["trip_plan"]`; document persistence mirrors this.
3. **Flights/hotels are data fetchers** -- logistics and tile search run as deterministic steps, not agent personas.
4. **Domain expertise remains modular** -- Tier 1 specialist planning still uses `vertical_specialist.py`.
5. **Single response voice** -- `conversationalist.py` streams one final assistant response using current state.
6. **Centralized LLM factory** -- all LLM calls still use `get_llm_by_model()` and `settings.*_model`.
7. **Deterministic envelope** -- `_build_envelope()` computes view state, ack status, and document payload.
8. **Pure-Python itinerary synthesis** -- builder remains non-LLM.

---

## Package Structure

```
backend/app/planner/
├── __init__.py              # Facade exports (stable public API)
├── chip_generator.py        # Suggestion chip templates for complete envelope
├── conversationalist.py     # Final response generation (single streaming LLM call)
├── coordinator.py           # Deterministic turn planner + step executor + envelope builder
├── hashing.py               # Stable hashing utilities (make_cache_key, field_hash)
├── llm_factory.py           # Provider-agnostic LLM factory (OpenAI/Gemini auto-routing) + extract_token_usage(), resolve_schema_refs()
├── patterns_registry.py     # Shared regex/keyword patterns (BUDGET_PATTERNS, TRAVELER_PATTERNS, SETTINGS_KEYWORDS)
├── specialist_registry.py   # Specialist config SSoT (keywords, constraints, enhancements, flags)
├── test_mode.py             # Test mode detection
#   Frontend mirror: frontend/lib/specialists.ts (colors, icons, keywords, display names)
├── schemas/                 # Coordinator protocol schemas (Phase 1+)
│   ├── __init__.py
│   └── coordinator_schemas.py  # ChangeType, ClassifierOutput, TripBrief, SpecialistPlan, ReplanRequest, ExecutionStep, ExecutionPlan
├── nodes/                   # Domain/library modules called directly by coordinator
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
├── services/
│   ├── __init__.py          # Services package
│   ├── admin_utils.py       # Cache management, debugging, observability, startup validation
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
```

---

## Coordinator Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    COORDINATOR TURN FLOW (execute_turn)                     │
│                                                                              │
│  1) classify_change(user_message, trip_state_summary)                       │
│  2) apply classifier fields to state + snapshot pre-change hashes           │
│  3) plan_turn() -> ExecutionPlan[StepType...]                               │
│  4) execute steps (parallel where allowed):                                 │
│       dispatch_specialists || search_tiles                                  │
│       then local_intel / build_itinerary                                    │
│  5) generate_response_streaming() via conversationalist                     │
│  6) _build_envelope() -> complete payload + suggestion chips + ack status   │
│                                                                              │
│  SSE events: token | node_status | partial | complete | error               │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Coordinator Execution Steps

| StepType | Executed By | Purpose | Emits partial event |
| --- | --- | --- | --- |
| `CLASSIFY` | `router_extraction.classify_change()` | Intent + extracted fields + change classification | `trip_inputs` (after apply) |
| `DISPATCH_SPECIALISTS` | `_dispatch_specialists_parallel()` + `vertical_specialist.dispatch_specialist_with_brief()` | Replan only affected Tier 1 domains | `strategy_sections` |
| `LOCAL_INTEL` | `_run_local_intel()` | Build/update local expert section | `strategy_sections` |
| `SEARCH_TILES` | `_search_tiles()` | Refresh flights/hotels/activities by change type | `tiles` |
| `BUILD_ITINERARY` | `_build_itinerary()` | Run pure-Python itinerary builder + store `builder_result` | none |
| `GENERATE_RESPONSE` | `conversationalist.generate_response_streaming()` | Stream final assistant response | token stream |
| `SHORT_CIRCUIT` | `_short_circuit_message()` and state reset helpers | Deterministic greeting/reset/question handling | none |

### Parallelism Rules

- `DISPATCH_SPECIALISTS` and `SEARCH_TILES` may run in parallel via `_execute_parallel_group()`.
- `LOCAL_INTEL` remains sequential to avoid concurrent writes to `strategy_sections`.
- Partial failures in parallel groups are recorded in `turn_meta["partial_failures"]` and surfaced via `ack_updates`.

### Idempotent / Short-Circuit Routing

- Repeated messages with no effective `fields_changed` and an existing itinerary now route to `GENERATE_RESPONSE` only, skipping specialist + logistics + builder.
- A dedicated `INITIAL_PLAN` guard also skips full recomputation when an itinerary already exists and no fields changed; otherwise it continues with selective tile/build steps when strategy is already present.

---

## Envelope and Chip Pipeline

`_build_envelope()` in `coordinator.py` is the canonical complete-payload builder.

Core behaviors:
- Builds `trip_inputs` from `trip_plan` + `trip_settings`
- Computes `plan_view_state` (`S0_BOOTSTRAP` / `S2_STRATEGY_READY` / `S3_*`)
- Generates chips via `chip_generator._generate_chips_from_state()`
- Sets `ack_status` from route violations, applied field changes, and partial failures
- Emits `constraints_validated`, `constraint_violations`, `applied_updates`, `ack_updates`
- Serializes state with `state_serde.serialize_agent_state()`

`_compute_coordinator_s3_state()` maps builder outcomes:
- `success=True, day_cards, no conflicts` -> `S3_ITINERARY_READY`
- `success=True, day_cards, conflicts` -> `S3_EDITING`
- `success=False, day_cards` -> `S3_PARTIAL_CONFLICT`
- otherwise -> `S3_BLOCKED`

---

## Library Modules (Surviving Node Code)

These modules survived the architecture migration. They are no longer standalone LangGraph nodes -- they are library code called directly by coordinator step handlers. They retain their internal logic and can still be called directly for testing.

### RouterExtraction (`router_extraction.py`)

LLM-based intent classification + field extraction. Single LLM call produces `RouterOutput` schema.

**Key functions:**
- `_sanitize_user_message()` -- Escapes prompt-template metacharacters before interpolation.
- `_classify_and_extract_with_llm()` -- Unified extraction call that returns `RouterOutput` and performs cache lookup/write.
- `_classify_change_type()` -- Lightweight second-pass classifier that derives `change_type`, `affects`, `preserves`, and `informs`.
- `classify_change()` -- Coordinator-aware classifier with two-pass flow:
  1. `RouterOutput` from `_classify_and_extract_with_llm()`
  2. `ChangeClassification` from `_classify_change_type()` (retries once on transient failure)
  3. Merge into `ClassifierOutput`.
- `_validate_extraction()` -- Post-extraction validation, including past-date normalization
  - Dates within the last 7 days are now treated as intentional and left untouched; older past dates are bumped to next occurrence.

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
    reset_budget: bool = False
    reset_hotel: bool = False

    # Settings extraction
    activities_per_day: Optional[int] = None
    skill_level: Optional[str] = None  # "beginner", "intermediate", "advanced"

    hotel_min_stars: Optional[int] = None
    hotel_style: Optional[str] = None
    hotel_amenities: List[str] = []
    hotel_location: Optional[str] = None
    flight_direct_only: Optional[bool] = None
    flight_cabin_class: Optional[str] = None

    # Multi-destination
    multi_destination_detected: bool = False

    # Intent classification
    planning_intent: Optional[str] = None
    question_type: Optional[str] = None

    # Date corrections applied by backend validation
    date_auto_adjustments: List[Dict[str, str]] = []
```

### VerticalSpecialist (`vertical_specialist.py`)

Domain specialist with LLM-first architecture. 8 specialists (diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari).

**Key functions:**
- `generate_specialist_output_llm()` -- Core LLM generation (wrapped by `get_specialist_advice` tool)
- `generate_all_specialists_parallel()` -- Batch parallel execution with caching
- `_build_specialist_prompt()` -- Shared prompt builder (system + user prompt) used by specialist generation and coordinator `dispatch_specialist_with_brief()`. Accepts optional `scheduling_context` for cross-specialist coordination.
- `dispatch_specialist_with_brief()` -- Coordinator bridge: converts `TripBrief` into `generate_specialist_output_llm()` arguments via `_BriefAsTripPlan` adapter. Supports `ReplanRequest` for selective re-dispatch.
- `build_scheduling_context()` -- Builds a scheduling-context block from a `TripBrief` (reserved days, target day count, hotel zone) appended to the specialist user prompt.

Recent behavior:
- `_build_specialist_prompt()` now returns `(system, user, max_acts)` and applies category-aware, density-aware capping.
- `_build_specialist_prompt()` caps specialist `available_days` at 60% of trip duration to preserve room for mixed non-specialist activities.
- `TripBrief` now flows into `_BriefAsTripPlan` with `activities_per_day` and active `categories` to bias distribution across specialists.
- Specialist outputs are additionally capped after parsing so `max_acts` is never exceeded in cacheable payloads.
- Constraint text is anchored to relative wording (for example, "day before departure"), and cached outputs are re-anchored by `_reanchor_constraint_dates()` before merge.
- "feasible + zero activities" outputs are converted to `caveat` responses and skipped for L2 cache write, preventing stale empty specialist cache entries.
- Prompt guidance now uses explicit exact bounds (`EXACTLY`) and hard caps (`Do NOT generate more than Y`) to prevent specialist over-generation.
- Safety buffer days are explicitly excluded from the specialist activity-count ceiling in prompt context.
- `SafetyHealth` now includes advisory fields: `advisory_level` (`none`, `caution`, `warning`, `avoid`) and `advisory_reason`.

**LLM-first architecture:** Single LLM call generates feasibility + activities + constraints. Falls back to minimal safety constraints if LLM fails (parse error, timeout).

Uses `_SPECIALIST_FLAT_SCHEMA` (inlined `$defs` via `resolve_schema_refs()`) for Gemini function calling compatibility.

### LocalExpert (`local_expert.py`)

City logistics concierge with Phase A/B architecture.

**Phase A (instant):** Static skeleton from constraint data. Returns Trip Overview card immediately. Stashes Phase B enrichment closure in `_pending_enrichments` dict.

**Phase B (background):** LLM enrichment fired after DB commit in `streaming.py`. Uses `build_enrichment_closure()`, with module-level `_pending_enrichments` dict, `_pending_lock`, and `_active_destination_enrichments` set for dedupe.

Recent behavior:
- Cache reuse path seeds legacy list reconstruction from prior-turn `constraints_applied`/`content_added` so repeated turns keep stable high-signal Travel Intel density while avoiding duplicate entries.
- `local_expert.txt` now explicitly requests travel advisory reasoning (`advisory_level` + `advisory_reason`) so advisory context can be surfaced in plan summaries.

### LogisticsNode (`logistics_node.py`)

Flight/hotel/activity fetching with safety logic.

**Provider cascade:** Google Places -> Mock in logistics_node; Curated -> Google Places -> Mock in tile_service/service.py.

**Key features:**
- Separate cache key hashes for hotels/activities/flights
- Two-tier activity system (Tier 1 specialist + Tier 2 experience)
- No-fly safety logic (registry-driven via `_NOFLY_CATEGORIES`)
- Hotels and activities fetched in parallel via `asyncio.gather()`
- Google Places hotel providers cap hotel results at top-3 per fetch (cost guard for photo-proxy traffic)
- `build_signed_photo_url()` now returns `None` when photos are disabled and caps requested TTL by `settings.google_places_photo_signed_ttl_max` (default max 3600s; default request 1800s)
- Hotel-star filtering now cascades down (`min_stars-1 ... 1`) before fallback-to-originals, with applied threshold tracked in `state.metadata`.
- General-only trips (no specialist/categories) call `browse_activities()` across default categories to seed larger activity pools for long itineraries.
- Experience tiles are stashed into `metadata["browseable_activities"]`, and Google Places backfill now propagates rating/review_count/deeplink when available.
- When generated Tier 2 tiles are below expected density (`free_days * activities_per_day`), logistics executes a browse fallback using mapped alternative categories, appends successful backfill tiles, and preserves them in browseable activity metadata.

### ConstraintGuard (`constraint_guard.py`)

Mostly deterministic validation. One LLM exception: `check_route_constraint()` calls `validate_place_exists()` (via `validation_cache.py`, LLM-backed with TTL caching).

**Checks:**
- `check_budget_constraint()` -- Total cost vs budget allocation (30/40/30 split)
- `check_temporal_constraints()` -- Date validity, duration limits
- `check_specialist_constraints()` -- Registry-driven departure buffer + cross-domain
- `check_route_constraint()` -- Same-city error + unknown destination (LLM-backed)
- `_check_cross_domain_from_sections()` -- Stateless section-driven cross-domain check

**ConstraintGuard class** still exists with `check_all()` for legacy graph-path invocations. The `validate_plan` tool calls the individual check functions directly (`check_budget_constraint`, `check_temporal_constraints`, `check_specialist_constraints`, `check_route_constraint`) rather than `ConstraintGuard.check_all()`.

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

Coordinator/build path usage -- called from `coordinator._build_itinerary()` and `/api/expand-itinerary`.

### Algorithm Phases

```
┌─────────────────────────────────────────────────────────────────┐
│  ItineraryBuilder.build() Algorithm                             │
│                                                                  │
│  1.    Day Skeleton - DayCard[] from dates                      │
│  2.    Extract Specialist Content - Activities + constraints    │
│  2.5   Enrich Activities from Tiles - Google Places data merge  │
│  2a.   Constraint Merge - Priority resolution (BLOCKING>STRONG) │
│  2b.   Early Conflict Detection - Irreconcilable check         │
│  3.    Anchor Placement - Arrival/departure from flights       │
│  4.    Buffer Injection - Safety blocks by severity            │
│  5.    Activity Distribution - Round-robin interleaving        │
│        (includes day preference capping internally; periods      │
│        avoid duplicate morning/afternoon/evening collisions)   │
│  5.5   Free Day Placeholders - Empty day handling              │
│  5.55  Restore Browse-Pinned Tiles - User-added Google Places  │
│  5.6   Experience Tile Placement - Tier 2 on free/spare days   │
│  5.25  Preferred Activity Placement - Hearted tiles (2-pass)   │
│  6.    Tile Matching - Hotels span all days, preferences weighted│
│  6.5   Constraint Tagging - Inline constraints for frontend      │
│  6.75  Chronological Sort - Final block ordering                 │
│  7.    Temporal Conflict Detection - Post-placement overflow     │
│                                                                  │
│  Called from: coordinator._build_itinerary() +                  │
│              /api/expand-itinerary                               │
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

**Phase 2.5: Prepare Activities + Post-Build Enrichment**

Specialist `content_added` is first converted to synthetic activity tiles (`source_agent='vertical_specialist'`) in
`coordinator._inject_specialist_tiles_into_state()`. Pre-build preparation (`_prepare_activity_tiles_for_build`) applies:
1. Geocode fallback for tiles missing geo (cheap Geocoding API call, L1+L2 cached)
2. Photo URL signing for tiles with `photo_name` (free, local computation)
3. Unsplash placeholder fallback for tiles still missing images (free, local)

Builder enrichment follows this order:
1. direct `tile_id` match between `ActivityOutput.tile_id` and coordinator-generated specialist tiles
2. normalized-title fallback against all activity tiles.

The matched tile object is stored on each enriched activity (`activity._matched_tile`) and drives `booked_tile` assignment in
`ItineraryBuilder._assign_booked_tiles_for_frontend()`, which powers richer photos/metadata in frontend cards.

**Post-build enrichment** (`_post_build_enrich_placed_activities`) runs after the builder returns day cards. It enriches only
blocks that were actually placed in the itinerary and lack a `google_place_id`, using `enrich_activities_with_places` with
`path_label="post_build_enrich"`. This defers expensive Google Places API calls to after placement, so only placed blocks
(typically 3-5) incur API cost instead of all candidate tiles (10+). Enriched fields (coordinates, google_place_id, deeplink,
signed photo URL) are written back directly to the day_card blocks.

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

When the `no_altitude_after_dive` constraint is present and both diving and altitude activities (hiking, skiing, climbing -- derived from diving's `cross_domain_blocks` in the registry) exist, `_distribute_activities` bypasses round-robin and uses ordered clustering:

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

**Day Preference Capping (internal to Phase 5)**

**Hallucination Guard:** `_parse_day_preferences(raw, user_text)` rejects LLM-inferred day counts when the user message contains no digits -- the LLM is hallucinating counts from trip duration. Only explicit user statements like "3 days diving" produce valid preferences. Additionally, parsed preferences are scoped to categories mentioned this turn (`activity_categories + specialist_hints`) to prevent the LLM from hallucinating day counts for categories the user didn't reference.

When `activity_day_preferences` are set (e.g., `{"diving": 3, "hiking": 2}`), the builder caps each specialist's activity list to the user-requested count within Phase 5's `_distribute_activities`, BEFORE cross-domain clustering or round-robin. The cap is a maximum -- if only 2 diving activities exist but user asked for 3, all 2 are placed. Remaining specialists (without day preferences) fill leftover days via the existing distribution logic.

**Phase 5.6: Experience Tile Placement and `activities_per_day` scaling**

`ItineraryBuilder` normalizes `activities_per_day` to `_activities_per_day` in `__init__`
(`max(1, min(input_data.activities_per_day or 2, 5))`).

In Phase 5.6:

- **Pass 1 (free-day fill):** each free day accepts up to `target_per_day` experience tiles
  where `target_per_day` is `_activities_per_day`, subject to hour and category caps.
- Specialist-origin tiles (`source_agent='vertical_specialist'`) are excluded from experience placement.
- **Pass 2 (co-schedule):** remaining experience tiles are placed on specialist days using the
  same capacity + time-slot scoring pass.
- `_day_remaining_capacity()` enforces both time-hour and block capacity, and clamps placements
  to `_activities_per_day` as a hard per-day ceiling after prior allocations.
- If `period` collides with existing blocks on a day, placement shifts to the first open slot in
  morning/afternoon/evening before writing the block.

**Phase 5.25: Preferred Activity Placement (Two-Pass)**

Runs AFTER Phase 5.6 (experience tile placement). The builder populates remaining free slots with user-preferred activities (hearted tiles). Uses a two-pass strategy:

1. **Pass 1 (Unified Slot Model):** Collects preferred tiles from `preferences.preferred_activity_ids`. **D3 category filter:** Before collecting, each tile is checked against `self._active_categories` (derived from `input_data.activity_categories`, set at `ItineraryBuilder.__init__`). If the user has explicitly set categories (`activity_categories is not None`) and a tile's category is not in the active set, it is skipped. Builds slot map (3 periods per day), places via round-robin on least-loaded days.
2. **Pass 2 (Co-Schedule Fallback):** Tiles that couldn't fit in Pass 1 are deferred. Re-scans using `_day_remaining_capacity()` + `_time_slot_score()` for hour-based placement on specialist days with spare capacity.
   If the target period is occupied, the block is moved to the first available slot on that day.

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
- `activities_placed`: alias used in coordinator `builder_result` payload for placed count
- `activities_dropped`: dropped-count in coordinator `builder_result` (`total_activities_input - activities_placed`)
- Drop ratio (`1 - activities_placed/total_activities_input`) is captured in `turn_meta['builder_result']` (via `success`, `activities_placed`, and `activities_dropped`) for guard suppression and suggestion-chip telemetry

**Preference Weighting:**

- User heart preferences passed via `PreferenceOverrideInput`
- Preferred hotels get 1.5x score multiplier
- Preference attribution badges: "user_preferred", "ai_selected", "ai_override"

**Capacity Model:**

- `DAY_CAPACITY_HOURS = 11.0` (24h - 8 sleep - 3 meals/transit - 2 reserve)
- `MAX_BLOCKS_PER_DAY = 3`
- `DEFAULT_EXPERIENCE_HOURS = 1.5` (default duration for experience tiles)
- `MAX_SAME_CATEGORY_PER_DAY = 2` (prevents 3x yoga on one day)

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
| **_classify_change** (via `router_extraction.py`) | Yes | `settings.router_model` (via `llm_factory`) | `RouterOutput`, `ChangeClassification`, `ClassifierOutput` | Two-pass intent/extraction + lightweight change classification |
| **dispatch_specialists** (via `coordinator.py` + `vertical_specialist.py`) | Yes (function_calling, flattened schema) | `settings.specialist_model` (via `llm_factory`) | `LLMSpecialistOutput` via `_SPECIALIST_FLAT_SCHEMA` | Specialist planning with fallback |
| **local_intel** (via `local_expert.py`) | Yes | `settings.local_expert_model` (via `llm_factory`) | `LocalExpertOutput` | Structured output with `method="function_calling"`, guarded parsing + LLM token accounting |
| **search_tiles** (via `logistics_node.py`) | No | N/A | N/A | API/provider calls only (Curated, Google Places, Mock) |
| **validate_plan** (via `constraint_guard.py`) | No | `settings.guard_model` (place validation only) | N/A | Mostly deterministic |
| **build_itinerary** (via `itinerary_builder.py`) | No | N/A | N/A | Pure Python scheduling |
| **generate_response** (via `conversationalist.py`) | No | `settings.synthesizer_planning_model` | N/A | Free-form natural language responses |

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
5. **Gemini schema pipeline** -- Use `gemini_safe_schema(strip_unsupported_schema_keys(resolve_schema_refs(schema)))` for Gemini function-calling compatibility. `resolve_schema_refs(schema)` alone is not sufficient.
6. **`patterns_registry.py`** -- Shared regex/keyword lists used by multiple planner modules. Centralizes `BUDGET_PATTERNS`, `TRAVELER_PATTERNS`, and `SETTINGS_KEYWORDS`.

---

## State Models

### NomadicAgentState (Runtime State)

The agent's runtime state, extending LangChain's `AgentState` with trip planning context.

Note: this class is kept for compatibility during migration; the coordinator reads and writes it as a plain state dict via direct key access (not through an active LangGraph `StateGraph`). A future cleanup should replace it with a lightweight `TypedDict`.

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
    specialist_plans: Annotated[dict, _merge_dicts]    # Coordinator specialist plan outputs keyed by topic
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

### Activity Settings (Planner Metadata)

`activity_settings` values are passed through `TripSettings` metadata and normalized in `coordinator._apply_activity_updates()`:

```python
class ActivitySettings(BaseModel):
    categories: List[str] = []
    skill_level: Optional[str] = None
    day_preferences: Dict[str, int] = {}  # {"diving": 3, "hiking": 2}
    activities_per_day: int = 2  # 1-3; None coerces to 2 for legacy payloads
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
- `_trim_messages(messages, max_messages=20)` -- Keeps first 2 + last N messages for context window management (default 20 = 10 turns)

---

## Specialist Domain Knowledge

> **SSoT:** All specialist configuration (keywords, constraints, enhancements, flags, backfill affinity) lives in `backend/app/planner/specialist_registry.py`. Top destinations and activities are LLM-generated per prompt file -- no hardcoded destination lists. Tier 2 is open-ended (no fixed validation set). `display_name(category)` provides canonical display names. `backfill_affinity_tags` drives complementary category selection for free-day backfill. Adding a specialist requires: 1) add entry to `SPECIALIST_REGISTRY`, 2) update `_EXPECTED_SPECIALISTS`, 3) create `prompts/specialists/{topic}.txt`.

**Fill-Day Validation:** `validate_fill_day_placement(target_day, specialist_type, day_cards, total_days, has_departure_flight)` checks placement against registry constraints: no-fly buffer proximity to departure, cross-domain forward adjacency, and cross-domain reverse adjacency. Returns `FillDayRejection(code, reason, suggestion)` or `None` if valid.

### Diving

**Constraints (from registry):**
| Rule | Type | Severity | Cross-Domain |
|------|------|----------|--------------|
| `no_fly_24h` | temporal | blocking | flights |
| `no_altitude_after_dive` | safety | blocking | skiing, hiking, climbing |

**Registry flags:** `has_geographic_constraint=True`, `has_nofly_buffer=True`, `min_days_needed=4`, `backfill_affinity_tags=["water", "outdoors"]`
**Cross-domain blocks:** `ALTITUDE_AFTER_DIVE` -> `("skiing", "hiking", "climbing")` (24h buffer, blocking)

### Hiking

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `morning_start_recommended` | temporal | soft |
| `proper_footwear_required` | equipment | soft |
| `altitude_acclimatization` | safety | strong |

**Registry flags:** `has_altitude_buffer=True`, `min_days_needed=3`, `backfill_affinity_tags=["outdoors", "culture"]`

### Skiing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `check_snow_conditions` | safety | blocking |

**Registry flags:** `has_geographic_constraint=True`, `min_days_needed=3`, `backfill_affinity_tags=["outdoors", "culture"]`

### Cycling

No hardcoded constraints (LLM-generated only)

**Registry flags:** `min_days_needed=3` (default), `backfill_affinity_tags=["outdoors", "culture"]`

### Surfing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `tide_and_swell_check` | safety | soft |
| `reef_awareness` | safety | strong |
| `skill_appropriate_breaks` | equipment | soft |

**Registry flags:** `min_days_needed=3` (default), `backfill_affinity_tags=["water", "outdoors"]`

### Climbing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `altitude_acclimatization` | safety | strong |
| `gear_check_required` | equipment | strong |

**Registry flags:** `has_altitude_buffer=True`, `min_days_needed=3`, `backfill_affinity_tags=["outdoors", "culture"]`

### Sailing

No hardcoded constraints (LLM-generated only)

**Registry flags:** `min_days_needed=3` (default), `backfill_affinity_tags=["water", "outdoors"]`

**Backward compat:** Keywords include old "boating" terms; `category_mappings` maps `"boating" -> "sailing"`.

### Wildlife Safari

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `guide_required` | safety | strong |

**Registry flags:** `min_days_needed=3` (default), `backfill_affinity_tags=["outdoors", "culture"]`

---

## Constraint Validation

### Validation Categories

| Category   | Check                                                                              | Severity     | Note                                                                           |
| ---------- | ---------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------ |
| **Route**  | `origin == destination`                                                            | **blocking** | Triggers `SAME_CITY_ERROR`                                                     |
| **Route**  | `validate_place_exists(dest)`                                                      | **blocking** | Triggers `UNKNOWN_DESTINATION_ERROR`                                           |
| Budget     | `total_cost > budget`                                                              | blocking     | `suggested_action="Reduce total spend by $N or increase budget"` |
| Budget     | `category_cost > allocation`                                                       | warning      | `suggested_action="Look for more affordable {category} options"` |
| Temporal   | `start_date < today`                                                               | blocking     | `DATE_IN_PAST` -- last-resort check (extraction auto-bumps first)              |
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
When the ItineraryBuilder persists a constraint rule (e.g., `no_fly_buffer`) and succeeds (`state.metadata.get("last_builder_success") == True`) with acceptable drop ratio (`state.metadata.get("last_builder_drop_ratio", 0.0) < 0.5`), the guard suppresses duplicate violations on the next turn -- the builder is already enforcing the constraint via clustering. If the builder **failed** or dropped too much volume (>= 50%), the violation is re-surfaced so the agent can generate resolution chips.

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
| Specialist | `specialist_cache.py` | 128 | 1h | 168h (env: SPECIALIST_CACHE_TTL_HOURS) | `specialist::v4::{topic}::{dest}::{iso_month}::m::{skill}::{dpref}::{phash}` | LLM outputs. Dates coarsened to ISO month (YYYY-MM); duration dropped (specialist content is duration-agnostic). |
| Experience | `experience_generator.py` | 128 | 1h | 72h (env: EXPERIENCE_CACHE_TTL_HOURS) | `experience::v2::{dest}::{sorted_cats}::{month_or_half_year}::n{tiles_per_category}` | Tier 2 tiles. Seasonal categories keep `YYYY-MM`; non-seasonal categories normalize to `YYYY-H1`/`YYYY-H2` for higher cache reuse. |
| Tile | `tile_cache.py` | 256 | 24h | 72h (env: TILE_CACHE_TTL_HOURS) | `tile::v2::{provider}::{type}::{dest}::{start_date}::{end_date}[::{variant}]` | Provider API data |
| Browse | `activity_browser.py` | 256 | 6h | 720h (env: GOOGLE_PLACES_ENRICHMENT_CACHE_TTL_HOURS) | `browse::v2::{dest}::{sorted_cats}::{month}::{center_bucket}` | On-demand Browse Activities tiles |
| Places Enrichment | `google_places_provider.py` | 2048 | 24h | 720h (env: GOOGLE_PLACES_ENRICHMENT_CACHE_TTL_HOURS) | `places::enrich::v3::{dest}::{title}::q{sig}` | Google Places enrich-by-title lookups. Title normalized via `_normalize_title_for_cache` (strips specialist qualifiers for higher hit rate). |
| Geocode | `google_places_provider.py` | 1000 (TTLCache) | 24h | 8760h (1yr) | `geocode::v1::{normalized_dest}` | Geocoding API lat/lng results. L2 uses `cache_type='geocode'`. |
| Photo Proxy | `main.py` | 500 | 24h | N/A | `photo::{photo_name}::{width}x{height}` | Server-side photo bytes cache. Skips upstream fetch + spend guard on hit. |
| Router | `router_cache.py` | 500 | 1h | N/A | `router::v3::SHA256({normalized_text}:{today_date}:{context_fingerprint})[:32]` | NL extraction |

**Database Table:** `response_cache` with `cache_type` column for filtering (values: `'specialist'`, `'experience'`, `'experience_single'`, `'tiles'`, `'geocode'`, `'iata'`). Browse and Places enrichment L2 entries use `cache_type='tiles'`.

**Experience cache recovery (incremental regen):** `experience_generator.py` now supports category-by-category reuse to avoid recomputing unchanged Tier 2 categories:

- On composite cache miss it probes `experience_single` entries first from L1 (`_mem`) and then L2.
- Cached per-category tiles are merged with state metadata before generation; only newly introduced categories are regenerated.
- Regenerated tiles are merged back into state metadata (`generated_tier2_categories`) and written back to the relevant caches, so subsequent turns reuse them.
- Month normalization is category-aware: any seasonal category in the request keeps month precision; fully non-seasonal sets collapse to half-year buckets.

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
| iso_month | `2025-02` | YYYY-MM from trip midpoint date (for cross-month spans, e.g. Mar 31-Apr 7 -> `2025-04`); duration dropped (specialist content is duration-agnostic) |
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

Key format: `router::v3::{sha256({normalized_text}:{today_date}:{context_fingerprint})[:32]}`.
Stats keys are exposed as `l1_hits`, `l1_misses`, and `skipped_context_dependent` (context-dependent inputs are explicitly skipped).
`make_cache_key()` now serializes `None` inputs as `__NONE__` to avoid accidental key collisions.

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
| Restoration    | `state_serde.py` + `streaming.py` complete envelope assembly | Reads typed `TripSettings` via `get_trip_settings(state)` and serializes sub-models into output `trip_inputs` and `trip_settings`                                                                                 |
| Input merge    | `streaming.py` (SSE endpoint)                        | `_USER_OWNED_SETTINGS` guard -- document baseline wins for settings fields                                                                                                                   |
| Output persist | `crud_document.py` `apply_planner_update()`          | Strips settings from graph output before `merge_trip_inputs()`                                                                                                                               |

---

## Prompt File Mapping

### Prompts

```
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

| File | Used By | Purpose |
| --- | --- | --- |
| `specialists/*.txt` | `vertical_specialist.py` | Domain-specific specialist guidance |
| `specialists/generic_activity.txt` | `vertical_specialist.py` | Fallback prompt for open-ended Tier 2 categories |
| `specialists/local_expert.txt` | `local_expert.py` | Local expert enrichment and travel-intel prompt |

`conversationalist.py` builds its system prompt dynamically in code (trip context + specialist findings + turn context + quality rules); there is no standalone `planner/prompts/planner.py` template in the current architecture.

### Conversationalist Context Assembly (`build_response_context`)

`build_response_context()` currently assembles the LLM context in this order:

1. **Persona** -- destination-aware (with local culture/style hints) or generic persona block
2. Trip context block (`_build_trip_context_block`)
3. **"What the User Sees Right Now"** -- rendered dynamically when `day_cards` or `strategy_sections` exist in state, including day/activity counts and visible hotel/itinerary context while avoiding direct UI description
4. Specialist findings (`_build_specialist_findings_block`)
5. Itinerary status (`_build_itinerary_status_block`)
6. Outcome (`_build_outcome_block`) for mutation turns (add/remove/settings/date/spatial preference/logistics changes), including optional budget usage summary from candidate tiles
7. Diff block (`_build_diff_block`) with top-tracked `trip_plan`/`trip_settings` field deltas for change-aware responses
8. Turn context (`_build_turn_context_block`)
9. **Already-Said dedup block** with recent assistant replies (max 6), to prevent repetitive responses
10. **Hard rules** (`_VOICE_BASE`) + intent-specific voice block with per-intent sentence limits (enforced by `_enforce_sentence_limit()`)

This keeps the final assistant turn aligned with what the backend just applied, and prevents it from repeating already delivered content.

---

## Streaming Architecture

### Current Implementation: Coordinator Streaming

`generate_sse()` in `streaming.py` restores session state, then always calls `coordinator.execute_turn()`.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  STREAMING FLOW (streaming.py -> coordinator.execute_turn)                  │
│                                                                              │
│  1. Restore session state with restore_agent_state()                         │
│  2. Execute coordinator steps (classify, specialists/tile fetch, builder)    │
│  3. Forward SSE events immediately: token/node_status/partial/feasibility_warning/error │
│  4. Persist complete envelope via apply_planner_update()                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Streaming Events

| Event Type | Data | Description |
| --- | --- | --- |
| `node_status` | `{node, status, label, icon_key, estimated_duration_ms}` | Coordinator step progress mapped to legacy node/tool names |
| `token` | `string` | Response text streamed from `conversationalist.generate_response_streaming()` |
| `partial` | `{kind: "strategy_sections"\|"tiles"\|"trip_inputs", payload: any}` | Progressive render from coordinator step outputs |
| `feasibility_warning` | `{topic, status, reason, alternative}` | Coordinator feasibility signal. Forwarded by `generate_sse()` as a public SSE event for frontend toast display. |
| `complete` | `{document, session_state, version, updated_at, ...}` | Public SSE payload built in `generate_sse()` after `apply_planner_update()`, wrapping/normalizing coordinator `_build_envelope()` output |
| `error` | `{message}` | Error information |

### Step-to-node mapping (`_step_node_name`)

- `DISPATCH_SPECIALISTS` -> `get_specialist_advice`
- `SEARCH_TILES` -> `search_tiles`
- `LOCAL_INTEL` -> `get_local_intel`
- `BUILD_ITINERARY` -> `build_itinerary`
- `GENERATE_RESPONSE` -> `response`

### Complete Envelope (`_build_envelope()`)

Coordinator complete payload includes `plan_view_state`, `tiles`, `strategy_sections`, `itinerary_day_cards`, `constraints_validated`, `constraint_violations`, `ack_status`, `ack_updates`, and `applied_updates`. `ack_status` now supports `partial` when only partial-failure updates were generated.

`coordinator._build_envelope()` also emits envelope-level `trip_settings` (fresh booking/hotel/activity settings), plus `itinerary_overview`, `itinerary_assumptions`, and `hotel_filter_cascaded` when present in turn/persistent metadata.
It now serializes `itinerary_day_cards=[]` when builder runs but returns no cards.

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

`google_places_provider.py` runs on a Pro-tier field mask (Enterprise fields like rating/userRatingCount/editorialSummary are excluded). Activity/hotel tile ratings and review counts are normalized deterministically by rank for UI consistency. Hotel price estimates are derived from baseline nightly rate plus preference multipliers (`min_stars`, `style`) when raw provider price/rating fields are unavailable.

### Settings-Aware Tile Filtering

| Setting Type                    | Filter Applied                                      | Budget Allocation |
| ------------------------------- | --------------------------------------------------- | ----------------- |
| `budget` (hotels)               | `tile.price_estimate <= budget * settings.budget_allocation_hotels`              | Configured ratio |
| `budget` (activities)           | `tile.price_estimate <= budget * settings.budget_allocation_activities`              | Configured ratio |
| `budget` (flights)              | `tile.price_estimate <= budget * settings.budget_allocation_flights`              | Configured ratio |
| `hotel_settings.min_stars`      | `tile.rating >= min_stars` (rating may be deterministic provider heuristic on Pro-tier paths) | -                 |
| `flight_settings.direct_only`   | `tile.meta.stops == 0`                              | -                 |

Current tile filtering is budget/transport/hotel driven only; no user-profile gating is applied in filtering.

---

## Booking Provider Interface (Scaffolding)

> **Status:** Interface defined, real provider implementation deferred until API access.

### Design Decision

**Booking = REST endpoints, NOT coordinator steps**

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

| Module | Exports |
| --- | --- |
| `planner` | `execute_turn`, `build_trip_state_summary`, `restore_graph_state`, `state_to_session_state`, `trip_plan_to_trip_inputs`, hashing helpers |
| `planner.state` | `GraphState`, `TripPlan`, `TripSegment`, `ItineraryBlock`, `SpecialistConstraint`, `SpecialistStateOutput` |
| `planner.state.agent_state` | `NomadicAgentState` |
| `planner.hashing` | `stable_hash`, `stable_hash_short`, `canonicalize_destinations`, `make_cache_key` |
| `planner.coordinator` | `execute_turn`, `plan_turn`, `_build_envelope`, `_compute_coordinator_s3_state` |
| `planner.schemas.coordinator_schemas` | `ChangeType`, `ClassifierOutput`, `TripBrief`, `SpecialistPlan`, `ReplanRequest`, `ExecutionPlan`, `ExecutionStep`, `StepType` |

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
| `S0_BOOTSTRAP`        | Core fields missing, OR core fields set but no content (no tiles, no sections)     | Setup checklist, blank slate                 |
| `S2_STRATEGY_READY`   | Has strategy sections, OR has tiles (hotels or activities)                         | Strategy preview or full logistics dashboard |
| `S3_ITINERARY_READY`  | Builder succeeded -- day_cards exist and conflict count is 0                       | Full timeline with scheduled activities      |
| `S3_EDITING`          | Builder succeeded -- day_cards exist and conflicts remain                          | Timeline visible with non-blocking conflicts |
| `S3_PARTIAL_CONFLICT` | Builder failed with conflicts but returned partial day_cards                       | Partial timeline with unschedulable blocks   |
| `S3_BLOCKED`          | Builder failed, no day_cards returned                                              | No timeline, blocked state                   |

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

Built by `_build_envelope()` in `coordinator.py`.

```python
{
    "assistant_message": "...",
    "suggested_responses": ["...", "...", "..."],
    "session_state": {...},
    "trip_inputs": {...},
    "ready_to_generate": bool,
    "document": {
        "plan_view_state": "S0_BOOTSTRAP" | "S2_STRATEGY_READY" | "S3_ITINERARY_READY" | "S3_EDITING" | "S3_PARTIAL_CONFLICT" | "S3_BLOCKED",
        "tiles": {...},           # Flattened ID-based map
        "strategy_sections": [...], # Specialist + local expert sections
        "itinerary_day_cards": [...] | null,
        "constraints_validated": [...],
        "constraint_violations": [...],
        "itinerary_overview": str | null,
        "itinerary_assumptions": str | null,
        "hotel_filter_cascaded": str | null,
        "ack_status": "applied" | "partial" | "rejected" | "no_change",
        "ack_updates": [{"field": str, "to": str}],
        "applied_updates": [...],
    },
}
```
