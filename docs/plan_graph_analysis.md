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
| Domain Specialists    | 1     | LocalExpert (static knowledge, no LLM) |
| Data Fetchers         | 1     | LogisticsNode (flight fetching + safety logic) |
| Deterministic Nodes   | 1     | ConstraintGuard (pure Python validation) |
| **Total Nodes**       | **7** | Core graph nodes                        |

> **Note:** `ItineraryBuilder` is a pure Python **service** (not a LangGraph node). It's called from the `/api/expand-itinerary` endpoint, preserving the 7-node architecture.

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
│  • EXPLORATION → Generic Q&A using Local Expert knowledge (no LLM)          │
│  • SOFT_TRANSITION → Routes to PLANNING when dates OR activities provided   │
│  • PLANNING + no specialist → LocalExpert (city logistics)                  │
│  • PLANNING + specialist → VerticalSpecialist                               │
│  ~150 tokens, ~300ms (0 tokens for exploration mode)                        │
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
│  Fetches and sanitizes tile data (flights, hotels, activities)              │
│  1. Check for curated destination (Dubai, Rome, Chamonix)                   │
│     → CuratedProvider for hotels/activities                                 │
│  2. Fallback to MockProviders for non-curated destinations                  │
│  3. Curated/Demo flights with carrier sanitization (XX → Emirates)          │
│  4. Apply 24h no-fly safety logic if diving constraints exist               │
│                                                                             │
│  Outputs to: state.tiles["flights"], ["hotels"], ["activities"]             │
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

| Node | Type | Purpose | LLM Model | Max Tokens | Streaming |
|------|------|---------|-----------|------------|-----------|
| `router` (IntentRouter) | LLM (Fast) | Intent classification | GPT-4o-mini | 150 | None |
| `architect` (TripArchitect) | LLM (Smart) | Core planning, SSoT management | gpt-4o | Variable | Simulated |
| `specialist` (VerticalSpecialist) | LLM (Expert) | Domain constraints + content | gpt-4o | Variable | Simulated |
| `local_expert` (LocalExpert) | Static Dict | City logistics concierge | N/A (static) | N/A | None |
| `logistics` (LogisticsNode) | Data Fetcher | Flight fetching + safety | N/A | N/A | None |
| `guard` (ConstraintGuard) | Python | Validation (NO LLM) | N/A | N/A | None |
| `synthesizer` (Synthesizer) | LLM (Writer) | Response generation | gpt-4o | Variable | True (astream_events) |

*LocalExpert uses static knowledge from `LOCAL_EXPERT_KNOWLEDGE` dictionary. No LLM calls.

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

LLM-based intent classification AND field extraction using GPT-4o-mini with Pydantic structured output.

| Classification | Trigger | Action |
|----------------|---------|--------|
| `GREETING` | "Hi", "Hello", "Thanks!" (no planning content) | Static response, skip architect |
| `RESET` | "Start over", "Reset", "Begin again" | Clear state, static response |
| `PLANNING` | Everything else (trip-related) | Extract fields → Pass to Specialist or LocalExpert |

**Critical Rules:**
- "Hi, I want to go to Paris" → PLANNING (has content!)
- "No, I prefer Rome" → PLANNING (negation with alternative)
- "Stop in Rome" → PLANNING (layover, not reset!)
- If unsure, default to PLANNING (let architect handle it)

**Structured Output Extraction (P0 Fix):**

When `has_dates_in_message` is detected (via regex), the Router calls `_classify_and_extract_with_llm()` which:
1. Uses `llm.with_structured_output(RouterOutput)` for guaranteed schema extraction
2. Extracts dates, destination, origin, travelers, budget in ONE call
3. Populates `state.trip_plan` immediately via `_populate_trip_plan_from_router_output()`
4. Sets `router_extracted_fields = True` flag for TripArchitect to skip duplicate extraction

**Date Indicator Detection:**
```python
DATE_INDICATORS = [
    r"\b(january|february|march|...)\b",  # Month names
    r"\b(next week|next month|this weekend|tomorrow)\b",  # Relative dates
    r"\b\d{1,2}[/-]\d{1,2}\b",  # Numeric patterns
]
```

This fixes the bug where users said "I want to go diving March 1-8" but were asked for dates again.

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

### LocalExpert

The "Concierge" node for city trips - ensures the Agent Feed is never empty. Uses **static knowledge** (no LLM calls).

**Activation:** Default when no niche specialist (diving/hiking/skiing) is detected. Also runs first in multi-specialist flows (Trip DNA anchor).

**Implementation:** Pure dictionary lookup from `LOCAL_EXPERT_KNOWLEDGE`:
```python
LOCAL_EXPERT_KNOWLEDGE = {
    "bali": LocalExpertKnowledge(...),
    "dubai": LocalExpertKnowledge(...),
    "paris": LocalExpertKnowledge(...),
    # ~10 destinations with comprehensive data
}

def local_expert(state):
    knowledge = LOCAL_EXPERT_KNOWLEDGE.get(destination.lower())
    # No LLM call - returns static data directly
```

**Provides:**
- Opening hours and closed days (e.g., "Louvre closed on Tuesdays")
- Booking lead times for popular attractions
- Transit passes and efficiency tips (e.g., "Paris Museum Pass saves €40+")
- Cultural considerations (dining hours, tipping, dress codes)
- Seasonality information
- Safety and health tips

**Static Knowledge Destinations:**
- Bali, Dubai, Paris, Rome, London, Amsterdam, Tokyo, New York, Thailand

**Output Format (Pydantic Schema for data storage, NOT LLM extraction):**
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
    constraints: List[LocalConstraint]
    recommendations: List[LocalRecommendation]
```

**Note:** LocalExpert uses Pydantic for **data storage** (structured knowledge), not for LLM extraction. This is different from nodes like IntentRouter that use `llm.with_structured_output()`.

**LLM Fallback (Exploration Mode):** When answering generic Q&A about unknown destinations, the IntentRouter may use an LLM fallback (`_llm_fallback_answer`) - but this is NOT part of LocalExpert itself.

### LogisticsNode (NEW)

Centralized tile fetching with safety logic. Runs AFTER Specialist/LocalExpert, BEFORE Architect.

**Provider Routing Strategy (Consistent with TileService):**

| Destination Type | Hotels | Activities | Flights |
|------------------|--------|------------|---------|
| Curated (Dubai, Rome, Chamonix) | CuratedProvider | CuratedProvider | Curated + Demo Backup |
| Non-Curated | MockProvider | MockProvider | Demo Backup |

> **Note:** Amadeus providers are disabled for now to ensure consistent behavior between first request and regeneration flows.

**Safety Logic (Diving Integration):**
- Detects diving constraints from VerticalSpecialist
- Applies 24h no-fly surface interval calculation
- Tags flights as safe/unsafe with `logic_hook` explanation

**Carrier Sanitization:**
- Maps test carrier codes to real airlines (XX → Emirates)
- Uses `CARRIER_MAP` from `demo_curation.py`

**Output:**
- `state.tiles["flights"]` - Flight tiles for frontend display
- `state.tiles["hotels"]` - Hotel tiles for frontend display
- `state.tiles["activities"]` - Activity tiles for frontend display
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

### ItineraryBuilder (Pure Python - No LLM)

Transforms specialist content + tiles into day-by-day timeline.

**Location:** `backend/app/services/itinerary_builder.py`

**Why No LLM:** Deterministic scheduling is faster and more predictable than LLM-based generation. The specialists provide the "what", the builder provides the "when".

**Algorithm (6 phases):**

```
┌─────────────────────────────────────────────────────────────────┐
│  ItineraryBuilder (Pure Python - No LLM)                        │
│  Transforms specialist content + tiles into day-by-day timeline  │
│                                                                  │
│  Algorithm (6 phases):                                           │
│  1. Temporal Scaffolding - Create DayCard[] from dates           │
│  2. Anchor Placement - Arrival/departure from flight tiles       │
│  3. Buffer Injection - Safety blocks (no-fly, acclimatization)   │
│  4. Activity Distribution - Round-robin interleaving by day      │
│  5. Tile Matching - Hotels span all days, preferences weighted   │
│  6. Constraint Tagging - Attach inline constraints to blocks     │
│                                                                  │
│  Routing: Logistics → ItineraryBuilder → Guard → Synthesizer    │
└─────────────────────────────────────────────────────────────────┘
```

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
| `proximity_optimized` | success | hotel | Location optimized for activities |

**Frontend Rendering:** See `docs/ux_unified_architecture.md` Section I.A.2 "Inline Constraints Display"

**Preference Weighting:**
- User heart preferences passed via `PreferenceOverrideInput`
- Preferred hotels get 1.5x score multiplier
- Preference attribution badges: "user_preferred", "ai_selected", "ai_override"

**Conflict Detection:**
- Temporal capacity (>11h activities per day)
- Constraint clash (diving + high-altitude hiking same day)
- Insufficient days for planned activities

---

## Structured Output Usage

Pydantic structured output is used for LLM nodes that need **guaranteed schema extraction**. Nodes that generate natural language or use static data do NOT use structured output.

### Node-by-Node Status

| Node | Uses Structured Output? | LLM Used? | Schema(s) | Purpose |
|------|------------------------|-----------|-----------|---------|
| **IntentRouter** | ✅ Yes | GPT-4o-mini | `RouterOutput`, `IntentClassification` | Intent + field extraction in one call |
| **TripArchitect** | ✅ Yes | GPT-4o | `ExtractedTripFields`, `ExtractedSettingsFields` | Trip field & settings extraction |
| **LocalExpert** | ❌ No | ❌ Static | N/A | Uses `LOCAL_EXPERT_KNOWLEDGE` dict |
| **VerticalSpecialist** | ⚙️ Optional | GPT-4o | `SpecialistOutput` | Enable with `USE_SPECIALIST_LLM=true` env var |
| **LogisticsNode** | ❌ No | ❌ N/A | N/A | API calls only (Amadeus, curated data) |
| **ConstraintGuard** | ❌ No | ❌ N/A | N/A | Pure Python rule-based validation |
| **Synthesizer** | ❌ No | GPT-4o | N/A | Free-form natural language (correct) |

> **Note:** VerticalSpecialist uses hardcoded knowledge by default for consistent, fast responses. Enable `USE_SPECIALIST_LLM=true` to use LLM-generated constraints via `specialist_llm.py`. Falls back to hardcoded if LLM fails.

### Design Principle

**Rule of thumb:**
- **LLM extracts structured information** → Use `.with_structured_output(Schema)` ✅
- **LLM generates natural language** → Don't use structured output ❌
- **No LLM (static data, APIs, validation)** → N/A ❌

### RouterOutput Schema

The IntentRouter uses a combined schema for intent classification + field extraction in a single LLM call:

```python
class RouterOutput(BaseModel):
    """Combined intent classification + field extraction."""
    intent: Literal["GREETING", "RESET", "PLANNING"]
    destination: Optional[str] = None
    origin: Optional[str] = None
    start_date: Optional[str] = None  # YYYY-MM-DD format
    end_date: Optional[str] = None    # YYYY-MM-DD format
    duration_days: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    budget: Optional[float] = None
    specialist_hints: Optional[List[str]] = None
    has_dates_in_message: bool = False

# Usage
llm = ChatOpenAI(model="gpt-4o-mini")
structured_llm = llm.with_structured_output(RouterOutput)
result: RouterOutput = await structured_llm.ainvoke(messages)
```

**Benefits:**
- Type-safe extraction with Pydantic validation
- No regex parsing errors
- Dates extracted immediately (fixes P0 bug where dates were asked twice)
- Single LLM call instead of separate intent + extraction calls

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
    severity: ConstraintSeverity = ConstraintSeverity.STRONG  # Priority for conflicts
    applies_to: Optional[str]    # "flights", "activities", etc.
    parameters: Dict[str, Any]   # e.g., {"max_depth_without_cert": 18}
    reason: Optional[str]        # Human-readable explanation

class ConstraintSeverity(str, Enum):
    """Constraint priority for multi-specialist conflict resolution."""
    BLOCKING = "blocking"  # Safety/Legal - always wins (e.g., 24h no-fly)
    STRONG = "strong"      # Optimization - negotiates (e.g., best weather)
    SOFT = "soft"          # Preference - defers (e.g., scenic route)
```

**Note:** Uses `Literal` because constraints are created by code (not LLM-generated).
Compare with `LocalConstraint` which uses `str` for LLM-generated content.

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

    # === S3 Itinerary View Enhancement Fields ===
    # See docs/ux_unified_architecture.md Section 10.C for UI mapping

    # Rich display fields
    duration: Optional[str]           # Human-readable: "4 hours", "Half day"
    scheduled_time: Optional[str]     # Exact time: "08:00 AM" (for flights/check-in)
    logistics_details: Optional[str]  # Terminal info, hotel address
    hotel_name: Optional[str]         # For check-in/check-out blocks

    # Booking integration
    requires_booking: bool = False    # True = show ghost slot in UI if not booked
    booking_category: Optional[Literal["hotel", "flight", "activity"]]
    booked_tile_id: Optional[str]     # Reference to selected tile (if user has booked)

    # Coordinates for map integration
    coordinates: Optional[Tuple[float, float]]  # (lat, lng) for map POI
```

**S3 Block Type Mapping:**

| Backend Field | Frontend Component | Condition |
|---------------|-------------------|-----------|
| `buffer_type in ["arrival", "departure"]` | `LogisticsBlock` | Flight logistics |
| `type.includes("check")` | `LogisticsBlock` | Hotel check-in/out |
| `is_buffer and buffer_type == "no_fly"` | `SafetyBlock` | No-fly constraint |
| `is_buffer` | `SafetyBlock` | Rest day / acclimatization |
| `requires_booking and not booked_tile_id` | `GhostSlot` | Unbooked placeholder |
| Default | `ActivityMiniCard` | Rich activity card |

---

## Exploration Mode

The IntentRouter supports **Exploration Mode** for handling generic travel questions before the user is ready to plan. This creates a conversational travel agent experience.

### Question Type Detection

Questions are classified into types that map to Local Expert knowledge sections:

| Question Type | Keywords | Local Expert Section |
|--------------|----------|---------------------|
| `couples` | romantic, honeymoon | `destination_overview` |
| `family` | kids, children | `destination_overview` |
| `weather` | climate, rain, season | `seasonality` |
| `safety` | dangerous, crime, security | `safety_health` |
| `costs` | expensive, cheap, budget | `money_costs` |
| `visa` | passport, entry, immigration | `visa_entry` |
| `transport` | taxi, uber, scooter | `transportation` |
| `cultural` | wear, dress, clothes | `cultural_norms` |
| `activities` | must see, must do | `things_to_do` |
| `accommodation` | stay, hotel, neighborhood | `neighborhoods` |
| `scams` | rip off, tourist trap | `scams_traps` |
| `packing` | bring, luggage, adapter | `packing` |
| `connectivity` | sim, wifi, internet | `connectivity` |

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

ACTIVITY_INDICATORS = [
    r"\b(diving|dive|scuba|snorkel)\b",
    r"\b(hiking|trek|climb|trail)\b",
    r"\b(skiing|snowboard|ski)\b",
]
```

### Intent Classification

| Intent | Condition | Behavior |
|--------|-----------|----------|
| `ready` | Explicit planning signal OR (date AND activity) | Continue to PLANNING flow |
| `soft_transition` | Has date OR activity | **Routes to PLANNING** (dates/activities = actionable input) |
| `exploring` | Generic question, no planning signals | Comprehensive answer + "What else?" |

### Progressive Nudging

| Question # | Response Ending |
|-----------|-----------------|
| 1 | "What else would you like to know?" |
| 2 | "When are you thinking of going?" (soft nudge) |
| 3+ | "I can help plan your trip when you're ready..." |

### Conversation State Tracking

```python
state.metadata["exploration_mode"] = True
state.metadata["generic_question_count"] = 2
state.metadata["last_destination_context"] = "Bali"
state.metadata["short_circuit_type"] = "exploration"  # or "soft_transition"
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

```python
def route_after_router(state: GraphState) -> Literal["specialist", "local_expert", "architect", "synthesizer"]:
    # GREETING/RESET short-circuits skip to synthesizer
    if state.metadata.get("short_circuit_response"):
        return "synthesizer"

    # First pass: active_specialist is "local_expert" (always first in queue)
    # Niche specialists (diving, etc.) wait in pending_specialists
    if state.active_specialist:
        if state.active_specialist == "local_expert":
            return "local_expert"
        return "specialist"  # For niche specialists in multi-specialist loop

    # Default → architect (shouldn't happen if router sets local_expert)
    return "architect"
```

### Route After Specialist

**Multi-Specialist Loop:** After LocalExpert completes, niche specialists (diving, etc.)
are processed in queue order. Each specialist clears `active_specialist` at end.

```python
def route_after_specialist(state: GraphState):
    # 1. Multi-specialist: If pending specialists exist, run the next one
    #    e.g., after local_expert, pending_specialists = ["diving"]
    if state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        if next_specialist == "local_expert":
            return "local_expert"
        return "specialist"  # Routes to vertical_specialist

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

## Itinerary Builder Service

**Location:** `backend/app/services/itinerary_builder.py`

**Purpose:** Pure Python service that transforms specialist outputs into chronological, constraint-validated timeline. Called from `/api/expand-itinerary`.

**NOT a LangGraph node** - preserves 7-node architecture invariant.

### Algorithm Phases

```
Phase 1: Temporal Scaffolding
├─ Create DayCard[] skeleton from start_date to end_date
├─ Calculate trip duration
└─ Initialize empty block lists per day

Phase 2: Anchor Placement
├─ Arrival block on Day 1 (from flight tiles)
├─ Departure block on last day (from flight tiles)
└─ Hotel check-in/check-out blocks

Phase 2a: Multi-Specialist Block Collection
├─ Collect ItineraryBlock[] from each specialist
├─ Tag with source_specialist for color-coding
└─ Preserve constraint references

Phase 2b: Conflict Detection & Resolution
├─ Detect temporal_capacity violations (>11h/day)
├─ Detect constraint_clash between specialists
├─ Resolve by severity: BLOCKING > STRONG > SOFT
└─ Generate ConflictResolution if irreconcilable

Phase 3: Buffer Injection
├─ Safety buffers (24h no-fly after diving)
├─ Rest days (acclimatization for altitude)
└─ Placed by constraint severity (BLOCKING first)

Phase 4: Activity Distribution (with Preference Weighting)
├─ Normalize activity IDs for frontend/backend matching
├─ Weight activities by user preferences (is_user_preferred flag)
├─ Sort: preferred activities first, then round-robin interleaving
├─ Max 2-3 activities per day
├─ Respect day capacity (11 usable hours)
├─ Alternate for variety (dive → hike → dive)
└─ Set preference_status on blocks ('user_preferred' | null)

Phase 5: Tile Matching
├─ Hotels span all days
├─ Activities matched to day blocks
├─ Flights attached to arrival/departure
└─ Hotel preference attribution (user_preferred metadata)

Phase 6: Constraint Tagging (Inline Display)
├─ Tag blocks with relevant constraints for frontend display
├─ Diving constraints:
│   ├─ no_fly_buffer: Applied to last dive before departure
│   └─ surface_interval: Between consecutive dive days
├─ Constraint structure: { id, severity, icon, title, description }
└─ Stored in block.active_constraints[]
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

| Severity | Examples | Resolution |
|----------|----------|------------|
| **BLOCKING** | 24h no-fly (diving), visa requirements, permits | Always wins |
| **STRONG** | Best weather timing, equipment availability, opening hours | Negotiates |
| **SOFT** | Scenic routes, photo opportunities, early starts | Defers |

### Timezone Handling Infrastructure

The itinerary builder includes timezone infrastructure for cross-timezone constraint calculations:

**Available Helpers:**
- `get_destination_utc_offset(destination)` - Returns UTC offset for common destinations
- `normalize_to_destination_tz(dt, destination)` - Converts datetime to destination local time
- `calculate_hours_between(time1, time2, destination, use_timezone)` - Calculates hours with optional timezone normalization

**Current Status:** MVP assumes all times are in destination local timezone. This is correct for most dive trip scenarios where:
- Dive times are local
- Flight departure times shown in local time by airlines
- Users think in local time

**Enable Full Timezone Support:** Set `use_timezone=True` in `calculate_hours_between()` for cross-timezone flight calculations.

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

**Early Return Detection:**
- If 🔥 log is missing, check for `❌ [expand-itinerary]` logs indicating:
  - Missing end_date
  - Trip too short (< 2 days)
  - Session/document not found

**Common Issues:**

| Symptom | Log to Check | Fix |
|---------|--------------|-----|
| No backend logs at all | `DEBUG` env var | Set `DEBUG=full` in backend/.env |
| No backend logs | Session/doc check | Verify session cookie |
| `sections=0` | Frontend payload | Check Network tab for empty `strategy_sections` |
| `activities=0` | Content extraction | Verify `content_added` in strategy_sections |
| Build succeeds but UI unchanged | Browser console | Check `mergeEnvelope` logs + Zustand selector (see ux_unified_architecture.md) |

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
    severity: Literal["blocking", "strong", "soft"]
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

**Frontend Handling:** `ConflictResolutionModal` displays conflicts and resolution options.

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
├── amadeus_provider.py   # Amadeus API (disabled for now)
└── curated_provider.py   # Curated content for hero destinations
```

### Provider Routing Consistency

Both `logistics_node.py` and `tile_service/service.py` use identical routing logic:

| Flow | Destination Type | Provider Used |
|------|------------------|---------------|
| First Request (logistics_node) | Curated | CuratedProvider |
| First Request (logistics_node) | Non-Curated | MockProviders |
| Regeneration (tile_service) | Curated | CuratedProvider |
| Regeneration (tile_service) | Non-Curated | MockProviders |

This ensures tiles have consistent images and data regardless of how they were fetched.

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
        "plan_view_state": "P0_MINIMAL" | "P1_ENRICHED" | "P2_LOGISTICS" | "P3_FINALIZED",
        "tiles": {...},           # Flattened ID-based map
        "strategy_sections": [...], # Agent cards data
    },
}
```

### Planning Phases (Density-Oriented)

| Phase | Description | Data Richness |
|-------|-------------|---------------|
| `P0_MINIMAL` | Destination only, no specialists yet | Minimal input |
| `P1_ENRICHED` | Specialists run, strategy sections present | Strategy cards visible |
| `P2_LOGISTICS` | Tiles fetched, suggestions available | Full dashboard |
| `P3_FINALIZED` | Itinerary validated, ready to book | Complete itinerary |

### Two-Mode Frontend System

> **NOTE:** The frontend uses a simplified two-mode system (PLANNING + BOOKING). Planning phases (P0-P3) represent data richness within PLANNING mode.

| Frontend Mode | Planning Phases | Description |
|---------------|-----------------|-------------|
| **PLANNING** | `P0_MINIMAL` → `P1_ENRICHED` → `P2_LOGISTICS` → `P3_FINALIZED` | Progressive enrichment |
| **BOOKING** | After `P3_FINALIZED` + "Proceed to Booking" click | Transaction + price comparison |

**Key Points:**
- PLANNING mode evolves naturally based on user inputs (no explicit "Build" click)
- Dates auto-trigger tile search (SOFT gate)
- "Proceed to Booking" is the only HARD gate (explicit click required)
- See `docs/ux_unified_architecture.md` Section I for full specification

#### Mode-Aware Tile Components

| Component | Mode | Purpose | Location |
|-----------|------|---------|----------|
| `SuggestionCard` | PLANNING | Shows tiles with AI reasoning | `components/plan/tiles/` |
| `BookableCard` | BOOKING | Shows price comparison | `components/plan/tiles/` |
| `SuggestionBlock` | PLANNING | Timeline block for suggestions | `components/plan/timeline/blocks/` |
| `AlternativesModal` | PLANNING | "Change" sheet with alternatives | `components/plan/modals/` |

#### Mode-Aware Layout Components

| Component | Mode Support | Purpose | Location |
|-----------|--------------|---------|----------|
| `PlanHeader` | Both | Optional ModeIndicator (PLANNING/BOOKING pills) vs legacy GlassCommandBar | `components/plan/` |
| `UnifiedChipRow` | Both | Chips disabled (read-only) in BOOKING mode | `components/plan/` |
| `TileDetailsModal` | Both | "Why this?" in PLANNING, price comparison in BOOKING | `components/tiles/` |
| `StrategyStageRenderer` | Both | Derives mode from activeView, passes to BookingSection | `components/plan/` |

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

| Direction | Trigger | Action |
|-----------|---------|--------|
| Timeline → Map | User scrolls itinerary | Map flies to location, highlights pin |
| Map → Timeline | User clicks pin | Timeline scrolls to item, ring highlight |

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
