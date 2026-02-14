# Plan Graph Architecture

> **Source**: `backend/app/plan_graph.py` > **Planner Package**: `backend/app/planner/` > **Prompt Files**: `backend/app/prompts/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Package Structure](#package-structure)
3. [Node Architecture Diagram](#node-architecture-diagram)
4. [Complete Node Reference Table](#complete-node-reference-table)
5. [Key Node Details](#key-node-details)
6. [State Models](#state-models)
7. [Routing Logic](#routing-logic)
8. [Specialist Domain Knowledge](#specialist-domain-knowledge)
9. [Constraint Validation](#constraint-validation)
10. [Caching Architecture](#caching-architecture)
11. [Selective Regeneration](#selective-regeneration)
12. [Prompt File Mapping](#prompt-file-mapping)
13. [Streaming Architecture](#streaming-architecture)
14. [Tile Service Architecture](#tile-service-architecture)
15. [Booking Provider Interface](#booking-provider-interface-scaffolding)

---

## Architecture Overview

LangGraph-based conversational trip planning system with **7 nodes**.

| Category            | Count | Description                                                                                                                 |
| ------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------- |
| LLM-Powered Nodes   | 4     | IntentRouter, TripArchitect, VerticalSpecialist, Synthesizer                                                                |
| Domain Specialists  | 1     | LocalExpert (Static Dict + Optional LLM, gated by `LOCAL_EXPERT_USE_LLM`, default off, uses `settings.extraction_model` via `llm_factory` when enabled) |
| Data Fetchers       | 1     | LogisticsNode (flight fetching + safety logic)                                                                              |
| Deterministic Nodes | 1     | ConstraintGuard (mostly deterministic + one LLM-backed validation: `validate_place_exists()` via gpt-4o-mini)               |
| **Total Nodes**     | **7** | Core graph nodes                                                                                                            |

> **Note:** `ItineraryBuilder` is a pure Python **service** (not a LangGraph node). It's called from both `format_result()` in `response_envelope.py` (via `itinerary_adapter.py`, shadow mode at S2_STRATEGY_READY) and the `/api/expand-itinerary` endpoint. The 7-node architecture is preserved.

### Design Principles

1. **"Flights/Hotels are NOT Agents"** - They are data fetchers (LogisticsNode + TileService)
2. **"Diving IS an Agent"** - It requires domain logic (VerticalSpecialist)
3. **"Architect sees the whole picture"** - Avoids context fracture
4. **TripPlan is the SSoT** - Single Source of Truth for trip state
5. **LLM-Based Intent Classification** - No regex minefield, `settings.router_model` (default `gpt-4o-mini`) classifies
6. **Panic Button** - Hard-coded reset commands bypass LLM entirely
7. **Constraint Injector Pattern** - Specialist runs BEFORE Architect calls tools
8. **Local Expert Fallback** - Generic trips always have content via LocalExpert
9. **Auto-Fix Loop** - ConstraintGuard can loop back to Architect once to self-correct
10. **Itinerary Synthesis** - ItineraryBuilder is pure Python (no LLM) for deterministic scheduling
11. **Exploration Mode** - Conversational Q&A using Local Expert knowledge before planning
12. **Progressive Nudging** - Gradual transition from exploration to planning (1st: open, 2nd: soft nudge, 3rd+: invitation)

---

## Package Structure

```
backend/app/planner/
├── __init__.py              # Facade exports (stable public API)
├── cache_access.py          # Cache utilities
├── hashing.py               # Stable hashing utilities
├── meta.py                  # Metadata helpers
├── meta_keys.py             # Metadata key constants
├── llm_factory.py           # Provider-agnostic LLM factory (OpenAI/Gemini auto-routing)
├── telemetry.py             # Telemetry instrumentation
├── test_mode.py             # Test mode detection
├── specialist_registry.py   # Specialist config SSoT (keywords, constraints, enhancements, flags)
#   Frontend mirror: frontend/lib/specialists.ts (colors, icons, keywords, display names)
├── nodes/                   # Node implementations
│   ├── __init__.py          # Node exports
│   ├── constraint_guard.py  # Mostly deterministic validation (one LLM-backed check: validate_place_exists)
│   ├── input_gate_config.py # Input gate threshold constants (dates, travelers, budget)
│   ├── input_gates.py       # Pre-routing input validation (5 gates: Date, Duration, Traveler, Budget, Destination)
│   ├── intent_router.py     # LLM-based intent classification
│   ├── local_expert.py      # City logistics concierge
│   ├── logistics_node.py    # Flight fetching + safety logic
│   ├── router_category_sync.py # Tier 2 activity detection, actionable input, planning readiness
│   ├── router_extraction.py # LLM-based intent classification + field extraction (RouterOutput schema)
│   ├── router_utils.py      # Shared router utilities (greetings, origin detection, destination context)
│   ├── specialist_schemas.py # Specialist Pydantic schemas
│   ├── synthesizer.py       # Unified response generation
│   ├── trip_architect.py    # Core planning node (The Boss)
│   └── vertical_specialist.py # Domain specialist (8 specialists, registry-driven)
├── services/
│   ├── __init__.py          # Services package (exports section_builder + itinerary_adapter + iata_resolver)
│   ├── admin_utils.py       # Cache management, debugging, observability, startup validation
│   ├── iata_resolver.py     # IATA airport code resolver (LLM-backed with state caching)
│   ├── itinerary_adapter.py # Thin bridge: GraphState → ItineraryBuilder
│   ├── response_envelope.py # Formats GraphState → frontend response (trip inputs, sections, itinerary)
│   ├── section_builder.py   # Strategy section CRUD (upsert, anchor sort, builders)
│   └── state_serde.py       # State serialization: GraphState ↔ session_state, TripPlan → trip_inputs
└── state/
    ├── __init__.py          # State exports
    ├── graph_state.py       # State models (GraphState, TripPlan, TripSettings, SpecialistConstraint, etc.)
    └── typed_meta.py        # Typed metadata bridge (TurnMeta, PersistentMeta, get_trip_settings)
```

---

## Node Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ENTRY POINT                                     │
│                                                                              │
│  PANIC BUTTON CHECK (in run_turn, BEFORE graph)                             │
│  Commands: /reset, reset, stop, clear, /stop, /clear                        │
│  → Bypasses LLM entirely, returns reset response                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  IntentRouter (LLM - Fast: router_model, default GPT-4o-mini)               │
│  ─────────────────────────────────────                                      │
│  LLM-based intent classification (no regex!)                                │
│  • Classifies: GREETING, RESET, or PLANNING                                 │
│  • Detects: specialist_hint (8 specialists via registry)                   │
│  • GREETING/RESET → Static response, skip to Synthesizer                    │
│  • SETTINGS_TO_LOGISTICS → Hotel/flight/budget/traveler changes → Logistics │
│  • ACTIONABLE_TO_LOGISTICS → Tier 2 activities, removals, skill, resets     │
│  • EXPLORATION → Generic Q&A using Local Expert knowledge (LLM fallback for unknown destinations) │
│  • SOFT_TRANSITION → Routes to PLANNING when dates OR activities provided   │
│  • PLANNING + no specialist → LocalExpert (city logistics)                  │
│  • PLANNING + specialist → VerticalSpecialist                               │
│  ~150 tokens, ~300ms (0 tokens for exploration/settings/actionable modes)   │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼──────────────────────────┬───────────────┐
         │ GREETING/RESET          │ PLANNING                 │ PLANNING      │
         │ (short_circuit)         │ (specialist detected)    │ (generic)     │
         ▼                         ▼                          ▼               │
┌────────────────────┐  ┌─────────────────────────┐  ┌────────────────────────┤
│  → Synthesizer     │  │  VerticalSpecialist     │  │  LocalExpert           │
│    (skip architect)│  │  (LLM - Expert)         │  │  (City Concierge)      │
│                    │  │  ─────────────────────  │  │  ────────────────────  │
│  Returns static    │  │  Domain expert node     │  │  • Opening hours       │
│  response with     │  │  8 specialists via      │  │  • Booking windows     │
│  suggested_replies │  │  specialist_registry.py │  │  • Transit passes      │
│                    │  │                         │  │  • Cultural tips       │
│                    │  │                         │  │                        │
│                    │  │  Returns:               │  │  Returns:              │
│                    │  │  • Constraints          │  │  • Constraints         │
│                    │  │  • Content blocks       │  │  • Recommendations     │
│                    │  │  • Critique             │  │  • Strategy section    │
│                    │  │  • Enhancements         │  │                        │
└────────────────────┘  └───────────┬─────────────┘  └───────────┬────────────┘
                                    │                            │
                                    │                            │
                                    └─────────────┬──────────────┘
                                                  │
                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LogisticsNode (Data Fetcher - No LLM)                                      │
│  ─────────────────────────────────────                                      │
│  Fetches and sanitizes tile data (flights, hotels, activities)              │
│  1. Check for curated destination (Dubai, Rome, Chamonix, Bali, Patagonia)  │
│     → CuratedProvider for hotels/activities                                 │
│  2. Fallback to MockProviders for non-curated destinations                  │
│  3. Curated/Demo flights with carrier sanitization (XX → Emirates)          │
│  4. Apply 24h no-fly safety logic if diving constraints exist               │
│                                                                             │
│  Outputs to: state.tiles["flights"], ["hotels"], ["activities"]             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │ route_after_logistics()     │
                    │ Skip if architect ran       │
                    ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  TripArchitect (LLM - Smart) [SKIPPED if already ran this turn]             │
│  ────────────────────────────                                               │
│  "The Boss" - General Agent in UI                                           │
│  • Manages TripPlan (SSoT)                                                  │
│  • Modes: pre_core (inspiration), missing_fields, planning                  │
│  • Calls fetch_travel_tiles tool when needed                                │
│  • Respects constraints from Specialist/LocalExpert                         │
│  • Extracts: destination, origin, dates from user text                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │ tiles or constraints        │ no validation needed
                    ▼                             │
┌────────────────────────────────────┐            │
│  ConstraintGuard (Python)          │            │
│  ────────────────────────────────  │            │
│  Mostly deterministic validation   │            │
│  One LLM-backed check:            │            │
│  validate_place_exists (gpt-4o-mini)│           │
│  • Budget: total < allocation      │            │
│  • Temporal: dates valid           │            │
│  • Specialist: departure buffer    │            │
│  • Specialist: cross-domain blocks │            │
│                                    │            │
│  Returns: violations[], has_blocking│           │
│                                    │            │
│  AUTO-FIX LOOP (NEW):              │            │
│  If blocking + retry_count < 1     │            │
│    → Route back to Architect       │            │
│    → Self-correct before user sees │            │
└───────────────┬────────────────────┘            │
                │                                 │
                └────────────────┬────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Synthesizer (LLM - Writer)                                                 │
│  ───────────────────────────                                                │
│  Unified response generation                                                │
│  • Response type-aware tone (planning = solver, greeting = warm)            │
│  • Generates suggestions via registry-driven pool (up to 3 chips)           │
│  • Enriches content with Unsplash images                                    │
│  • Handles constraint warnings gracefully                                   │
│  • Templates: greeting, exploration, planning, specialist_update            │
│                                                                             │
│  Response Type Classification:                                              │
│  • greeting: short_circuit_type in ("greeting", "reset")                    │
│  • exploration: exploration_mode flag set                                   │
│  • specialist_update: specialist_hint OR specialist_just_ran                │
│  • planning: trip_plan.destination exists (default solver tone)             │
│                                                                             │
│  Solver Identity (planning/specialist_update):                              │
│  - "Expedition Leader" voice: SHOW expertise through specifics              │
│  - NEVER say "Specialist active", "Buffer applied" — system jargon          │
│  - Explain constraints naturally within recommendations                     │
│  - 2-3 sentences max, no travel-brochure adjectives                         │
│                                                                             │
│  Key Principle: "One voice, regardless of which agents contributed"         │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
                              ┌─────────┐
                              │   END   │
                              └─────────┘
```

### Frontend Trigger Points

The frontend triggers itinerary generation via the "Build Itinerary" CTA when:

1. Destination is set
2. Dates are provided
3. (Optional) User has hearted preferred tiles

**API Call:** `POST /api/expand-itinerary` with:

```json
{
  "preferences": {
    "preferred_hotel_ids": ["tile_id_1", "tile_id_2"],
    "preferred_activity_ids": ["tile_id_3"]
  }
}
```

The `ItineraryBuilder` applies a 1.5x score multiplier to preferred tiles when
selecting accommodations. Attribution is tracked via `preference_status` field
on day blocks (`user_preferred`, `ai_selected`, or `ai_override`).

---

## Complete Node Reference Table

### Nodes

| Node                              | Type                       | Purpose                           | LLM Model                                                          | Max Tokens | Streaming             |
| --------------------------------- | -------------------------- | --------------------------------- | ------------------------------------------------------------------ | ---------- | --------------------- |
| `router` (IntentRouter)           | LLM (Fast)                 | Intent classification             | `settings.router_model` (default `gpt-4o-mini`, via `llm_factory`) | 150        | None                  |
| `architect` (TripArchitect)       | LLM (Smart)                | Core planning, SSoT management    | `settings.extraction_model` (default `gpt-4o-mini`, via `llm_factory`) | Variable   | Simulated             |
| `specialist` (VerticalSpecialist) | LLM (Expert)               | Domain constraints + content      | `settings.specialist_model` (default `gpt-4o`, via `llm_factory`) | Variable   | Simulated             |
| `local_expert` (LocalExpert)      | Static Dict + Optional LLM | City logistics concierge          | `settings.extraction_model` (when `LOCAL_EXPERT_USE_LLM=true`, default off) | N/A        | None                  |
| `logistics` (LogisticsNode)       | Data Fetcher               | Flight fetching + safety          | N/A                                                                | N/A        | None                  |
| `guard` (ConstraintGuard)         | Python                     | Validation (mostly deterministic) | gpt-4o-mini (place validation only, via `validate_place_exists()`) | N/A        | None                  |
| `synthesizer` (Synthesizer)       | LLM (Writer)               | Response generation               | `settings.synthesizer_exploration_model` (exploration/specialist_update) or `settings.synthesizer_planning_model` (planning), via `llm_factory` | Variable   | True (astream_events) |

\*LocalExpert uses static knowledge from `LOCAL_EXPERT_KNOWLEDGE` dictionary. Optional LLM generation is gated by `LOCAL_EXPERT_USE_LLM` (default off) and uses `settings.extraction_model` via `get_llm_by_model(...)`.

### NODE_STATUS_CONFIG (UI Progress Labels)

| Node           | Label                           | Icon     | Estimated Duration |
| -------------- | ------------------------------- | -------- | ------------------ |
| `router`       | "Reading your message..."       | brain    | 300ms              |
| `architect`    | "Understanding your request..." | building | 800ms              |
| `specialist`   | "Consulting expert..."          | star     | 1000ms             |
| `local_expert` | "Loading local knowledge..."    | building | 50ms               |
| `logistics`    | "Fetching flight options..."    | plane    | 2000ms             |
| `guard`        | "Checking constraints..."       | shield   | 100ms              |
| `synthesizer`  | "Writing response..."           | pen      | 1500ms             |

### Streaming Legend

| Symbol    | Mode                 | Description                                 |
| --------- | -------------------- | ------------------------------------------- |
| None      | `buffered:internal`  | Internal node, no user-facing output        |
| Simulated | `simulate_streaming` | Token-by-token delivery with 15-35ms delays |
| True      | `astream_events`     | Real-time tokens from LLM API via LangGraph |

---

## Key Node Details

### IntentRouter

LLM-based intent classification AND field extraction using `settings.router_model` (default `gpt-4o-mini`) with Pydantic structured output via `get_llm_by_model(...)`.

| Classification          | Trigger                                        | Action                                                                                 |
| ----------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------- |
| `GREETING`              | "Hi", "Hello", "Thanks!" (no planning content) | Static response, skip architect                                                        |
| `RESET`                 | "Start over", "Reset", "Begin again"           | Clear state, static response                                                           |
| `PLANNING`              | Everything else (trip-related)                 | Extract fields → Pass to Specialist or LocalExpert                                     |
| `GENERATE_PLAN_TRIGGER` | "GENERATE_PLAN_TRIGGER" message from frontend  | Trigger mechanism (sets intent to `"booking"`) → Force clear tiles → Full regeneration |

**GENERATE_PLAN_TRIGGER Handling:**

When the frontend sends the `GENERATE_PLAN_TRIGGER` message, the router detects it via `is_generate_trigger` flag and sets `state.intent = "booking"` (not a separate intent type):

```python
# intent_router.py - forced tile cache clear
elif is_generate_trigger:
    state.intent = "booking"
    # FORCE clear tiles - ensures fresh tiles for new destination
    state.tiles = {}
    state.metadata["tiles_destination"] = None
    logger.info("[Router] 🔥 GENERATE_PLAN_NOW - forced tile cache clear")
```

This ensures that when a user changes destination (e.g., Bali → Paris) and clicks Refresh:

1. Old Bali tiles are cleared immediately
2. LogisticsNode fetches fresh Paris tiles
3. Frontend receives new tiles, not cached stale data

**Critical Rules:**

- "Hi, I want to go to Paris" → PLANNING (has content!)
- "No, I prefer Rome" → PLANNING (negation with alternative)
- "Stop in Rome" → PLANNING (layover, not reset!)
- If unsure, default to PLANNING (let architect handle it)

**Two-Path Architecture (Phase 2):**

The Router uses two distinct execution paths depending on whether a plan is already active:

| Path                       | Condition                | LLM Extraction                                         | Settings/Modifications                                                                                                 | Origin Detection                                |
| -------------------------- | ------------------------ | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| **Post-plan (LLM-first)**  | `plan_is_active` (S2/S3) | Runs FIRST on every message                            | Read from `RouterOutput` fields via `_collect_settings_from_extraction()` / `_collect_modifications_from_extraction()` | Read from `RouterOutput.origin`                 |
| **Pre-plan (regex-first)** | No active plan           | Runs only when `has_date_in_message` detected by regex | Regex-based detection in `_detect_actionable_input()`                                                                  | Regex-based via `_detect_origin_from_message()` |

**Post-plan fast path:** When `plan_is_active`, the LLM extraction call (`_classify_and_extract_with_llm()`, `max_tokens=700`) runs unconditionally. The `RouterOutput` includes 10 additional fields for modification/settings extraction (see schema below). Three shared state-mutation helpers then apply the results:

1. `_apply_origin_to_state(state, origin, ...)` — sets `trip_plan.origin`, resolves IATA code
2. `_apply_settings_to_state(state, settings_dict)` — writes hotel/flight settings to `TripSettings`
3. `_apply_modifications_to_state(state, mods_dict)` — processes removals, skill level changes, budget/hotel resets

**Regex settings merge fallback:** After LLM extraction, `_detect_settings_from_message()` (regex-based) runs as a fallback to catch settings the LLM missed (e.g., "5-star hotels only" → `hotel_min_stars`). Regex settings are merged into LLM settings for keys not already extracted. Additionally, `reset_hotel` / `reset_budget` flags are suppressed when the same extraction also sets `hotel_settings` / `budget` (prevents the LLM from incorrectly flagging a reset alongside a concrete setting).

**Pre-plan path:** Regex detection runs first (`DATE_INDICATORS`, `ORIGIN_PATTERNS`, `_detect_actionable_input()`). The opportunistic LLM extraction gate fires only when `has_date_in_message and not router_extracted_fields`, avoiding redundant extraction when the post-plan path already ran.

**Reader functions** in `router_category_sync.py` bridge `RouterOutput` dict to structured dicts:

- `_collect_settings_from_extraction(ro_dict)` → `{"hotel_min_stars": 4, "flight_cabin_class": "business", ...}` or `None`
- `_collect_modifications_from_extraction(ro_dict, state)` → `{"remove_categories": [...], "add_categories": [...], "skill_level": "advanced", ...}` or `None`
- `_get_current_categories(state)` → current category list from `activity_settings`

**Structured Output Extraction:**

`_classify_and_extract_with_llm()` uses `llm.with_structured_output(RouterOutput)` with `settings.router_model` (default `gpt-4o-mini`):

1. Retries once on failure (`MAX_RETRIES = 1`) with raw error logging per attempt
2. Treats `parsed is None` as a failed extraction attempt (ambiguous short input), then retries/fails through the same error path
3. Extracts dates, destination, origin, travelers, budget, activity_day_preferences, modifications, and settings in ONE call
4. Populates `state.trip_plan` immediately via `_populate_trip_plan_from_router_output(state, router_output, destination, user_text)`
5. Sets `router_extracted_fields = True` flag for TripArchitect to skip duplicate extraction
6. `ROUTER_EXTRACTION_PROMPT` has 9 tasks: (1) Intent Classification, (2) Field Extraction, (3) Flags, (4) Activity Categories (Tier 2), (5) Activity Day Preferences, (6) Modification Detection, (7) Settings Extraction, (8) Planning Intent Classification, (9) Question Classification. Specialist Detection is embedded in the prompt between Tasks 3 and 4.

**Error Handling (no silent fallbacks):**

If all extraction retries are exhausted, the exception propagates to the caller. Both call sites in `intent_router.py` (opportunistic extraction and unresolved token resolution) have their own `try/except` that log the failure, set `state.metadata["router_extraction_failed"] = True`, and continue without overwriting state. The `_debug.router_extraction_failed` flag surfaces in the SSE response envelope for frontend observability.

**Field Normalization (Cache Key Consistency):**

Extracted fields are validated and normalized to ensure consistent cache keys:

```python
def _validate_extraction(extracted: dict, today_date: str) -> dict:
    # Normalize destination/origin (remove country suffixes)
    # "Bali, Indonesia" → "Bali"
    # "NYC" → "New York"
    for field in ["destination", "origin"]:
        if extracted.get(field):
            extracted[field] = _normalize_city_name(extracted[field])

    # Validate date format (must be YYYY-MM-DD)
    # Swap if end < start

    # Normalize activities to lowercase
    # "Scuba Diving" → "diving"

    return extracted
```

The LLM prompt also instructs canonical extraction:

- Destinations: "Paris, France" → "Paris"
- Abbreviations: "NYC" → "New York", "LA" → "Los Angeles"
- Edge cases kept: "Mexico City", "Kansas City", "Washington DC"

**Date Indicator Detection:**

```python
DATE_INDICATORS = [
    r"\b(january|february|march|...)\b",  # Month names
    r"\b(next week|next month|this weekend|tomorrow)\b",  # Relative dates
    r"\b\d{1,2}[/-]\d{1,2}\b",  # Numeric patterns
]
# Canonical copy lives in specialist_registry.py
```

This fixes the bug where users said "I want to go diving March 1-8" but were asked for dates again.

**Plan-Active Extraction Gate:** When a plan is active (`plan_view_state` in `S2_STRATEGY_READY`/`S3_ITINERARY_READY`), the LLM extractor fires on EVERY message (post-plan LLM-first path). This ensures date modifications from suggestion chips (e.g., "Extend to Feb 17" -- abbreviated months that regex misses) are always extracted. Cost: ~$0.0004/call x 5-8 planning turns.

**Post-Extraction Intent Upgrade:** After opportunistic extraction, if dates changed (`start_date != old_start_date or end_date != old_end_date`), `planning_intent` is upgraded to `"soft_transition"` regardless of the initial classification. This routes to the soft_transition path that re-queues specialists with new dates, preventing the stale "exploring" classification from short-circuiting.

**Post-Plan Date Drift Guard:** After LLM extraction in the post-plan path, the router checks whether the user's text actually mentions date-change signals before accepting extracted date mutations. If `start_date` changed but the user text lacks start-related keywords ("start", "begin", "from", "depart", "leave on", "move"), the start date is reverted to `old_start`. Same for `end_date` with end-related keywords ("extend", "until", "end", "through", "shorten", "move"). Prevents the LLM from drifting dates on messages like "tell me more about diving" that happen to re-extract dates with slight shifts.

**Input Gate Validation (Post-Extraction):**

After LLM extraction populates `state.trip_plan`, the router runs `_run_input_gates(state)` via `GateRegistry`. Five gates validate trip fields:

| Gate              | Checks                                                            | Severity         |
| ----------------- | ----------------------------------------------------------------- | ---------------- |
| `DateGate`        | Past dates, end before start, >18 months out                      | blocking         |
| `DurationGate`    | <1 day, >90 days (blocking); >30 days (warning)                   | blocking/warning |
| `TravelerGate`    | Children without adults, >25 total                                | blocking         |
| `BudgetGate`      | <$50 (blocking), >$500K (blocking), >$100K (warning)              | blocking/warning |
| `DestinationGate` | Multi-destination detection (LLM flag primary, 3+ comma fallback) | warning          |

Blocking gates short-circuit to synthesizer (`short_circuit_type: "gate_blocked"`). Warnings continue with notes in `state.metadata["input_gate_warnings"]`. Gate exceptions are caught and logged (fail-open). Thresholds are centralized in `input_gate_config.py`. **Important:** `router_extracted_fields` is set BEFORE input gates run — even if gates block, the Architect should NOT re-extract the same message on a subsequent turn.

**Multi-Destination Handling:** `RouterOutput` includes `multi_destination_detected` field. When true, `_populate_trip_plan_from_router_output()` stashes `_multi_dest_from_llm` and `_deferred_destinations` on `trip_plan` for `DestinationGate` to produce a warning like "Starting with Rome — we can plan Switzerland after this itinerary is set."

**Specialist Detection:**

Specialist keywords are defined in `backend/app/planner/specialist_registry.py` via `ALL_SPECIALIST_KEYWORDS`.
The registry manages detection for **8 specialists**: diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari.
Intent router imports and uses these keywords for both specialist detection and activity indicator matching.

**Actionable Input Detection (Pre-Exploration):**

`_detect_actionable_input()` runs AFTER settings detection, BEFORE `detect_planning_intent()`.
Catches chat inputs that would otherwise be swallowed by the exploration short-circuit:

| Input Type               | Detection                                                 | Route                           | Example             |
| ------------------------ | --------------------------------------------------------- | ------------------------------- | ------------------- |
| Tier 2 activity addition | `TIER2_ACTIVITY_KEYWORDS` (from `specialist_registry.py`) | `ACTIONABLE_TO_LOGISTICS`       | "yoga as well"      |
| Activity removal         | `REMOVAL_PATTERN` + known-activity guard                  | `ACTIONABLE_TO_LOGISTICS`       | "skip the yoga"     |
| Skill level              | `SKILL_LEVEL_MAP` keywords                                | `ACTIONABLE_TO_LOGISTICS`       | "I'm a beginner"    |
| Budget reset             | `RESET_BUDGET_PATTERN`                                    | `ACTIONABLE_TO_LOGISTICS`       | "no budget limit"   |
| Hotel reset              | `RESET_HOTEL_PATTERN`                                     | `ACTIONABLE_TO_LOGISTICS`       | "any hotel is fine" |
| Mixed Tier 1+2           | Tier 2 detected + Tier 1 keyword present                  | Fall through to SOFT_TRANSITION | "yoga and diving"   |
| Misspelled activity      | `_fuzzy_resolve_token()` via rapidfuzz                    | `ACTIONABLE_TO_LOGISTICS`       | "hking and divng"   |

**Fuzzy Typo Resolution (Pre-LLM):**

Unresolved tokens (words not matching any known category, stop word, or skill level) are fuzzy-matched
against `_FUZZY_VOCAB` (union of `TIER2_ACTIVITY_KEYWORDS` and `TIER1_SPECIALIST_NAMES`) using
`rapidfuzz.fuzz.ratio` with `score_cutoff` from `settings.fuzzy_match_score_cutoff` (default 76).
Matches are added directly to `add_categories`; only truly unresolved tokens fall through to
the LLM alias resolution path in `intent_router.py`. Graceful degradation: if `rapidfuzz` is
unavailable, the fuzzy step is silently skipped.

`_detect_specialist_keywords()` in `router_extraction.py` also has a fuzzy fallback: when exact
keyword matching finds nothing, it fuzzy-matches input words against `ALL_SPECIALIST_KEYWORDS` topic
names using the same scorer and threshold.

Uses the same `origin_only_logistics` fast-path flag as `SETTINGS_TO_LOGISTICS`.

**Tier 1 Category Sync (SOFT_TRANSITION):**

When specialists are detected via chat in the SOFT_TRANSITION path, they are now also synced to
`activity_settings.categories`. Without this, logistics sees `categories=[]` and treats it as
"pure Tier 1", suppressing all activity tiles — even when Tier 2 activities are added later.

**Routing Decision (Local Expert Always First):**

CRITICAL: Local Expert ALWAYS runs first to generate the "Trip Overview" anchor card.
Niche specialists are ADDITIVE, not replacements.

```python
# When "diving in Bali" detected:
# Queue built: ["local_expert", "diving"]
#
# Flow:
# 1. Router → LocalExpert (generates Trip Overview)
# 2. LocalExpert → VerticalSpecialist (generates Diving Strategy)
# 3. VerticalSpecialist → Logistics/Architect
```

- Specialist detected → Queue = `["local_expert", "diving"]` → LocalExpert first
- No specialist → Queue = `["local_expert"]` → LocalExpert only

See `ux_unified_architecture.md` Section III.A for full specification.

### TripArchitect

"The Boss" - the General Agent in the UI.

| Mode             | Trigger                        | Behavior                                 |
| ---------------- | ------------------------------ | ---------------------------------------- |
| `pre_core`       | No destination                 | Inspiration mode - ask leading questions |
| `missing_fields` | Has destination, missing dates | Trigger Setup Modal                      |
| `planning`       | Core fields present            | Build trip with tools                    |

**Extraction Logic:**

- Origin: Detects "from X to Y" pattern
- Destination: Detects "to X", "in X", "visit X" patterns
- Dates: Placeholder (uses real date parsing in production)
- Settings: LLM-based extraction gated by `_has_settings_keywords()` — only triggers
  on compound phrases with booking context (`"direct flight"`, `"budget hotel"`,
  `"skip flights"`). Generic words like "class", "activity", "budget" alone do NOT
  trigger extraction. The LLM prompt requires explicit user intent for toggle=off.

**Tool Usage:**

```python
# Only calls fetch_travel_tiles when:
# - Plan is ready (destination + dates)
# - User asked for booking options
# - Don't have fresh tiles already
# - Logistics hasn't already provided tiles (skip redundant fetch)
```

**GENERATE_PLAN_NOW:** When all trip fields are present and the trigger message is the synthetic `GENERATE_PLAN_NOW` (from stepper re-run), LLM extraction is skipped entirely — the existing `trip_plan` fields are authoritative.

**Extraction Skip Guards:** Three conditions skip the Architect's LLM extraction: (1) `router_extracted_fields` flag set by Router, (2) system trigger message (`GENERATE_PLAN_NOW`, `BUILD_PLAN`, `REFRESH`), (3) core fields already present (destination + dates + router_output in metadata). The third guard catches edge cases where the flag wasn't set but extraction already ran.

**Tile Fetch Skip:** `should_fetch_tiles()` returns `False` when `state.tiles` already contains hotels or activities from LogisticsNode, preventing a redundant ~13s tile fetch. Activities from LogisticsNode are preserved during `fetch_tiles()` (Phase 5.6 needs them for logistics backfill).

**Condensed Tile Summary:** Response formatting uses a single sentence for all tile categories (e.g., `"Found **5 hotels**, **3 flights**."`) instead of per-category sentences.

### VerticalSpecialist

Domain expert that runs BEFORE Architect calls tools. **Uses LLM-first architecture with hardcoded fallback.**

**Key Insight:** Returns BOTH constraints AND content.

| Output           | Type                   | Example                             |
| ---------------- | ---------------------- | ----------------------------------- |
| `constraints`    | SpecialistConstraint[] | "24h surface interval after diving" |
| `content_blocks` | ItineraryBlock[]       | "Day 2: USAT Liberty Wreck"         |
| `critique`       | string                 | Review of current plan              |
| `enhancements`   | string[]               | "Book dive shop in advance"         |

#### LLM-First Architecture (Zero-Template System)

**Implementation:** Single LLM call per specialist generates feasibility + activities + constraints.

```python
# Prompts loaded from backend/app/prompts/specialists/{topic}.txt via registry
system_prompt = load_prompt(topic)  # from specialist_registry

# User skill level injected when available
if skill_level:
    system_prompt += f"\n\nUSER SKILL LEVEL: {skill_level}. ..."

async def generate_specialist_output_llm(topic, destination, trip_plan, db=None, skill_level=None, target_activities=None):
    """Single LLM call generates feasibility + activities + constraints."""
    llm = get_llm_by_model(settings.specialist_model, temperature=0.2)
    return await llm.with_structured_output(LLMSpecialistOutput).ainvoke(...)
```

**Token Optimization:** The user prompt does NOT include a JSON schema example - OpenAI's
function calling API receives the Pydantic schema from `.with_structured_output()` directly.
This saves ~200-500 tokens per specialist call while maintaining schema enforcement at the API level.

**Activity Count Scaling:** The LLM prompt dynamically scales the requested activity count based on trip duration:

- Short trips (≤5 available days): 2-3 activities
- Medium trips (6-10 available days): 3-5 activities
- Long trips (11+ available days): scales up to ~60% of available days, capped at 7
- **Default cap (no day preference):** max 3 activities — prevents unbounded specialists from overstuffing the itinerary
  Available days = `duration_days - 2` (excluding arrival/departure). When `day_preferences` provides an explicit count, the cap respects that instead.

**Fallback Mechanism:** If LLM fails (parse error, timeout), falls back to minimal safety constraints from the registry:

```python
def _get_minimal_safety_constraints(topic: str) -> List[SpecialistConstraint]:
    """Registry-driven fallback when LLM fails - safety over features."""
    config = get_specialist_config(topic)
    if not config or not config.hardcoded_constraints:
        return []
    return [SpecialistConstraint(**hc) for hc in config.hardcoded_constraints]
```

**Domain Knowledge (LLM-Generated):**
All 8 specialists use LLM-generated domain knowledge. Prompt files instruct the LLM to use world knowledge for real destinations, including approximate lat/lng coordinates per activity.

- Diving: Flight buffers, certification requirements, real dive sites
- Hiking: Altitude acclimatization, elevation data, trail recommendations
- Skiing: Snow conditions, avalanche awareness, resort suggestions
- Cycling: Route distances, elevation, surface types
- Surfing: Wave heights, tide conditions, skill requirements
- Climbing: Altitude acclimatization, gear inspection, route difficulty
- Sailing: Weather windows, licensing, vessel requirements
- Wildlife Safari: Seasonal migration, guide requirements, drive timing

#### LLM Feasibility Layer

Geographic feasibility checking, gated by the `has_geographic_constraint` flag in the specialist registry.

**Registry-Gated Architecture:**

- Specialists with `has_geographic_constraint=True` (diving, skiing) → LLM feasibility check
- Specialists with `has_geographic_constraint=False` (hiking, cycling, surfing, climbing, sailing, wildlife_safari) → auto-feasible

```python
config = get_specialist_config(topic)
if not config or not config.has_geographic_constraint:
    return ("feasible", None, None)  # auto-feasible

# LLM check (200ms, cached)
possible, reason = get_feasibility_llm("diving", "Chamonix")
# LLM determines: landlocked alpine town → diving impossible
```

**Caching:** `@lru_cache(maxsize=1000)` - cache key is `f"{topic}:{destination}"`

**Cost:** ~$0.0001 per check, ~200ms latency (first call only)

**Fail-Open Policy:** If LLM fails, assume possible. False positives (user discovers no dive sites) are acceptable; false negatives (blocking valid destinations) break UX.

**Frontend Handling:** S2StrategyView renders infeasible specialists with:

- Red border and "Unavailable" badge
- `feasibility_reason` message from backend (no hardcoded frontend destination suggestions)

#### Multi-Specialist Optimization (Single-Entry Batch Processing)

When multiple specialists are queued (e.g., "diving and hiking in Bali"), the system uses two key optimizations:

1. **Parallel LLM execution:** All specialist LLM calls run concurrently via `asyncio.gather()`, cached in `state.metadata["parallel_llm_results"]`
2. **Single-entry batch processing:** All specialists are processed in ONE graph entry instead of re-entering the node per specialist. The `pending_specialists` queue is drained upfront and processed in a sequential loop within `_merge_specialist_into_state()`.

**Architecture:**

```
# OLD: Multiple graph re-entries (sequential Unsplash + assembly per entry)
Router → specialist(diving) → route_after_specialist → specialist(hiking) → route_after_specialist → logistics
              920ms                                        1133ms

# NEW: Single graph entry (parallel Unsplash + sequential assembly)
Router → specialist(diving+hiking) → route_after_specialist → logistics
              ~1400ms
```

**Implementation (`vertical_specialist()`):**

```python
# 1. Parallel LLM trigger (unchanged - first specialist triggers all)
all_specialists = [topic] + list(state.pending_specialists)
parallel_results = await generate_all_specialists_parallel(...)
state.metadata["parallel_llm_results"] = {...}

# 2. Drain queue and batch process
all_topics = [topic] + list(state.pending_specialists)
state.pending_specialists = []  # Drain — handle all in this entry

# 3. Parallel Unsplash prefetch (skip cached topics)
topics_to_prefetch = [t for t in all_topics if not _is_selectively_cached(t)]
if len(topics_to_prefetch) > 1:
    await asyncio.gather(*[prefetch_destination_images(dest, activities=[t]) for t in topics_to_prefetch])

# 4. Sequential processing loop
for current_topic in all_topics:
    await _merge_specialist_into_state(state, current_topic, ...)
```

**`_merge_specialist_into_state()` helper:**

- Selective regeneration check at top (skip cached topics via `return`, not `return state`)
- Creates `VerticalSpecialist(topic)`, calls `generate_output(state)` (Unsplash cache already warm)
- Handles infeasible (`return` — loop continues), caveat, feasible paths
- **Destination-level infeasibility cache:** If a cached section has `feasibility_status == "infeasible"` and the destination hasn't changed, the specialist is skipped without re-querying the LLM (infeasibility is destination-dependent, not date-dependent — skiing in Bali stays infeasible regardless of trip duration). Returns early with `specialist_infeasible` metadata + `SPECIALIST_INFEASIBLE` UI event.
- **Parallel batch filter:** Before parallel execution, specialists already marked infeasible at the current destination (via `strategy_sections`) are filtered from `all_specialists` to avoid redundant LLM calls.
- Assembles strategy section, injects constraints/content blocks, builds UI state

**Cache Strategy:**

- LLM results cached in `state.metadata["parallel_llm_results"]` as serialized dicts
- Subsequent specialist processing deserializes cached results using `LLMSpecialistOutput.model_validate()`
- Unsplash images cached in `_memory_cache` dict — parallel prefetch warms cache for all topics at once
- **Single specialist:** Uses L1+L2 database cache directly (same path as parallel)

**Debug Output (DEBUG=full):**

```
# Multi-specialist (single entry, parallel Unsplash)
[DEBUG] [SPECIALIST] PARALLEL TRIGGER: 2 specialists detected
[DEBUG] [SPECIALIST] Parallel Unsplash prefetch: 2 topics (['diving', 'hiking'])
[DEBUG] Processing diving (1/2)
[DEBUG] Processing hiking (2/2)
[DEBUG] ✓ SPECIALIST | ~1400ms | topics=diving,hiking

# Single specialist (L1+L2 cache)
[DEBUG] [SPECIALIST] Single specialist 'diving' - using cached LLM path
[DEBUG] [SPECIALIST_CACHE] ✅ HIT for diving - skipping LLM
[DEBUG] ✓ SPECIALIST | ~10ms | topic=diving
```

**Performance Impact:**
| Scenario | Cold (no cache) | Warm (L2 hit) | Hot (L1 hit) |
|----------|-----------------|---------------|--------------|
| 1 specialist | ~5s (LLM) | ~50ms (DB) | ~10ms (memory) |
| 2 specialists | ~5s (parallel LLM) + ~1.4s (batch) | ~100ms | ~20ms |
| 3 specialists | ~6s (parallel LLM) + ~2s (batch) | ~150ms | ~30ms |

**Key constraint:** Specialists are processed sequentially within the batch because `generate_output()` reads state (constraints, activity days) that prior specialists may have modified. Only Unsplash I/O is parallelized.

### LocalExpert

The "Concierge" node for city trips - ensures the Agent Feed is never empty. Uses **Static Dict + Optional LLM** (gated by `LOCAL_EXPERT_USE_LLM`, default off, uses `settings.extraction_model` via `llm_factory` when enabled).

**Activation:** Default when no niche specialist (diving/hiking/skiing) is detected. Also runs first in multi-specialist flows (Trip DNA anchor).

**Implementation:** Pure dictionary lookup from `LOCAL_EXPERT_KNOWLEDGE`:

```python
LOCAL_EXPERT_KNOWLEDGE = {
    "dubai": {...},
    "paris": {...},
    "rome": {...},
    "london": {...},
    "amsterdam": {...},
    "tokyo": {...},
    "new york": {...},
    "bali": {...},
    # 8 destinations with comprehensive data
}

def local_expert(state):
    knowledge = LOCAL_EXPERT_KNOWLEDGE.get(destination.lower())
    # Static dict lookup; optional LLM gated by LOCAL_EXPERT_USE_LLM env var
```

**Provides:**

- Opening hours and closed days (e.g., "Louvre closed on Tuesdays")
- Booking lead times for popular attractions
- Transit passes and efficiency tips (e.g., "Paris Museum Pass saves €40+")
- Cultural considerations (dining hours, tipping, dress codes)
- Seasonality information
- Safety and health tips

**Static Knowledge Destinations:**

- Bali, Dubai, Paris, Rome, London, Amsterdam, Tokyo, New York

**Output Format (Pydantic Schema — used for both data storage and optional LLM extraction):**

```python
class LocalConstraint(BaseModel):
    type: str = "general"
    description: str
    severity: str = "info"

class LocalRecommendation(BaseModel):
    title: str
    description: str
    category: str = "logistics"
    logic_hook: str = ""

class LocalExpertOutput(BaseModel):
    """Comprehensive structured output with 12 categories + legacy fields."""
    # Overview
    destination_overview: DestinationOverview
    # The 12 Categories
    visa_entry: VisaEntry
    safety_health: SafetyHealth
    money_costs: MoneyCosts
    transportation: Transportation
    cultural_norms: CulturalNorms
    connectivity: Connectivity
    seasonality: Seasonality
    things_to_do: ThingsToDo
    neighborhoods: Neighborhoods
    accommodation: Accommodation
    scams_traps: ScamsTraps
    packing: Packing
    # Legacy fields for backward compatibility
    constraints: List[LocalConstraint]
    recommendations: List[LocalRecommendation]
    quick_tips: List[str]
```

**Note:** `LocalExpertOutput` is used for both static `LOCAL_EXPERT_KNOWLEDGE` data storage and optional LLM extraction (when `LOCAL_EXPERT_USE_LLM=true`). Each of the 12 categories is a nested Pydantic model with detailed sub-fields (e.g., `MoneyCosts` contains `currency`, `tipping: TippingInfo`, `typical_costs: TypicalCosts`, `daily_budget: DailyBudget`).

**LLM Fallback (Exploration Mode):** When answering generic Q&A about unknown destinations, the IntentRouter may use an LLM fallback (`_llm_fallback_answer`) - but this is NOT part of LocalExpert itself.

### LogisticsNode

Centralized tile fetching with safety logic. Runs AFTER Specialist/LocalExpert, BEFORE Architect.

**Provider Routing Strategy (Consistent with TileService):**

| Destination Type                                 | Hotels          | Activities      | Flights               |
| ------------------------------------------------ | --------------- | --------------- | --------------------- |
| Curated (Dubai, Rome, Chamonix, Bali, Patagonia) | CuratedProvider | CuratedProvider | Curated + Demo Backup |
| Non-Curated                                      | MockProvider    | MockProvider    | Demo Backup           |

> **Note:** Amadeus providers are disabled for now to ensure consistent behavior between first request and regeneration flows.

**Airport Code Resolution:**

- IATA codes are resolved by `services/iata_resolver.py:resolve_iata_codes()`
- Primary path: extracted by RouterOutput LLM call (piggybacks on existing intent extraction — free)
- Fast-path (regex origin): resolved in IntentRouter origin detection block before handoff to logistics
- Fallback: `resolve_iata_codes()` reads `state.trip_plan.origin_iata`/`destination_iata` first (instant), fires `settings.iata_resolver_model` via `get_llm_by_model(...)` only if missing (~50 tokens)
- No hardcoded airport mappings — all IATA codes are LLM-resolved

**Safety Logic (Diving Integration):**

- Detects diving constraints from VerticalSpecialist
- Applies 24h no-fly surface interval calculation
- Tags flights as safe/unsafe with `logic_hook` explanation

**Carrier Sanitization:**

- Maps test carrier codes to real airlines (XX → Emirates)
- Uses `CARRIER_MAP` from `demo_curation.py`

**Cache Key Split:** Logistics uses separate hashes for hotels and activities to prevent cross-busting (changing activity settings shouldn't invalidate hotel cache and vice versa):

- `_hotel_logistics_hash()`: origin, destination, dates, travelers, budget, hotel_settings, flight_settings
- `_activity_logistics_hash()`: origin, destination, dates, travelers, budget, activity categories, skill_level

**Output:**

- `state.tiles["flights"]` - Flight tiles for frontend display
- `state.tiles["hotels"]` - Hotel tiles for frontend display
- `state.tiles["activities"]` - Activity tiles for frontend display (two-tier filtering when specialists active)
- `state.metadata["flight_options"]` - Backwards compatibility

**Two-Tier Activity System:**

Activities use a two-tier system. **Tier 1** categories (diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari) trigger full specialist graph runs — when active, their generic logistics tiles are suppressed since specialists own that layer. **Tier 2** categories (yoga, cooking, nightlife, temples, beach, shopping, photography, sailing, wellness, culture, music, wine, food) generate real, destination-specific experience tiles via `gpt-4o-mini` structured output.

When niche specialists are active, suppression is tier-aware:

```python
# Canonical constant — single source of truth
TIER1_SPECIALISTS = TIER1_SPECIALIST_NAMES  # from specialist_registry (8 specialists)
NICHE_SPECIALISTS = TIER1_SPECIALISTS
TIER1_CATEGORIES = TIER1_SPECIALISTS

executed = state.metadata.get("executed_strategy_topics", [])
has_niche_specialist = any(t in NICHE_SPECIALISTS for t in executed)

if has_niche_specialist:
    selected_cats = set(trip_inputs.get("activity_settings", {}).get("categories", []))
    tier2_cats = selected_cats - TIER1_CATEGORIES

    if not tier2_cats:
        # Pure Tier 1 — selective backfill for free days
        # Counts specialist-claimed days vs trip length, subtracts buffers
        # (arrival/departure + no-fly buffer from registry).
        # If free_days <= 1: full suppression (specialist fills trip).
        # If free_days > 1: keeps up to free_days logistics activities
        # for Phase 5.6 to place on actual free days.
        state.tiles["activities"] = kept_or_empty
    else:
        # Mixed — generate Tier 2 experience tiles via LLM
        experience_tiles = await generate_experiences(
            destination=plan.destination,
            categories=list(tier2_cats),
            month=month,
            budget=plan.budget,
            tier1_specialists=active_niche,
        )
        if experience_tiles:
            state.tiles["activities"] = experience_tiles
        else:
            # Fallback: keyword match (original behavior)
            matching = [t for t in activity_dicts if _tile_matches_categories(t, tier2_cats)]
            state.tiles["activities"] = matching
else:
    # No niche specialist — check if user selected Tier 2 categories
    tier2_only = selected_cats - TIER1_CATEGORIES
    if tier2_only:
        experience_tiles = await generate_experiences(
            destination=plan.destination,
            categories=list(tier2_only),
            month=month,
            budget=plan.budget,
        )
        if experience_tiles:
            state.tiles["activities"] = experience_tiles
```

**Experience Generator Service:** `backend/app/services/experience_generator.py`

Generates 2–4 activities per Tier 2 category via `gpt-4o-mini` structured output (`tiles_per_category` param, default 2). `LogisticsNode._compute_tiles_per_category()` scales the count based on placeable days (free days + co-schedulable specialist days): `clamp(total_placeable // num_categories, 2, 4)` where `free_days = trip_days − specialist_activity_days − 2` and `total_placeable = free_days + specialist_days`. Each tile includes title, subtitle, category, duration, price estimate, time of day, skill level, and description (one-sentence hook, e.g. "Traditional flow with rice paddy views"). Tiles have deterministic IDs (`exp_{dest}_{category}_{index}`) for heart persistence. Uses L1+L2 caching (cache key includes `:n{tiles_per_category}` suffix). Falls back to `_tile_matches_categories()` keyword matching on LLM failure.

**Duration constraint:** System prompt enforces 1–4 hour single-session activities. Post-processing clamps `duration_hours > 4` to 4h to prevent multi-day retreats from being generated (e.g., "Bali Yoga Retreat" at 48h).

**Image resolution:** `_experience_to_tile_dict()` uses `get_cached_image_url()` (memory cache lookup only, no API call). If the Unsplash prefetch hasn't populated the cache, `image_url` is `None` and the frontend renders a placeholder shimmer.

**Parallel category generation:** `_parallel_category_generate()` runs all category LLM calls concurrently via `asyncio.gather()`, reusing L1/L2 cache per category. Used by `generate_experiences()` for multi-category requests.

| Trip Type                         | Categories                      | `executed_strategy_topics`   | Activities                                              |
| --------------------------------- | ------------------------------- | ---------------------------- | ------------------------------------------------------- |
| "diving in Bali" (short trip)     | `["diving"]`                    | `["local_expert", "diving"]` | **Suppressed** (specialist fills trip)                  |
| "diving in Bali" (long trip)      | `["diving"]`                    | `["local_expert", "diving"]` | **Selective backfill** (kept for free days)             |
| "diving + yoga + cooking in Bali" | `["diving", "yoga", "cooking"]` | `["local_expert", "diving"]` | **LLM-generated** yoga + cooking tiles (mixed Tier 1+2) |
| "yoga + cooking in Bali"          | `["yoga", "cooking"]`           | `["local_expert"]`           | **LLM-generated** yoga + cooking tiles (pure Tier 2)    |
| "trip to Rome"                    | `[]`                            | `["local_expert"]`           | **All shown** (no categories selected)                  |

### ConstraintGuard

Mostly deterministic validation. One LLM-backed check: `validate_place_exists()` calls `validate_input_async()` from `app.validation` (gpt-4o-mini with TTL caching). Fails open if validation service is unavailable.

All other checks are registry-driven pure Python. Geographic and seasonal checks were deleted — the VerticalSpecialist LLM handles these via `check_feasibility()`.

| Constraint Type | Check                                                    | Severity |
| --------------- | -------------------------------------------------------- | -------- |
| Route           | `origin == destination`                                  | blocking |
| Route           | `validate_place_exists(dest)` returns false              | blocking |
| Budget          | Total cost < budget                                      | blocking |
| Budget          | Category cost < allocation                               | warning  |
| Temporal        | start_date in past (`DATE_IN_PAST`)                      | blocking |
| Temporal        | end_date > start_date                                    | blocking |
| Temporal        | Duration < 30 days                                       | info     |
| Specialist      | Departure buffer (any `has_nofly_buffer` specialist)     | blocking |
| Specialist      | Cross-domain blocks (declarative via registry)           | blocking |
| Specialist      | Cross-domain from strategy sections (stateless fallback) | blocking |
| Capacity        | Activity count > available days (registry-driven)        | blocking |

**Auto-Fix Loop with Route Error Short-Circuit:**

```python
def route_after_guard(state: GraphState) -> Literal["architect", "synthesizer"]:
    turn = get_turn_meta(state)
    has_blocking = turn.has_blocking_violations
    retry_count = state.guard_retry_count
    violations = turn.constraint_violations  # List[Dict[str, Any]]

    # 1. UNFIXABLE CONSTRAINT SHORT-CIRCUIT
    # Route and specialist errors are unfixable by Architect.
    unfixable_categories = {"route", "specialist"}
    is_unfixable = any(v.get("category") in unfixable_categories for v in violations)
    if is_unfixable:
        return "synthesizer"

    # 2. OPTIMIZATION AUTO-FIX
    # Budget/capacity errors can be self-corrected by the Architect.
    if has_blocking and retry_count < 1:
        return "architect"  # Loop back for auto-fix

    return "synthesizer"
```

**Budget Allocation:**

```python
BUDGET_ALLOCATIONS = {
    "flights": 0.30,   # 30%
    "hotels": 0.40,    # 40%
    "activities": 0.30 # 30%
}
```

### Synthesizer

Unified response generator - "One voice, regardless of which agents contributed."

**Response Types:**

1. Greeting - Welcome message (short-circuit, no LLM)
2. Exploration - Pre-core destination exploration
3. Specialist Update - Acknowledgment after specialist runs
4. Planning - Full planning mode with tiles/constraints
5. Gate-blocked - Input validation failure (routes to `planning` type for natural LLM explanation)

**Performance Optimizations:**

- **Model Routing**: Intelligent model selection by response complexity
  - `exploration` / `specialist_update` → `settings.synthesizer_exploration_model` (default `gpt-4o-mini`)
  - `planning` → `settings.synthesizer_planning_model` (default `gpt-4o`)
  - Provider auto-selected by `get_llm_by_model(...)` (OpenAI/Gemini)
  - Greeting responses bypass LLM entirely (gated by `_should_use_llm_synthesis()`)
  - Gate-blocked responses use LLM (override short-circuit bypass) with pre-computed fallback
- **Prompt Caching**: Template loading and Jinja2 rendering cached via `@lru_cache`
  - Eliminates ~7-13ms disk I/O + compilation per call
  - 4 cached variants (one per response_type)
- **Context Trimming**: Dynamic conversation history depth
  - `exploration`: 4 messages (2 turns)
  - `specialist_update`: 8 messages (4 turns — needs prior responses to avoid repetition)
  - `planning`: 8 messages (4 turns, full context)
  - Saves ~200 tokens per simple response

**Per-Response-Type Token Limits:**

- `exploration`: 200 tokens (terse conversational)
- `specialist_update`: 250 tokens (ack + counts + room for varied voice)
- `planning`: 350 tokens (constraint reasoning + counts)
- Default (fallback): 500 tokens

**Context Enrichment (`_build_synthesis_context()`):**

- Budget breakdown: Per-category cost vs allocation (flights 30%, hotels 40%, activities 30%)
- Structured constraint violations: Budget violations get `## Budget Issue` header with conversational framing; non-budget/non-route violations get `## Constraint Alerts` with `suggested_action` passthrough. Falls back to plain `state.constraints_violated` string dump for older sessions without rich metadata.
- Day preference context: User-requested day allocations per activity category
- Per-specialist generated counts from `strategy_sections[].content_added` (`## Specialist Activities Generated`), used for count phrasing instead of `day_preferences` when both exist
- Builder drop reporting: When `last_builder_drop_ratio > 0` and builder succeeded, includes "Activity placement: X of Y specialist activities placed (Z couldn't fit)" with natural-language framing guidance (e.g., "extending your trip by a couple days would fit them all"). Reads `builder_activities_input` and `builder_activities_placed` from `state.metadata`.
- Builder scheduling conflicts: `state.metadata["builder_conflicts"]` (surfaced by `response_envelope.py` from builder results) — day, type, severity, message per conflict
- Date change delta: When dates changed this turn, includes "Trip extended/shortened by N days" with old→new date range (from `prev_trip_values_snapshot`)
- Added categories: `state.metadata["added_categories"]` — new categories this turn for targeted acknowledgment
- Turn number + anti-repetition: Injects turn count and strict instructions to vary sentence structure, opening, and flow across consecutive responses
- `change_type` signal (specialist_update only): Classifies the update trigger for prompt routing — `STEPPER_RERUN` (synthetic GENERATE_PLAN_NOW), `SETTINGS_CHANGE` (settings_just_updated flag), `NEW_CATEGORY` (added_categories present), `DATE_CHANGE` (start_date/end_date in turn_applied), `PLAN_UPDATE` (fallback). The prompt template uses `change_type` to select per-type response templates (terse ack for settings, delta + date for extensions, etc.)
- Input gate violations: `## Input Validation Issue` section with each violation message + suggested action. Instructs LLM to explain naturally without using technical terms ("validation", "gate", "constraint").
- Input gate warnings: `## Input Notes` section with each warning message, mentioned naturally in response.

**LLM Failure Fallback:**
When synthesis fails (provider error or unusable response payload), all response types return a static `FALLBACK_MESSAGE` ("I've updated your trip plan — check the itinerary on the right. Let me know if you'd like to adjust anything."). `GREETING_TEMPLATE` is preserved for the fast greeting path (no LLM).

**Always includes:**

- `suggested_replies` (up to 3 chips, no padding)
- Image enrichment via Unsplash
- Graceful constraint warnings

**Suggestion Engine (registry-driven):**

`generate_suggestions()` derives all chips from router capability registries × current state.
Zero hardcoded specialist names — adding a specialist to `specialist_registry.py` or question type
to `QUESTION_TYPE_MAPPING` automatically makes it available as a suggestion.

**Structured Chips (`suggestion_chips`):** In addition to `suggestion_chip_meta`, the synthesizer now emits `state.metadata["suggestion_chips"]` — a list of `SuggestionChip` dicts with `{message, action_type, action_target, chip_type, category, icon}`. `PILL_ACTION_MAP` maps chip categories to frontend actions: date chips → `("open_pill", "dates")`, booking chips → respective sheets, budget/travelers → their sheets, and direct-flight preference chips (`plan_flight_pref`, legacy `plan_flight_direct`) → `("trigger_action", "set_direct_flights_only")`. Categories not in the map default to `("send_message", None)`. Passed through `response_envelope.py` as `suggestion_chips`.

Priority cascade (each path also stores `suggestion_chip_meta` on `state.metadata` for frontend styling):

1. **Budget blocking** → `["Increase budget to ${suggested}", "Find cheaper {largest_cat}", "Fewer activity days"]` (icon: `dollar-sign`; fires before generic blocking handler)
2. Non-budget blocking violations → `["Extend to {date}", "Add buffer day between activities", "Remove {specialist}"]` (includes `DAY_PREFERENCE_EXCEEDS_CAPACITY` → "Reduce {largest} to N days"). "Extend to" date uses builder's `new_duration` from `state.metadata["last_builder_resolutions"]` when available (more accurate than +2 heuristic).
3. Route violations → `["Back to {prev}", "Different city", "Help me choose"]`
4. Pool-based (condition × priority × category dedup):
   - P0: destination_choice / date_contextual / date_prompt
   - P1: "Build my itinerary"
   - P3: specialist cross-sell (from `ALL_SPECIALIST_KEYWORDS` minus `executed_strategy_topics`)
   - P4: plan progression — preference refinement chips at S2+ (e.g., "5-star hotels only", "Direct flights only", activity exploration). Generated by `_build_plan_progression_suggestions()` based on which settings are NOT yet configured.
   - P5: "Set my departure city"
   - P6: question suggestions (from `SUGGESTABLE_QUESTION_TYPES`)

At S2+ (active plan with dates), plan progression chips (P4) outprioritize exploration questions (P6),
ensuring chips suggest plan actions rather than exploration. Question chips remain available as
backfill and are actionable post-planning (routed through the `question_answer` short-circuit path).

**Logic Guard Voice:** When a blocking route violation is detected (`category="route"`), the Synthesizer shifts to **"Architectural Safety Mode"**. It refuses to generate enthusiasm or itinerary content and instead provides a firm, corrective statement (e.g., "I cannot generate a route where Origin and Destination are identical.").

**Safety Constraint Surfacing:** When non-route blocking violations are detected (e.g., diving surface interval), the synthesis context includes a `⚠️ SAFETY CONSTRAINT VIOLATION` section prompting the LLM to mention the safety issue and suggest plan adjustments.

**Settings-Update Violation Override:** When `settings_just_updated` is true AND `constraint_violations` exist (e.g., user adds hiking to a diving trip), the synthesizer routes to the full LLM path instead of using the short acknowledgment string. This ensures violations are surfaced in the chat response even during settings updates. Suggestion chips are also always regenerated when violations are present.

**True Streaming:**
Uses LangGraph's `astream_events` to tap into the LLM token stream:

```python
async for event in graph.astream_events(state, version="v2"):
    if event.get("event") == "on_chat_model_stream":
        node = event.get("metadata", {}).get("langgraph_node")
        if node == "synthesizer":
            chunk = event.get("data", {}).get("chunk")
            yield {"type": "token", "data": chunk.content}
```

---

### ItineraryBuilder (Pure Python - No LLM)

Transforms specialist content + tiles into day-by-day timeline.

**Location:** `backend/app/services/itinerary_builder.py`

**Why No LLM:** Deterministic scheduling is faster and more predictable than LLM-based generation. The specialists provide the "what", the builder provides the "when".

**Algorithm (7 phases with sub-phases):**

```
┌─────────────────────────────────────────────────────────────────┐
│  ItineraryBuilder (Pure Python - No LLM)                        │
│  Transforms specialist content + tiles into day-by-day timeline  │
│                                                                  │
│  Algorithm (phases with sub-phases):                                             │
│  1.    Temporal Scaffolding - Create DayCard[] from dates        │
│  2.    Extract Specialist Content - Activities + constraints     │
│  2a.   Merge Constraints - Priority resolution                   │
│  2b.   Detect Early Conflicts - Capacity validation              │
│  3.    Anchor Placement - Arrival/departure from flight tiles    │
│  4.    Buffer Injection - Safety blocks (no-fly, acclimatization)│
│  5.    Activity Distribution - Clustering OR round-robin         │
│  5.5   Free Day Placeholders - Add placeholders for empty days   │
│  5.6   Experience Tile Placement:                                │
│         Pass 0: Pinned tiles on target day (fill-day Browse→Add) │
│         Pass 1: Free day placement (existing behavior)           │
│         Pass 2: Co-schedule on specialist days with capacity     │
│  5.25  Preferred Activity Placement - Fill free days with hearts │
│  6.    Tile Matching - Hotels span all days, preferences weighted│
│  6.5   Constraint Tagging - Inline constraints for frontend      │
│  6.75  Chronological Sort - Final block ordering                 │
│  7.    Temporal Conflict Detection - Post-placement overflow     │
│                                                                  │
│  Called from: format_result() (shadow at S2) + /api/expand-itinerary │
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
    dive_slots = (available_after_buffer + 1) // 2  # ceiling — diving gets remainder
    altitude_slots = available_after_buffer - dive_slots
    trim(diving, dive_slots); trim(altitude, altitude_slots)
else:
    conflict("Cannot fit diving + buffer + altitude in trip")

# Total capacity: activities can share days via interleaving
max_capacity = usable_days * MAX_BLOCKS_PER_DAY  # 3 blocks/day
if total_activity_days > max_capacity:
    auto_truncate_proportionally()  # Silent trim, no conflict
```

**Key Insight:** The no-fly buffer only restricts DIVING placement, not total capacity. Day 7 of an 8-day trip can have hiking activities even though diving is blocked (24h before flight). The buffer doesn't reduce total trip capacity—it restricts which activities can go where.

**Cross-Domain Trim Math:** For a trip with diving + altitude activities and a 24h buffer:

| Trip | Usable | After buffer | Dive slots | Altitude slots | Result        |
| ---- | ------ | ------------ | ---------- | -------------- | ------------- |
| 5d   | 3      | 2            | 1          | 1              | Trimmed       |
| 7d   | 5      | 4            | 2          | 2              | Trimmed       |
| 9d   | 7      | 6            | 3          | 3              | Trimmed       |
| 3-4d | 1-2    | 0-1          | —          | —              | Real conflict |

**Two-Layer No-Fly Enforcement:**

1. **Phase 2b (Count):** Truncates diving activity count to fit available slots (`diving_slots = usable_days - buffer_days`)
2. **Phase 4 (Placement):** Restricts diving to days at or before `departure - 1 - buffer_days` (e.g., Day 2 at latest for a 4-day trip). If the round-robin lands on a restricted day for diving, it wraps to an earlier valid day. Other specialists (hiking, etc.) are unaffected and can still use those days.

**Cross-Domain Clustering (Phase 4 — `no_altitude_after_dive`):**

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
Day 5: REST — decompression buffer
Day 6: Hike 1 (Mt Batur)
Day 7: Hike 2 (Campuhan Ridge)
Day 8: Hike 3 (Sekumpul)
Day 9: Departure
```

**Phase 5.24: Day Preference Capping**

**Hallucination Guard:** `_parse_day_preferences(raw, user_text)` rejects LLM-inferred day counts when the user message contains no digits — the LLM is hallucinating counts from trip duration. Only explicit user statements like "3 days diving" produce valid preferences. Additionally, parsed preferences are scoped to categories mentioned this turn (`activity_categories ∪ specialist_hints`) to prevent the LLM from hallucinating day counts for categories the user didn't reference (e.g., surfing: 3 when user only said "add 2 days nightlife").

When `activity_day_preferences` are set (e.g., `{"diving": 3, "hiking": 2}`), the builder caps each specialist's activity list to the user-requested count BEFORE cross-domain clustering or round-robin. The cap is a maximum — if only 2 diving activities exist but user asked for 3, all 2 are placed. Remaining specialists (without day preferences) fill leftover days via the existing distribution logic.

**Phase 5.25: Preferred Activity Placement (Two-Pass)**

After creating free day placeholders, the builder populates days with user-preferred activities (hearted tiles). Uses a two-pass strategy:

1. **Pass 1 (Unified Slot Model):** Collects preferred tiles from `preferences.preferred_activity_ids`. Builds slot map (3 periods per day), places via round-robin on least-loaded days. Arrival/departure days have locked periods. Buffer blocks don't lock periods.
2. **Pass 2 (Co-Schedule Fallback):** Tiles that couldn't fit in Pass 1 (all slots full or specialist-per-day cap) are deferred. Re-scans using `_day_remaining_capacity()` + `_time_slot_score()` for hour-based placement on specialist days with spare capacity.

Activity blocks created this way have `preference_status: "user_preferred"` for UI attribution.

**Phase 6: Constraint Tagging (Inline Display)**

After distributing activities, the builder tags blocks with relevant constraints for inline UI display. This makes constraint-first optimization visible to users. **Note:** Standalone buffer day cards have been removed - all safety constraints are now shown as inline badges on the relevant activity blocks.

Each specialist type has its own constraint generator:

**Diving Constraints:**

- `no_fly_buffer` (warning): Applied to last dive when within 2 days of departure
- `surface_interval` (info): Applied to all dives for safety communication

**Hiking Constraints:**

- `fitness_required` (info): Applied when `intensity == "challenging"`
- `early_start_recommended` (info): Applied to morning activities

**Skiing Constraints:**

- `avalanche_awareness` (warning): Applied when summary contains "off-piste", "backcountry", or "freeride"
- `advanced_terrain` (info): Applied when `intensity == "challenging"`

**Surfing Constraints:**

- `tide_timing` (info): Applied to all surfing activities

**Climbing Constraints:**

- `altitude_acclimatization` (warning): Applied above 3000m elevation. Builder places the acclimatization buffer on the day before the first altitude-activity day (hiking/climbing/skiing blocks), not hardcoded to day 3. Fallback to day 3 if no altitude blocks are scheduled.
- `gear_inspection` (info): Applied to all climbing activities

**Sailing Constraints:**

- `weather_window` (info): Applied to all sailing activities

**Wildlife Safari Constraints:**

- `guide_required` (info): Applied to all game drive activities

**Hotel Constraints:**

- `proximity_optimized` (success): Applied to check-in blocks, lists active specialists (e.g., "Proximity to diving, hiking activities")

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
| `altitude_acclimatization` | warning | climbing | Above 3000m elevation. Placed day before first altitude-activity (hiking/climbing/skiing), fallback to day 3 |
| `gear_inspection` | info | climbing | Equipment safety check |
| `weather_window` | info | sailing | Check weather conditions |
| `guide_required` | info | wildlife_safari | Professional guide for game drives |
| `proximity_optimized` | success | hotel | Location optimized for activities |

**Frontend Rendering:** See `docs/ux_unified_architecture.md` Section I.A.2 "Inline Constraints Display"

**Result Metrics:**

- `total_activities_input`: Activities fed into distribution
- `total_activities_placed`: Activities actually placed on timeline (excludes buffers, logistics, free days)
- Drop ratio (`1 - placed/input`) stored in `state.metadata["last_builder_drop_ratio"]` for guard suppression and synthesizer drop reporting

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

1. **Block-level** (`check_specialist_constraints()`): Reads `plan.itinerary_blocks` for day-level scheduling conflicts. Only effective when blocks are populated (specialist just ran). **Capacity gate:** if the trip has enough days (`available_after_buffer >= 2`), the violation is skipped (builder handles sequencing). Mirrors the capacity logic in `_check_cross_domain_from_sections`.
2. **Section-level** (`_check_cross_domain_from_sections(start_date, end_date)`): Reads `persistent.strategy_sections` to detect specialist co-existence. **Capacity-aware:** only emits a violation when the trip is too short for minimum viable (available_after_buffer < 2). When the trip is long enough, the builder trims instead. Deduplicated against block-level violations by `code`. **Suppressed on subsequent turns** when the corresponding builder constraint is already persisted in `existing_rules`. Mapping: `_violation_to_constraint_rule = {"ALTITUDE_AFTER_DIVE": "no_altitude_after_dive"}`.

**Violation lifecycle:** Turn N (first co-existence, trip long enough): no violation → builder trims → constraint injected. Turn N (trip too short): violation fires → constraint injected → user informed with suggestion chips. Turn N+1+: constraint already in `existing_rules` → section-level violation suppressed.

**Constraint Injection (decoupled from violations):** The guard injects `SpecialistConstraint` (e.g. `rule="no_altitude_after_dive"`) whenever specialists co-exist, **regardless of whether a violation was emitted**. This ensures the builder has the constraint for sequencing even when the trip is long enough that no violation fires. Injection iterates over `persistent.executed_strategy_topics` and checks registry `cross_domain_blocks` directly (idempotent via `existing_rules` check).

Data flow: `registry (CrossDomainBlock) → guard (co-existence check) → SpecialistConstraint injection → builder (_find_constraint)`

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

**Design Principle:** Builder defines canonical IDs → LLM outputs flexible natural language → Builder normalizes for detection. This inverts the typical approach where LLM must match exact constraint names.

**Matching Strategy:**

1. Exact match on canonical name
2. Exact match on any alias
3. Partial match (alias contained in rule name)
4. Case-insensitive with `-`/`_`/` ` normalization

**Usage in Conflict Detection:**

```python
# Instead of: if any(c.rule == "no_altitude_after_dive" for c in constraints)
# Use: if _find_constraint(constraints, "no_altitude_after_dive")

altitude_constraint = _find_constraint(constraints, "no_altitude_after_dive")
nofly_constraint = _find_constraint(constraints, "min_24h_buffer_after_dive")
```

### Partial Timeline (Conflict Visualization)

When conflicts are detected, the builder returns a **partial schedule** showing what CAN be scheduled, with unschedulable activities marked.

**Backend Implementation:**

```python
class DayBlockOutput(BaseModel):
    # ... existing fields
    unschedulable: bool = False
    unschedulable_reason: Optional[str] = None

def _build_partial_schedule(self, days, primary_specialist, activities, constraints):
    """Build partial timeline with schedulable activities + unschedulable markers."""
    # Place primary specialist activities
    days = self._place_anchors(days, {}, None)
    days = self._inject_safety_buffers(days, constraints)

    # Mark other specialists as unschedulable
    for specialist, acts in activities.items():
        if specialist != primary_specialist:
            for activity in acts:
                unschedulable_block = DayBlockOutput(
                    summary=activity.title,
                    specialist_type=specialist,
                    unschedulable=True,
                    unschedulable_reason=f"Requires 24h buffer after {primary_specialist}",
                )
                days[-2].blocks.append(unschedulable_block)
    return days
```

**Frontend Rendering:**

- Unschedulable blocks show with `opacity-60`, dashed amber border
- "Cannot schedule" warning badge with AlertTriangle icon
- Activity title shown with strikethrough
- `unschedulable_reason` displayed as italic amber text

**SSE Envelope:**

```python
yield format_sse({
    "type": "envelope",
    "plan_view_state": "S3_PARTIAL_CONFLICT",
    "day_cards": [d.dict() for d in partial_days],  # Partial schedule
    "conflicts": [c.dict() for c in conflicts],
    "resolutions": [r.dict() for r in resolutions],
})
```

**UX Flow:** Partial timeline auto-renders when `conflicts.length > 0 && day_cards.length > 0`. No extra "Show partial" click needed - user sees schedulable activities + grayed unschedulable markers inline. ConflictResolutionBanner shows only `extend_dates` and `remove_specialist` options.

---

## Structured Output Usage

Pydantic structured output is used for LLM nodes that need **guaranteed schema extraction**. Nodes that generate natural language or use static data do NOT use structured output.

### Node-by-Node Status

| Node                   | Uses Structured Output? | LLM Used?                                | Schema(s)                                             | Purpose                                                       |
| ---------------------- | ----------------------- | ---------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------- |
| **IntentRouter**       | ✅ Yes                  | `settings.router_model` (via `llm_factory`) | `RouterOutput`, `IntentClassification`             | Intent + field extraction in one call                         |
| **TripArchitect**      | ✅ Yes                  | `settings.extraction_model` (via `llm_factory`) | `ExtractedTripFields`, `ExtractedSettingsFields` | Trip field & settings extraction                              |
| **LocalExpert**        | ❌ No                   | ❌ Static                                | N/A                                                   | Uses `LOCAL_EXPERT_KNOWLEDGE` dict                            |
| **VerticalSpecialist** | ✅ Yes                  | `settings.specialist_model` (via `llm_factory`) | `LLMSpecialistOutput`, `LLMActivity`, `LLMConstraint` | LLM-first with fallback                                   |
| **LogisticsNode**      | ❌ No                   | ❌ N/A                                   | N/A                                                   | API calls only (Amadeus, curated data)                        |
| **ConstraintGuard**    | ❌ No                   | gpt-4o-mini (place validation only)      | N/A                                                   | Mostly deterministic; `validate_place_exists()` is LLM-backed |
| **Synthesizer**        | ❌ No                   | `settings.synthesizer_*_model` (by response type, via `llm_factory`) | N/A                                      | Free-form natural language (correct)                          |

> **Note:** VerticalSpecialist uses **LLM-first architecture** by default. Single LLM call generates feasibility + activities + constraints. Falls back to minimal safety constraints if LLM fails (parse error, timeout).

### Design Principle

**Rule of thumb:**

- **LLM extracts structured information** → Use `.with_structured_output(Schema)` ✅
- **LLM generates natural language** → Don't use structured output ❌
- **No LLM (static data, APIs, validation)** → N/A ❌

### RouterOutput Schema

The IntentRouter uses a combined schema for intent classification + field extraction in a single LLM call (`max_tokens=700`):

```python
class RouterOutput(BaseModel):
    """Combined intent classification + field extraction."""
    # ── Intent classification ──
    intent: Literal["GREETING", "RESET", "PLANNING"]
    confidence: float  # 0.0-1.0
    reasoning: str  # Brief explanation of classification

    # ── Specialist & activity detection ──
    specialist_hints: List[str] = []
    activity_categories: List[str] = []  # Tier 2 categories (yoga, cooking, nightlife, etc.)
    activity_day_preferences: Optional[str] = None  # JSON string: '{"diving": 3, "hiking": 2}'

    # ── Core trip fields ──
    destination: Optional[str] = None
    origin: Optional[str] = None
    origin_iata: Optional[str] = None       # IATA code (e.g. SFO, LHR)
    destination_iata: Optional[str] = None   # IATA code (e.g. DPS, CDG)
    start_date: Optional[str] = None  # YYYY-MM-DD format
    end_date: Optional[str] = None    # YYYY-MM-DD format
    duration_days: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    budget: Optional[float] = None

    # ── Flags ──
    has_dates_in_message: bool = False
    has_activity_in_message: bool = False  # True if specific activities mentioned
    planning_ready: bool = False  # True if user explicitly wants to plan NOW

    # ── Modification intents (Phase 2) ──
    removal_targets: List[str] = []       # Activities to remove: ["hiking", "yoga"]
    skill_level: Optional[str] = None     # "beginner", "intermediate", "advanced"
    reset_budget: bool = False            # True = clear budget constraint
    reset_hotel: bool = False             # True = clear hotel preferences

    # ── Settings extraction (Phase 2) ──
    hotel_min_stars: Optional[int] = None       # 1-5 star rating
    hotel_style: Optional[str] = None           # "luxury", "boutique", "budget", "mid-range"
    hotel_amenities: List[str] = []             # ["pool", "spa", "gym", ...]
    hotel_location: Optional[str] = None        # "beachfront", "city_center", "airport"
    flight_direct_only: Optional[bool] = None   # True = direct flights only
    flight_cabin_class: Optional[str] = None    # "economy", "premium_economy", "business", "first"

    # ── Intent classification (Phase 3) ──
    planning_intent: Optional[str] = None       # "ready", "modifying", "exploring", "greeting"
    question_type: Optional[str] = None         # "weather", "safety", "costs", "visa", etc.

# Usage
llm = get_llm_by_model(settings.router_model)
structured_llm = llm.with_structured_output(RouterOutput)
result: RouterOutput = await structured_llm.ainvoke(messages)
```

**ROUTER_EXTRACTION_PROMPT Tasks:**

1. Intent Classification (GREETING/RESET/PLANNING)
2. Field Extraction (destination, origin, IATA codes, dates, travelers, budget)
3. Flags (has_dates_in_message, has_activity_in_message, planning_ready)
4. Activity Categories (Tier 2: yoga, cooking, nightlife, etc.)
5. Activity Day Preferences (day count JSON string)
6. Modification Detection (removal_targets, skill_level, reset flags)
7. Settings Extraction (hotel stars/style/amenities/location, flight direct/cabin)
8. Planning Intent Classification (ready/modifying/exploring/greeting)
9. Question Classification (weather/safety/costs/visa/transport/cultural/activities/accommodation/scams/packing/connectivity/money/couples/family)

Specialist Detection is embedded between Tasks 3 and 4 (using `_SPECIALIST_KEYWORD_PROMPT` from the registry).

**Benefits:**

- Type-safe extraction with Pydantic validation
- No regex parsing errors
- Dates extracted immediately (fixes P0 bug where dates were asked twice)
- Single LLM call instead of separate intent + extraction calls
- Post-plan modifications (removals, settings) extracted in the same call as intent

### State Population Flow

```
User: "I want to go diving March 1-8"
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│  IntentRouter                                            │
│  1. _classify_and_extract_with_llm() → RouterOutput      │
│  2. _populate_trip_plan_from_router_output()             │
│     - state.trip_plan.start_date = "2025-03-01"         │
│     - state.trip_plan.end_date = "2025-03-08"           │
│     - state.trip_plan.duration_days = 8                 │
│  3. Set router_extracted_fields = True                   │
└─────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│  TripArchitect                                           │
│  Checks router_extracted_fields flag                     │
│  → Skips duplicate extraction (dates already in state)   │
└─────────────────────────────────────────────────────────┘
```

**Key Fix:** `TripPlan` expects dates as `Optional[str]` (YYYY-MM-DD format), not `datetime.date` objects. The Router validates the format but stores the raw string.

---

## State Models

### GraphState

Unified state for the 7-node architecture.

```python
class GraphState(BaseModel):
    # Chat history
    messages: List[BaseMessage]

    # The Single Source of Truth
    trip_plan: TripPlan

    # Intent classification
    intent: Optional[Literal["general", "booking", "specialist"]]

    # Specialist activation
    active_specialist: Optional[str]  # "diving", "hiking", "local_expert", etc.
    active_agent_id: Optional[str]    # For UI display

    # Multi-specialist support: queue of specialists to process
    pending_specialists: List[str]

    # Tile inventory
    tiles: Dict[str, List[Dict]]  # {"flights": [], "hotels": [], "activities": []}

    # Constraint violations
    constraints_violated: List[str]

    # Auto-fix loop counter
    guard_retry_count: int = 0

    # UI events
    ui_events: List[str]

    # Response state
    last_summary: Optional[str]
    suggested_replies: List[str]

    # Metadata
    metadata: Dict[str, Any]

    # TRACKING: Detect input changes to trigger re-planning
    last_constraint_hash: Optional[str]
```

### TripPlan (SSoT)

Single Source of Truth for the trip's **core dimensions** (who, where, when, budget).

Settings fields (`activity_settings`, `hotel_settings`, `flight_settings`,
`transport_settings`, `booking_types`) are now typed via the `TripSettings` model
(using `get_trip_settings(state)` accessor). The typed settings live in
`metadata["trip_settings"]`; the legacy `metadata["trip_inputs"]` dict is deprecated
but preserved for backward compatibility. See [Settings Ownership & Document Merge](#settings-ownership--document-merge-v33).

```python
class TripPlan(BaseModel):
    # Core fields
    destination: Optional[str]
    origin: Optional[str]
    origin_iata: Optional[str]       # IATA code — resolved by RouterOutput or iata_resolver service
    destination_iata: Optional[str]   # IATA code — resolved by RouterOutput or iata_resolver service
    start_date: Optional[str]
    end_date: Optional[str]

    # Travelers
    travelers: int = 1
    adults: int = 1
    children: int = 0

    # Budget
    budget: Optional[float]
    currency: str = "USD"

    # Status
    status: Literal["draft", "planning", "ready", "booked"]

    # Booked segments
    segments: List[TripSegment]

    # DEPRECATED Stage 2B: content now lives on strategy_sections[].content_blocks
    itinerary_blocks: List[ItineraryBlock]

    # Constraints from Specialist
    constraints: List[SpecialistConstraint]

    # Metadata
    trip_type: Optional[str]  # "diving", "hiking", etc.
    vibe: Optional[str]       # "adventure", "relaxation", etc.
```

### Activity (LLM-Generated)

Rich activity model with topic-specific optional fields. Generated by `generate_specialist_output_llm()`.

```python
class Activity(BaseModel):
    title: str
    description: str = ""
    location: Optional[str] = None
    duration_hours: float = 3.0
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"

    # Scheduling hints (LLM can suggest)
    day: Optional[int] = None
    period: Optional[Literal["morning", "afternoon", "evening"]] = None

    # Display
    image_url: Optional[str] = None
    logic_hook: Optional[str] = None  # Pro tip for UI

    # Topic-specific optional fields
    depth_meters: Optional[int] = None           # diving
    certification_required: Optional[str] = None # diving
    elevation_meters: Optional[int] = None       # hiking
    distance_km: Optional[float] = None          # hiking
    trail_type: Optional[str] = None             # hiking
    vertical_meters: Optional[int] = None        # skiing
    run_difficulty: Optional[str] = None         # skiing

    # Extension point
    topic_metadata: Dict[str, Any] = Field(default_factory=dict)
```

### SpecialistConstraint

Constraint injected by VerticalSpecialist.

```python
class SpecialistConstraint(BaseModel):
    constraint_id: str = ""      # Unique ID: "no_fly_24h", "altitude_buffer"
    type: Literal["temporal", "safety", "equipment", "certification", "budget"]
    rule: str                    # e.g., "min_24h_buffer_after_dive"
    severity: ConstraintSeverity = ConstraintSeverity.STRONG  # Priority for conflicts
    applies_to: Optional[str]    # DEPRECATED: Use applies_to_categories
    applies_to_categories: List[str] = []  # Cross-domain targeting (e.g., ["hiking", "flights"])
    parameters: Dict[str, Any]   # e.g., {"max_depth_without_cert": 18}
    reason: Optional[str]        # Human-readable explanation
    # UI display fields
    label: Optional[str] = None  # Short display label
    icon: Optional[str] = None   # Emoji icon
    buffer_hours: Optional[int] = None  # For temporal constraints

class ConstraintSeverity(str, Enum):
    """Constraint priority for multi-specialist conflict resolution."""
    BLOCKING = "blocking"  # Safety/Legal - always wins (e.g., 24h no-fly)
    STRONG = "strong"      # Optimization - negotiates (e.g., best weather)
    SOFT = "soft"          # Preference - defers (e.g., scenic route)
```

**Note:** Uses `Literal` because constraints are created by code (not LLM-generated).
Compare with `LocalConstraint` which uses `str` for LLM-generated content.

**Cross-Domain Constraints:** The `applies_to_categories` field enables constraints from one specialist to affect another (e.g., diving's `no_altitude_after_dive` targets hiking activities).

### ItineraryBlock

Content block from VerticalSpecialist.

```python
class ItineraryBlock(BaseModel):
    day: int
    title: str
    description: str
    type: Literal["activity", "meal", "transport", "rest", "experience", "buffer"]
    image_url: Optional[str]
    duration_hours: Optional[float]
    location: Optional[str]
    source_specialist: Optional[str]  # "diving", "hiking", etc.
    skill_level: Optional[str]        # "beginner", "intermediate", "advanced"
    safety_notes: Optional[str]
    tile_id: Optional[str]            # If bookable
    logic_hook: Optional[str]         # Pro tip for UI display
    # Buffer/Safety block fields
    is_buffer: bool = False
    buffer_type: Optional[Literal["no_fly", "rest_day", "acclimatization", "arrival", "departure"]]
    buffer_reason: Optional[str]

    # Coordinates for map integration
    coordinates: Optional[List[float]]  # [lng, lat] for Mapbox
```

> **Note:** S3 Itinerary View enhancement fields (`duration`, `scheduled_time`, `logistics_details`, `hotel_name`, `requires_booking`, `booking_category`, `booked_tile_id`) live on `DayBlockOutput` in `backend/app/services/itinerary_builder.py`, NOT on `ItineraryBlock` in `backend/app/planner/state/schemas.py`. The `ItineraryBlock` schema above is the specialist output; the `DayBlockOutput` schema is the itinerary builder output that the frontend consumes.

**S3 Block Type Mapping:**

| Backend Field                             | Frontend Component | Condition                  |
| ----------------------------------------- | ------------------ | -------------------------- |
| `buffer_type in ["arrival", "departure"]` | `LogisticsBlock`   | Flight logistics           |
| `type.includes("check")`                  | `LogisticsBlock`   | Hotel check-in/out         |
| `is_buffer and buffer_type == "no_fly"`   | `SafetyBlock`      | No-fly constraint          |
| `is_buffer`                               | `SafetyBlock`      | Rest day / acclimatization |
| `requires_booking and not booked_tile_id` | `GhostSlot`        | Unbooked placeholder       |
| Default                                   | `ActivityMiniCard` | Rich activity card         |

---

## Exploration Mode

The IntentRouter supports **Exploration Mode** for handling generic travel questions before the user is ready to plan. This creates a conversational travel agent experience.

### Question Type Detection

Questions are classified into types that map to Local Expert knowledge sections:

| Question Type   | Keywords                                                                  | Local Expert Section   |
| --------------- | ------------------------------------------------------------------------- | ---------------------- |
| `couples`       | romantic, honeymoon                                                       | `destination_overview` |
| `family`        | kids, children                                                            | `destination_overview` |
| `weather`       | climate, rain, season                                                     | `seasonality`          |
| `safety`        | dangerous, crime, security                                                | `safety_health`        |
| `costs`         | expensive, cheap, budget                                                  | `money_costs`          |
| `visa`          | passport, entry, immigration                                              | `visa_entry`           |
| `transport`     | taxi, uber, scooter                                                       | `transportation`       |
| `cultural`      | wear, dress, clothes                                                      | `cultural_norms`       |
| `activities`    | must see, must do                                                         | `things_to_do`         |
| `accommodation` | stay, hotel, neighborhood, lodging, resort, hostel, airbnb, accommodation | `neighborhoods`        |
| `scams`         | rip off, tourist trap                                                     | `scams_traps`          |
| `packing`       | bring, luggage, adapter                                                   | `packing`              |
| `connectivity`  | sim, wifi, internet                                                       | `connectivity`         |

### Planning Readiness Detection

```python
PLANNING_READINESS_SIGNALS = [
    "plan my trip", "help me plan", "let's plan", "plan this",
    "i'm ready", "let's do it", "let's go", "book",
    "what are my options", "show me options",
]

DATE_INDICATORS = [
    r"\b(january|february|...)\b",  # Month names
    r"\b(next week|next month|this weekend|tomorrow)\b",
    r"\b\d{1,2}[/-]\d{1,2}\b",  # Date patterns
]

# ACTIVITY_INDICATORS removed — now uses ALL_SPECIALIST_KEYWORDS from specialist_registry.py
has_activity = any(
    kw in text_lower for kws in ALL_SPECIALIST_KEYWORDS.values() for kw in kws
)
```

### Intent Classification

| Intent                  | Condition                                                                       | Behavior                                                                                                                                                                                                                                                                                                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ready`                 | Explicit planning signal OR (date AND activity)                                 | Continue to PLANNING flow                                                                                                                                                                                                                                                                                                                                                                                    |
| `actionable`            | Tier 2 activity, removal, skill level, or setting reset (pre-exploration check) | Update categories/settings → `ACTIONABLE_TO_LOGISTICS` fast path. If mixed Tier 1+2, updates categories then falls through to `soft_transition`                                                                                                                                                                                                                                                              |
| `soft_transition`       | Has date OR activity (Tier 1 keyword)                                           | **Routes to PLANNING** (dates/activities = actionable input). Detects specialists from both message text AND `activity_settings.categories` (UI pill selections). Syncs detected specialists to `activity_settings.categories`. On date changes, clears `constraint_hash`, `itinerary_blocks` (prevents false ALTITUDE_AFTER_DIVE from stale blocks), and `parallel_llm_results` (forces specialist re-run). |
| `exploring`             | Generic question, no planning signals                                           | Comprehensive answer + "What else?". **Auto-upgrade:** If destination + start_date + end_date already collected from prior turns and no plan is active yet, upgrades to `soft_transition` (prevents "dates turn 1 + destination turn 2" from stalling in exploration)                                                                                                                                        |
| `exploring` (post-plan) | Question with active plan (S2/S3)                                               | Section-specific answer via `question_answer` short-circuit                                                                                                                                                                                                                                                                                                                                                  |

### Post-Planning Question Routing

When `planning_intent == "exploring"` and the plan is active, the router classifies the question type
and returns section-specific content instead of canned exploration responses.

**Plan-active detection** uses `_is_plan_active(state)` (intent_router.py), which checks two signals:

1. **Primary:** `plan_view_state` in metadata (persisted by `format_result` since response_envelope.py writes it back)
2. **Fallback:** `strategy_sections` contains any section with `specialist_type` not in `("general", "local_expert")`

The fallback ensures plan detection works even if `plan_view_state` is missing from restored state. `local_expert`
sections are excluded because they exist pre-plan (exploration phase). This helper is used in three places:
the POST-PLAN FAST PATH gate, the exploration post-plan branch, and `_build_plan_progression_suggestions`.

**Question routing:**

- **Recognized question** (e.g., accommodation, weather): `generate_comprehensive_answer` produces a
  section-specific answer from `LOCAL_EXPERT_KNOWLEDGE`. Sets `short_circuit_type = "question_answer"`.
  No exploration ending is appended. Synthesizer uses the pre-computed answer and generates fresh
  state-aware suggestion chips.
- **Unrecognized question** (`qtype == "general"`): Falls through to LLM (exploration_mode disabled).

This avoids routing through the full graph (local_expert cache would no-op, `route_after_specialist`
would trigger unnecessary logistics).

### Progressive Nudging

**State-aware ending override** (checked first):
| Condition | Response Ending |
|-----------|-----------------|
| Origin + dest set, no dates | "When are you thinking of going?" |
| Dest set, no dates | "When would you like to go?" |

**Fallback (question-count based):**
| Question # | Response Ending |
|-----------|-----------------|
| 1 | "What else would you like to know?" |
| 2 | "When are you thinking of going?" (soft nudge) |
| 3+ | "I can help plan your trip when you're ready..." |

The state-aware override ensures the exploration ending matches what the suggestion chips
are showing (e.g., date chips), rather than asking a generic "what else?" when the next
logical step is clearly setting dates.

### Conversation State Tracking

```python
state.metadata["exploration_mode"] = True
state.metadata["generic_question_count"] = 2
state.metadata["last_destination_context"] = "Bali"
state.metadata["short_circuit_type"] = "exploration"  # or "soft_transition" or "question_answer"
```

### Example Flow

```
User: "Is Bali fun for couples?"
→ Intent: exploring, destination: Bali, qtype: couples
→ Returns comprehensive answer from LOCAL_EXPERT_KNOWLEDGE["bali"]["destination_overview"]
→ Ending: "What else would you like to know?"

User: "What's the weather like?"
→ Intent: exploring, destination: Bali (from context), qtype: weather
→ Returns seasonality answer
→ Ending: "When are you thinking of going?" (question #2 = soft nudge)

User: "Maybe February and we want to dive"
→ Intent: ready (has date AND activity)
→ Continues to normal PLANNING flow with specialists
```

**Post-Planning Example:**

```
[Plan is active — S2_STRATEGY_READY]

User: "What about lodging options?"
→ Intent: exploring, destination: Bali, has_active_plan: True
→ classify_question_type → ("accommodation", "neighborhoods")
→ generate_comprehensive_answer → neighborhoods content (areas, vibes, avoid)
→ short_circuit_type = "question_answer"
→ Synthesizer uses pre-computed answer, generates fresh chips
```

---

## Routing Logic

### Panic Button (Pre-Graph)

Hard-coded reset commands bypass LLM entirely.

```python
PANIC_COMMANDS = frozenset({"/reset", "reset", "stop", "clear", "/stop", "/clear"})

# In run_turn() BEFORE graph invocation:
if user_message.strip().lower() in PANIC_COMMANDS:
    return _create_reset_response()  # No LLM, instant
```

### Route After Router

**NOTE:** Due to "Local Expert Always First" pattern, `active_specialist` is always
`"local_expert"` on first pass. Niche specialists are in `pending_specialists` queue.

**IMPORTANT:** Order of checks matters! `origin_only_logistics` fast path must be checked
BEFORE `active_specialist` to avoid bypassing specialists when flag bleeds across turns.
All ephemeral flags are cleared in `_restore_graph_state()` at turn start.

```python
def route_after_router(state: GraphState) -> Literal["specialist", "local_expert", "logistics", "architect", "synthesizer"]:
    turn = get_turn_meta(state)

    # ORIGIN/SETTINGS/ACTIONABLE FAST PATH: Route directly to logistics
    # Used by: origin detection, settings changes, Tier 2 activity additions,
    # activity removals, skill level changes, setting resets.
    # Skips architect/specialists - only fetches tiles and rebuilds itinerary.
    if turn.origin_only_logistics:
        return "logistics"

    # Short-circuits (greeting, reset, exploration, question_answer) skip to synthesizer
    if turn.short_circuit_response:
        return "synthesizer"

    # CRITICAL: If specialists are queued BUT destination is missing,
    # route to Architect FIRST to extract destination from user message.
    if state.active_specialist and not state.trip_plan.destination:
        return "architect"

    # First pass: active_specialist is "local_expert" (always first in queue)
    # Niche specialists (diving, etc.) wait in pending_specialists
    if state.active_specialist:
        if state.active_specialist == "local_expert":
            return "local_expert"
        return "specialist"  # For niche specialists in multi-specialist loop

    # Default → architect
    return "architect"
```

### Route After Specialist

**Multi-Specialist Batch:** After LocalExpert completes, the specialist node processes ALL
niche specialists (diving, hiking, etc.) in a single graph entry via `_merge_specialist_into_state()`.
The `pending_specialists` queue is drained at the start of the batch, so `route_after_specialist`
sees an empty queue and routes forward (to logistics/architect/synthesizer).

The `pending_specialists` check below is kept as a **safety guard** but should never fire
under normal operation — the batch loop handles all specialists before returning.

```python
def route_after_specialist(state: GraphState):
    turn = get_turn_meta(state)

    # 1. Safety guard: If pending specialists somehow remain, run the next one
    #    (Should not fire — batch loop in vertical_specialist drains the queue)
    if state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        if next_specialist == "local_expert":
            return "local_expert"
        return "specialist"  # Routes to vertical_specialist

    # 2. Speculative Intent: Skip tools, go to Synthesizer (Preload)
    if state.intent == "speculative":
        return "synthesizer"

    # 3. Auto-fetch: destination + (booking intent OR generate trigger OR dates)
    can_search = has_destination and (is_booking or turn.is_generate_trigger or has_dates)
    if can_search:
        return "logistics"

    # 4. Skip architect if it already ran this turn
    #    Prevents double-call: router→logistics(skip)→architect→local_expert→architect(again)
    if turn.architect_ran_this_turn:
        return _should_run_guard(state)

    # 5. General Intent: Extract fields in Architect (skip tiles)
    return "architect"
```

### Graph Edge Flow

```
Entry: router

router → logistics (origin/settings/actionable fast path)
       → specialist/local_expert/architect/synthesizer (conditional)
specialist → specialist/local_expert (pending queue safety guard) OR logistics (booking) OR architect (general) OR synthesizer (speculative)
         NOTE: specialist no longer self-loops under normal operation — all niche specialists processed in single entry via batch loop
local_expert → specialist/local_expert (pending queue) OR logistics (booking) OR architect (general) OR synthesizer (speculative)
logistics → architect/guard/synthesizer (conditional - skip architect if already ran)
architect → specialist/local_expert (deferred dispatch) OR logistics (auto-fetch) OR guard/synthesizer (conditional)
guard → architect/synthesizer (conditional - auto-fix loop)
synthesizer → END
```

### Route After Architect

Routes after architect completes. Handles deferred specialist dispatch, local expert fallback,
auto-fetch logistics, and guard/synthesizer fallthrough.

```python
def route_after_architect(
    state: GraphState,
) -> Literal["specialist", "local_expert", "logistics", "guard", "synthesizer"]:
    turn = get_turn_meta(state)
    persistent = get_persistent_meta(state)

    has_destination = bool(state.trip_plan.destination)
    has_dates = bool(state.trip_plan.start_date)
    has_tiles = bool(state.tiles)
    is_speculative = state.intent == "speculative"
    local_expert_ran = persistent.local_expert_ran
    logistics_attempted = turn.logistics_attempted

    # 1. DEFERRED SPECIALIST DISPATCH: If specialists were queued but deferred
    #    (no destination), now route to them since architect extracted it.
    if has_destination and state.active_specialist:
        if state.active_specialist == "local_expert":
            return "local_expert"
        return "specialist"

    # 2. LOCAL EXPERT RULE: destination + no specialist ran + general intent
    is_general_intent = state.intent in ("general", "planning", None)
    needs_local_expert = (
        has_destination
        and not local_expert_ran
        and is_general_intent
        and not state.active_specialist
    )
    if needs_local_expert:
        return "local_expert"

    # 3. AUTO-FETCH: dates set but no tiles, not speculative, logistics not yet attempted
    can_fetch = has_destination and not logistics_attempted
    if has_dates and not has_tiles and not is_speculative and can_fetch:
        return "logistics"

    # 4. Fall through to guard logic
    return _should_run_guard(state)
```

### Route After Logistics (Skip Double Architect)

**Optimization:** Architect runs once per turn for field extraction. After logistics fetches tiles,
if architect already ran earlier in the same turn, skip directly to guard/synthesizer.

```python
def route_after_logistics(state: GraphState) -> Literal["architect", "guard", "synthesizer"]:
    """Skip architect if fields already extracted this turn."""
    turn = get_turn_meta(state)
    # Per-turn flags are reset via reset_turn_metadata() at turn boundary
    if turn.architect_ran_this_turn:
        return _should_run_guard(state)  # Reuse existing helper
    return "architect"
```

**Performance Impact:** Saves ~800ms + one GPT-4o call per plan with tiles.

### Should Run Guard

```python
def _should_run_guard(state: GraphState) -> Literal["guard", "synthesizer"]:
    # Always run guard if destination is set (route validation)
    if state.trip_plan.destination:
        return "guard"
    # Also run for tiles/constraints
    if state.tiles or state.trip_plan.constraints:
        return "guard"
    return "synthesizer"
```

### Route After Guard (Auto-Fix vs. Rejection)

```python
def route_after_guard(state: GraphState) -> Literal["architect", "synthesizer"]:
    turn = get_turn_meta(state)
    has_blocking = turn.has_blocking_violations
    retry_count = state.guard_retry_count
    violations = turn.constraint_violations  # List[Dict[str, Any]]

    # 1. UNFIXABLE SHORT-CIRCUIT (route + specialist errors)
    # User Intent errors (Rome->Rome, Atlantis) and specialist conflicts
    # are UNFIXABLE by the Architect — bypass auto-fix loop.
    unfixable_categories = {"route", "specialist"}
    if any(v.get("category") in unfixable_categories for v in violations):
        return "synthesizer"  # Triggers Amber "REJECTED" receipt

    # 2. OPTIMIZATION AUTO-FIX
    # Budget/Schedule errors can be self-corrected by the Architect.
    if has_blocking and retry_count < 1:
        return "architect"

    return "synthesizer"
```

**Route errors bypass auto-fix because:**

- The Architect cannot fix user intent errors (it would hallucinate destinations)
- The user must provide valid input
- Triggers Amber "REJECTED" receipt in UI (DS Section 20)

---

## Specialist Domain Knowledge

> **SSoT:** All specialist configuration (keywords, constraints, enhancements, flags) lives in `backend/app/planner/specialist_registry.py`. Top destinations and activities are LLM-generated per prompt file — no hardcoded destination lists. Router LLM prompts (`CLASSIFICATION_PROMPT`, `ROUTER_EXTRACTION_PROMPT`), Pydantic schemas (`SpecialistOutput.specialist_type`, `RouterOutput.specialist_hints`), and validation sets (`KNOWN_CATEGORIES`) are all derived from the registry at module load time. Adding a specialist requires only: 1) add entry to `SPECIALIST_REGISTRY`, 2) create `prompts/specialists/{topic}.txt`.

**Fill-Day Validation:** `validate_fill_day_placement(target_day, specialist_type, day_cards, total_days, has_departure_flight)` checks placement against registry constraints: cross-domain buffers on adjacent days, no-fly buffer proximity to departure, arrival/departure day restrictions, and `min_days_needed`. Returns `FillDayRejection(code, reason, suggestion)` or `None` if valid.

### Diving

**Constraints (from registry):**
| Rule | Type | Severity | Cross-Domain |
|------|------|----------|--------------|
| `no_fly_24h` | temporal | blocking | flights |
| `no_altitude_after_dive` | safety | blocking | hiking, trekking, mountaineering, skiing, climbing |

**Registry flags:** `has_geographic_constraint=True`, `has_nofly_buffer=True`, `min_days_needed=4`
**Cross-domain blocks:** `ALTITUDE_AFTER_DIVE` → skiing, hiking, climbing (24h buffer, blocking)

**Note:** Top destinations are LLM-generated from `specialists/diving.txt` using world knowledge.

### Hiking

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `morning_start_recommended` | temporal | soft |
| `proper_footwear_required` | equipment | soft |
| `altitude_acclimatization` | safety | strong |

**Registry flags:** `has_altitude_buffer=True`

**Note:** Hiking is affected by diving's `no_altitude_after_dive` cross-domain block (one-directional: diving → hiking).

### Skiing

**Constraints (from registry):**
| Rule | Type | Severity |
|------|------|----------|
| `check_snow_conditions` | safety | blocking |

**Registry flags:** `has_geographic_constraint=True`

### Cycling

**Constraints (from registry):**
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

**Note:** Climbing is affected by diving's `no_altitude_after_dive` cross-domain block and shares altitude buffer logic with hiking.

### Sailing

**Constraints (from registry):**
No hardcoded constraints (LLM-generated only)

**Backward compat:** Keywords include old "boating" terms; `category_mappings` maps `"boating" → "sailing"`.

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
| Budget     | `total_cost > budget`                                                              | blocking     | Auto-fixable, `suggested_action="Reduce total spend by $N or increase budget"` |
| Budget     | `category_cost > allocation`                                                       | warning      | Auto-fixable, `suggested_action="Look for more affordable {category} options"` |
| Temporal   | `end_date < start_date`                                                            | blocking     | Auto-fixable                                                                   |
| Temporal   | `duration > 30 days`                                                               | info         |                                                                                |
| Temporal   | `duration < 1 day`                                                                 | warning      |                                                                                |
| Specialist | Departure buffer (registry: `has_nofly_buffer`)                                    | blocking     | Unfixable                                                                      |
| Specialist | Cross-domain via blocks (registry: `cross_domain_blocks`)                          | blocking     | Unfixable                                                                      |
| Specialist | Cross-domain via sections (stateless fallback)                                     | blocking     | Unfixable                                                                      |
| Capacity   | Activity count > available days                                                    | blocking     | Auto-fixable                                                                   |
| Capacity   | Day preference count > effective days (`DAY_PREFERENCE_EXCEEDS_CAPACITY`)          | blocking     | Auto-fixable                                                                   |
| Capacity   | Multi-specialist aggregate exceeds capacity (`MULTI_SPECIALIST_CAPACITY_EXCEEDED`) | warning      | Auto-fixable                                                                   |

**Multi-Specialist Aggregate Capacity Check:** Sums activity counts across ALL active specialists. Individual specialist checks may pass, but combined they can exceed timeline capacity (`effective_days * 2` specialist activities max, since specialist activities are 3-5h each). Accounts for cross-domain buffer days. Fires when `len(active_specialists) >= 2` and `total_activities > max_capacity`.

**Builder-Aware Suppression:**
When the ItineraryBuilder persists a constraint rule (e.g., `no_fly_buffer`) and succeeds (`state.metadata["last_builder_success"] == True`) with acceptable drop ratio (`last_builder_drop_ratio < 0.5`), the guard suppresses duplicate violations on the next turn — the builder is already enforcing the constraint via clustering. If the builder **failed** OR dropped ≥50% of activities, the violation is re-surfaced so the synthesizer can generate resolution chips (e.g., "Extend to Mar 12").

**Deleted checks (handled by specialist LLM feasibility):**

- ~~Geographic: Diving in landlocked country~~ → specialist `check_feasibility()` returns `infeasible`
- ~~Seasonal: Hiking in winter / Skiing in summer~~ → specialist LLM prompt includes seasonality
- ~~season.py~~ → deleted entirely (sole consumer was the guard)

---

## Caching Architecture

### Cache Implementations

**Planner Caches (Session-Scoped):**
| Cache | Class | Max Size | TTL | Key Components | Purpose |
|-------|-------|----------|-----|----------------|---------|
| `ResponseCache` | `CacheNode` | 200 | 3600s | node_name, core_fields_hash, follow_up_hash | Reuse responses |
| `TileCache` | `CacheNode` | 100 | 300s | session_id, tile_type, query_hash | Cache tile API results |

**Two-Tier LLM/API Caches (Cross-Session):**
| Cache | Service File | L1 Size | L1 TTL | L2 TTL | Key Format | Purpose |
|-------|-------------|---------|--------|--------|------------|---------|
| Specialist | `specialist_cache.py` | 128 | 1h | 7 days | `specialist:{topic}:{dest}:{month}:{bucket}:{skill}:{dpref}:{phash}` | LLM outputs |
| Experience | `experience_generator.py` | 128 | 1h | 7 days | `experience:{dest}:{sorted_cats}:{month}:n{tiles_per_category}` | Tier 2 tiles |
| Tile | `tile_cache.py` | 256 | 24h | 24h | `tiles:{provider}:{type}:{dest}:{dates}` | Provider API data |
| Router | `router_cache.py` | 500 | 1h | N/A | `SHA256({text}:{date})` | NL extraction |

**Database Table:** `response_cache` with `cache_type` column for filtering (values: `'specialist'`, `'experience'`, `'tiles'`).

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

Located in `backend/app/validation.py`, stores LLM-verified place names.

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
- Primary Key: `(destination, variant)` — destination key is activity-aware (e.g., `"bali:diving"`)
- `_db_destination_key()` normalizes destination + optional first activity for cache partitioning

**Lookup Order:**

1. In-memory cache (async lock, fastest)
2. Database cache (persistent, activity-aware key)
3. Unsplash API (2s timeout, fresh fetch)
4. Picsum fallback (deterministic seed-based)

**Non-blocking in endpoints:** `get_image_url_sync()` checks memory cache only (populated by fire-and-forget prefetch). Destination images are decorative and never gate the response.

### Specialist LLM Cache

Two-tier cache for VerticalSpecialist LLM outputs. Reduces LLM calls by ~86% for repeated destination/activity queries.

**Service:** `backend/app/services/specialist_cache.py`

**Tier 1: In-Memory TTLCache (Thread-Safe)**

- Storage: `cachetools.TTLCache` with `RLock` for thread safety
- Separate `_stats_lock` RLock for hit/miss counters (prevents counter race conditions)
- Max size: 128 entries
- TTL: 1 hour
- Key format: `specialist:{topic}:{dest}:{month}:{bucket}:{skill}:{dpref}:{phash}`

**Tier 2: Database Cache**

- Table: `response_cache` (filtered by `cache_type = 'specialist'`)
- TTL: 7 days
- Primary Key: `cache_key` (VARCHAR 256)
- Storage: JSONB for `LLMSpecialistOutput.model_dump()`

**Cache Key Components:**
| Component | Example | Purpose |
|-----------|---------|---------|
| topic | `diving` | Specialist type |
| destination | `bali` | Normalized lowercase |
| month | `2025-02` | YYYY-MM from start_date (seasonal bucketing) |
| bucket | `week` | Duration bucket: weekend(1-3d), short(4-5d), week(6-8d), extended(9-11d), twoweek(12-15d), long(16d+). Max 3-day spread per bucket prevents activity count regression (cached 9-day result underserving 14-day trip) |
| skill | `advanced` / `any` | User skill level (prevents cross-skill cache poisoning) |
| dpref | `dp5` / `dpany` | Day preference count for this topic (busts cache when user adjusts day allocation) |
| phash | `9c22ff5f` | 8-char blake2s hash of prompt file (auto-invalidates on edit) |

**Lookup Order:**

1. L1 in-memory (thread-safe) → ~1ms
2. L2 PostgreSQL → ~50ms (promotes to L1 on hit)
3. LLM API call → ~5s (writes to both layers)

**Admin Endpoints:**

- `GET /api/admin/specialist-cache-stats` - Hit/miss statistics
- `POST /api/admin/clear-specialist-cache` - Clear both layers

**Integration Points:**

- Multi-specialist: `generate_all_specialists_parallel(day_preferences=...)` - batch cache lookup/write, passes per-topic `day_pref` to cache key and `target_activities` to LLM generation. Timeout: 90s (up from 45s to accommodate multi-topic parallel calls).
- Single specialist: `vertical_specialist()` - direct L1+L2 lookup before `generate_specialist_output_llm()`

### Experience Generator Cache

Two-tier cache for Tier 2 experience tiles generated by `gpt-4o-mini`. Inline within `experience_generator.py` (same pattern as specialist cache, no separate cache module).

**Service:** `backend/app/services/experience_generator.py`

**Tier 1: In-Memory TTLCache (Thread-Safe)**

- Storage: `cachetools.TTLCache` with `RLock` for thread safety
- Max size: 128 entries
- TTL: 1 hour
- Key format: `experience:{destination}:{sorted_categories}:{month}:n{tiles_per_category}`

**Tier 2: Database Cache**

- Table: `response_cache` (filtered by `cache_type = 'experience'`)
- TTL: 7 days
- Storage: JSONB array of tile dicts

**Cache Key Components:**
| Component | Example | Purpose |
|-----------|---------|---------|
| destination | `bali` | Normalized lowercase |
| categories | `cooking\|nightlife\|yoga` | Sorted alphabetically for stable keys |
| month | `2026-03` | Seasonal context (not full dates) |
| tiles_per_category | `n2` | Count per category (prevents cross-count cache poisoning) |

**Why month granularity (not full dates):** Experiences are seasonal, not date-specific. A yoga retreat in Bali is relevant for all of March, unlike specialist activities which may vary by exact trip duration.

**DB Session:** Creates its own via `_get_async_session_factory()` — zero coupling with caller (runs outside logistics_node's `async with db:` scope).

**Lookup Order:**

1. L1 in-memory (thread-safe) → ~1ms
2. L2 PostgreSQL → ~50ms (promotes to L1 on hit)
3. `gpt-4o-mini` structured output → ~2-3s (writes to both layers)

**Duration clamping on cache reads:** `_clamp_tile_durations()` runs on both L1 and L2 cache returns, capping `meta.duration_hours` to 4h. Defensive against stale cache entries from before the generation-time clamp was added (LLM sometimes generates 48h multi-day retreats). Generation-time clamping at line 418-424 handles fresh tiles; cache-read clamping handles stale ones.

**Single-Day Generation:** `generate_experience_tiles_for_day()` generates tiles for a specific day number. Round-robins across provided categories, calls `generate_single_category()` in parallel (reuses L1/L2 cache). `base_index = day_number * 100` for unique tile IDs. When `categories` is `None`/empty, falls back to `["activities"]` so the LLM picks destination-appropriate experiences. Used by the `/api/document/fill-day` endpoint (no graph execution).

**Fill-Day Endpoint Enhancements** (`/api/document/fill-day`):

- **Tier 1/Tier 2 separation:** Incoming categories are split into Tier 1 (specialist-owned, e.g. diving/hiking) and Tier 2 (experience generator). Only Tier 2 categories are passed to the experience generator. Tier 1 activities are reused from existing specialist sections.
- **Registry-driven constraint validation:** `validate_fill_day_placement()` from `specialist_registry.py` checks Tier 1 placement against cross-domain blocks, no-fly buffers, and arrival/departure restrictions. Returns rejection response (`rejected: true`, `rejection_reason`, `rejection_code`, `rejection_suggestion`) instead of silently placing invalid activities.
- **Reliable diving guard:** Adjacent-day cross-domain checks ignore `specialist_type="diving"` blocks unless activity text/constraints indicate actual dive context (e.g., dive/scuba markers or `surface_interval` rule), preventing false altitude-after-dive rejections from mis-labeled generic activities.
- **Session stream gate:** Fill-day requests queue behind active `/api/graph_plan/stream` runs for the same session to avoid patch/build races on `day_cards`.
- **Effective trip-span guard:** Fill-day no-fly/arrival-departure checks derive `total_days` from the max of trip-input span and day-card span (with `len(day_cards)` fallback), preventing stale rejection decisions when one source lags.
- **Specialist tile reuse:** For Tier 1 categories, unplaced activities from `strategy_sections[].content_added[]` are reused (proper constraints, images, metadata). Round-robin picks from the least-placed category for even distribution.
- **Priority chain:** Specialist reuse → pinned tiles → experience generator → empty (all placed)
- **Single tile per fill:** `tiles_per_day=1` — generates one activity per fill request for fine-grained control
- **Pinned placement:** Generated tiles are tagged with `meta.pinned_day = day_number`, ensuring the builder places them on the target day (via Pass 0) instead of redistributing
- **Cross-domain exclusion:** Adjacent-day constraint filter now uses `SPECIALIST_REGISTRY[].cross_domain_blocks` instead of hardcoded diving check. Dynamically reads `target_specialists` from each adjacent day's specialist type.
- **Rich DayBlocks:** `activity_type` uses `tile.title` (display name), `specialist_type` resolves via tile-level → requested Tier 1 → meta.category fallback. Blocks include `image_url`, `duration` (formatted string), `booked_tile`, `booking_category`, and use tile's `time_of_day` for period assignment (fallback to round-robin)
- **Tile store merge:** Generated tiles are added to `doc_data.tiles` map (enables hearting/referencing in frontend)
- **Category-aware labels:** Day card label uses unique categories from generated tiles (e.g., "Yoga & Beach Day") instead of generic "Filled"
- **Categories optional:** `categories` param no longer required (400 → graceful fallback to destination-appropriate activities)

**Integration Point:** `logistics_node.py` → Tier 2 activity block (both mixed Tier 1+2 and pure Tier 2 paths)

#### Tier 2 Latency Optimization

**Problem:** Turn 3 ("yoga and nightlife") took 10.6s, with 8.6s in Logistics and ~5-8s in a single `gpt-4o-mini` call.

**Solution:** Three complementary optimizations reducing latency from 10.6s → <5s (50%+ improvement):

**Tier A: Schema Compression (15-20% reduction)**

- Removed unused `subtitle` field, added `description` field (one-sentence hook, e.g., "Traditional flow with rice paddy views")
- Compressed system prompt (~80→~50 tokens) — requests vivid one-sentence description per activity
- Derived subtitle: `f"{time_of_day.capitalize()} {category.capitalize()}"` (e.g., "Morning Yoga")
- `description` propagated to tile dict via `meta.description`, displayed in MiniCard/TileCard/TileDetailsModal
- **Critical:** Cache key unchanged — tile dict shape evolved (new field), stale cache entries lack `description` (graceful: renders empty)
- Impact: 5-8s → 4-6.4s LLM call time (description adds ~10 tokens per tile, negligible)

**Tier B: Speculative Prefetch (2-4s hidden in mixed flows)**

- Router fires `asyncio.create_task(generate_experiences(..., state=None))` when Tier 2 intent detected
- **Critical:** Passes `state=None` to avoid dict mutation race condition
- Prefetch populates L1 cache → Logistics awaits task → instant L1 cache hit
- Logistics checks `metadata["tier2_prefetch_task"]` and awaits with 10s timeout
- Limitation: ~0s savings for pure Tier 2 flows (no specialist to overlap with)
- Impact: Masks 2-4s of generation time via parallel execution in mixed Tier 1+2 flows

**Tier C: Progressive Streaming (perceived latency improvement)**

- Split single batched LLM call into per-category parallel calls using `asyncio.gather()`
- New function: `generate_single_category(category, base_index)` for parallel generation
- **Critical:** `base_index` offsets preserve image diversity (cat1=0, cat2=2, cat3=4)
- Pattern: `asyncio.gather(*tasks, return_exceptions=True)` for fault tolerance
- Impact: First tiles visible in 1-2s (vs 5-8s), total time ~2s for 3 categories

**Cache Compatibility:** Zero migration needed - tile dict shape unchanged, L2 entries remain valid

**Risk Mitigation:**

- Race condition: `state=None` in prefetch prevents concurrent dict mutation
- Image diversity: `base_index` offsets maintain 0-5 variant range across parallel calls
- Fault tolerance: `return_exceptions=True` prevents one category failure from blocking others

**Files Modified:**

- `experience_generator.py`: Schema compression, parallel generation, `generate_single_category()`
- `intent_router.py`: Prefetch trigger, `_prefetch_tier2_experiences()` helper. **Changed:** Tier 2 prefetch now fires regardless of Tier 1 presence (uses full `activity_settings.categories` minus Tier 1, not just additions). This ensures mixed inputs like "diving and yoga" prefetch yoga tiles during specialist execution. L1/L2 cache makes redundant prefetches ~0ms.
- `logistics_node.py`: Prefetch consumption logic (both mixed and pure Tier 2 paths). **Changed:** Hotel search now uses `await hotel_provider.search_async(ctx)` instead of sync `asyncio.run()` wrapper, avoiding event-loop blocking in async contexts.

#### Session-Level Cache (`parallel_llm_results`)

In addition to L1+L2 caches, specialist outputs are cached in `state.metadata["parallel_llm_results"]` within a single graph execution. This prevents duplicate LLM calls when multiple specialists run in the same turn.

**Problem Solved:** When destination or dates change mid-session, the session cache could return stale content (e.g., Bali dive sites for a New York trip).

**Invalidation Logic (at TOP of `vertical_specialist()`):**

```python
# Track context changes by destination + month:bucket + Tier 1 day_preferences
cached_key = state.metadata.get("_last_specialist_key", "")
current_dest = (state.trip_plan.destination or "").lower().strip()
_month = start_date[:7] if start_date else "no-month"
_bucket = compute_duration_bucket(start_date, end_date)  # weekend/short/week/extended/twoweek/long
# Only Tier 1 prefs — Tier 2 changes (nightlife, yoga) don't affect specialist outputs
_tier1_prefs = {k: v for k, v in day_prefs.items() if k in TIER1_SPECIALIST_NAMES}
_dp_suffix = json.dumps(_tier1_prefs, sort_keys=True) if _tier1_prefs else ""
current_key = f"{current_dest}:{_month}:{_bucket}:{_dp_suffix}"

if cached_key and cached_key != current_key:
    _debug_log(f"[SPECIALIST] Context changed ({cached_key} → {current_key}), invalidating")
    state.metadata.pop("parallel_llm_results", None)

state.metadata["_last_specialist_key"] = current_key
```

**Why `destination:month:bucket:tier1_prefs`:**

- Destination change: Different location = different content
- Month change: Different season = different recommendations (rainy vs dry season)
- Duration bucket change: Different trip class = different activity counts (uses same buckets as specialist_cache: weekend/short/week/extended/twoweek/long)
- Tier 1 day preference change: User adjusts day allocation via stepper = different target counts. Tier 2 changes (nightlife, yoga) filtered out — they don't affect specialist LLM output.
- Date extensions within the same month+bucket are cache-safe (specialist recommendations don't change for "Feb 11-14" vs "Feb 11-18" when both map to `2026-02:week`)
- Matches L1+L2 persistent specialist_cache key strategy for consistency

**Incremental Merge:** New parallel results are merged into existing `parallel_llm_results` dict (preserves cached topics from prior turns). Topics already in cache are skipped during generation — only `topics_needing_gen` are sent to the LLM.

**Invalidation Triggers:**
| Change | Example | Result |
|--------|---------|--------|
| Destination | `bali:2026-02:week:...` → `new york:2026-02:week:...` | Cache cleared |
| Month | `bali:2026-02:week` → `bali:2026-08:week` | Cache cleared |
| Duration bucket | `bali:2026-02:week` → `bali:2026-02:extended` | Cache cleared |
| Tier 1 day prefs | `...:{"diving": 3}` → `...:{"diving": 5}` | Cache cleared |
| Same month+bucket | `Feb 11-14` → `Feb 11-18` (both `week`) | Cache preserved |

### Tile Data Cache

Two-tier cache for hotel/activity provider data. Reduces API calls and improves response time for repeated searches.

**Service:** `backend/app/services/tile_cache.py`

**Tier 1: In-Memory TTLCache (Thread-Safe)**

- Storage: `cachetools.TTLCache` with `RLock` for thread safety
- Max size: 256 entries
- TTL: 24 hours
- Key format: `tiles:{provider}:{type}:{dest}:{start_date}:{end_date}`

**Tier 2: Database Cache**

- Table: `response_cache` (filtered by `cache_type = 'tiles'`)
- TTL: 24 hours
- Storage: JSONB array of tile dicts

**Cache Key Components:**
| Component | Example | Purpose |
|-----------|---------|---------|
| provider | `amadeus`, `curated` | Data source |
| type | `hotel`, `activity` | Tile vertical |
| dest | `bali` | Normalized lowercase |
| dates | `2025-02-01:2025-02-14` | Search date range |

**Why 24h TTL:** Hotel prices and availability change daily, but not hourly. 24h balances freshness vs hit rate.

**Admin Endpoints:**

- `GET /api/admin/tile-cache-stats` - Hit/miss statistics
- `POST /api/admin/clear-tile-cache` - Clear both layers

**Integration Point:** `logistics_node.py` → `_search_hotels_and_activities()`

### Router Extraction Cache

L1-only cache for IntentRouter NL extraction results. Only caches self-contained queries to prevent cross-conversation pollution.

**Service:** `backend/app/services/router_cache.py`

**Tier 1: In-Memory TTLCache (Thread-Safe)**

- Storage: `cachetools.TTLCache` with `RLock`
- Max size: 500 entries
- TTL: 1 hour
- Key format: `SHA256({normalized_text}:{today_date})[:32]`

**No L2:** Conversational context is short-lived; L2 would have low hit rate.

**CRITICAL: Context-Dependency Detection**

Queries that reference conversation context are NOT cached to prevent bugs:

| Query                                  | Cacheable | Reason                     |
| -------------------------------------- | --------- | -------------------------- |
| "I want to go diving in Bali Feb 1-14" | ✅ Yes    | Self-contained             |
| "Show me diving there"                 | ❌ No     | "there" depends on context |
| "I want that one"                      | ❌ No     | "that" depends on context  |
| "Same dates as before"                 | ❌ No     | "same" depends on context  |

**Context Words Detected:** `there`, `that`, `this`, `it`, `them`, `same`, `again`, `too`, `also`, `extend`, `shorten`, `more days`, `fewer days`

**Why Key Includes Date:** Relative dates like "next Friday" resolve differently depending on when asked.

**Admin Endpoints:**

- `GET /api/admin/router-cache-stats` - Hit/miss/skipped statistics
- `POST /api/admin/clear-router-cache` - Clear cache

**Integration Point:** `intent_router.py` → `_classify_and_extract_with_llm()`

---

## Selective Regeneration

Selective regeneration minimizes LLM calls when trip inputs change by computing the minimum required execution path based on which fields changed.

### Core Principle

```
Changed Fields Detection → Strategy Computation → Selective Execution → Cache Update
```

### Strategy Tiers (Lowest to Highest Cost)

| Strategy        | Trigger Fields                                                                              | Execution Path                    | Est. Time | LLM Calls             |
| --------------- | ------------------------------------------------------------------------------------------- | --------------------------------- | --------- | --------------------- |
| **BUILDER**     | `preferred_tile_ids`, `origin`                                                              | ItineraryBuilder only             | ~100ms    | None                  |
| **LOGISTICS**   | `adults`, `children`, `budget`, `flight_settings`, `hotel_settings`, `activity_skill_level` | LogisticsNode → Builder           | ~500ms    | None (API calls only) |
| **SPECIALISTS** | `start_date`, `end_date`, `activity_categories`                                             | Specialists → Logistics → Builder | ~3-8s     | Yes                   |
| **FULL**        | `destination`                                                                               | Full graph re-execution           | ~10-15s   | Yes                   |

### Field-to-Strategy Mapping

```python
# backend/app/services/regen_strategy.py
FIELD_IMPACT: Dict[str, RegenStrategy] = {
    # FULL - destination changes invalidate everything
    "destination": RegenStrategy.FULL,
    # SPECIALISTS - dates affect seasonal context and activity capacity
    "dates": RegenStrategy.SPECIALISTS,
    # SPECIALISTS - activity categories trigger specialist detection
    "activity_categories": RegenStrategy.SPECIALISTS,
    # LOGISTICS - affects tile availability/pricing, not recommendations
    "travelers": RegenStrategy.LOGISTICS,
    "budget": RegenStrategy.LOGISTICS,
    "flight_settings": RegenStrategy.LOGISTICS,
    "hotel_settings": RegenStrategy.LOGISTICS,
    "activity_skill_level": RegenStrategy.LOGISTICS,
    # BUILDER - only affects itinerary structure, reuse cached tiles
    "origin": RegenStrategy.BUILDER,
}
```

**Why dates trigger SPECIALISTS:** Seasonal context affects specialist recommendations. "Bali diving March" vs "Bali diving November" (monsoon season) produces different activity recommendations.

**Why activity_categories trigger SPECIALISTS:** Changing from general exploration to diving/hiking/skiing triggers specialist detection in IntentRouter, requiring new LLM-generated recommendations.

**Why settings trigger LOGISTICS:** Flight/hotel/activity settings affect tile filtering (direct flights, star ratings, skill levels) but don't invalidate specialist knowledge - we filter from cached tiles.

### Backend Implementation

#### On-Demand Field Hash Computation (main.py, regen_strategy.py)

Field hashes are computed on-demand at the `/api/expand-itinerary` endpoint by comparing the document's stored `trip_inputs` against the incoming request:

```python
# In expand_itinerary endpoint (main.py)
# Compute previous field hashes from document's stored trip_inputs
prev_trip_inputs = (
    doc_data.trip_inputs.model_dump() if doc_data.trip_inputs else {}
)
previous_hashes = compute_field_hashes(prev_trip_inputs)

# Compute current field hashes from request trip_inputs
current_hashes = compute_field_hashes(trip_inputs_data)

# Detect which fields changed
changed_fields = {
    k for k in current_hashes
    if current_hashes[k] != previous_hashes.get(k)
}
strategy = compute_strategy(changed_fields)
```

**Why on-demand instead of stored:** The `Session` model tracks authentication (tokens, expiry) while the `Document` model stores trip state. Computing hashes on-demand from `Document.trip_inputs` avoids schema changes and keeps the change detection logic centralized in the endpoint.

#### Strategy Computation (regen_strategy.py)

```python
def compute_strategy(changed_fields: Set[str]) -> RegenStrategy:
    """Most conservative strategy wins."""
    if not changed_fields:
        return RegenStrategy.BUILDER  # Preferences may have changed

    # Priority order: FULL > SPECIALISTS > LOGISTICS > BUILDER
    for strategy in STRATEGY_PRIORITY:
        if strategy in [FIELD_IMPACT.get(f) for f in changed_fields]:
            return strategy

    return RegenStrategy.BUILDER
```

#### Node-Level Cache Awareness

Each node checks if cached output can be reused before executing:

**VerticalSpecialist & LocalExpert:**

```python
# Check if cached section exists with matching destination
existing_sections = state.metadata.get("strategy_sections", [])
cached_section = next(
    (s for s in existing_sections if s.get("specialist_type") == topic), None
)
if cached_section and destination_unchanged:
    log(f"[{topic}] Cache HIT: Reusing cached output")
    return state  # No-op, skip LLM call
```

**LogisticsNode:**

```python
# Check if tiles exist for current destination
if state.tiles.get("hotels") and tiles_destination == current_destination:
    log("LOGISTICS", "Cache HIT: Reusing cached tiles")
    return state  # No-op, skip tile fetching
```

### Frontend Implementation (useItineraryRegeneration.ts)

The hook tracks both preferences AND trip inputs for change detection, using stable stringification to handle nested settings objects:

```typescript
// Stable JSON stringification for consistent hashing
// Ensures objects with different key orders produce the same hash
function stableStringify(obj: unknown): string {
  if (obj === null || obj === undefined) return "";
  if (typeof obj !== "object") return String(obj);
  if (Array.isArray(obj)) {
    return JSON.stringify(obj.map(stableStringify).sort());
  }
  const sortedKeys = Object.keys(obj).sort();
  const sortedObj = {};
  for (const key of sortedKeys) {
    sortedObj[key] = stableStringify(obj[key]);
  }
  return JSON.stringify(sortedObj);
}

// Hash trip inputs for change detection (including settings)
const tripInputsHash = useMemo(() => {
  if (!tripInputs) return "";
  const activitySettings = tripInputs.activity_settings || {};
  return JSON.stringify({
    destination: tripInputs.destination,
    start_date: tripInputs.start_date,
    end_date: tripInputs.end_date,
    adults: tripInputs.adults,
    children: tripInputs.children,
    budget: tripInputs.budget,
    origin: tripInputs.origin,
    // Settings fields use stable stringification for consistent hashing
    flight_settings: stableStringify(tripInputs.flight_settings),
    hotel_settings: stableStringify(tripInputs.hotel_settings),
    activity_categories: stableStringify(activitySettings.categories),
    activity_skill_level: activitySettings.skill_level || "",
  });
}, [tripInputs]);

// Combined change detection
const hasChanges = hasPreferenceChanges || hasTripInputChanges;
```

### Debounce with Visual Feedback

The hook provides visual feedback during the debounce period and a bypass button for impatient users:

**Configuration:**

- `AUTO_REGEN_DEBOUNCE_MS = 2000` (2 seconds, increased from 1.5s)

**States exposed:**

- `isPending` - true during countdown (debounce waiting)
- `isRegenerating` - true during actual regeneration
- `remainingSeconds` - countdown (2, 1, 0)
- `triggerImmediateRegeneration()` - bypass debounce, regenerate now

**Visual component (`RegenerationStatus.tsx`):**

- Fixed position bottom-right corner
- Shows "Planning updates in Ns..." during countdown
- Shows "Regenerating plan..." during regeneration
- "Generate Now" button to bypass debounce

**Race condition protection:**

```typescript
// isExecutingRegenRef prevents double regeneration if:
// 1. Debounce timer fires at exact same time as "Generate Now" click
// 2. Multiple rapid bypass clicks
// 3. Component receives concurrent trigger requests
const isExecutingRegenRef = useRef(false);

// Both debounce callback and triggerImmediateRegeneration check this:
if (isExecutingRegenRef.current) {
  console.log("Skipping - regeneration already in progress (race avoided)");
  return;
}
isExecutingRegenRef.current = true;
try {
  await regenerate();
} finally {
  isExecutingRegenRef.current = false;
}
```

### Settings Ownership & Document Merge

User-configurable settings (`activity_settings`, `hotel_settings`, `flight_settings`,
`transport_settings`, `booking_types`) follow a strict ownership model to prevent
stale graph state from overwriting user intent.

**Ownership Rule:** The document (written by `PATCH /api/document`) is the SSoT for
these fields. The graph session must never overwrite them with defaults.

**Three-layer defense:**

| Layer          | File                                                 | What it does                                                                                                                                                                                                                                                                                 |
| -------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Emission       | `plan_graph.py` `_trip_plan_to_trip_inputs()`        | Settings fields **omitted** from TripPlan conversion — they live on the document, not `TripPlan`                                                                                                                                                                                             |
| Restoration    | `plan_graph.py` `_build_trip_inputs_with_settings()` | Reads typed `TripSettings` via `get_trip_settings(state)` and serializes sub-models into output `trip_inputs`. **Override:** if `metadata["trip_inputs"]["activity_settings"]` has non-empty categories (from router's in-turn sync), those win over typed settings to survive serialization |
| Input merge    | `main.py` both chat endpoints                        | `_USER_OWNED_SETTINGS` guard — document baseline wins for settings fields                                                                                                                                                                                                                    |
| Output persist | `crud_document.py` `apply_planner_update()`          | Strips settings from graph output before `merge_trip_inputs()`                                                                                                                                                                                                                               |

**How the four layers work together:**
`_trip_plan_to_trip_inputs()` emits only scalar fields (destination, dates, etc.)
because settings live on the document, not TripPlan. The `_build_trip_inputs_with_settings()`
restoration layer reads typed settings via `get_trip_settings(state)` (from
`metadata["trip_settings"]`, falling back to legacy `metadata["trip_inputs"]`) and
serializes them back into the output `trip_inputs` dict. **Category override:**
after the typed-settings loop, `_build_trip_inputs_with_settings()` checks
`metadata["trip_inputs"]["activity_settings"]` — if it has non-empty categories
(written by the router's sync block during the turn), those override the typed
settings value. This ensures in-turn category writes survive to `apply_planner_update`,
which preserves non-empty categories in the document. The input merge guard
(layer 3) and persist strip (layer 4) provide defense-in-depth on the document side.

**Typed Settings:**

- `metadata["trip_settings"]` is the typed SSoT for settings (shadow-written in `_restore_graph_state`)
- `get_trip_settings(state)` accessor returns a `TripSettings` Pydantic model
- All nodes read settings via `get_trip_settings()` instead of raw `metadata["trip_inputs"]` dicts
- `metadata["trip_inputs"]` is deprecated but preserved for backward compat with old sessions
- After any write to `metadata["trip_inputs"]`, nodes rebuild typed settings via `state.metadata["trip_settings"] = get_trip_settings(state).model_dump()`

**Typed Routing Accessors:**

- All 5 routing functions use `get_turn_meta(state)` / `get_persistent_meta(state)` instead of raw `state.metadata.get()` reads
- `TurnMeta` fields include: `is_generate_trigger` (frontend Build Plan flag), `logistics_attempted` (prevents architect->logistics loop), `origin_only_logistics`, `short_circuit_response`, `architect_ran_this_turn`, `has_blocking_violations`, `constraint_violations`, `input_gate_violations` (list of gate blocker dicts), `input_gate_warnings` (list of gate warning dicts)
- `route_after_architect` uses both accessors: `turn` for `logistics_attempted`, `persistent` for `local_expert_ran`
- Regression tests: `tests/test_routing.py` (30 parameterized cases covering all routing branches)

**Input merge pattern (both endpoints in `main.py`):**

```python
_USER_OWNED_SETTINGS = {
    "activity_settings", "hotel_settings", "flight_settings",
    "transport_settings", "booking_types",
}
if document_data.trip_inputs:
    doc_inputs = document_data.trip_inputs.model_dump()
    session_inputs = session_state.get("trip_inputs", {})
    # Document as baseline, session overrides for graph-owned fields only
    merged = {**doc_inputs}
    for k, v in session_inputs.items():
        if v is not None and k not in _USER_OWNED_SETTINGS:
            merged[k] = v
    session_state["trip_inputs"] = normalize_trip_inputs(merged)
```

**Output persist strip (`apply_planner_update`):**

```python
# Strip user-owned settings from graph output before merge
if trip_inputs:
    cleaned_inputs = _trip_inputs_to_dict(trip_inputs)
    for field in _USER_OWNED_SETTINGS:
        cleaned_inputs.pop(field, None)
data.trip_inputs = merge_trip_inputs(data.trip_inputs, cleaned_inputs, ...)
```

**NL-Extracted Settings Bypass:**
When the Architect detects settings from natural language (e.g., "5-star hotels"),
these are stored in `state.metadata["extracted_settings"]` and deep-merged via a
separate path in `apply_planner_update(extracted_settings=...)`, bypassing the
user-owned field strip. Supported keys: `hotel_min_stars`, `flight_direct_only`,
`flight_cabin_class`, `activity_skill_level`, `flights_toggle` (`"on"`/`"off"` tri-state).

**Settings Extraction Keyword Guard:**
The Architect's `_has_settings_keywords()` gate uses compound phrases that require
booking context (e.g., `"direct flight"`, `"budget hotel"`, `"star hotel"`) rather
than generic words. This prevents false triggers on activity descriptions like
"yoga class" or "business district". The LLM prompt explicitly forbids inferring
toggle=off from absence — a toggle is "off" only when the user says "no hotels",
"skip flights", etc.

**Concurrent PATCH Safety:**
The session carries stale `trip_inputs` from the previous graph run — user-owned
fields set via PATCH (pill selections, settings sheets) are not reflected in the
session. Two additional guards fix this:

| Guard                     | Location                                                                    | Mechanism                                                                                                                                                                                                           |
| ------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_doc_settings` injection | `main.py` both endpoints → `plan_graph.py` `_restore_graph_state()`         | `db.refresh(document)`, extract user-owned fields into `session_state["_doc_settings"]`, merge them into `state.metadata["trip_inputs"]` inside `_restore_graph_state` so the router sees pill-selected specialists |
| Pre-persist refresh       | `crud_document.py` `apply_planner_update()` / `apply_planner_update_sync()` | `db.refresh(doc)` before `get_document_data(doc)` so the base document reflects any PATCHes that committed during the graph run                                                                                     |

Combined with the three-layer defense above, this ensures:

1. The graph **sees** pill-selected categories for specialist routing (Part 1)
2. The graph **cannot erase** pill-selected categories on output (Part 2)

**Defensive Check in IntentRouter (origin sync):**

```python
# If origin mismatch detected at graph entry, sync from trip_inputs
trip_inputs = state.metadata.get("trip_inputs", {})
trip_inputs_origin = trip_inputs.get("origin")
if trip_inputs_origin and not state.trip_plan.origin:
    logger.warning(f"ORIGIN MISMATCH: Syncing from trip_inputs")
    state.trip_plan.origin = trip_inputs_origin
```

### Performance Impact

| Scenario               | Without Selective Regen | With Selective Regen | Savings |
| ---------------------- | ----------------------- | -------------------- | ------- |
| Heart a tile           | ~10s (full graph)       | ~100ms (BUILDER)     | 99%     |
| Change origin          | ~10s (full graph)       | ~100ms (BUILDER)     | 99%     |
| Change travelers       | ~10s (full graph)       | ~500ms (LOGISTICS)   | 95%     |
| Change hotel stars     | ~10s (full graph)       | ~500ms (LOGISTICS)   | 95%     |
| Change flight settings | ~10s (full graph)       | ~500ms (LOGISTICS)   | 95%     |
| Change skill level     | ~10s (full graph)       | ~500ms (LOGISTICS)   | 95%     |
| Change dates           | ~10s (full graph)       | ~6s (SPECIALISTS)    | 40%     |
| Add activity category  | ~10s (full graph)       | ~6s (SPECIALISTS)    | 40%     |
| Change destination     | ~10s (full graph)       | ~10s (FULL)          | 0%      |

### Debug Logging

When `DEBUG=full`, selective regeneration logs its decisions:

```
[DEBUG] 🔄 [expand-itinerary] Selective Regen: strategy=builder, changed={'origin'}
[DEBUG] 🤿 SPECIALIST [diving] Cache HIT: Reusing cached output
[DEBUG] ✈️ LOGISTICS Cache HIT: Reusing cached tiles

[DEBUG] 🔄 [expand-itinerary] Selective Regen: strategy=logistics, changed={'hotel_settings'}
[DEBUG] 🤿 SPECIALIST [diving] Cache HIT: Reusing cached output
[DEBUG] ✈️ LOGISTICS Cache MISS: Re-fetching tiles with new settings

[DEBUG] 🔄 [expand-itinerary] Selective Regen: strategy=specialists, changed={'activity_categories'}
[DEBUG] 🤿 SPECIALIST [hiking] NEW: Generating recommendations
```

---

## Prompt File Mapping

### Prompts

```
backend/app/prompts/
├── synthesizer.txt                # Synthesizer - response generation (Jinja2 template)
└── specialists/
    ├── climbing.txt               # VerticalSpecialist - climbing domain
    ├── cycling.txt                # VerticalSpecialist - cycling domain
    ├── diving.txt                 # VerticalSpecialist - diving domain
    ├── hiking.txt                 # VerticalSpecialist - hiking domain
    ├── local_expert.txt           # LocalExpert - city logistics prompt (used when LOCAL_EXPERT_USE_LLM=true)
    ├── sailing.txt                # VerticalSpecialist - sailing domain
    ├── skiing.txt                 # VerticalSpecialist - skiing domain
    ├── surfing.txt                # VerticalSpecialist - surfing domain
    └── wildlife_safari.txt        # VerticalSpecialist - wildlife safari domain
```

### Prompt Purpose Summary

| File                              | Used By            | Purpose                                                                                                                                                                                                                                                                                                                                                                                    |
| --------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `synthesizer.txt`                 | Synthesizer        | Response generation, Jinja2 template with `response_type` conditional. Two main branches: `specialist_update` (post-plan changes, dispatches on `change_type`: SETTINGS_CHANGE, DATE_CHANGE, NEW_CATEGORY, STEPPER_RERUN, PLAN_UPDATE — each with a terse per-type template) and `planning` (first plan, voice selection by specialist vs general). Solver identity = "Expedition Leader". |
| `specialists/climbing.txt`        | VerticalSpecialist | Climbing domain knowledge                                                                                                                                                                                                                                                                                                                                                                  |
| `specialists/cycling.txt`         | VerticalSpecialist | Cycling domain knowledge                                                                                                                                                                                                                                                                                                                                                                   |
| `specialists/diving.txt`          | VerticalSpecialist | Diving domain knowledge                                                                                                                                                                                                                                                                                                                                                                    |
| `specialists/hiking.txt`          | VerticalSpecialist | Hiking domain knowledge                                                                                                                                                                                                                                                                                                                                                                    |
| `specialists/local_expert.txt`    | LocalExpert        | City logistics prompt (used when LOCAL_EXPERT_USE_LLM=true)                                                                                                                                                                                                                                                                                                                                |
| `specialists/sailing.txt`         | VerticalSpecialist | Sailing domain knowledge                                                                                                                                                                                                                                                                                                                                                                   |
| `specialists/skiing.txt`          | VerticalSpecialist | Skiing domain knowledge                                                                                                                                                                                                                                                                                                                                                                    |
| `specialists/surfing.txt`         | VerticalSpecialist | Surfing domain knowledge                                                                                                                                                                                                                                                                                                                                                                   |
| `specialists/wildlife_safari.txt` | VerticalSpecialist | Wildlife safari domain knowledge                                                                                                                                                                                                                                                                                                                                                           |

---

## Streaming Architecture

### Current Implementation: True Streaming via astream_events

Uses LangGraph's `astream_events` for real-time token streaming from the Synthesizer.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STREAMING FLOW                                                             │
│  ──────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  1. User sends message                                                       │
│  2. run_turn_streaming() creates state, invokes graph.astream_events()      │
│  3. Events emitted:                                                          │
│     - on_chain_start: Node transitions → node_status events                  │
│     - on_chat_model_stream: LLM tokens → token events (Synthesizer only)     │
│     - on_chain_end: Capture final state                                      │
│  4. "complete" event with full result                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Streaming Events

| Event Type     | Data                              | Description                                                    |
| -------------- | --------------------------------- | -------------------------------------------------------------- |
| `node_status`  | `{node, status, label, icon_key}` | Node progress tracking                                         |
| `logic_reveal` | `{node, label, status}`           | Routing decisions for Logic Terminal (e.g., "ROUTING: DIVING") |
| `token`        | `string`                          | Response text (from Synthesizer LLM)                           |
| `complete`     | `{...result}`                     | Full result object                                             |
| `error`        | `{message}`                       | Error information                                              |

### Streaming Implementation

```python
async for event in graph.astream_events(state, version="v2"):
    event_type = event.get("event")

    # Track node transitions
    if event_type == "on_chain_start":
        node_name = event.get("metadata", {}).get("langgraph_node")
        if node_name:
            yield {"type": "node_status", "data": {"node": node_name, "status": "started"}}

    # Stream tokens from Synthesizer's LLM
    elif event_type == "on_chat_model_stream":
        node = event.get("metadata", {}).get("langgraph_node")
        if node == "synthesizer":  # Only stream from synthesizer
            chunk = event.get("data", {}).get("chunk")
            if chunk and chunk.content:
                yield {"type": "token", "data": chunk.content}
```

### Streaming Parameters

```python
# Simulated streaming (fallback) parameters
STREAMING_PARAMS = {
    "base_delay_ms": 15,   # Minimum delay between tokens
    "max_delay_ms": 35,    # Maximum delay between tokens
    "jitter_ms": 8,        # Random jitter range
    "chunk_size": 1,       # Single tokens
}
```

---

## Token Savings Summary

| Optimization                 | Tokens Saved | Frequency     |
| ---------------------------- | ------------ | ------------- |
| GREETING/RESET short-circuit | ~800-1500    | ~20% of turns |
| Specialist caching           | ~500-1000    | ~30% of turns |
| Template responses           | ~500-1500    | ~40% of turns |
| Panic button bypass          | ~1000-2000   | ~5% of turns  |
| LocalExpert static knowledge | ~300-800     | ~50% of turns |

---

## Itinerary Builder Service

**Location:** `backend/app/services/itinerary_builder.py`

**Purpose:** Pure Python service that transforms specialist outputs into chronological, constraint-validated timeline. Called from `/api/expand-itinerary`.

**NOT a LangGraph node** - preserves 7-node architecture invariant.

### Algorithm Phases

```
Phase 1: Temporal Scaffolding (_create_day_skeleton)
├─ Create DayCard[] skeleton from start_date to end_date
├─ Calculate trip duration
└─ Initialize empty block lists per day

Phase 2: Extract Specialist Content (_extract_specialist_content)
├─ Collect activities and constraints from strategy_sections
├─ Tag with source_specialist for color-coding
└─ Preserve constraint references

Phase 2a: Constraint Merge (_merge_constraints)
├─ Merge constraints with priority resolution
└─ Resolve by severity: BLOCKING > STRONG > SOFT

Phase 2b: Early Conflict Detection (_detect_early_conflicts)
├─ Detect temporal_capacity violations (>11h/day)
├─ Detect constraint_clash between specialists
├─ Return partial schedule showing what CAN be scheduled
└─ Generate ConflictResolution if irreconcilable

Phase 3: Anchor Placement (_place_anchors)
├─ Arrival block on Day 1 (from flight tiles)
├─ Departure block on last day (from flight tiles)
└─ Hotel check-in/check-out blocks

Phase 4: Buffer Injection (_inject_safety_buffers)
├─ Safety buffers (24h no-fly after diving)
├─ Rest days (acclimatization for altitude)
└─ Placed by constraint severity (BLOCKING first)

Phase 5: Activity Distribution (_distribute_activities, with Preference Weighting + Even Spread)
├─ Normalize activity IDs for frontend/backend matching
├─ Weight activities by user preferences (is_user_preferred flag)
├─ Sort: preferred activities first
├─ NO-FLY DAY RESTRICTION: Diving activities blocked from days within buffer_days of departure
│   ├─ latest_dive_day = departure_idx - 1 - buffer_days (e.g., Day 2 for a 4-day trip)
│   ├─ Round-robin wraps to earlier valid days if current day is restricted
│   └─ Other specialists (hiking, etc.) unaffected — can still use restricted days
├─ EVEN DISTRIBUTION: Cycle through ALL days before filling any day with 2nd activity
│   └─ Prevents packing early days (Days 2-5) while leaving late days (6-7) empty
├─ Max 3 activities per day (only enforced after all days have 1+)
├─ Respect day capacity (11 usable hours)
├─ Alternate specialists for variety (dive → hike → dive)
└─ Set preference_status on blocks ('user_preferred' | null)

Phase 5.5: Free Day Placeholders (_handle_empty_days)
├─ Add FreeDay placeholder blocks on empty days
├─ Compute Tier 2 categories (user selections minus scheduled specialists)
└─ Pass Tier 2 categories for later experience tile placement

Phase 5.6: Experience Tile Placement (_place_experience_tiles) — Three-Pass Co-Scheduling
├─ Filter tiles by source_agent == "experience_generator"
│  └─ Fallback: if no experience tiles, use ANY non-preferred activity tiles
│     (type == "activity", no source_agent filter) for pure Tier 1 trips
│     where logistics_node is the only activity tile source
├─ Sort by time_of_day: morning → afternoon → evening
├─ Pass 0 (Pinned Tiles from fill-day):
│   ├─ Tiles with meta.pinned_day are placed on their target day first
│   ├─ Respects day capacity (_day_remaining_capacity check)
│   ├─ Removes free_day placeholder on target day, resets "Free Day" label
│   └─ Tiles that can't fit fall through to unpinned pool
├─ Pass 1 (Free Days):
│   ├─ Find free day indices (days with free_day placeholder blocks)
│   ├─ Place 1-2 tiles per free day (if hours fit)
│   ├─ Remove free_day placeholder, create activity DayBlockOutput
│   └─ Update day.label to category title (e.g., "Yoga Day")
├─ Pass 2 (Co-Schedule on Specialist Days):
│   ├─ For remaining unplaced tiles, scan all days via _day_remaining_capacity()
│   ├─ Score candidates: complement * 0.7 + headroom * 0.3
│   │   ├─ _time_slot_score(): evening on morning-day = 1.0, same slot = 0.1
│   │   └─ headroom: remaining_hours / DAY_CAPACITY_HOURS
│   ├─ Place on best-scoring day, update candidate capacity
│   └─ Specialist day labels NOT relabeled (keep "Diving Day", etc.)
└─ Tiles that don't fit anywhere are dropped with debug log

Phase 5.25: Preferred Activity Placement (_populate_free_days_with_preferences)
├─ Populate free days with user-preferred activities (hearted tiles)
├─ Pass 1 (Unified Slot Model): round-robin on least-loaded days
└─ Pass 2 (Co-Schedule Fallback): deferred tiles on specialist days with spare capacity

Phase 6: Tile Matching (_match_tiles)
├─ Hotels span all days (with preference weighting)
├─ Activities matched to day blocks
├─ Flights attached to arrival/departure
└─ Hotel preference attribution (user_preferred metadata)

Phase 6.5: Constraint Tagging (_apply_constraints_to_blocks, Inline Display)
├─ Tag blocks with relevant constraints for frontend display
├─ Diving constraints:
│   ├─ no_fly_buffer: Applied to last dive before departure
│   └─ surface_interval: Between consecutive dive days
├─ Constraint structure: { id, severity, icon, title, description }
└─ Stored in block.active_constraints[]

Phase 6.75: FINAL Chronological Sort (_sort_blocks_chronologically, CRITICAL)
├─ Runs AFTER all phases have added blocks (5.5, 5.25, 6.5)
├─ Sort by logistics bracket (arrival → activities → departure)
├─ Then by time slot (morning < afternoon < evening < night)
├─ Buffer types have fixed positions:
│   ├─ arrival: (0,0) First thing
│   ├─ check_in: (0,1) Right after arrival
│   ├─ acclimatization: (1,0) Activity slot, morning
│   ├─ surface_interval: (1,1) Activity slot, between dives
│   ├─ no_fly_buffer: (1,3) Activity slot, evening
│   └─ departure/check_out: (2,0) Last thing
└─ Ensures correct display order regardless of insertion order

Phase 7: Temporal Conflict Detection (_detect_temporal_conflicts)
├─ Detect post-placement overflow (>11h/day)
├─ Detect constraint clashes after all placement
└─ Return warnings (currently non-blocking)
```

### Preference Weighting Implementation

**ID Normalization:**

```python
def _normalize_activity_id(self, activity: ActivityBlock) -> str:
    """Generate consistent ID for matching across frontend/backend."""
    if activity.tile_id:
        return activity.tile_id
    title = activity.title or activity.source or ""
    return title.lower().replace(" ", "_").replace("'", "").replace("-", "_")
```

**Priority Sorting:**

```python
# Weight activities by preference before distribution
for activity in activities:
    activity_id = self._normalize_activity_id(activity)
    is_preferred = self.preferences.is_activity_preferred(activity_id)
    activity.is_user_preferred = is_preferred

# Sort: preferred first
activities.sort(key=lambda a: (0 if a.is_user_preferred else 1))
```

### Constraint Severity Hierarchy

Multi-specialist trips require conflict resolution when constraints clash.

| Severity     | Examples                                                   | Resolution  |
| ------------ | ---------------------------------------------------------- | ----------- |
| **BLOCKING** | 24h no-fly (diving), visa requirements, permits            | Always wins |
| **STRONG**   | Best weather timing, equipment availability, opening hours | Negotiates  |
| **SOFT**     | Scenic routes, photo opportunities, early starts           | Defers      |

### Timezone Handling

MVP assumes all times are in destination local timezone. This is correct for most scenarios where dive/activity times and flight times are shown in local time.

If cross-timezone constraint calculations are needed in the future, add timezone-aware helpers at that time (e.g., using `zoneinfo` stdlib). Do not hardcode destination timezone maps — violates "no hard-coded world data" rule.

**Resolution Example:**

```
Conflict: Day 4
├─ Diving specialist: "blocking" - 24h no-fly buffer
├─ Hiking specialist: "strong" - optimal weather for summit
└─ Resolution: Diving wins (blocking > strong)
    Action: Move hike to Day 2 or Day 3, keep buffer on Day 4
```

### Day Capacity Model

```
Total hours per day: 24
├─ Sleep buffer: 8 hours
├─ Meals/transit: 3 hours
├─ Available: 13 hours
└─ Reserve: 2 hours (flexibility)

Usable capacity per day: 11 hours
```

When activities exceed 11 hours, the builder:

1. Sorts blocks by constraint severity (SOFT first)
2. Removes lowest-priority blocks until under capacity
3. Suggests trip extension if still over capacity

### Integration

**Input:**

- `strategy_sections`: Specialist-generated content
- `tiles`: Flights, hotels, activities from TileService
- `trip_inputs`: Dates, destination, travelers

**Output:**

- `DayCard[]`: Chronological day-by-day structure
- `ConflictResolution` (if irreconcilable conflicts)

**Trigger:** `/api/expand-itinerary` endpoint

**Tile Source Selection:** The endpoint uses `force_full_rebuild` to decide tile source:

- `force_full_rebuild=True` (auto-expand after chat): Uses DB tiles (session-authoritative, written by `apply_planner_update` before SSE). Frontend tiles may be stale from `mergeEnvelope` which adds but never removes.
- `force_full_rebuild=False` (preference regen / manual rebuild): Uses frontend tiles if non-empty (include hearted tiles, user filters), falls back to DB tiles only when frontend sends none.

### Debugging the Itinerary Flow

**Enable debug logs:** Set `DEBUG=full` in `backend/.env`. Logs use `_debug()` from `app.debug_utils` which only outputs when DEBUG=full.

```bash
# backend/.env
DEBUG=full
```

When debugging S2 → S3 transitions, trace these logs in terminal:

```
[DEBUG] ✅ [expand-itinerary] Session & doc found        # Generator started
[DEBUG] 📊 [expand-itinerary] Input data: sections=2    # Frontend sent data
[DEBUG] 🔥 [expand-itinerary] BUILDER CALLED             # About to call builder
[DEBUG] [ItineraryBuilder] 🏗️ Starting build            # Builder received input
[DEBUG] [ItineraryBuilder] Extracted: activities=3      # Content parsed
[DEBUG] [ItineraryBuilder] ✅ Success: 8 day cards       # Build completed
[DEBUG] 📤 [expand-itinerary] Emitting envelope          # Sending to frontend
```

#### Node Timing (Performance Debugging)

When `DEBUG=full`, each LangGraph node logs its execution duration:

```
[DEBUG] 🧭 ROUTER START | message=diving and hiking bali march 1-5
[DEBUG] 🧭 ROUTER END | duration=892ms | intent=PLANNING specialist_hints=['diving', 'hiking']
[DEBUG] 🌍 LOCAL_EXPERT END | duration=12ms | destination=Bali
[DEBUG] 🤿 SPECIALIST END | duration=8432ms | topic=diving feasibility=feasible activities=3
[DEBUG] 🥾 SPECIALIST END | duration=10ms | topic=hiking (cached from parallel)
[DEBUG] ✈️ LOGISTICS END | duration=234ms | flights=4 hotels=3
[DEBUG] 📝 SYNTHESIZER END | duration=1823ms | tokens=412
```

**Timing Functions (in `debug_utils.py`):**

| Function                                             | Purpose                              |
| ---------------------------------------------------- | ------------------------------------ |
| `_debug_node_timer_start(node_name)`                 | Start timing (call at node entry)    |
| `_debug_node_timer_end(node_name, emoji, **outputs)` | End timing and log duration          |
| `NodeTimer(node_name, emoji)`                        | Context manager for automatic timing |

**Usage:**

```python
# Manual timing
_debug_node_timer_start("specialist")
# ... node code ...
_debug_node_timer_end("specialist", "🤿", topic=topic, activities=len(activities))

# Context manager
with NodeTimer("synthesizer", "📝") as timer:
    # ... node code ...
    timer.set_outputs(tokens=token_count)
```

**Early Return Detection:**

- If 🔥 log is missing, check for `❌ [expand-itinerary]` logs indicating:
  - Missing end_date
  - Trip too short (< 2 days)
  - Session/document not found

**Common Issues:**

| Symptom                         | Log to Check       | Fix                                                                            |
| ------------------------------- | ------------------ | ------------------------------------------------------------------------------ |
| No backend logs at all          | `DEBUG` env var    | Set `DEBUG=full` in backend/.env                                               |
| No backend logs                 | Session/doc check  | Verify session cookie                                                          |
| `sections=0`                    | Frontend payload   | Check Network tab for empty `strategy_sections`                                |
| `activities=0`                  | Content extraction | Verify `content_added` in strategy_sections                                    |
| Build succeeds but UI unchanged | Browser console    | Check `mergeEnvelope` logs + Zustand selector (see ux_unified_architecture.md) |

### Conflict Resolution Response

When conflicts cannot be automatically resolved:

```python
class ConflictResponse(BaseModel):
    success: bool = False
    error: str = "CONSTRAINT_CONFLICT"
    conflicts: List[Conflict]
    resolutions: List[Resolution]

class Conflict(BaseModel):
    type: Literal["temporal_capacity", "constraint_clash", "insufficient_days"]
    severity: ConstraintSeverity  # Enum: "blocking", "strong", "soft"
    day: Optional[int]
    specialists: List[str]
    message: str
    overflow_hours: Optional[float]

class Resolution(BaseModel):
    action: Literal["extend_trip", "reduce_activities", "reorder", "shift_activities"]
    description: str
    new_duration: Optional[int]
    keep_specialist: Optional[str]
    feasibility: Literal["recommended", "possible", "not_recommended"]
```

**Frontend Handling:** Constraint conflicts are handled inline — partial `day_cards` auto-render at `S3_PARTIAL_CONFLICT` view state, and blocking violations are re-surfaced by the constraint guard on the next chat turn (via `last_builder_success` metadata) so the synthesizer generates resolution suggestion chips.

---

## Key Exports

| Module              | Exports                                                                                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `planner`           | `run_turn`, `run_turn_streaming`, `GraphState`                                                                                                                 |
| `planner.state`     | `GraphState`, `TripPlan`, `TripSegment`, `ItineraryBlock`, `SpecialistConstraint`, `SpecialistOutput`, `UIEvent`, `MissingFieldsResponse`, `SynthesizerOutput` |
| `planner.hashing`   | `stable_hash`, `stable_hash_int`, `stable_hash_index`, `make_cache_key`                                                                                        |
| `planner.telemetry` | `TraceEnvelope`, `create_envelope`, `emit_event`, `emit_node_start`, `emit_node_end`                                                                           |
| `planner.nodes`     | `intent_router`, `trip_architect`, `vertical_specialist`, `local_expert`, `logistics_node`, `constraint_guard`, `synthesizer`                                  |

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
| `/api/admin/clear-validation-cache` | POST   | Clear validation caches                                                         |
| `/api/admin/fresh-start`            | POST   | Clear validation + response caches                                              |
| `/api/admin/clear-all-checkpoints`  | POST   | Clear ALL LangGraph checkpoints                                                 |
| `/api/admin/clear-all-caches`       | POST   | Comprehensive clear of ALL caches (includes L1+L2 for specialist, tile, router) |

---

## Tile Service Architecture

### Tile Refresh Endpoint

```
POST /api/tiles/refresh
```

| Field       | Type     | Description                               |
| ----------- | -------- | ----------------------------------------- |
| `branch_id` | string   | Branch to refresh tiles for               |
| `verticals` | string[] | Optional: ["hotel", "flight", "activity"] |

### Provider Architecture

```
tile_service/
├── __init__.py           # Exports: search_tiles + booking types
├── models.py             # SearchContext, TileSearchRequest
├── service.py            # search_tiles() orchestrator
├── provider_base.py      # Provider ABC + BookableProvider ABC
├── mock_provider.py      # Mock providers for development
├── amadeus_provider.py   # Amadeus API (disabled for now)
└── curated_provider.py   # Curated content for hero destinations
```

### Provider Routing Consistency

Both `logistics_node.py` and `tile_service/service.py` use identical routing logic:

| Flow                           | Destination Type | Provider Used   |
| ------------------------------ | ---------------- | --------------- |
| First Request (logistics_node) | Curated          | CuratedProvider |
| First Request (logistics_node) | Non-Curated      | MockProviders   |
| Regeneration (tile_service)    | Curated          | CuratedProvider |
| Regeneration (tile_service)    | Non-Curated      | MockProviders   |

This ensures tiles have consistent images and data regardless of how they were fetched.

### Settings-Aware Tile Filtering

Both `curated_provider.py` and `amadeus_provider.py` apply filters from `SearchContext`:

| Setting Type                    | Filter Applied                                      | Budget Allocation |
| ------------------------------- | --------------------------------------------------- | ----------------- |
| `budget` (hotels)               | `tile.price_estimate <= budget * 0.40`              | 40%               |
| `budget` (activities)           | `tile.price_estimate <= budget * 0.30`              | 30%               |
| `budget` (flights)              | `tile.price_estimate <= budget * 0.30`              | 30%               |
| `hotel_settings.min_stars`      | `tile.rating >= min_stars` (fallback: `meta.stars`) | -                 |
| `flight_settings.direct_only`   | `tile.meta.stops == 0`                              | -                 |
| `activity_settings.skill_level` | `tile_skill_level <= user_skill_level`              | -                 |

**Skill Level Filtering Logic:**

```python
# Order: beginner < intermediate < advanced
# User "intermediate" sees: beginner + intermediate tiles
# User "advanced" sees: all tiles
skill_order = ["beginner", "intermediate", "advanced"]
tile_idx = skill_order.index(tile_skill)
user_idx = skill_order.index(user_skill)
return tile_idx <= user_idx
```

**Implementation Files:**

- `backend/app/tile_service/curated_provider.py::search()` - Budget, stars, skill filtering at provider level
- `backend/app/tile_service/amadeus_provider.py::_search_async()` / `search_async()` - Budget filtering post-API. `search_async()` is a new public async entry point (both Flight and Hotel providers) for use from async contexts without `asyncio.run()` wrapping.
- `backend/app/planner/nodes/logistics_node.py` - Post-fetch hotel star filter (applies to all providers including mock/cached tiles)

---

## Booking Provider Interface (Scaffolding)

> **Status:** Interface defined, real provider implementation deferred until API access.

### Design Decision

**Booking = REST endpoints, NOT LangGraph nodes**

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
INITIATED → PENDING_PAYMENT → HOLD → CONFIRMED
                 ↓              ↓
              FAILED         EXPIRED
                 ↓
            CANCELLED
```

| Status            | Description                                |
| ----------------- | ------------------------------------------ |
| `INITIATED`       | Booking request received                   |
| `PENDING_PAYMENT` | Awaiting payment                           |
| `HOLD`            | Inventory temporarily reserved             |
| `CONFIRMED`       | Booking complete, confirmation code issued |
| `FAILED`          | Payment declined or inventory unavailable  |
| `CANCELLED`       | User or system cancelled                   |
| `EXPIRED`         | Hold/session expired                       |

### Key Types

| Type                  | Location           | Purpose                    |
| --------------------- | ------------------ | -------------------------- |
| `BookableProvider`    | `provider_base.py` | ABC for bookable providers |
| `BookingSession`      | `provider_base.py` | In-progress booking state  |
| `BookingConfirmation` | `provider_base.py` | Completed booking details  |
| `TravelerInfo`        | `provider_base.py` | Traveler data for booking  |
| `BookingError`        | `provider_base.py` | Structured error handling  |

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

## Public Interface

Planner exports the stable public API.

```python
# These are re-exported from plan_graph.py
from app.planner import (
    run_turn,              # Main entry point
    run_turn_streaming,    # SSE streaming entry point
    GraphState,            # State type
    get_planner_debug_info,
    validate_template_coverage,
    clear_all_caches,
    # ... and more
)
```

### Result Format

Built by `format_result()` orchestrator in `response_envelope.py`, which delegates to:

| Function                             | Responsibility                                                                                                                                                                                                                                          |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_build_trip_inputs_with_settings()` | TripPlan → trip_inputs + settings merge (reads typed `TripSettings` via `get_trip_settings()`, with metadata category override)                                                                                                                         |
| `_resolve_blocking_violations()`     | Route vs specialist violations, tile/state clearing                                                                                                                                                                                                     |
| ~~`_enrich_existing_sections()`~~    | **DELETED** — sections now created complete by `section_builder.py`                                                                                                                                                                                     |
| `_build_new_section()`               | Build new strategy section for General Agent (delegates to 7 sub-functions)                                                                                                                                                                             |
| `_upsert_section_and_persist()`      | SINGLETON/APPENDABLE upsert + anchor sort + metadata write (delegates to `SectionBuilder` service)                                                                                                                                                      |
| `build_itinerary_from_state()`       | Shadow: build itinerary at S2_STRATEGY_READY via `itinerary_adapter.py`                                                                                                                                                                                 |
| `_build_response_envelope()`         | Document + session_state + legacy fields + `itinerary_day_cards`. `suggested_responses` uses fallback: `state.suggested_replies` OR `state.metadata["synthesizer_output"]["suggested_replies"]` (recovers chips when GraphState parse loses the field). |

#### SectionBuilder Service (`backend/app/planner/services/section_builder.py`)

Strategy section CRUD was extracted from duplicated inline code in `vertical_specialist.py`, `local_expert.py`, and `plan_graph.py` into a single service:

| Function                                   | Responsibility                                                                                                                                            |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `upsert_section(metadata, section, mode=)` | Init-if-missing, filter-by-type, insert/append, anchor-sort. Modes: `"singleton"` (General at index 0) or `"appendable"` (specialists deduplicate+append) |
| `mark_topic_executed(metadata, topic)`     | Deduplicating append to `executed_strategy_topics`                                                                                                        |
| `build_specialist_section(..., day_pref=)` | Pure dict builder for niche specialist sections (diving, hiking, etc.). Includes `_cache_day_pref` for invalidation.                                      |
| `build_local_expert_section(...)`          | Pure dict builder for local expert sections (Magazine Layout)                                                                                             |
| `sort_sections_anchor_first(sections)`     | Anchor rule: `local_expert`/`general` always at index 0                                                                                                   |

Callers: `vertical_specialist.py`, `local_expert.py`, `plan_graph.py:_upsert_section_and_persist()`.

#### IATA Resolver (`backend/app/planner/services/iata_resolver.py`)

LLM-backed airport code resolver with state caching. Single source of truth for all IATA code resolution.

| Function                                         | Responsibility                                                                                                                                                            |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `resolve_iata_codes(origin, destination, state)` | Returns `(origin_code, dest_code)`. Reads `state.trip_plan.*_iata` first; fires `settings.iata_resolver_model` fallback (~50 tokens) only if missing. Caches resolved codes back onto state. |

Called by: IntentRouter (origin detection fast-path), LogisticsNode (flight search gating).

#### Itinerary Adapter (`backend/app/planner/services/itinerary_adapter.py`)

Thin bridge from `GraphState` to `ItineraryBuilder`. Uses shared `flatten_tiles_to_id_map()` from `backend/app/utils/tile_utils.py`.

| Function                            | Responsibility                                                                                         |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `build_itinerary_from_state(state)` | Build `ItineraryResult` from graph state. Returns `None` if preconditions not met (no dates/sections). |

Called by `format_result()` step 6.5 (shadow mode — exception → warning, doesn't block response). On success, sets `state.metadata["last_builder_success"] = True`, computes `last_builder_drop_ratio` (`1.0 - placed/input`), and persists `builder_activities_input` / `builder_activities_placed` counts for synthesizer drop reporting; on failure, sets success to `False`, drop ratio to `1.0`, and stores `state.metadata["last_builder_resolutions"]` (serialized `Resolution[]`) so the constraint guard on the next turn can decide whether to suppress or re-surface cross-domain violations.

```python
{
    "assistant_message": "...",
    "suggested_responses": ["...", "...", "..."],
    "suggested_response_meta": [{"chip_type": "cta"|"follow_up"|"setting", "category": "...", "icon": "..."|null}, ...],
    "session_state": {...},
    "branches": [],  # Document branches
    "trip_inputs": {...},
    "ready_to_generate": bool,
    "errors": [...],
    "document": {
        "plan_view_state": "S0_BOOTSTRAP" | "S2_STRATEGY_READY",  # Computed by _compute_plan_view_state(), persisted to state.metadata for next turn
        "tiles": {...},           # Flattened ID-based map (each tile gets `price_display` field: "$120" or null)
        "strategy_sections": [...], # Agent cards data (content_blocks dual-written)
        "itinerary_day_cards": [...] | null,  # ItineraryBuilder output (null until S2_STRATEGY_READY)
        "constraints_validated": [...] | null,  # Guard validation state
        "constraint_violations": [...] | null,  # Active violations
    },
}
# Note: graph_plan/stream endpoint copies itinerary_day_cards, suggested_responses,
# suggested_response_meta, constraints_validated, and constraint_violations from
# graph execution output into the SSE response document. This enables frontend to
# skip expand-itinerary when the graph already built the itinerary (GRAPH_BUILT path).
```

### View States (from `_compute_plan_view_state()`)

The response envelope computes `plan_view_state` based on data richness, then persists it to `state.metadata["plan_view_state"]` so the intent router can read it on the next turn via `_is_plan_active()`:

| View State            | Condition                                                                          | Data Richness                                |
| --------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------- |
| `S0_BOOTSTRAP`        | No tiles and no specialist content                                                 | Setup checklist, blank slate                 |
| `S2_STRATEGY_READY`   | Has tiles OR has specialist strategy sections                                      | Strategy preview or full logistics dashboard |
| `S3_ITINERARY_READY`  | Builder succeeded — day_cards exist (set by graph_plan/stream or expand-itinerary) | Full timeline with scheduled activities      |
| `S3_PARTIAL_CONFLICT` | Conflict detected during expand-itinerary (set by frontend)                        | Partial timeline with unschedulable blocks   |

### Two-Mode Frontend System

> **NOTE:** The frontend uses a simplified two-mode system (PLANNING + BOOKING). View states represent data richness within PLANNING mode.

| Frontend Mode | View States                          | Description                    |
| ------------- | ------------------------------------ | ------------------------------ |
| **PLANNING**  | `S0_BOOTSTRAP` → `S2_STRATEGY_READY` | Progressive enrichment         |
| **BOOKING**   | After "Proceed to Booking" click     | Transaction + price comparison |

**Key Points:**

- PLANNING mode evolves naturally based on user inputs (no explicit "Build" click)
- Dates auto-trigger tile search (SOFT gate)
- "Proceed to Booking" is the only HARD gate (explicit click required)
- See `docs/ux_unified_architecture.md` Section I for full specification

#### Mode-Aware Tile Components

| Component           | Mode     | Purpose                          | Location                  |
| ------------------- | -------- | -------------------------------- | ------------------------- |
| `SuggestionCard`    | PLANNING | Shows tiles with AI reasoning    | `components/plan/tiles/`  |
| `BookableCard`      | BOOKING  | Shows price comparison           | `components/plan/tiles/`  |
| `AlternativesModal` | PLANNING | "Change" sheet with alternatives | `components/plan/modals/` |

#### Mode-Aware Layout Components

| Component               | Mode Support | Purpose                                                                                            | Location             |
| ----------------------- | ------------ | -------------------------------------------------------------------------------------------------- | -------------------- |
| `PlanHeader`            | Both         | Hero image with enriched overlay (title, route+duration, specialist pills), TripSummaryPills strip | `components/plan/`   |
| `TripStatusBar`         | Mobile-only  | Two-tier: collapsed plain-text summary, expandable detail card with per-field edit buttons         | `components/chat/`   |
| `MobileModeHeader`      | Mobile-only  | Branding header + floating status pill (RESOLVING only — STABLE pill hidden)                       | `components/layout/` |
| `UnifiedChipRow`        | Both         | Chips disabled (read-only) in BOOKING mode                                                         | `components/plan/`   |
| `TileDetailsModal`      | Both         | "Why this?" in PLANNING, price comparison in BOOKING                                               | `components/tiles/`  |
| `StrategyStageRenderer` | Both         | Derives mode from activeView, passes to BookingSection                                             | `components/plan/`   |

#### Frontend State (documentStore.ts)

```typescript
// Cart state for BOOKING mode
cartTileIds: Set<string>;
addToCart: (tileId: string) => void;
removeFromCart: (tileId: string) => void;
clearCart: () => void;

// Selector hooks
useCartTileIds(): Set<string>
useCartActions(): { addToCart, removeFromCart, clearCart }
```

#### Map-Itinerary Sync (useMapSync)

| Direction      | Trigger                | Action                                   |
| -------------- | ---------------------- | ---------------------------------------- |
| Timeline → Map | User scrolls itinerary | Map flies to location, highlights pin    |
| Map → Timeline | User clicks pin        | Timeline scrolls to item, ring highlight |

**Files:**

- `hooks/useMapSync.ts` - Central sync state management
- `lib/route-utils.ts` - GeoJSON route generation
- `components/map/MapLayerFilter.tsx` - Activity type toggles

---

## Curated Content (Hero Destinations)

Demo-ready content for showcase destinations stored in `backend/app/data/demo_curation.py`.

### DEMO_MANIFEST Structure

```python
DEMO_MANIFEST = {
    "dubai": {
        "destination_gallery": [...],     # "Vibe Trio" images
        "curated_flights": [...],         # Pre-defined flight options
        "specialist_content": {
            "diving": [...],              # Diving activities with images
            "general": [...],             # General attractions
        },
    },
    "rome": {...},
    "chamonix": {...},
    "bali": {...},
    "patagonia": {...},
}
```

### CARRIER_MAP (Flight Sanitization)

```python
CARRIER_MAP = {
    "XX": {"name": "Emirates", "logo": "EK"},
    "BA": {"name": "British Airways", "logo": "BA"},
    # ...
}
```

Used by LogisticsNode to convert test carriers to real airline branding.
