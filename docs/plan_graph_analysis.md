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
11. [Prompt File Mapping](#prompt-file-mapping)
12. [Streaming Architecture](#streaming-architecture)
13. [Tile Service Architecture](#tile-service-architecture)
14. [Booking Provider Interface](#booking-provider-interface-scaffolding)

---

## Architecture Overview

LangGraph-based conversational trip planning system with **7 nodes**.

| Category              | Count | Description                             |
| --------------------- | ----- | --------------------------------------- |
| LLM-Powered Nodes     | 4     | IntentRouter, TripArchitect, VerticalSpecialist, Synthesizer |
| Domain Specialists    | 1     | LocalExpert (city logistics and tips) |
| Data Fetchers         | 1     | LogisticsNode (flight fetching + safety logic) |
| Deterministic Nodes   | 1     | ConstraintGuard (pure Python validation) |
| **Total Nodes**       | **7** | Core graph nodes                        |

### Design Principles

1. **"Flights/Hotels are NOT Agents"** - They are data fetchers (LogisticsNode + TileService)
2. **"Diving IS an Agent"** - It requires domain logic (VerticalSpecialist)
3. **"Architect sees the whole picture"** - Avoids context fracture
4. **TripPlan is the SSoT** - Single Source of Truth for trip state
5. **LLM-Based Intent Classification** - No regex minefield, GPT-4o-mini classifies
6. **Panic Button** - Hard-coded reset commands bypass LLM entirely
7. **Constraint Injector Pattern** - Specialist runs BEFORE Architect calls tools
8. **Local Expert Fallback** - Generic trips always have content via LocalExpert
9. **Auto-Fix Loop** - ConstraintGuard can loop back to Architect once to self-correct

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
├── nodes/                   # Node implementations
│   ├── __init__.py          # Node exports
│   ├── intent_router.py     # LLM-based intent classification
│   ├── trip_architect.py    # Core planning node (The Boss)
│   ├── vertical_specialist.py # Domain specialist (diving/hiking/skiing)
│   ├── local_expert.py      # City logistics concierge (NEW)
│   ├── logistics_node.py    # Flight fetching + safety logic (NEW)
│   ├── constraint_guard.py  # Pure Python validation
│   └── synthesizer.py       # Unified response generation
├── state/
│   ├── __init__.py          # State exports
│   └── schemas.py           # State models (GraphState, TripPlan)
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
│  • PLANNING + no specialist → LocalExpert (city logistics)                  │
│  • PLANNING + specialist → VerticalSpecialist                               │
│  ~150 tokens, ~300ms                                                        │
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
│  response with     │  │  Topics: diving, hiking │  │  • Booking windows     │
│  suggested_replies │  │  skiing, cycling,       │  │  • Transit passes      │
│                    │  │  boating                │  │  • Cultural tips       │
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
│  Fetches and sanitizes flight data                                          │
│  1. Check for curated flights (hero destinations: Dubai, Rome, Chamonix)    │
│  2. Fetch from Amadeus API if not curated                                   │
│  3. Fallback to demo backup if API fails                                    │
│  4. Sanitize carrier names (XX → Emirates)                                  │
│  5. Apply 24h no-fly safety logic if diving constraints exist               │
│                                                                             │
│  Outputs to: state.tiles["flights"], state.metadata["flight_options"]       │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  TripArchitect (LLM - Smart)                                                │
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
│  Pure Python validation (NO LLM)   │            │
│  • Budget: total < allocation      │            │
│  • Temporal: dates valid           │            │
│  • Geographic: landlocked diving   │            │
│  • Specialist: 24h surface interval│            │
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

### Nodes

| Node | Type | Purpose | LLM Model | Max Tokens | Streaming |
|------|------|---------|-----------|------------|-----------|
| `router` (IntentRouter) | LLM (Fast) | Intent classification | GPT-4o-mini | 150 | None |
| `architect` (TripArchitect) | LLM (Smart) | Core planning, SSoT management | gpt-4o | Variable | Simulated |
| `specialist` (VerticalSpecialist) | LLM (Expert) | Domain constraints + content | gpt-4o | Variable | Simulated |
| `local_expert` (LocalExpert) | LLM/Static | City logistics concierge | GPT-4o-mini* | Variable | None |
| `logistics` (LogisticsNode) | Data Fetcher | Flight fetching + safety | N/A | N/A | None |
| `guard` (ConstraintGuard) | Python | Validation (NO LLM) | N/A | N/A | None |
| `synthesizer` (Synthesizer) | LLM (Writer) | Response generation | gpt-4o | Variable | True (astream_events) |

*LocalExpert uses static knowledge by default; LLM mode controlled by `LOCAL_EXPERT_USE_LLM` env var.

### NODE_STATUS_CONFIG (UI Progress Labels)

| Node | Label | Icon | Estimated Duration |
|------|-------|------|-------------------|
| `router` | "Reading your message..." | brain | 300ms |
| `architect` | "Understanding your request..." | building | 800ms |
| `specialist` | "Consulting expert..." | star | 1000ms |
| `local_expert` | "Consulting local expert..." | building | 800ms |
| `logistics` | "Fetching flight options..." | plane | 2000ms |
| `guard` | "Checking constraints..." | shield | 100ms |
| `synthesizer` | "Writing response..." | pen | 1500ms |

### Streaming Legend

| Symbol | Mode | Description |
|--------|------|-------------|
| None | `buffered:internal` | Internal node, no user-facing output |
| Simulated | `simulate_streaming` | Token-by-token delivery with 15-35ms delays |
| True | `astream_events` | Real-time tokens from LLM API via LangGraph |

---

## Key Node Details

### IntentRouter

LLM-based intent classification using GPT-4o-mini.

| Classification | Trigger | Action |
|----------------|---------|--------|
| `GREETING` | "Hi", "Hello", "Thanks!" (no planning content) | Static response, skip architect |
| `RESET` | "Start over", "Reset", "Begin again" | Clear state, static response |
| `PLANNING` | Everything else (trip-related) | Pass to Specialist or LocalExpert |

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

**Routing Decision:**
- Specialist detected → `state.active_specialist = "diving"` → VerticalSpecialist
- No specialist → `state.active_specialist = "local_expert"` → LocalExpert

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

### LocalExpert (NEW)

The "Concierge" agent for city trips - ensures the Agent Feed is never empty.

**Activation:** Default when no niche specialist (diving/hiking/skiing) is detected.

**Provides:**
- Opening hours and closed days (e.g., "Louvre closed on Tuesdays")
- Booking lead times for popular attractions
- Transit passes and efficiency tips (e.g., "Paris Museum Pass saves €40+")
- Cultural considerations (dining hours, tipping, dress codes)

**Static Knowledge Destinations:**
- Dubai, Paris, Rome, London, Amsterdam, Tokyo, New York

**Output Format:**
```python
{
    "constraints": [
        {"type": "opening_hours", "description": "...", "severity": "warning"},
        {"type": "booking_window", "description": "...", "severity": "info"},
    ],
    "recommendations": [
        {"title": "Paris Museum Pass", "description": "...", "logic_hook": "Saves €40+..."},
    ]
}
```

**Reality Check:** Includes a pre-generation check to return EMPTY recommendations if the destination is fictional or unrecognized (e.g., "Atlantis", "Mordor"). This prevents hallucination of non-existent transit systems or opening hours.

### LogisticsNode (NEW)

Centralized flight fetching with safety logic. Runs AFTER Specialist/LocalExpert, BEFORE Architect.

**Data Sources (Priority Order):**
1. **Curated Flights**: Hero destinations (Dubai, Rome, Chamonix) with hand-picked carriers
2. **Amadeus API**: Live flight search for non-curated destinations
3. **Demo Backup**: Guaranteed fallback data if API fails

**Safety Logic (Diving Integration):**
- Detects diving constraints from VerticalSpecialist
- Applies 24h no-fly surface interval calculation
- Tags flights as safe/unsafe with `logic_hook` explanation

**Carrier Sanitization:**
- Maps test carrier codes to real airlines (XX → Emirates)
- Uses `CARRIER_MAP` from `demo_curation.py`

**Output:**
- `state.tiles["flights"]` - Flight tiles for frontend display
- `state.metadata["flight_options"]` - Backwards compatibility

### ConstraintGuard

Pure Python deterministic validation. **NO LLM calls.**

| Constraint Type | Check | Severity |
|-----------------|-------|----------|
| Route | `origin == destination` | blocking |
| Route | `validate_place_exists(dest)` returns false | blocking |
| Budget | Total cost < budget | blocking |
| Budget | Category cost < allocation | warning |
| Temporal | end_date > start_date | blocking |
| Temporal | Duration < 30 days | info |
| Geographic | Diving in landlocked country | blocking |
| Specialist | 24h surface interval | info |

**Auto-Fix Loop with Route Error Short-Circuit:**
```python
def route_after_guard(state: GraphState) -> Literal["architect", "synthesizer"]:
    has_blocking = state.metadata.get("has_blocking_violations", False)
    retry_count = state.guard_retry_count
    violations = state.metadata.get("constraint_violations", [])

    # 1. ROUTE ERROR SHORT-CIRCUIT (Logic Guards)
    # User Intent errors (Rome->Rome, Atlantis) are UNFIXABLE by the Architect.
    # They must bypass the auto-fix loop and go straight to rejection.
    if any(v.get("category") == "route" for v in violations):
        return "synthesizer"  # Triggers Amber "REJECTED" receipt

    # 2. OPTIMIZATION AUTO-FIX
    # Budget/Schedule errors can be self-corrected by the Architect.
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
1. Greeting - Welcome message
2. Inspiration - Pre-core destination exploration
3. Planning - Full planning mode with tiles/constraints

**Always includes:**
- `suggested_replies` (exactly 3 chips)
- Image enrichment via Unsplash
- Graceful constraint warnings

**Logic Guard Voice:** When a blocking route violation is detected (`category="route"`), the Synthesizer shifts to **"Architectural Safety Mode"**. It refuses to generate enthusiasm or itinerary content and instead provides a firm, corrective statement (e.g., "I cannot generate a route where Origin and Destination are identical.").

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
```

### TripPlan (SSoT)

Single Source of Truth for the trip.

```python
class TripPlan(BaseModel):
    # Core fields
    destination: Optional[str]
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
def route_after_router(state: GraphState) -> Literal["specialist", "local_expert", "architect", "synthesizer"]:
    # GREETING/RESET short-circuits skip to synthesizer
    if state.metadata.get("short_circuit_response"):
        return "synthesizer"

    # Specialist detected → run specialist first
    if state.active_specialist:
        if state.active_specialist == "local_expert":
            return "local_expert"
        return "specialist"

    # Default → architect (shouldn't happen if router sets local_expert)
    return "architect"
```

### Route After Specialist

```python
def route_after_specialist(state: GraphState):
    # 1. Recursion: If pending specialists exist, run the next one
    if state.pending_specialists:
        return "specialist"  # (or "local_expert")

    # 2. Speculative Intent: Skip tools, go to Synthesizer (Preload)
    if state.intent == "speculative":
        return "synthesizer"

    # 3. Booking Intent: Fetch tiles via Logistics
    if state.intent == "booking" or state.is_generate_trigger:
        return "logistics"

    # 4. General Intent: Extract fields in Architect (skip tiles)
    return "architect"
```

### Graph Edge Flow

```
Entry: router

router → specialist/local_expert/architect/synthesizer (conditional)
specialist → specialist (recursion) OR logistics (booking) OR architect (general) OR synthesizer (speculative)
local_expert → specialist (recursion) OR logistics (booking) OR architect (general) OR synthesizer (speculative)
logistics → architect (always)
architect → guard/synthesizer (conditional)
guard → architect/synthesizer (conditional - auto-fix loop)
synthesizer → END
```

### Should Run Guard

```python
def should_run_guard(state: GraphState) -> Literal["guard", "synthesizer"]:
    # Run guard if we have tiles or constraints to validate
    if state.tiles or state.trip_plan.constraints:
        return "guard"
    return "synthesizer"
```

### Route After Guard (Auto-Fix vs. Rejection)

```python
def route_after_guard(state: GraphState) -> Literal["architect", "synthesizer"]:
    has_blocking = state.metadata.get("has_blocking_violations", False)
    retry_count = state.guard_retry_count
    violations = state.metadata.get("constraint_violations", [])

    # 1. ROUTE ERROR SHORT-CIRCUIT (Logic Guards)
    # User Intent errors (Rome->Rome, Atlantis) are UNFIXABLE by the Architect.
    # They must bypass the auto-fix loop and go straight to rejection.
    if any(v.get("category") == "route" for v in violations):
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
- Dubai: Deep Dive Dubai, Jumeirah Artificial Reef, MV Dara Wreck

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

**Seasonality Guard:** Checks hemisphere/month alignment before generating content. Northern Hemisphere (Alps, Rockies, Japan) is December-April; Southern Hemisphere (NZ, Chile, Argentina) is June-September. Out-of-season requests (e.g., "Alps in July") are flagged as INFEASIBLE unless glacier skiing is specified.

---

## Constraint Validation

### Validation Categories

| Category | Check | Severity | Note |
|----------|-------|----------|------|
| **Route** | `origin == destination` | **blocking** | Triggers `SAME_CITY_ERROR` |
| **Route** | `validate_place_exists(dest)` | **blocking** | Triggers `UNKNOWN_DESTINATION_ERROR` |
| Budget | `total_cost > budget` | blocking | Auto-fixable |
| Budget | `category_cost > allocation` | warning | Auto-fixable |
| Temporal | `end_date < start_date` | blocking | Auto-fixable |
| Temporal | `duration > 30 days` | info | |
| Temporal | `duration < 1 day` | warning | |
| Seasonal | Hiking in Swiss Alps in winter | warning | |
| Seasonal | Skiing in summer months | warning | |
| Geographic | Diving in landlocked country | blocking | |
| Geographic | Beach in landlocked country | blocking | |
| Specialist | 24h surface interval (diving) | info | |
| Specialist | Altitude warning (hiking) | info | |
| Specialist | Certification required | warning | |

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

### Prompts

```
backend/app/prompts/
├── architect_system_prompt.txt    # TripArchitect - core planning instructions
├── synthesizer.txt                # Synthesizer - response generation
├── local_expert.txt               # LocalExpert - city logistics prompt
├── specialists/
│   ├── diving.txt                 # VerticalSpecialist - diving domain
│   ├── hiking.txt                 # VerticalSpecialist - hiking domain
│   ├── skiing.txt                 # VerticalSpecialist - skiing domain
│   └── local_expert.txt           # Alternative local expert prompt
├── _strategy_base.txt             # Shared strategy generation base
├── _scope_specialist.txt          # Specialist scope boundaries
├── _json_output.txt               # JSON output format rules
├── _never_invent.txt              # Never invent data rule
└── _markdown_rules.txt            # Markdown formatting rules
```

### Prompt Purpose Summary

| File | Used By | Purpose |
|------|---------|---------|
| `architect_system_prompt.txt` | TripArchitect | Core planning instructions, SSoT management |
| `synthesizer.txt` | Synthesizer | Response generation, voice consistency |
| `local_expert.txt` | LocalExpert | City logistics prompt (if LLM enabled) |
| `specialists/diving.txt` | VerticalSpecialist | Diving domain knowledge |
| `specialists/hiking.txt` | VerticalSpecialist | Hiking domain knowledge |
| `specialists/skiing.txt` | VerticalSpecialist | Skiing domain knowledge |

### Shared Includes

| File | Purpose |
|------|---------|
| `_strategy_base.txt` | Base template for strategy section generation |
| `_scope_specialist.txt` | Defines specialist responsibility boundaries |
| `_json_output.txt` | JSON output format rules |
| `_never_invent.txt` | Never invent data rule |
| `_markdown_rules.txt` | Markdown formatting rules |

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

| Event Type | Data | Description |
|------------|------|-------------|
| `node_status` | `{node, status, label, icon_key}` | Node progress tracking |
| `logic_reveal` | `{node, label, status}` | Routing decisions for Logic Terminal (e.g., "ROUTING: DIVING") |
| `token` | `string` | Response text (from Synthesizer LLM) |
| `complete` | `{...result}` | Full result object |
| `error` | `{message}` | Error information |

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

| Optimization | Tokens Saved | Frequency |
|--------------|--------------|-----------|
| GREETING/RESET short-circuit | ~800-1500 | ~20% of turns |
| Specialist caching | ~500-1000 | ~30% of turns |
| Template responses | ~500-1500 | ~40% of turns |
| Panic button bypass | ~1000-2000 | ~5% of turns |
| LocalExpert static knowledge | ~300-800 | ~50% of turns |

---

## Key Exports

| Module | Exports |
|--------|---------|
| `planner` | `run_turn`, `run_turn_streaming`, `GraphState`, `TripInputs` |
| `planner.state` | `GraphState`, `TripPlan`, `TripSegment`, `ItineraryBlock`, `SpecialistConstraint`, `SpecialistOutput`, `UIEvent`, `MissingFieldsResponse`, `SynthesizerOutput` |
| `planner.hashing` | `stable_hash`, `stable_hash_int`, `stable_hash_index`, `make_cache_key` |
| `planner.telemetry` | `TraceEnvelope`, `create_envelope`, `emit_event`, `emit_node_start`, `emit_node_end` |
| `planner.nodes` | `intent_router`, `trip_architect`, `vertical_specialist`, `local_expert`, `logistics_node`, `constraint_guard`, `synthesizer` |

---

## Admin Cache Management Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/clear-validation-cache` | POST | Clear validation caches |
| `/api/admin/fresh-start` | POST | Clear validation + response caches |
| `/api/admin/clear-all-checkpoints` | POST | Clear ALL LangGraph checkpoints |
| `/api/admin/clear-all-caches` | POST | Comprehensive clear of ALL caches |

---

## Tile Service Architecture

### Tile Refresh Endpoint

```
POST /api/tiles/refresh
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
├── mock_provider.py      # Mock providers for development
├── amadeus_provider.py   # Amadeus API integration
└── curated_provider.py   # Curated content provider
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

## Public Interface

Planner exports the stable public API.

```python
# These are re-exported from plan_graph.py
from app.planner import (
    run_turn,              # Main entry point
    run_turn_streaming,    # SSE streaming entry point
    GraphState,            # State type
    TripInputs,            # Input type
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
    "branches": [],  # Document branches
    "trip_inputs": {...},
    "ready_to_generate": bool,
    "errors": [...],
    "document": {
        "plan_view_state": "S0_BOOTSTRAP" | "S2_STRATEGY_READY",
        "tiles": {...},           # Flattened ID-based map
        "strategy_sections": [...], # Agent cards data
    },
}
```

### Plan View States

| State | Description |
|-------|-------------|
| `S0_BOOTSTRAP` | Show "Finish setup" checklist. CTA enabled when dest+dates set. |
| `S2_STRATEGY_READY` | Tiles loaded. Show strategy/tiles. |
| `S3_*` | Itinerary states (handled by expand-itinerary endpoint) |

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
