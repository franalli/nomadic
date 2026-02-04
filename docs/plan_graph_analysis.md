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
| `GENERATE_PLAN_NOW` | "GENERATE_PLAN_TRIGGER" (frontend Refresh button) | Force clear tiles → Full regeneration |

**GENERATE_PLAN_NOW Handling (Refresh Button):**

When the frontend Refresh button triggers `GENERATE_PLAN_NOW`:
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

**Structured Output Extraction (P0 Fix):**

When `has_dates_in_message` is detected (via regex), the Router calls `_classify_and_extract_with_llm()` which:
1. Uses `llm.with_structured_output(RouterOutput)` for guaranteed schema extraction
2. Extracts dates, destination, origin, travelers, budget in ONE call
3. Populates `state.trip_plan` immediately via `_populate_trip_plan_from_router_output()`
4. Sets `router_extracted_fields = True` flag for TripArchitect to skip duplicate extraction

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

Domain expert that runs BEFORE Architect calls tools. **Uses LLM-first architecture with hardcoded fallback.**

**Key Insight:** Returns BOTH constraints AND content.

| Output | Type | Example |
|--------|------|---------|
| `constraints` | SpecialistConstraint[] | "24h surface interval after diving" |
| `content_blocks` | ItineraryBlock[] | "Day 2: USAT Liberty Wreck" |
| `critique` | string | Review of current plan |
| `enhancements` | string[] | "Book dive shop in advance" |

#### LLM-First Architecture (Zero-Template System)

**Implementation:** Single LLM call per specialist generates feasibility + activities + constraints.

```python
SPECIALIST_SYSTEM_PROMPTS = {
    "diving": """You are a PADI-certified dive master planning safe dive trips.
CRITICAL SAFETY RULES (BLOCKING - cannot be violated):
1. NO-FLY TIME: 24h minimum after diving before flying
2. NO ALTITUDE: No activities above 2500m within 24h of diving...""",

    "hiking": """You are a certified mountain guide planning hiking expeditions.
Focus: elevation gain, acclimatization (max 500m/day above 3000m)....""",

    "skiing": """You are a certified ski instructor planning ski trips.
Focus: avalanche risk, skill progression, snow conditions...""",
}

async def generate_specialist_output_llm(topic, destination, trip_plan):
    """Single LLM call generates feasibility + activities + constraints."""
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    return await llm.with_structured_output(LLMSpecialistOutput).ainvoke(...)
```

**Token Optimization:** The user prompt does NOT include a JSON schema example - OpenAI's
function calling API receives the Pydantic schema from `.with_structured_output()` directly.
This saves ~200-500 tokens per specialist call while maintaining schema enforcement at the API level.

**Fallback Mechanism:** If LLM fails (parse error, timeout), falls back to minimal safety constraints:
```python
def _get_minimal_safety_constraints(topic: str) -> List[SpecialistConstraint]:
    """Hardcoded fallback when LLM fails - safety over features."""
    if topic == "diving":
        return [SpecialistConstraint(
            constraint_id="no_fly_24h",
            type="temporal",
            rule="24h_no_fly_after_diving",
            severity=ConstraintSeverity.BLOCKING,
            ...
        )]
```

**Domain Knowledge (LLM-Generated):**
- Diving: Flight buffers, certification requirements, real dive sites
- Hiking: Altitude acclimatization, elevation data, trail recommendations
- Skiing: Snow conditions, avalanche awareness, resort suggestions

#### LLM Feasibility Layer

Geographic feasibility checking for unknown destinations (e.g., "diving in Chamonix").

**Two-Tier Architecture:**
1. **Hardcoded List (Fast):** ~400 known destination/activity combinations
2. **LLM Fallback (Cached):** GPT-4o-mini check for unknown destinations

```python
# Tier 1: Hardcoded check (0ms)
if destination in DIVING_FEASIBILITY["infeasible"]:
    return ("infeasible", "Diving not available", alternative)

# Tier 2: LLM check (200ms, cached)
possible, reason = get_feasibility_llm("diving", "Chamonix")
# LLM determines: landlocked alpine town → diving impossible
```

**LLM Prompt:**
```
Is {topic} activity possible in {destination}?

Rules:
- Diving requires coastline, large lakes, or dedicated dive facilities
- Skiing requires mountains with reliable snow or indoor ski facilities
- Hiking requires terrain suitable for walking trails

Respond JSON: {"possible": true/false, "reason": "brief"}
```

**Caching:** `@lru_cache(maxsize=1000)` - cache key is `f"{topic}:{destination}"`

**Cost:** ~$0.0001 per check, ~200ms latency (first call only)

**Fail-Open Policy:** If LLM fails, assume possible. False positives (user discovers no dive sites) are acceptable; false negatives (blocking valid destinations) break UX.

**Frontend Handling:** S2StrategyView renders infeasible specialists with:
- Red border and "Unavailable" badge
- `feasibility_reason` message
- `alternative_suggestion` (e.g., "Consider Bali, Red Sea, or Maldives")

#### Parallel LLM Execution (Multi-Specialist Optimization)

When multiple specialists are queued (e.g., "diving and hiking in Bali"), the system uses parallel LLM execution to reduce latency from ~8-12s (sequential) to ~4-6s (parallel).

**Implementation:**
```python
async def generate_all_specialists_parallel(
    topics: List[str],
    destination: str,
    trip_plan: TripPlan,
) -> Dict[str, Optional[LLMSpecialistOutput]]:
    """Run all specialist LLM calls in parallel using asyncio.gather()."""

    async def safe_generate(topic: str) -> Tuple[str, Optional[LLMSpecialistOutput]]:
        try:
            result = await generate_specialist_output_llm(topic, destination, trip_plan)
            return (topic, result)
        except Exception as e:
            _debug_log(f"[SPECIALIST] Parallel call failed for {topic}: {e}")
            return (topic, None)

    tasks = [safe_generate(topic) for topic in topics]
    results = await asyncio.gather(*tasks)
    return {topic: output for topic, output in results}
```

**Cache Strategy:**
- Results are cached in `state.metadata["parallel_llm_results"]` as serialized dicts
- Subsequent specialist node calls deserialize cached results using `LLMSpecialistOutput.model_validate()`
- **Multi-specialist:** First specialist triggers parallel fetch for all; others use in-memory cache
- **Single specialist:** Uses L1+L2 database cache directly (same path as parallel, ensures cache hits across sessions)

**Debug Output (DEBUG=full):**
```
# Multi-specialist (parallel)
[DEBUG] [SPECIALIST] PARALLEL TRIGGER: 2 specialists detected
[DEBUG] 🤿 SPECIALIST END | duration=8432ms | topic=diving feasibility=feasible activities=3
[DEBUG] 🥾 SPECIALIST END | duration=10ms | topic=hiking (cached)

# Single specialist (L1+L2 cache)
[DEBUG] [SPECIALIST] Single specialist 'diving' - using cached LLM path
[DEBUG] [SPECIALIST_CACHE] Looking up cache for diving in Bali
[DEBUG] [SPECIALIST_CACHE] ✅ HIT for diving - skipping LLM
[DEBUG] 🤿 SPECIALIST END | duration=10ms | topic=diving
```

**Performance Impact:**
| Scenario | Cold (no cache) | Warm (L2 hit) | Hot (L1 hit) |
|----------|-----------------|---------------|--------------|
| 1 specialist | ~5s (LLM) | ~50ms (DB) | ~10ms (memory) |
| 2 specialists | ~5s (parallel) | ~100ms | ~20ms |
| 3 specialists | ~6s (parallel) | ~150ms | ~30ms |

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

**Algorithm (8 phases):**

```
┌─────────────────────────────────────────────────────────────────┐
│  ItineraryBuilder (Pure Python - No LLM)                        │
│  Transforms specialist content + tiles into day-by-day timeline  │
│                                                                  │
│  Algorithm (8 phases):                                           │
│  1.   Temporal Scaffolding - Create DayCard[] from dates         │
│  2.   Anchor Placement - Arrival/departure from flight tiles     │
│  3.   Buffer Injection - Safety blocks (no-fly, acclimatization) │
│  4.   Activity Distribution - Round-robin interleaving by day    │
│  5.   Free Day Placeholders - Add placeholders for empty days    │
│  5.25 Preferred Activity Placement - Fill free days with hearts  │
│  6.   Tile Matching - Hotels span all days, preferences weighted │
│  7.   Constraint Tagging - Attach inline constraints to blocks   │
│                                                                  │
│  Routing: Logistics → ItineraryBuilder → Guard → Synthesizer    │
└─────────────────────────────────────────────────────────────────┘
```

**Phase 5.25: Preferred Activity Placement**

After creating free day placeholders, the builder populates free days with user-preferred activities (hearted tiles). This ensures hearted activities appear in the itinerary:

1. Collects preferred tiles from `preferences.preferred_activity_ids` (ordered by user preference)
2. Finds free days (days with only FreeDay placeholder, skipping arrival/departure)
3. Replaces FreeDay placeholders with activity blocks from preferred tiles
4. If more preferred activities than free days, extras are dropped (no conflicts created)

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
- Cross-domain constraint clash (diving + hiking within 24h buffer via `no_altitude_after_dive`)
- Insufficient days for planned activities

**Cross-Domain Constraints:** The `no_altitude_after_dive` constraint (BLOCKING severity) prevents scheduling high-altitude hiking/trekking/mountaineering within 24 hours of diving activities. Validated in `_detect_early_conflicts()`.

#### Constraint Alias Normalization

LLMs generate constraint names with natural variation (e.g., `"no_altitude_24h"`, `"altitude_buffer"`, `"no-altitude-after-diving"`). The builder normalizes these via **alias mapping** to ensure robust constraint detection regardless of LLM phrasing.

**Location:** `backend/app/services/itinerary_builder.py` (lines ~186-210)

```python
CONSTRAINT_ALIASES: Dict[str, List[str]] = {
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
    aliases = CONSTRAINT_ALIASES.get(canonical_rule, [])
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

| Node | Uses Structured Output? | LLM Used? | Schema(s) | Purpose |
|------|------------------------|-----------|-----------|---------|
| **IntentRouter** | ✅ Yes | GPT-4o-mini | `RouterOutput`, `IntentClassification` | Intent + field extraction in one call |
| **TripArchitect** | ✅ Yes | GPT-4o | `ExtractedTripFields`, `ExtractedSettingsFields` | Trip field & settings extraction |
| **LocalExpert** | ❌ No | ❌ Static | N/A | Uses `LOCAL_EXPERT_KNOWLEDGE` dict |
| **VerticalSpecialist** | ✅ Yes | GPT-4o | `LLMSpecialistOutput`, `LLMActivity`, `LLMConstraint` | LLM-first with fallback |
| **LogisticsNode** | ❌ No | ❌ N/A | N/A | API calls only (Amadeus, curated data) |
| **ConstraintGuard** | ❌ No | ❌ N/A | N/A | Pure Python rule-based validation |
| **Synthesizer** | ❌ No | GPT-4o | N/A | Free-form natural language (correct) |

> **Note:** VerticalSpecialist uses **LLM-first architecture** by default. Single LLM call generates feasibility + activities + constraints. Falls back to minimal safety constraints if LLM fails (parse error, timeout).

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
logistics → architect/guard/synthesizer (conditional - skip architect if already ran)
architect → guard/synthesizer (conditional)
guard → architect/synthesizer (conditional - auto-fix loop)
synthesizer → END
```

### Route After Logistics (Skip Double Architect)

**Optimization:** Architect runs once per turn for field extraction. After logistics fetches tiles,
if architect already ran earlier in the same turn, skip directly to guard/synthesizer.

```python
def route_after_logistics(state: GraphState) -> Literal["architect", "guard", "synthesizer"]:
    """Skip architect if fields already extracted this turn."""
    # Flag is cleared in _restore_graph_state(), set at end of architect node
    if state.metadata.get("architect_ran_this_turn", False):
        return _should_run_guard(state)  # Reuse existing helper
    return "architect"
```

**Performance Impact:** Saves ~800ms + one GPT-4o call per plan with tiles.

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
| Rule | Type | Reason | Cross-Domain |
|------|------|--------|--------------|
| `min_24h_buffer_after_dive` | temporal | Decompression sickness risk | flights |
| `min_18h_surface_interval` | temporal | Minimum before single dive | flights |
| `advanced_cert_required_for_deep` | safety | Dives below 18m need AOW | activities |
| `no_altitude_after_dive` | safety | Altitude >2500m within 24h increases DCS risk | hiking, trekking, mountaineering, skiing |

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

**Note:** Hiking is affected by diving's `no_altitude_after_dive` constraint (one-directional: diving → hiking).

**Top Destinations:**
- Patagonia: Torres del Paine W Trek, Fitz Roy Summit Approach
- Nepal: Everest Base Camp, Annapurna Circuit

### Skiing

**Constraints:**
| Rule | Type | Reason |
|------|------|--------|
| `check_snow_conditions` | temporal | Verify avalanche reports |
| `guide_required_offpiste` | certification | Certified guide for off-piste |

**Note:** Skiing is affected by diving's `no_altitude_after_dive` constraint (one-directional: diving → skiing).

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
| Specialist | No altitude after diving (cross-domain) | info | ItineraryBuilder enforces |

### Landlocked Countries (Partial List)

Switzerland, Austria, Czech Republic, Hungary, Nepal, Mongolia, Bolivia, Rwanda, Ethiopia, and more.

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
| Specialist | `specialist_cache.py` | 128 | 1h | 7 days | `specialist:{topic}:{dest}:{month}:{duration}` | LLM outputs |
| Tile | `tile_cache.py` | 256 | 24h | 24h | `tiles:{provider}:{type}:{dest}:{dates}` | Provider API data |
| Router | `router_cache.py` | 500 | 1h | N/A | `SHA256({text}:{date})` | NL extraction |

**Database Table:** `response_cache` with `cache_type` column for filtering (values: `'specialist'`, `'tiles'`).

### Cache Invalidation Triggers

| Trigger | Caches Invalidated |
|---------|-------------------|
| Core fields change | response, tile |
| `end_date` change | tile |
| `adults/children` change | tile |
| Strategy topic switch | response |
| Destination change | `parallel_llm_results` (session) |
| Month change | `parallel_llm_results` (session) |
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

### Specialist LLM Cache

Two-tier cache for VerticalSpecialist LLM outputs. Reduces LLM calls by ~86% for repeated destination/activity queries.

**Service:** `backend/app/services/specialist_cache.py`

**Tier 1: In-Memory TTLCache (Thread-Safe)**
- Storage: `cachetools.TTLCache` with `RLock` for thread safety
- Separate `_stats_lock` RLock for hit/miss counters (prevents counter race conditions)
- Max size: 128 entries
- TTL: 1 hour
- Key format: `specialist:{topic}:{destination}:{month}:{duration}`

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
| month | `2025-02` | Seasonal context |
| duration | `14` | Trip length affects activity count |

**Lookup Order:**
1. L1 in-memory (thread-safe) → ~1ms
2. L2 PostgreSQL → ~50ms (promotes to L1 on hit)
3. LLM API call → ~5s (writes to both layers)

**Admin Endpoints:**
- `GET /api/admin/specialist-cache-stats` - Hit/miss statistics
- `POST /api/admin/clear-specialist-cache` - Clear both layers

**Integration Points:**
- Multi-specialist: `generate_all_specialists_parallel()` - batch cache lookup/write
- Single specialist: `vertical_specialist()` - direct L1+L2 lookup before `generate_specialist_output_llm()`

#### Session-Level Cache (`parallel_llm_results`)

In addition to L1+L2 caches, specialist outputs are cached in `state.metadata["parallel_llm_results"]` within a single graph execution. This prevents duplicate LLM calls when multiple specialists run in the same turn.

**Problem Solved:** When destination or dates change mid-session, the session cache could return stale content (e.g., Bali dive sites for a New York trip).

**Invalidation Logic (at TOP of `vertical_specialist()`):**

```python
# Track context changes by destination + month
cached_key = state.metadata.get("_last_specialist_key", "")
current_dest = (state.trip_plan.destination or "").lower().strip()
current_month = state.trip_plan.start_date[:7] if state.trip_plan.start_date else "no-dates"
current_key = f"{current_dest}:{current_month}"

if cached_key and cached_key != current_key:
    _debug_log(f"[SPECIALIST] Context changed ({cached_key} → {current_key}), invalidating")
    state.metadata.pop("parallel_llm_results", None)

state.metadata["_last_specialist_key"] = current_key
```

**Why `destination:month`:**
- Destination change: Different location = different content
- Month change: Different season = different recommendations (rainy vs dry season)
- Matches L1+L2 cache key format for consistency

**Invalidation Triggers:**
| Change | Example | Result |
|--------|---------|--------|
| Destination | `bali:2026-02` → `new york:2026-02` | Cache cleared |
| Month | `bali:2026-02` → `bali:2026-08` | Cache cleared |
| Day only | `bali:2026-02` → `bali:2026-02` | Cache preserved |

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

| Query | Cacheable | Reason |
|-------|-----------|--------|
| "I want to go diving in Bali Feb 1-14" | ✅ Yes | Self-contained |
| "Show me diving there" | ❌ No | "there" depends on context |
| "I want that one" | ❌ No | "that" depends on context |
| "Same dates as before" | ❌ No | "same" depends on context |

**Context Words Detected:** `there`, `that`, `this`, `it`, `them`, `same`, `again`, `too`, `also`

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

| Strategy | Trigger Fields | Execution Path | Est. Time | LLM Calls |
|----------|---------------|----------------|-----------|-----------|
| **BUILDER** | `preferred_tile_ids`, `origin` | ItineraryBuilder only | ~100ms | None |
| **LOGISTICS** | `adults`, `children`, `budget`, `flight_settings`, `hotel_settings`, `activity_skill_level` | LogisticsNode → Builder | ~500ms | None (API calls only) |
| **SPECIALISTS** | `start_date`, `end_date`, `activity_categories` | Specialists → Logistics → Builder | ~3-8s | Yes |
| **FULL** | `destination` | Full graph re-execution | ~10-15s | Yes |

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
  if (obj === null || obj === undefined) return '';
  if (typeof obj !== 'object') return String(obj);
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
  if (!tripInputs) return '';
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
    activity_skill_level: activitySettings.skill_level || '',
  });
}, [tripInputs]);

// Combined change detection
const hasChanges = hasPreferenceChanges || hasTripInputChanges;
```

### Debounce with Visual Feedback (v3.2)

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
  console.log('Skipping - regeneration already in progress (race avoided)');
  return;
}
isExecutingRegenRef.current = true;
try {
  await regenerate();
} finally {
  isExecutingRegenRef.current = false;
}
```

### Origin Sync for Flight Fetching (v3.3)

The origin field set via the settings panel (PATCH `/api/document`) must be properly synced to the graph state when users trigger chat or regeneration. Without proper sync, flights won't be fetched even when origin is set.

**Root Cause (Fixed):**
The chat API was merging request `trip_inputs` BEFORE loading the document, causing document-stored fields (like origin) to be lost when the request had partial `trip_inputs`.

**Fix Pattern:**
```python
# In main.py chat endpoints (both regular and streaming)
# Always use document trip_inputs as BASELINE, then merge request on top
if document_data.trip_inputs:
    doc_inputs = document_data.trip_inputs.model_dump()
    session_inputs = session_state.get("trip_inputs", {})
    # Document values as baseline, session (request) values override
    merged = {**doc_inputs, **{k: v for k, v in session_inputs.items() if v is not None}}
    session_state["trip_inputs"] = normalize_trip_inputs(merged)
```

**Defensive Check in IntentRouter:**
```python
# If origin mismatch detected at graph entry, sync from trip_inputs
trip_inputs = state.metadata.get("trip_inputs", {})
trip_inputs_origin = trip_inputs.get("origin")
if trip_inputs_origin and not state.trip_plan.origin:
    logger.warning(f"ORIGIN MISMATCH: Syncing from trip_inputs")
    state.trip_plan.origin = trip_inputs_origin
```

**Diagnostic Logging (LogisticsNode):**
```
[LOGISTICS] trip_plan.origin='Rome'
[LOGISTICS] metadata.trip_inputs.origin='Rome'
[LOGISTICS] flights_enabled=True
[LOGISTICS] ✈️ Fetching flights: Rome → London
```

### Performance Impact

| Scenario | Without Selective Regen | With Selective Regen | Savings |
|----------|------------------------|----------------------|---------|
| Heart a tile | ~10s (full graph) | ~100ms (BUILDER) | 99% |
| Change origin | ~10s (full graph) | ~100ms (BUILDER) | 99% |
| Change travelers | ~10s (full graph) | ~500ms (LOGISTICS) | 95% |
| Change hotel stars | ~10s (full graph) | ~500ms (LOGISTICS) | 95% |
| Change flight settings | ~10s (full graph) | ~500ms (LOGISTICS) | 95% |
| Change skill level | ~10s (full graph) | ~500ms (LOGISTICS) | 95% |
| Change dates | ~10s (full graph) | ~6s (SPECIALISTS) | 40% |
| Add activity category | ~10s (full graph) | ~6s (SPECIALISTS) | 40% |
| Change destination | ~10s (full graph) | ~10s (FULL) | 0% |

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

| Function | Purpose |
|----------|---------|
| `_debug_node_timer_start(node_name)` | Start timing (call at node entry) |
| `_debug_node_timer_end(node_name, emoji, **outputs)` | End timing and log duration |
| `NodeTimer(node_name, emoji)` | Context manager for automatic timing |

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
| `/api/admin/cache-stats` | GET | Unified stats for all caches (specialist, tile, router) |
| `/api/admin/specialist-cache-stats` | GET | Specialist cache hit/miss statistics |
| `/api/admin/tile-cache-stats` | GET | Tile cache hit/miss statistics |
| `/api/admin/router-cache-stats` | GET | Router cache hit/miss/skipped statistics |
| `/api/admin/clear-specialist-cache` | POST | Clear specialist L1 + L2 |
| `/api/admin/clear-tile-cache` | POST | Clear tile L1 + L2 |
| `/api/admin/clear-router-cache` | POST | Clear router L1 only |
| `/api/admin/clear-validation-cache` | POST | Clear validation caches |
| `/api/admin/fresh-start` | POST | Clear validation + response caches |
| `/api/admin/clear-all-checkpoints` | POST | Clear ALL LangGraph checkpoints |
| `/api/admin/clear-all-caches` | POST | Comprehensive clear of ALL caches (includes L1+L2 for specialist, tile, router) |

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

Both `curated_provider.py` and `amadeus_provider.py` apply filters from `SearchContext`:

| Setting Type | Filter Applied | Budget Allocation |
|--------------|----------------|-------------------|
| `budget` (hotels) | `tile.price_estimate <= budget * 0.40` | 40% |
| `budget` (activities) | `tile.price_estimate <= budget * 0.30` | 30% |
| `budget` (flights) | `tile.price_estimate <= budget * 0.30` | 30% |
| `hotel_settings.min_stars` | `tile.rating >= min_stars` (fallback: `meta.stars`) | - |
| `flight_settings.direct_only` | `tile.meta.stops == 0` | - |
| `activity_settings.skill_level` | `tile_skill_level <= user_skill_level` | - |

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
- `backend/app/tile_service/curated_provider.py::search()` - Budget, stars, skill filtering
- `backend/app/tile_service/amadeus_provider.py::_search_async()` - Budget filtering post-API

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
| `S3_PARTIAL_CONFLICT` | Conflict detected, partial schedule shown | Partial timeline with unschedulable blocks |

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
