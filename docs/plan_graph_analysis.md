# Plan Graph V2 Architecture

> **Source**: `backend/app/plan_graph_v2.py` > **Planner Package**: `backend/app/planner/` > **Prompt Files**: `backend/app/prompts/`

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
11. [Prompt File Mapping](#prompt-file-mapping)
12. [Streaming Architecture](#streaming-architecture)
13. [Tile Service Architecture](#tile-service-architecture)
14. [Booking Provider Interface](#booking-provider-interface-scaffolding)

---

## Architecture Overview

LangGraph-based conversational trip planning system with **6 nodes** (optimized from 19).

| Category              | Count | Description                             |
| --------------------- | ----- | --------------------------------------- |
| LLM-Powered Nodes     | 3     | IntentRouter, TripArchitect, Synthesizer |
| Domain Specialists    | 1     | VerticalSpecialist (diving/hiking/skiing) |
| Deterministic Nodes   | 1     | ConstraintGuard (pure Python validation) |
| Total Nodes           | 5     | Core graph nodes + entry routing        |

### Design Principles (V2)

1. **"Flights/Hotels are NOT Agents"** - They are data fetchers (TileService tool)
2. **"Diving IS an Agent"** - It requires domain logic (VerticalSpecialist)
3. **"Architect sees the whole picture"** - Avoids context fracture
4. **TripPlan is the SSoT** - Single Source of Truth for trip state
5. **LLM-Based Intent Classification** - No regex minefield, GPT-4o-mini classifies
6. **Panic Button** - Hard-coded reset commands bypass LLM entirely
7. **Constraint Injector Pattern** - Specialist runs BEFORE Architect calls tools

### Migration Summary

| Aspect | V1 | V2 |
|--------|----|----|
| Nodes | 19 | 6 |
| Prompts | 27 | ~10 |
| Intent Detection | Regex gates + precedence | LLM classification |
| Routing | GateEvaluator (13 gates) | Simple conditional edges |
| State | Fragmented trip_inputs | Unified TripPlan SSoT |
| Specialists | LLM nodes per domain | Single VerticalSpecialist |

---

## Package Structure

```
backend/app/planner/
├── __init__.py              # Facade exports (stable public API)
├── cache_access.py          # Cache utilities
├── hashing.py               # Stable hashing utilities
├── meta.py                  # Metadata helpers
├── meta_keys.py             # Metadata key constants
├── streaming.py             # Streaming infrastructure
├── telemetry.py             # Telemetry instrumentation
├── test_mode.py             # Test mode detection
├── node_utils.py            # Simple utilities for module-level imports
├── nodes_v2/                # V2 Node implementations
│   ├── __init__.py          # Node exports
│   ├── intent_router.py     # LLM-based intent classification
│   ├── trip_architect.py    # Core planning node (The Boss)
│   ├── vertical_specialist.py # Domain specialist (diving/hiking/skiing)
│   ├── constraint_guard.py  # Pure Python validation
│   └── synthesizer.py       # Unified response generation
├── state/
│   ├── __init__.py          # State exports
│   └── schemas_v2.py        # V2 state models (GraphStateV2, TripPlan)
└── cache/
    ├── __init__.py          # Cache exports
    ├── framework.py         # CacheNode ABC + all cache implementations
    └── compat.py            # Backward-compatible function signatures
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
│  IntentRouter (LLM - Fast: GPT-4o-mini)                                     │
│  ─────────────────────────────────────                                      │
│  LLM-based intent classification (no regex!)                                │
│  • Classifies: GREETING, RESET, or PLANNING                                 │
│  • Detects: specialist_hint (diving/hiking/skiing/cycling/boating)          │
│  • GREETING/RESET → Static response, skip to Synthesizer                    │
│  • PLANNING → Pass to Architect (with optional specialist)                  │
│  ~150 tokens, ~300ms                                                        │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │ GREETING/RESET          │ PLANNING                │ PLANNING
         │ (short_circuit)         │ (specialist detected)   │ (general)
         ▼                         ▼                         ▼
┌────────────────────┐  ┌─────────────────────────┐  ┌────────────────────────┐
│  → Synthesizer     │  │  VerticalSpecialist     │  │  → TripArchitect       │
│    (skip architect)│  │  (LLM - Expert)         │  │                        │
│                    │  │  ─────────────────────  │  │                        │
│  Returns static    │  │  Domain expert node     │  │                        │
│  response with     │  │  Topics: diving, hiking │  │                        │
│  suggested_replies │  │  skiing, cycling,       │  │                        │
│                    │  │  boating                │  │                        │
│                    │  │                         │  │                        │
│                    │  │  Returns:               │  │                        │
│                    │  │  • Constraints          │  │                        │
│                    │  │  • Content blocks       │  │                        │
│                    │  │  • Critique             │  │                        │
│                    │  │  • Enhancements         │  │                        │
└────────────────────┘  └───────────┬─────────────┘  └───────────┬────────────┘
                                    │                            │
                                    │                            │
                                    └─────────────┬──────────────┘
                                                  │
                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  TripArchitect (LLM - Smart)                                                │
│  ────────────────────────────                                               │
│  "The Boss" - General Agent in UI                                           │
│  • Manages TripPlan (SSoT)                                                  │
│  • Modes: pre_core (inspiration), missing_fields, planning                  │
│  • Calls fetch_travel_tiles tool when needed                                │
│  • Respects constraints from Specialist                                     │
│  • Extracts: destination, origin, dates from user text                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │ tiles or constraints        │ no validation needed
                    ▼                             │
┌────────────────────────────────────┐            │
│  ConstraintGuard (Python)          │            │
│  ────────────────────────────────  │            │
│  Pure Python validation (NO LLM)   │            │
│  • Budget: total < allocation      │            │
│  • Temporal: dates valid           │            │
│  • Geographic: landlocked diving   │            │
│  • Specialist: 24h surface interval│            │
│                                    │            │
│  Returns: violations[], has_blocking│           │
└───────────────┬────────────────────┘            │
                │                                 │
                └────────────────┬────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Synthesizer (LLM - Writer)                                                 │
│  ───────────────────────────                                                │
│  Unified response generation                                                │
│  • Consistent voice across all response types                               │
│  • Generates suggested_replies (always 3 chips)                             │
│  • Enriches content with Unsplash images                                    │
│  • Handles constraint warnings gracefully                                   │
│  • Templates: greeting, inspiration, planning                               │
│                                                                             │
│  Key Principle: "One voice, regardless of which agents contributed"         │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
                              ┌─────────┐
                              │   END   │
                              └─────────┘
```

---

## Complete Node Reference Table

### V2 Nodes

| Node | Type | Purpose | LLM Model | Max Tokens | Streaming |
|------|------|---------|-----------|------------|-----------|
| `intent_router` | LLM (Fast) | Intent classification | GPT-4o-mini | 150 | None |
| `trip_architect` | LLM (Smart) | Core planning, SSoT management | GPT-4 | Variable | Simulated |
| `vertical_specialist` | LLM (Expert) | Domain constraints + content | GPT-4 | Variable | Simulated |
| `constraint_guard` | Python | Validation (NO LLM) | N/A | N/A | None |
| `synthesizer` | LLM (Writer) | Response generation | GPT-4 | Variable | Simulated |

### Streaming Legend

| Symbol | Mode | Description |
|--------|------|-------------|
| None | `buffered:internal` | Internal node, no user-facing output |
| Simulated | `simulate_streaming` | Token-by-token delivery with 15-35ms delays |
| Real | `true_stream` | Real-time tokens from LLM API |

---

## Key Node Details

### IntentRouter

LLM-based intent classification using GPT-4o-mini.

| Classification | Trigger | Action |
|----------------|---------|--------|
| `GREETING` | "Hi", "Hello", "Thanks!" (no planning content) | Static response, skip architect |
| `RESET` | "Start over", "Reset", "Begin again" | Clear state, static response |
| `PLANNING` | Everything else (trip-related) | Pass to Architect |

**Critical Rules:**
- "Hi, I want to go to Paris" → PLANNING (has content!)
- "No, I prefer Rome" → PLANNING (negation with alternative)
- "Stop in Rome" → PLANNING (layover, not reset!)
- If unsure, default to PLANNING (let architect handle it)

**Specialist Detection:**
```python
SPECIALIST_KEYWORDS = {
    "diving": ["dive", "diving", "scuba", "snorkel", "reef", "padi", ...],
    "hiking": ["hike", "trek", "trail", "mountain", "summit", "alpine", ...],
    "skiing": ["ski", "snowboard", "slope", "powder", "piste", ...],
    "cycling": ["cycle", "bike", "bicycle", "mtb", "road bike", ...],
    "boating": ["sail", "boat", "yacht", "charter", "catamaran", ...],
}
```

### TripArchitect

"The Boss" - the General Agent in the UI.

| Mode | Trigger | Behavior |
|------|---------|----------|
| `pre_core` | No destination | Inspiration mode - ask leading questions |
| `missing_fields` | Has destination, missing dates | Trigger Setup Modal |
| `planning` | Core fields present | Build trip with tools |

**Extraction Logic:**
- Origin: Detects "from X to Y" pattern
- Destination: Detects "to X", "in X", "visit X" patterns
- Dates: Placeholder (uses real date parsing in production)

**Tool Usage:**
```python
# Only calls fetch_travel_tiles when:
# - Plan is ready (destination + dates)
# - User asked for booking options
# - Don't have fresh tiles already
```

### VerticalSpecialist

Domain expert that runs BEFORE Architect calls tools.

**Key Insight:** Returns BOTH constraints AND content.

| Output | Type | Example |
|--------|------|---------|
| `constraints` | SpecialistConstraint[] | "24h surface interval after diving" |
| `content_blocks` | ItineraryBlock[] | "Day 2: USAT Liberty Wreck" |
| `critique` | string | Review of current plan |
| `enhancements` | string[] | "Book dive shop in advance" |

**Domain Knowledge:**
- Diving: Flight buffers, certification requirements, top sites
- Hiking: Altitude acclimatization, proper footwear, trek recommendations
- Skiing: Snow conditions, guide requirements, resort suggestions

### ConstraintGuard

Pure Python deterministic validation. **NO LLM calls.**

| Constraint Type | Check | Severity |
|-----------------|-------|----------|
| Budget | Total cost < budget | blocking |
| Budget | Category cost < allocation | warning |
| Temporal | end_date > start_date | blocking |
| Temporal | Duration < 30 days | info |
| Geographic | Diving in landlocked country | blocking |
| Specialist | 24h surface interval | info |

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
1. Greeting - Welcome message
2. Inspiration - Pre-core destination exploration
3. Planning - Full planning mode with tiles/constraints

**Always includes:**
- `suggested_replies` (exactly 3 chips)
- Image enrichment via Unsplash
- Graceful constraint warnings

---

## State Models

### GraphStateV2

Unified state for the 6-node architecture.

```python
class GraphStateV2(BaseModel):
    # Chat history
    messages: List[BaseMessage]

    # The Single Source of Truth
    trip_plan: TripPlan

    # Intent classification
    intent: Optional[Literal["general", "booking", "specialist"]]

    # Specialist activation
    active_specialist: Optional[str]  # "diving", "hiking", etc.
    active_agent_id: Optional[str]    # For UI display

    # Tile inventory
    tiles: Dict[str, List[Dict]]  # {"flights": [], "hotels": [], "activities": []}

    # Constraint violations
    constraints_violated: List[str]

    # UI events
    ui_events: List[str]

    # Response state
    last_summary: Optional[str]
    suggested_replies: List[str]

    # Metadata
    metadata: Dict[str, Any]
```

### TripPlan (SSoT)

Single Source of Truth for the trip.

```python
class TripPlan(BaseModel):
    # Core fields
    destination: Optional[str]
    destinations: List[str]      # For multi-city
    origin: Optional[str]
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

    # Specialist content
    itinerary_blocks: List[ItineraryBlock]

    # Constraints from Specialist
    constraints: List[SpecialistConstraint]

    # Metadata
    trip_type: Optional[str]  # "diving", "hiking", etc.
    vibe: Optional[str]       # "adventure", "relaxation", etc.
```

### SpecialistConstraint

Constraint injected by VerticalSpecialist.

```python
class SpecialistConstraint(BaseModel):
    type: Literal["temporal", "safety", "equipment", "certification", "budget"]
    rule: str                    # e.g., "min_24h_buffer_after_dive"
    applies_to: Optional[str]    # "flights", "activities", etc.
    parameters: Dict[str, Any]   # e.g., {"max_depth_without_cert": 18}
    reason: Optional[str]        # Human-readable explanation
```

### ItineraryBlock

Content block from VerticalSpecialist.

```python
class ItineraryBlock(BaseModel):
    day: int
    title: str
    description: str
    type: Literal["activity", "meal", "transport", "rest", "experience"]
    image_url: Optional[str]
    duration_hours: Optional[float]
    location: Optional[str]
    source_specialist: Optional[str]  # "diving", "hiking", etc.
    skill_level: Optional[str]        # "beginner", "intermediate", "advanced"
    safety_notes: Optional[str]
    tile_id: Optional[str]            # If bookable
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

```python
def route_after_router(state: GraphStateV2) -> Literal["specialist", "architect", "synthesizer"]:
    # GREETING/RESET short-circuits skip to synthesizer
    if state.metadata.get("short_circuit_response"):
        return "synthesizer"

    # Specialist detected → run specialist first
    if state.active_specialist:
        return "specialist"

    # Default → architect
    return "architect"
```

### Should Run Guard

```python
def should_run_guard(state: GraphStateV2) -> Literal["guard", "synthesizer"]:
    # Run guard if we have tiles or constraints to validate
    if state.tiles or state.trip_plan.constraints:
        return "guard"
    return "synthesizer"
```

---

## Specialist Domain Knowledge

### Diving

**Constraints:**
| Rule | Type | Reason |
|------|------|--------|
| `min_24h_buffer_after_dive` | temporal | Decompression sickness risk |
| `min_18h_surface_interval` | temporal | Minimum before single dive |
| `advanced_cert_required_for_deep` | safety | Dives below 18m need AOW |

**Top Destinations:**
- Bali: USAT Liberty Wreck, Manta Point Nusa Penida, Crystal Bay
- Maldives: Hanifaru Bay, Maaya Thila
- Egypt: SS Thistlegorm, Ras Mohammed

### Hiking

**Constraints:**
| Rule | Type | Reason |
|------|------|--------|
| `altitude_acclimatization` | safety | Max 500m/day above 3000m |
| `proper_footwear_required` | equipment | Hiking boots for mountain trails |

**Top Destinations:**
- Patagonia: Torres del Paine W Trek, Fitz Roy Summit Approach
- Nepal: Everest Base Camp, Annapurna Circuit

### Skiing

**Constraints:**
| Rule | Type | Reason |
|------|------|--------|
| `check_snow_conditions` | temporal | Verify avalanche reports |
| `guide_required_offpiste` | certification | Certified guide for off-piste |

**Top Destinations:**
- Chamonix: Vallee Blanche, Les Grands Montets
- Japan: Niseko Powder, Hakuba Valley

---

## Constraint Validation

### Validation Categories

| Category | Check | Severity |
|----------|-------|----------|
| Budget | `total_cost > budget` | blocking |
| Budget | `category_cost > allocation` | warning |
| Temporal | `end_date < start_date` | blocking |
| Temporal | `duration > 30 days` | info |
| Temporal | `duration < 1 day` | warning |
| Geographic | Diving in landlocked country | blocking |
| Geographic | Beach in landlocked country | blocking |
| Specialist | 24h surface interval (diving) | info |
| Specialist | Altitude warning (hiking) | info |
| Specialist | Certification required | warning |

### Landlocked Countries (Partial List)

Switzerland, Austria, Czech Republic, Hungary, Nepal, Mongolia, Bolivia, Rwanda, Ethiopia, and more.

---

## Caching Architecture

### Cache Implementations

| Cache | Class | Max Size | TTL | Key Components | Purpose |
|-------|-------|----------|-----|----------------|---------|
| `ResponseCache` | `CacheNode` | 200 | 3600s | node_name, core_fields_hash, follow_up_hash | Reuse responses |
| `TileCache` | `CacheNode` | 100 | 300s | session_id, tile_type, query_hash | Cache tile API results |

### Cache Invalidation Triggers

| Trigger | Caches Invalidated |
|---------|-------------------|
| Core fields change | response, tile |
| `end_date` change | tile |
| `adults/children` change | tile |
| Strategy topic switch | response |
| Session timeout | All |

### Validation Cache (Origin/Destination Verification)

Located in `backend/app/validation.py`, stores LLM-verified place names.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `validation_cache_size` | 5000 | Max entries before LRU eviction |
| `validation_cache_ttl` | 604800 (7 days) | Time before entries expire |

**Cache Layers:**

| Cache | Purpose | TTL |
|-------|---------|-----|
| `_validation_cache` | Positive validation results | 7 days |
| `_negative_cache` | Invalid locations | 15 minutes |
| `_split_cache` | Multi-destination splits | 7 days |

### Image Cache (Unsplash)

Two-tier cache for destination images.

**Tier 1: In-Memory Cache**
- Storage: Python dict `_memory_cache`
- Key format: `"destination:variant"`
- Max variants: 6 per destination

**Tier 2: Database Cache**
- Table: `unsplash_image_cache`
- TTL: Permanent
- Primary Key: `(destination, variant)`

**Lookup Order:**
1. In-memory cache (fastest)
2. Database cache (persistent)
3. Unsplash API (fresh fetch)
4. Picsum fallback (deterministic seed-based)

---

## Prompt File Mapping

### V2 Prompts

| File | Used By | Purpose |
|------|---------|---------|
| `architect_system_prompt.txt` | TripArchitect | Core planning instructions |
| `specialists/diving.txt` | VerticalSpecialist | Diving domain knowledge |
| `specialists/hiking.txt` | VerticalSpecialist | Hiking domain knowledge |
| `specialists/skiing.txt` | VerticalSpecialist | Skiing domain knowledge |
| `synthesizer.txt` | Synthesizer | Response generation |

### Shared Includes

| File | Purpose |
|------|---------|
| `_json_output.txt` | JSON output format rules |
| `_never_invent.txt` | Never invent data rule |
| `_markdown_rules.txt` | Markdown formatting rules |

---

## Streaming Architecture

### Current Implementation: Simulated Streaming

V2 uses simulated streaming for consistent UX. True LLM streaming planned for future iteration.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STREAMING FLOW                                                             │
│  ──────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  1. User sends message                                                       │
│  2. run_turn_streaming() runs full graph                                     │
│  3. Result captured in result_state.last_summary                             │
│  4. Response emitted as single "token" event                                 │
│  5. "complete" event with full result                                        │
│                                                                              │
│  Future: True LLM streaming via StreamingContext                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Streaming Events

| Event Type | Data | Description |
|------------|------|-------------|
| `node_status` | `{node, status}` | Node progress tracking |
| `token` | `string` | Response text |
| `complete` | `{...result}` | Full V1-compatible result |
| `error` | `{message}` | Error information |

### Streaming Parameters

```python
STREAMING_PARAMS = {
    "base_delay_ms": 15,   # Minimum delay between tokens
    "max_delay_ms": 35,    # Maximum delay between tokens
    "jitter_ms": 8,        # Random jitter range
    "chunk_size": 1,       # Single tokens
}
```

---

## Token Savings Summary

| Optimization | Tokens Saved | Frequency |
|--------------|--------------|-----------|
| GREETING/RESET short-circuit | ~800-1500 | ~20% of turns |
| Specialist caching | ~500-1000 | ~30% of turns |
| Template responses | ~500-1500 | ~40% of turns |
| Panic button bypass | ~1000-2000 | ~5% of turns |

---

## Key Exports

| Module | Exports |
|--------|---------|
| `planner` | `run_turn`, `run_turn_streaming`, `GraphState`, `TripInputs` |
| `planner.state` | `GraphStateV2`, `TripPlan`, `TripSegment`, `ItineraryBlock`, `SpecialistConstraint`, `SpecialistOutput`, `UIEvent`, `MissingFieldsResponse`, `SynthesizerOutput` |
| `planner.hashing` | `stable_hash`, `stable_hash_int`, `stable_hash_index`, `make_cache_key` |
| `planner.telemetry` | `TraceEnvelope`, `create_envelope`, `emit_event`, `emit_node_start`, `emit_node_end` |
| `planner.nodes_v2` | `intent_router`, `trip_architect`, `vertical_specialist`, `constraint_guard`, `synthesizer` |

---

## Admin Cache Management Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/admin/clear-validation-cache` | POST | Clear validation caches |
| `/v1/admin/fresh-start` | POST | Clear validation + response caches |
| `/v1/admin/clear-all-checkpoints` | POST | Clear ALL LangGraph checkpoints |
| `/v1/admin/clear-all-caches` | POST | Comprehensive clear of ALL caches |

---

## Tile Service Architecture

### Tile Refresh Endpoint

```
POST /v1/tiles/refresh
```

| Field | Type | Description |
|-------|------|-------------|
| `branch_id` | string | Branch to refresh tiles for |
| `verticals` | string[] | Optional: ["hotel", "flight", "activity"] |

### Provider Architecture

```
tile_service/
├── __init__.py           # Exports: search_tiles + booking types
├── models.py             # SearchContext, TileSearchRequest
├── service.py            # search_tiles() orchestrator
├── provider_base.py      # Provider ABC + BookableProvider ABC
└── mock_provider.py      # Mock providers for development
```

### Settings-Aware Tile Filtering

| Setting Type | Filter Applied |
|--------------|----------------|
| `hotel_settings.min_stars` | `rating >= min_stars` |
| `hotel_settings.amenities` | Must include all requested amenities |
| `flight_settings.cabin_class` | Filter by cabin type |
| `flight_settings.direct_only` | Exclude layover flights |
| `activity_settings.categories` | Filter by activity type |

---

## Booking Provider Interface (Scaffolding)

> **Status:** Interface defined, real provider implementation deferred until API access.

### Design Decision

**Booking = REST endpoints, NOT LangGraph nodes**

| Reason | Detail |
|--------|--------|
| Explicit consent | Financial transactions need user confirmation |
| No LLM reasoning | Simple CRUD operations |
| Audit trail | Different error handling requirements |
| PCI compliance | Payment data handling considerations |

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

| Status | Description |
|--------|-------------|
| `INITIATED` | Booking request received |
| `PENDING_PAYMENT` | Awaiting payment |
| `HOLD` | Inventory temporarily reserved |
| `CONFIRMED` | Booking complete, confirmation code issued |
| `FAILED` | Payment declined or inventory unavailable |
| `CANCELLED` | User or system cancelled |
| `EXPIRED` | Hold/session expired |

### Key Types

| Type | Location | Purpose |
|------|----------|---------|
| `BookableProvider` | `provider_base.py` | ABC for bookable providers |
| `BookingSession` | `provider_base.py` | In-progress booking state |
| `BookingConfirmation` | `provider_base.py` | Completed booking details |
| `TravelerInfo` | `provider_base.py` | Traveler data for booking |
| `BookingError` | `provider_base.py` | Structured error handling |

---

## UI Events

Events emitted to frontend for UI updates.

| Event | Trigger | Frontend Action |
|-------|---------|-----------------|
| `UI_RESET` | RESET intent or panic button | Clear chat, reset state |
| `SPECIALIST_ACTIVE` | Specialist detected | Show specialist badge |
| `SPECIALIST_DONE` | Specialist finished | Update UI |
| `TILES_LOADING` | Fetching tiles | Show loading state |
| `TILES_READY` | Tiles fetched | Display tile cards |
| `CONSTRAINT_VIOLATED` | Validation failed | Show warning banner |
| `MISSING_FIELDS` | Core fields missing | Trigger Setup Modal |
| `PLAN_READY` | Plan complete | Enable booking |

---

## V1-Compatible Interface

V2 exports maintain backward compatibility with main.py.

```python
# These are re-exported from plan_graph_v2.py
from app.planner import (
    run_turn,              # Main entry point
    run_turn_streaming,    # SSE streaming entry point
    GraphState,            # Alias for GraphStateV2
    TripInputs,            # V1-compatible input type
    get_planner_debug_info,
    validate_template_coverage,
    clear_all_caches,
    # ... and more
)
```

### Result Format

```python
{
    "assistant_message": "...",
    "suggested_responses": ["...", "...", "..."],
    "session_state": {...},
    "branches": [],  # V2 doesn't use branches
    "trip_inputs": {...},
    "ready_to_generate": bool,
    "errors": [...],
}
```
