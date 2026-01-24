# Plan Graph Architecture

> **Source**: `backend/app/plan_graph.py` > **Planner Package**: `backend/app/planner/` > **Prompt Files**: `backend/app/prompts/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Package Structure](#package-structure)
3. [Node Architecture Diagram](#node-architecture-diagram)
4. [Complete Node Reference Table](#complete-node-reference-table)
5. [Key Node Details](#key-node-details)
6. [Strategy Stages](#strategy-stages)
7. [Gate Precedence Reference](#gate-precedence-reference)
8. [Short Circuits Reference](#short-circuits-reference)
9. [Caching Architecture](#caching-architecture)
10. [Prompt File Mapping](#prompt-file-mapping)
11. [Streaming Architecture](#streaming-architecture)
12. [Tile Service Architecture](#tile-service-architecture)
13. [Booking Provider Interface](#booking-provider-interface-scaffolding)

---

## Architecture Overview

LangGraph-based conversational trip planning system with **19 nodes**.

| Category            | Count | Description                       |
| ------------------- | ----- | --------------------------------- |
| LLM-Powered Nodes   | 10    | Use OpenAI API for generation     |
| Deterministic Nodes | 9     | Pure Python logic, no LLM         |
| Short Circuit Types | 9     | Bypass patterns for fast response |
| Caching Strategies  | 5     | Token-saving cache mechanisms     |

### Design Principles

1. **Template-First**: Use templates before LLM calls
2. **Gated Specialists**: Block domain specialists until core fields collected
3. **Pre-Core Mode**: Answer domain questions while collecting core fields
4. **Value-First Strategy**: Provide destination inspiration before asking for core fields
5. **Gate Precedence**: Lower-precedence gates yield to higher-priority paths
6. **LQA Pre-pass**: Zero-LLM extraction of simple answers
7. **LLM Budget**: Max 1 LLM call per non-ready turn with deterministic fallback
8. **SSoT Enforcement**: Single source of truth for state mutations via `StateWriter`

---

## Package Structure

```
backend/app/planner/
├── __init__.py              # Facade exports
├── cache_access.py          # Cache utilities
├── hashing.py               # Stable hashing utilities
├── meta.py                  # Metadata helpers
├── meta_keys.py             # Metadata key constants
├── metadata_mutator.py      # Type-safe atomic metadata mutations
├── streaming.py             # Streaming infrastructure
├── telemetry.py             # Telemetry instrumentation
├── test_mode.py             # Test mode detection
├── node_utils.py            # Simple utilities for module-level imports
├── cache/
│   ├── __init__.py          # Cache exports
│   ├── framework.py         # CacheNode ABC + all cache implementations
│   └── compat.py            # Backward-compatible function signatures
├── normalization/
│   ├── __init__.py          # Normalization exports
│   ├── types.py             # NormalizationError dataclass
│   ├── date.py              # DateNormalizer, DateProvenance
│   └── trip_inputs.py       # TripInputNormalizer
├── parsing/
│   ├── __init__.py          # Parsing exports
│   ├── provenance.py        # Parse provenance tracking
│   └── lqa_parsers.py       # LQA field parsers
├── gates/
│   ├── __init__.py          # Gate exports
│   ├── precedence.py        # GatePrecedence IntEnum (10-999)
│   ├── result.py            # GateResult dataclass
│   ├── constants.py         # DateErrorCode, CORE_FIELD_PRIORITY
│   ├── readiness.py         # TripReadiness + compute_trip_readiness()
│   ├── evaluator_v2.py      # GateEvaluator orchestrator
│   ├── types.py             # GraphMetadata TypedDict
│   ├── base.py              # Gate ABC, GateContext
│   ├── keyword_utils.py     # keyword_match() utility
│   ├── intent_detection.py  # Intent detection utilities
│   ├── topic_detection.py   # Strategy topic detection (SINGLE SOURCE OF TRUTH)
│   ├── suppression.py       # SuppressionPredicates (bridge, lifecycle, ownership)
│   ├── checks/              # Gate check functions (P4 module extraction)
│   │   ├── __init__.py      # Exports for check utilities
│   │   ├── strategy.py      # Strategy expansion detection
│   │   └── short_circuit.py # Vague affirmation detection
│   └── implementations/     # Individual gate classes
│       ├── __init__.py      # Gate class exports + GATE_REGISTRY
│       ├── short_circuit.py # ShortCircuitGate, InfeasibilityGate
│       ├── generate_requested.py
│       ├── ready_no_fields.py
│       ├── fast_path.py
│       ├── specialist_pre_core.py
│       ├── strategy_topic_switch.py
│       ├── strategy_pre_core.py
│       ├── strategy_expansion.py
│       ├── strategy_post_core.py
│       ├── core_collection.py
│       ├── heuristic_gates.py
│       └── router_llm.py
├── state/
│   ├── __init__.py          # State exports
│   └── writer.py            # StateWriter class (SSoT enforcement)
└── nodes/
    ├── __init__.py          # Node exports
    ├── base.py              # NodeContext, node_decorator
    ├── confidence.py        # Extraction confidence utilities
    ├── llm_utils.py         # LLM call timing utilities
    ├── lqa_prepass.py       # LQA pre-pass node
    ├── router.py            # Router node
    ├── extractor.py         # Extractor node
    ├── schemas.py           # Pydantic schemas (ExtractorOutput, RouterOutput)
    ├── specialist_main.py   # Shared specialist handler
    ├── strategy_main.py     # Strategy nodes
    ├── specialist/          # Specialist subpackage
    │   ├── __init__.py
    │   ├── base.py          # CORE_FIELDS, SPECIALIST_TYPES
    │   ├── guards.py        # Core field guards
    │   ├── templates.py     # Response templates
    │   ├── groundedness.py  # Tile-based groundedness guardrail
    │   ├── response_processor.py
    │   └── parallel.py      # Parallel specialist execution
    └── strategy/            # Strategy subpackage
        ├── __init__.py
        ├── base.py          # Strategy keywords and helpers
        ├── stage0.py        # Stage0Coordinator
        ├── stages.py        # Stage coordinators and trackers
        └── orchestrator.py  # Strategy orchestration for plan generation
```

---

## Node Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ENTRY POINT                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  lqa_prepass                                                                 │
│  ───────────                                                                 │
│  Zero-LLM pre-pass for simple answers to last question                      │
│  • Parses: dates, numbers, city names, suggestion echoes                    │
│  • Success → skip extractor, route to normalize_inputs                      │
│  • Max input: 150 chars                                                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                 ┌─────────────────┴─────────────────┐
                 │ LQA success                       │ LQA skip/fail
                 ▼                                   ▼
┌────────────────────────────┐    ┌────────────────────────────────────────────┐
│  normalize_inputs          │    │  extractor                                  │
│  ─────────────────         │    │  ─────────                                  │
│  Deterministic cleanup     │    │  LLM-based trip data extraction             │
│  • Date normalization      │    │  • Light mode: 200 tokens (turns 0-2)       │
│  • City name cleanup       │    │  • Full mode: 400 tokens (complex input)    │
│  • Field validation        │    │  • Cache: 300s TTL, keyed by input+fields   │
│  • Error detection         │    │  • Bypasses: greeting, initial extraction,  │
│  No LLM                    │    │    strategy bootstrap                       │
└────────────┬───────────────┘    └──────────────────┬─────────────────────────┘
             │                                       │
             └───────────────────┬───────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  GateEvaluator                                                               │
│  ─────────────                                                               │
│  Centralized routing logic - checks 13 gates in precedence order             │
│  • Precedence 10-999: first match wins                                       │
│  • Tracks gate_trace for debugging                                           │
│  • Yields: higher gates suppress lower ones                                  │
│  No LLM                                                                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
     ┌─────────────┬───────────────┼───────────────┬─────────────┬────────────┐
     │             │               │               │             │            │
     ▼             ▼               ▼               ▼             ▼            ▼
┌─────────┐ ┌───────────┐ ┌─────────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│short_   │ │required_  │ │ specialists │ │ router │ │strategy_ │ │generate_ │
│circuit  │ │fields     │ │             │ │        │ │node      │ │responder │
│         │ │           │ │flights      │ │        │ │          │ │          │
│Template │ │Template   │ │hotels       │ │Scoring │ │3 stages: │ │Explicit  │
│responses│ │+ LLM      │ │transport    │ │+ LLM   │ │0: pre-   │ │generate  │
│for hi/  │ │fallback   │ │activities   │ │fallback│ │   core   │ │request   │
│thanks/  │ │           │ │correction   │ │        │ │1: outline│ │handling  │
│yes/no   │ │Collects:  │ │general      │ │256 tok │ │2: expand │ │          │
│         │ │dest/dates │ │             │ │        │ │          │ │          │
│No LLM   │ │origin/etc │ │512 tok each │ │Cache:  │ │450-1536  │ │No LLM    │
│         │ │           │ │             │ │follow- │ │tokens    │ │          │
│         │ │180 tok    │ │Cache:       │ │up cache│ │          │ │          │
│         │ │           │ │follow-up    │ │        │ │Cache:    │ │          │
│         │ │           │ │cache        │ │        │ │5 min TTL │ │          │
└────┬────┘ └─────┬─────┘ └──────┬──────┘ └───┬────┘ └────┬─────┘ └────┬─────┘
     │            │              │            │           │            │
     └────────────┴──────────────┴─────┬──────┴───────────┴────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  validate_and_merge                                                          │
│  ──────────────────                                                          │
│  Computes trip readiness via TripReadiness dataclass                         │
│  • Checks: core_complete, ready_to_generate, blocking_errors                 │
│  • Auto-enables booking types when ready                                     │
│  • Sets question_target for next turn                                        │
│  No LLM                                                                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────────────────┐
│  branch_postprocess                                                          │
│  ──────────────────                                                          │
│  Multi-city branch splitting and ID generation                               │
│  • Splits: "Paris then Rome" → separate branches                            │
│  • Generates: unique branch IDs                                              │
│  • Normalizes: specs per branch                                              │
│  No LLM                                                                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │ tiles needed                │ no tiles
                    ▼                             │
┌────────────────────────────────┐                │
│  tile_search                   │                │
│  ───────────                   │                │
│  External API for hotels/      │                │
│  flights/activities tiles      │                │
│  • Requires: core fields       │                │
│  • Cache: TileCache            │                │
│  • Key: intent+dest+dates+     │                │
│    travelers (budget filtered) │                │
│  No LLM                        │                │
└───────────────┬────────────────┘                │
                │                                 │
                └────────────────┬────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  summarize                                                                   │
│  ─────────                                                                   │
│  Final response assembly                                                     │
│  • Generates: default follow-up suggestions                                  │
│  • Appends: safety snippets (visa, health, etc.)                            │
│  • Formats: suggested_responses for UI                                       │
│  No LLM                                                                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  response_polish                                                             │
│  ───────────────                                                             │
│  Deterministic message stripping                                             │
│  • Removes: emojis, filler phrases                                           │
│  • Skips: template responses, short-circuit messages                         │
│  No LLM                                                                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
                              ┌─────────┐
                              │   END   │
                              └─────────┘
```

---

## Complete Node Reference Table

### LLM-Powered Nodes

| Node | Prompt File | Purpose | Max Tokens | Streaming | Validation |
|------|-------------|---------|------------|-----------|------------|
| `extractor` | `extractor.txt` | Extract trip data from user input | 400 | 🔒 None | ✅ Pydantic |
| `extractor` (light) | `extractor_light.txt` | Light extraction for simple inputs | 200 | 🔒 None | ✅ Pydantic |
| `router` | `router.txt` | Intent classification | 256 | 🔒 None | ✅ Pydantic |
| `required_fields_node` | `required_fields.txt` | Collect missing core fields | 180 | 🌊 Real | `jloads_safe` |
| `flights_node` | `flights.txt` | Flight preferences | 512 | 🌊 Real | `jloads_safe` |
| `hotels_node` | `hotels.txt` | Hotel preferences | 512 | 🌊 Real | `jloads_safe` |
| `transport_node` | `transport.txt` | Ground transport preferences | 512 | 🌊 Real | `jloads_safe` |
| `activities_node` | `activities.txt` | Activity preferences | 512 | 🌊 Real | `jloads_safe` |
| `correction_node` | `correction.txt` | Handle user corrections | 512 | 🌊 Real | `jloads_safe` |
| `general_node` | `general.txt` | Multi-domain queries | 512 | 🌊 Real | `jloads_safe` |

### Validation Legend

| Symbol | Method | Description |
|--------|--------|-------------|
| ✅ Pydantic | `parse_llm_output()` | Type-safe parsing with Pydantic schema validation |
| `jloads_safe` | `jloads_safe()` | Resilient JSON parsing with fallback (no schema validation) |

> **Note:** Specialist nodes use `jloads_safe` with real-time streaming (`call_llm_streaming_with_json_field`)
> for graceful degradation with partial JSON. Strategy nodes use simulated streaming for deterministic pacing.
> Extractor and router are buffered internal nodes where strict Pydantic validation provides better type safety.

### Strategy Nodes

| Node | Prompt File | Purpose | Max Tokens | Stage | Streaming | Validation |
|------|-------------|---------|------------|-------|-----------|------------|
| `strategy_node` (stage0) | `strategy_pre_core.txt` | Pre-core value-first response | 450 | 0 | ✨ Simulated | `jloads_safe` |
| `strategy_node` (stage0-known) | `strategy_pre_core_known_dest.txt` | Pre-core with known destination | 450 | 0 | ✨ Simulated | `jloads_safe` |
| `strategy_node` (stage0-discovery) | `strategy_pre_core_discovery.txt` | Pre-core destination exploration | 450 | 0 | ✨ Simulated | `jloads_safe` |
| `strategy_node` (stage1) | `strategy_{topic}.txt` | Initial strategy outline | 512 | 1 | ✨ Simulated | `jloads_safe` |
| `strategy_node` (stage2) | `strategy_{topic}.txt` | Expansion details | 1536 | 2 | ✨ Simulated | `jloads_safe` |
| `missing_fields_guard` | `missing_fields_guard.txt` | Guard for missing fields | 100 | — | 🔒 None | `jloads_safe` |

### Deterministic Nodes (No LLM)

| Node | Purpose | Streaming | Cache |
|------|---------|-----------|-------|
| `lqa_prepass` | Zero-LLM answer extraction from simple inputs | 🔒 None | None |
| `normalize_inputs` | Normalize extracted inputs (dates, cities) | 🔒 None | None |
| `validate_and_merge` | Compute trip readiness, set question_target | 🔒 None | None |
| `branch_postprocess` | Split multi-city branches, generate IDs | 🔒 None | None |
| `tile_search` | Search for tiles (hotels/flights/activities) | 🔒 None | TileCache |
| `summarize` | Generate follow-ups, format responses | ✨ Simulated | None |
| `short_circuit_responder` | Handle greetings/confirmations | ✨ Simulated | None |
| `generate_responder` | Handle explicit generation requests, call strategy orchestrator | ✨ Simulated | None |
| `response_polish` | Deterministic message stripping (emojis, filler phrases) | 🔒 None | None |

### Streaming Legend

| Symbol | Mode | Description |
|--------|------|-------------|
| 🔒 None | `buffered:internal` | Internal node, no user-facing output |
| ✨ Simulated | `simulate_streaming` | Token-by-token delivery with 15-35ms delays for visual effect |
| ⚡ Fast UX | `fast_stream_buffered` | Chunked delivery of pre-buffered response (no artificial delays) |
| 🌊 Real | `true_stream` | Real-time tokens from LLM API (used by specialists via `call_llm_streaming_with_json_field`) |

---

## Key Node Details

### LQA Prepass

Zero-LLM pre-pass that attempts to parse simple answers to the last question asked.

| Condition | Action |
|-----------|--------|
| Input ≤ 150 chars | Attempt LQA parsing |
| Matches `question_target` | Skip extractor, route to `normalize_inputs` |
| Suggestion echo | Direct match to suggested response |
| Date-like input | Parse via `is_text_date_compatible()` |
| Number input | Parse as travelers/budget |
| City name | Parse as destination/origin |
| Negation with alternative | Parse "not Paris, maybe Barcelona" → "Barcelona" |

#### Suggestion Echo Guards (v6)

The suggestion echo feature has safeguards to prevent false positives:

| Guard | Condition | Purpose |
|-------|-----------|---------|
| `ui_phase` | Skip if `ui_phase == "expanded"` | Full planner UI doesn't use suggestion chips |
| `suggestion_clicked` | Skip if not present | Requires explicit click signal from frontend |
| Text match | Skip if `suggestion_clicked != user_text` | Prevents misrouting on text mismatch |
| `question_id` | Skip if stale | Prevents matching suggestions from previous turns |

**Data Flow (verified):**
1. **Frontend** → `streamGraphPlan()` includes `ui_phase` and `suggestion_clicked` in body
2. **Backend endpoints** (`/v1/graph_plan`, `/v1/graph_plan/stream`) → inject into `session_state["metadata"]`
3. **run_turn / run_turn_streaming** → `metadata = deepcopy(session_state.get("metadata", {}))`
4. **_try_suggestion_echo** → reads `state.metadata.get("ui_phase")` and `state.metadata.get("suggestion_clicked")`

**Frontend Integration:**
- Pass `suggestion_clicked` in `GraphPlanRequest` when user clicks a suggestion chip
- In expanded mode (`ui_phase="expanded"`), suggestion echo is disabled entirely

### Extractor

Extracts structured trip data from user text.

| Mode | Prompt | Max Tokens | Trigger |
|------|--------|------------|---------|
| Light | `extractor_light.txt` | 200 | `turn_number < 3` OR simple input |
| Full | `extractor.txt` | 400 | Complex input OR multiple fields detected |

### Router

Intent classification node with multi-signal scoring.

| Signal | Weight | Description |
|--------|--------|-------------|
| Domain keywords | High | "flight", "hotel", "activities" |
| Question + keyword | High | "what hotels?" pattern |
| Extraction fields | Medium | Which fields were extracted |
| User intent | Medium | From extraction confidence |

### Specialists

Domain-specific nodes with gating logic:

| Gate | Condition | Behavior |
|------|-----------|----------|
| Core fields missing | `ready_to_generate = False` | Block, redirect to required_fields |
| Pre-core mode | Domain keyword + core missing | Template response + core question |
| Full mode | All core fields present | Full LLM response |

### Keyword Filtering Rules

Keywords must be **specific enough** to avoid false positives:

| Avoided Keyword | Reason | Replacement |
|-----------------|--------|-------------|
| `stay` | Matches "during my stay" | `where to stay`, `place to stay` |
| `rental` | Matches "equipment rental" | `car rental`, `rent a car` |
| `car` | Matches "cable car" | `car rental`, `rent a car` |
| `drive` | Matches "drive for adventure" | `drive there`, `driving directions` |
| `booking` | Ambiguous | `book a room`, `book flights` |

Keywords are defined in:
- `routing_keywords.py` - Master keyword-to-intent mapping
- `plan_graph.py` - Multi-domain detection and router fallback
- `planner/nodes/strategy/base.py` - Strategy topic switch detection

### Strategy Topic Switch Routing

When user switches from strategy (e.g., hiking) to a domain (e.g., hotels):

| Detected Switch | Routed To | Example |
|-----------------|-----------|---------|
| `hotels` | `hotels_node` | "I want to book hotels" |
| `flights` | `flights_node` | "I want to book flights" |
| `ground_transport` | `transport_node` | "I need a car rental" |
| `activities` | `activities_node` | "What activities are there?" |

This ensures domain-specific requests get proper specialist handling even when initiated from a strategy context.

### Strategy Orchestrator (Plan Generation)

When `generate_responder` is triggered, it calls the strategy orchestrator to enrich branches with LLM-generated content.

**Location:** `planner/nodes/strategy/orchestrator.py`

| Function | Purpose |
|----------|---------|
| `detect_relevant_strategies(state)` | Maps `activity_settings.categories` to strategy topics |
| `orchestrate_strategies(state)` | Calls strategy nodes in parallel via `asyncio.gather` |
| `call_strategy_for_plan(state, topic)` | LLM call for single topic (1536 tokens max) |
| `parse_strategy_response(response, topic)` | Extracts vibe, highlights, flow, notes from markdown |
| `merge_strategy_results(results)` | Combines multiple strategy results into one |

**Category to Strategy Mapping:**

| Activity Category | Strategy Topic |
|-------------------|----------------|
| hiking, trekking, mountains, trails | `hiking` |
| diving, scuba, snorkeling, underwater | `diving` |
| skiing, snowboarding, winter sports | `skiing` |
| cycling, biking, bicycle | `cycling` |
| boating, sailing, yachting, kayaking | `boating` |

**Branch Enrichment Fields (StrategyContent):**

| Field | Type | Description |
|-------|------|-------------|
| `vibe` | `string` | Trip mood/theme (1 sentence) |
| `focus` | `string` | Trip focus description |
| `highlights` | `string[]` | Key experiences (3-5 items) |
| `flow` | `string[]` | Day-by-day outline (3-7 items) |
| `notes` | `string[]` | Practical tips (3-4 items) |
| `one_liner` | `string` | Single sentence trip essence (max 80 chars) |
| `principles` | `string[]` | Core approach chips (2-4 items, max 50 chars each) |
| `must_dos` | `string[]` | Essential experiences (3-5 items) |
| `optional_upgrades` | `string[]` | Nice-to-haves (2-3 items) |
| `logistics_notes` | `string[]` | Practical logistics tips (2-4 items) |
| `tradeoffs_summary` | `string` | Why this approach (max 300 chars) |
| `strategy_node_id` | `string` | Provenance identifier (e.g., "hiking_strategist_v1") |
| `strategy_version` | `string` | Prompt/logic version |

---

## Strategy Stages

| Stage | Name | Trigger | Max Tokens | Gate | Output |
|-------|------|---------|------------|------|--------|
| 0 | Pre-Core | Strategy topic + dates + destination | 450 | `STRATEGY_PRE_CORE_VALUE` (80) | Duration-aware itinerary + 1 question |
| 1 | Outline | Core fields complete + `last_strategy_topic` | 512 | `STRATEGY_POST_CORE` (35) | Activity outline with sections |
| 2 | Expansion | User requests "show more" | 600-1536 | `STRATEGY_EXPANSION` (10) | Expanded section or full plan |

### Duration Context

| Days | Context |
|------|---------|
| ≤3 | Short trip - focus on highlights |
| 4-5 | Standard trip - balance highlights with free time |
| 6-7 | Week trip - deeper exploration |
| 8-14 | Extended trip - regional exploration |
| >14 | Long trip - comprehensive exploration |

---

## Gate Precedence Reference

Gates are checked in strict precedence order. First match wins.

| Precedence | Gate Name | Destination | Trigger Condition | Description |
|------------|-----------|-------------|-------------------|-------------|
| 10 | `STRATEGY_EXPANSION` | `strategy_node` | "show more" + pending expansion | Expansion on existing strategy |
| 20 | `GENERATE_REQUESTED` | `generate_responder` | "generate my itinerary" pattern | Explicit generate request |
| 30 | `SHORT_CIRCUIT` | `short_circuit_responder` | Greeting/yes/no/thanks patterns | Quick response bypass |
| 30 | `INFEASIBILITY_DETECTION` | `correction_node` | Infeasibility signals detected | Conflict handling |
| 35 | `STRATEGY_POST_CORE` | `strategy_node` (stage 1) | core_complete + last_strategy_topic | Stage 1 after core complete |
| 38 | `STRATEGY_TOPIC_SWITCH` | `strategy_node` | Intent verb + new topic + cooldown | Mid-session topic change (before READY_NO_FIELDS) |
| 40 | `READY_NO_FIELDS` | `summarize` / specialist / `strategy_node` | core_complete + no blocking errors | Ready state routing |
| 50 | `FAST_PATH` | `required_fields_node` | strategy_bootstrap_active | Bootstrap optimization |
| 60 | `SPECIALIST_PRE_CORE` | Specialists (pre-core) | Domain keyword + core missing | Pre-core domain response |
| 80 | `STRATEGY_PRE_CORE_VALUE` | `strategy_node` (stage 0) | Strategy topic + dates + destination | Value-first response |
| 90 | `CORE_COLLECTION` | `required_fields_node` | Core fields missing | Collect missing fields |
| 110 | `QUESTION_KEYWORD` | Based on keyword | Question word + domain keyword | Question heuristic |
| 999 | `ROUTER_LLM` | `router` node | Fallback | LLM classification |

### Gate Suppression Rules

- `SPECIALIST_PRE_CORE` yields to `STRATEGY_PRE_CORE_VALUE` when strategy topic detected
- `READY_NO_FIELDS` routes to specialist nodes when explicit domain keywords detected
- `READY_NO_FIELDS` routes to `strategy_node` when activity keywords detected (hiking, diving, etc.)

---

## Short Circuits Reference

### Short Circuit Types

| Type | Pattern | Handler | Tokens Saved | Example |
|------|---------|---------|--------------|---------|
| `greeting` | `GREETING_PATTERN` | `short_circuit_responder` | ~800-1500 | "hi", "hello", "hey" |
| `confirmation_yes` | `YES_PATTERN` | `short_circuit_responder` | ~800-1500 | "yes", "yeah", "yep" |
| `confirmation_no` | `NO_PATTERN` | `short_circuit_responder` | ~800-1500 | "no", "nope", "cancel" |
| `confirm_typo` | Typo confirmation flow | `required_fields_node` | ~500 | "yes that's right" (after typo check) |
| `field_answer` | Field-specific safety net | `required_fields_node` | ~500 | Direct answer to last question |
| `generate_request` | `GENERATE_REQUEST_PATTERN` | `generate_responder` | ~500 | "generate my itinerary" |
| `off_topic` | Router detection | `summarize` | ~500 | Non-travel queries |
| `strategy_bootstrap` | Simple strategy prompts | Skip extractor | ~500-1000 | "I want to go hiking" |
| `initial_extraction` | First message patterns | Skip extractor | ~500-1000 | Destination-only input |

### Short Circuit Detection Flow

```python
def _detect_short_circuit(text, state):
    # 1. Skip if input > 200 chars
    # 2. Check GREETING_PATTERN
    # 3. Check GENERATE_REQUEST_PATTERN (if core complete)
    # 4. Check YES_PATTERN with pending_action
    # 5. Check NO_PATTERN
    # 6. Check typo confirmation flow (confirm_typo)
    # 7. Check field-specific answer (field_answer)
    # 8. Return None → normal pipeline
```

### Extractor Bypass Conditions

| Bypass | Trigger | Result |
|--------|---------|--------|
| Greeting bypass | `GREETING_PATTERN` match | Empty extraction |
| Initial extraction | First message with destination patterns | Deterministic parsing |
| Strategy bootstrap | Simple strategy prompt | Skip extractor LLM |

---

## Caching Architecture

### Cache Implementations

| Cache | Class | Max Size | TTL | Key Components | Purpose |
|-------|-------|----------|-----|----------------|---------|
| `ExtractorCache` | `CacheNode` | 100 | 300s | session_id, user_text_hash, core_fields_hash, extractor_mode, model_id | Avoid re-extracting same input |
| `ResponseCache` | `CacheNode` | 200 | 3600s | node_name, core_fields_hash, follow_up_hash, user_text_hash, model_id, settings_hash | Reuse specialist responses |
| `StrategyCache` | `CacheNode` | 100 | 300s | session_id, topic, core_fields_hash, user_text_hash, section_id, stage0_lifecycle_hash, model_id | Reuse strategy content |
| `TileCache` | `CacheNode` | 100 | 300s | session_id, tile_type, query_hash | Cache tile API results |
| `GateEvaluationCache` | `CacheNode` | 200 | 300s | session_id, user_text_hash, trip_inputs_hash, metadata_hash | Cache routing decisions |

### Per-Node Caching Strategy

| Node | Cache Used | Key | Hit Condition | Invalidation |
|------|------------|-----|---------------|--------------|
| `lqa_prepass` | None | — | — | Stateless parser |
| `extractor` | `ExtractorCache` | session+text+fields+mode+model | Same input with same state | Core fields change, TTL |
| `router` | `ResponseCache` | node+fields+followup+text+model | Same context | Core fields change, TTL |
| `required_fields_node` | Template cache | — | Template match | — |
| `flights_node` | `ResponseCache` | specialist+fields+intent+settings | Same trip context | Core/settings change |
| `hotels_node` | `ResponseCache` | specialist+fields+intent+settings | Same trip context | Core/settings change |
| `transport_node` | `ResponseCache` | specialist+fields+intent+settings | Same trip context | Core/settings change |
| `activities_node` | `ResponseCache` | specialist+fields+intent+settings | Same trip context | Core/settings change |
| `strategy_node` | `StrategyCache` | topic+fields+text+section+lifecycle | Same topic + fields | Topic switch, TTL |
| `tile_search` | `TileCache` | intent+dest+dates+travelers+settings | Same query params + settings | Traveler/date/settings change |

### Cache Invalidation Triggers

| Trigger | Caches Invalidated |
|---------|-------------------|
| Core fields change | extractor, response, strategy, tile |
| `end_date` change | tile |
| `adults/children` change | tile |
| `budget` change | None (client-side filtering) |
| `hotel_settings` change | tile (hotels) |
| `flight_settings` change | tile (flights) |
| `activity_settings` change | tile (activities) |
| Strategy topic switch | strategy |
| Session timeout | All |
| Explicit clear | All (via `clear_all_caches()`) |

### Cache Version Control

All caches use payload wrapping with version metadata:

```python
CachePayload:
    - schema_version: int      # CACHE_SCHEMA_VERSION
    - logic_version: int       # NODE_LOGIC_VERSION[node]
    - prompt_bundle_hash: str  # Hash of all prompt files
    - planner_build_id: str    # Build identifier
    - created_at: float
    - data: Any
```

### Validation Cache (Origin/Destination Verification)

Located in `backend/app/validation.py`, this cache stores LLM-verified place names.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `validation_cache_size` | 5000 | Max entries before LRU eviction |
| `validation_cache_ttl` | 604800 (7 days) | Time before entries expire |

**Cache Layers:**

| Cache | Purpose | TTL |
|-------|---------|-----|
| `_validation_cache` | Positive validation results | 7 days |
| `_negative_cache` | Invalid locations | 15 minutes |
| `_split_cache` | Multi-destination splits ("Paris and Rome") | 7 days |
| `_prompt_cache` | Formatted prompts | 7 days |
| `_fallback_cache` | Last known good answer | 7 days |
| `_rate_counter_cache` | Per-session rate limiting counters | 5 minutes |

**When Validation is Called:**
- Origin extracted from "from X to Y" pattern
- Origin NOT in `KNOWN_CITIES`
- Cache miss (not verified in last 7 days)

**Token Cost:** ~100-120 tokens per LLM verification call

**Progressive Learning:**
- Verified places logged as `LEARNED_PLACE: '{place}' verified`
- Review logs periodically to add popular places to `KNOWN_CITIES`

### Image Cache (Unsplash)

Located in `backend/app/services/unsplash.py`, this two-tier cache stores destination images.

**Tier 1: In-Memory Cache**

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Storage | Python dict `_memory_cache` | Hot cache within process |
| TTL | None (process lifetime) | Lost on server restart |
| Key format | `"destination:variant"` | e.g., `"paris:0"`, `"paris:hiking:2"` |
| Max variants | 6 per destination | Different images for different tiles |

**Tier 2: Database Cache**

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Table | `unsplash_image_cache` | Persistent across restarts |
| TTL | None (permanent) | Images never expire |
| Primary Key | `(destination, variant)` | Composite key for multi-variant support |

**Lookup Order:**
1. In-memory cache (fastest)
2. Database cache (persistent)
3. Unsplash API (fresh fetch)
4. Picsum fallback (deterministic seed-based)

**Stored Fields:**
- `image_id`: Unsplash image ID
- `photographer`: Photographer name
- `photographer_url`: Profile link
- `unsplash_url`: Image page URL
- `download_location`: API endpoint for tracking

---

## Prompt File Mapping

### Main Prompts

| File | Used By | Max Tokens | In Hash | Purpose |
|------|---------|------------|---------|---------|
| `extractor.txt` | `extractor` (full) | 400 | Yes | Full trip data extraction |
| `extractor_light.txt` | `extractor` (light) | 200 | Yes | Light extraction for simple inputs |
| `router.txt` | `router` | 256 | Yes | Intent classification |
| `required_fields.txt` | `required_fields_node` | 180 | Yes | Collect missing core fields |
| `required_fields_confirm.txt` | `required_fields_node` | 180 | No | Typo confirmation |
| `flights.txt` | `flights_node` | 512 | Yes | Flight preferences |
| `hotels.txt` | `hotels_node` | 512 | Yes | Hotel preferences |
| `transport.txt` | `transport_node` | 512 | Yes | Ground transport |
| `activities.txt` | `activities_node` | 512 | Yes | Activity preferences |
| `correction.txt` | `correction_node` | 512 | Yes | Handle corrections |
| `general.txt` | `general_node` | 512 | Yes | Multi-domain queries |
| `missing_fields_guard.txt` | `_invoke_guard` | 100 | No | Missing fields guard |
| `condense.txt` | `condense_long_message` | 256 | No | Condense long messages |
| `required_fields_templates.json` | `required_fields_node` | N/A | Yes | Template cache for field collection |

### Strategy Prompts

| File | Topic | Max Tokens | In Hash |
|------|-------|------------|---------|
| `strategy_pre_core.txt` | All (unified) | 450 | Yes |
| `strategy_pre_core_known_dest.txt` | All (with dest) | 450 | Yes |
| `strategy_pre_core_discovery.txt` | All (discovery) | 450 | Yes |
| `strategy_general.txt` | general | 512-1536 | No |
| `strategy_hiking.txt` | hiking | 512-1536 | Yes |
| `strategy_diving.txt` | diving | 512-1536 | Yes |
| `strategy_skiing.txt` | skiing | 512-1536 | Yes |
| `strategy_cycling.txt` | cycling | 512-1536 | Yes |
| `strategy_boating.txt` | boating | 512-1536 | Yes |

### Shared Includes (Helper Prompts)

| File | Purpose | In Hash |
|------|---------|---------|
| `_json_output.txt` | JSON output format rules | No |
| `_scope_specialist.txt` | Specialist scope rules | No |
| `_never_invent.txt` | Never invent data rule | No |
| `_markdown_rules.txt` | Markdown formatting rules | No |
| `_strategy_base.txt` | Strategy base template | No |

> **Note:** Helper prompts prefixed with `_` are included by other prompts and not directly in the prompt bundle hash.

---

## Streaming Architecture

### Current Implementation: Real-Time + UX Simulated Streaming

The streaming architecture uses **real-time token streaming** for LLM responses and **simulated streaming** for non-LLM responses. This ensures users see tokens as the LLM generates them while maintaining consistent UX for all response types.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STREAMING FLOW                                                             │
│  ──────────────────────────────────────────────────────────────────────────│
│                                                                              │
│  LLM RESPONSES (Real-Time):                                                  │
│  1. User sends message                                                       │
│  2. run_turn_streaming() creates StreamingContext                            │
│  3. Graph runs in background task                                            │
│  4. LLM nodes stream assistant_message tokens via StreamingContext           │
│  5. Tokens yielded to SSE as they arrive                                     │
│  6. After streaming completes: parse JSON, apply deltas, set question_target │
│                                                                              │
│  User sees: Tokens appear immediately as LLM generates them 🌊               │
│                                                                              │
│  NON-LLM RESPONSES (UX Simulated):                                           │
│  1. Graph completes (no tokens emitted during execution)                     │
│  2. Final message streamed via simulate_streaming() with 15-35ms delays      │
│                                                                              │
│  User sees: Token-by-token appearance with natural timing ✨                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### StreamingContext Pattern

Real-time streaming is achieved via `StreamingContext` stored in a module-level registry.
The context is NOT stored in `state.metadata` because `asyncio.Queue` is not serializable by LangGraph's checkpointer.

```python
# In run_turn_streaming()
from app.planner.streaming import (
    StreamingContext, register_streaming_context, unregister_streaming_context
)

streaming_ctx = StreamingContext()
register_streaming_context(turn_thread_id, streaming_ctx)
state.metadata["_streaming_thread_id"] = turn_thread_id  # Only store the lookup key

# In specialist/strategy nodes
from app.planner.streaming import get_streaming_context

thread_id = state.metadata.get("_streaming_thread_id")
streaming_ctx = get_streaming_context(thread_id)
out = await call_llm_streaming_with_json_field(
    model=model,
    prompt=prompt,
    stream_field="assistant_message",  # Only stream this field
    streaming_ctx=streaming_ctx,
    ...
)
# AFTER streaming completes - parse JSON and apply deltas

# Cleanup (in run_turn_streaming after graph completes)
unregister_streaming_context(turn_thread_id)
```

### Streaming Modes

| Mode | Symbol | Function | Behavior |
|------|--------|----------|----------|
| `real:llm` | 🌊 | `call_llm_streaming_with_json_field()` | Real-time tokens from OpenAI |
| `simulated:template` | ✨ | `simulate_streaming()` | Token-by-token 15-35ms delays |
| `simulated:cached` | ✨ | `simulate_streaming()` | Token-by-token 15-35ms delays |
| `simulated:deterministic` | ✨ | `simulate_streaming()` | Token-by-token 15-35ms delays |
| `simulated:llm_fallback` | ✨ | `simulate_streaming()` | Fallback when LLM didn't stream |
| `buffered:internal` | 🔒 | N/A | No streaming (internal nodes) |

### Streaming by Node Type

| Category | Nodes | LLM Call | Response Delivery | Symbol |
|----------|-------|----------|-------------------|--------|
| Internal | extractor, router, lqa_prepass, normalize_inputs, validate_and_merge | Buffered | None (internal state) | 🔒 |
| Strategy LLM | stage0, stage1, stage2 | `call_llm_streaming_with_json_field` | Real-time | 🌊 |
| Specialist LLM | flights, hotels, transport, activities, correction, general | `call_llm_streaming_with_json_field` | Real-time | 🌊 |
| Template | required_fields:template, pre_core templates | N/A | `simulate_streaming` | ✨ |
| Cached | any:cache | N/A | `simulate_streaming` | ✨ |
| Deterministic | short_circuit_responder, summarize | N/A | `simulate_streaming` | ✨ |

**Legend:**
- 🔒 **None** - Internal nodes, no user-facing output
- 🌊 **Real** - Tokens streamed in real-time from OpenAI during graph execution
- ✨ **UX Simulated** - Token-by-token with delays after graph completes

### Streaming Parameters (Consistent Across All Modes)

All simulated streaming uses consistent timing parameters defined in `streaming.py`:

```python
STREAMING_PARAMS = {
    "base_delay_ms": 15,   # Minimum delay between tokens
    "max_delay_ms": 35,    # Maximum delay between tokens
    "jitter_ms": 8,        # Random jitter range
    "chunk_size": 1,       # Single tokens
}
```

### Provenance to Streaming Mode Mapping

| Provenance | Description | Delivery Mode |
|------------|-------------|---------------|
| `llm` | Real-time LLM response | 🌊 Real-time during execution |
| `template` | Template-generated response | ✨ `simulate_streaming` |
| `deterministic` | Pure Python logic response | ✨ `simulate_streaming` |
| `codegen` | Code-generated response | ✨ `simulate_streaming` |
| `cached` | Retrieved from cache | ✨ `simulate_streaming` |
| `llm_fallback` | LLM didn't stream (unexpected) | ✨ `simulate_streaming` |

### Critical Sequencing for Real-Time Streaming

**IMPORTANT**: For LLM responses, deltas and state mutations are applied **ONLY AFTER** streaming completes:

```
1. Start streaming LLM call
2. Emit assistant_message tokens to frontend as they arrive
3. Accumulate full JSON response in background
4. Stream completes (all tokens received)
5. Parse complete JSON
6. Apply deltas to trip_inputs
7. Set question_target, suggested_responses
8. Return updated state
```

This ensures:
- User sees tokens immediately (good UX)
- Deltas extracted from complete, validated JSON (data integrity)
- No partial state visible during streaming

---

## Token Savings Summary

| Optimization | Tokens Saved | Frequency |
|--------------|--------------|-----------|
| LQA prepass success | ~500-1000 | ~30% of turns |
| Light extractor mode | ~200-270 | ~60% of turns |
| Template responses | ~500-1500 | ~40% of turns |
| Cache hits | ~500-2000 | ~20% of turns |
| Scoring router bypass | ~256 | ~50% of turns |
| Strategy bootstrap | ~500-1000 | ~10% of turns |
| Response polish skip | ~512 | ~50% of turns |

---

## Retention Policy Summary

Comprehensive view of all cache and data retention policies.

### LLM Response Caches (In-Memory)

| Cache | TTL | Max Size | Configurable |
|-------|-----|----------|--------------|
| ResponseCache | 1 hour | 200 | `response_cache_ttl_seconds` |
| ExtractorCache | 5 minutes | 100 | `extractor_cache_ttl_seconds` |
| StrategyCache | 5 minutes | 100 | `strategy_cache_ttl_seconds` |
| GateEvaluationCache | 5 minutes | 200 | (hardcoded) |
| TileCache | 5 minutes | 100 | (hardcoded) |

### Validation Caches (In-Memory)

| Cache | TTL | Max Size | Configurable |
|-------|-----|----------|--------------|
| Place validation | 7 days | 5000 | `validation_cache_ttl` |
| Negative cache | 15 minutes | 500 | `validation_negative_cache_ttl` |
| Split cache | 7 days | 500 | `validation_split_cache_size` |
| Prompt cache | 7 days | 500 | `validation_prompt_cache_size` |
| Fallback cache | 7 days | 500 | `validation_fallback_cache_size` |
| Rate counter | 5 minutes | 10000 | `validation_rate_limit_window` |

### Image Caches

| Cache | TTL | Storage | Configurable |
|-------|-----|---------|--------------|
| Unsplash in-memory | Process lifetime | Python dict | None |
| Unsplash DB | Permanent | PostgreSQL | None |

### Session & State

| Component | TTL | Storage | Configurable |
|-----------|-----|---------|--------------|
| Session Cookie | 14 days | Browser | `SESSION_MAX_AGE` |
| DB Session (idle) | 14 days | PostgreSQL | `SESSION_IDLE_TIMEOUT_DAYS` |
| DB Session (absolute) | 90 days | PostgreSQL | `SESSION_ABSOLUTE_TIMEOUT_DAYS` |
| LangGraph Checkpoints | 24 hours | In-memory | `checkpoint_ttl_hours` |

### Persistent Data (No TTL)

| Component | Storage | Notes |
|-----------|---------|-------|
| PlanDocument | PostgreSQL | Trip data, branches, tiles, selections |
| Chat Messages | PostgreSQL | Full conversation history |
| Unsplash Images | PostgreSQL | Cached image metadata with attribution |

---

## Key Exports

| Module | Exports |
|--------|---------|
| `planner` | `run_turn`, `run_turn_streaming`, `GateEvaluator` |
| `planner.gates` | `GatePrecedence`, `GateResult`, `TripReadiness`, `compute_trip_readiness`, `GateEvaluator` |
| `planner.gates.implementations` | All 13 individual gate classes |
| `planner.cache` | `CacheNode`, `ResponseCache`, `ExtractorCache`, `StrategyCache`, `TileCache`, `GateEvaluationCache` |
| `planner.normalization` | `DateNormalizer`, `DateProvenance`, `TripInputNormalizer`, `NormalizationError` |
| `planner.parsing` | `PARSE_PROVENANCE_PRECEDENCE`, `LQA_FIELD_PARSERS` |
| `planner.gates.topic_detection` | `detect_strategy_topic_from_text`, `detect_strategy_topic_from_settings`, `detect_strategy_topic` |
| `planner.gates.suppression` | `SuppressionPredicates` |
| `planner.gates.checks` | `is_strategy_expansion_request`, `is_vague_affirmation`, `StrategyExpansionResult`, `StrategyTier`, `STRATEGY_TIER_MAX_TOKENS`, `StrategyExpansionTarget` |
| `planner.state` | `StateWriter` (methods: `set_question_target`, `write_trip_input`, `write_trip_inputs`, `set_metadata`, `get_mutations`, `get_mutation_summary`, `get_applied_updates`, `set_active_category`, `set_last_summary`, `set_suggested_responses`, `set_pending_strategy_expansion`, `set_flag`, `set_parsed_inputs`, `apply`) |
| `planner.nodes` | `extractor`, `lqa_prepass`, `router`, `_specialist`, `_strategy_stage0`, `strategy_node` |
| `planner.nodes.schemas` | `ExtractorOutput`, `RouterOutput`, `BudgetDelta`, `IntentType`, `TopicType` |
| `planner.nodes.strategy` | `orchestrate_strategies`, `merge_strategy_results`, `detect_relevant_strategies`, `StrategyContent`, `StrategyResult` |

---

## Admin Cache Management Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/admin/clear-validation-cache` | POST | Clear validation caches, re-populate with common values |
| `/v1/admin/fresh-start` | POST | Clear validation + response + prune stale checkpoints (preserves rate limiting) |
| `/v1/admin/clear-all-checkpoints` | POST | Clear ALL LangGraph checkpoints |
| `/v1/admin/clear-all-caches` | POST | **Comprehensive clear of ALL caches including Unsplash** |

### `/v1/admin/clear-all-caches`

Clears everything:

| Cache System | What's Cleared |
|--------------|----------------|
| Planner Framework | ResponseCache, ExtractorCache, StrategyCache, TileCache, GateEvaluationCache |
| Validation | All 6 validation caches including rate limiting |
| Unsplash Memory | In-memory image cache (`_memory_cache`) |
| Unsplash Database | Persistent image cache (`UnsplashImageCache` table) |
| Checkpoints | All LangGraph checkpoints |
| Prompts | LRU prompt cache, Jinja2 template cache, `_PROMPTS_LOADED` set |

**Response Format:**

```json
{
    "timestamp": "2024-01-15T10:30:00.000000",
    "caches_cleared": {
        "planner_and_validation": 150,
        "unsplash_memory": 45,
        "unsplash_database": 100
    },
    "total_entries_cleared": 295,
    "before": {
        "validation": {"positive": 100, "negative": 50, ...},
        "response": {"follow_up": 50},
        "checkpoints": {"total": 5},
        "unsplash_memory": {"entries": 45, "destinations": 15}
    },
    "after": {
        "validation": {"positive": 0, "negative": 0, ...},
        "response": {"follow_up": 0},
        "checkpoints": {"total": 0},
        "unsplash_memory": {"entries": 0, "destinations": 0}
    }
}
```

---

## Tile Service Architecture

### Tile Refresh Endpoint

Tiles can be refreshed on-demand when user preferences change mid-conversation.

```
POST /v1/tiles/refresh
```

| Field | Type | Description |
|-------|------|-------------|
| `branch_id` | string | Branch to refresh tiles for |
| `verticals` | string[] | Optional: ["hotel", "flight", "activity"] |

**Flow:**
1. Frontend detects settings change (via `useBranchManager.ts`)
2. Calls `refreshTiles()` API with affected verticals
3. Backend clears TileCache for affected cache keys
4. Fresh tiles fetched from providers with new settings
5. Response includes updated tiles for display

### Provider Architecture

```
tile_service/
├── __init__.py           # Exports: search_tiles + booking types
├── models.py             # SearchContext, TileSearchRequest
├── service.py            # search_tiles() orchestrator
├── provider_base.py      # Provider ABC + BookableProvider ABC
└── mock_provider.py      # MockHotelProvider, MockFlightProvider, MockActivityProvider
```

| Class | Type | Purpose |
|-------|------|---------|
| `Provider` | ABC | Base for search-only providers |
| `BookableProvider` | ABC | Extends Provider with booking methods |
| `MockHotelProvider` | Provider | Settings-aware hotel tiles |
| `MockFlightProvider` | Provider | Settings-aware flight tiles |
| `MockActivityProvider` | Provider | Settings-aware activity tiles |

### Settings-Aware Tile Filtering

Mock providers filter results based on `trip_inputs` settings:

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

| Flow | Use Case | Example Providers |
|------|----------|-------------------|
| `REDIRECT` | Affiliate programs | Booking.com, Expedia affiliates |
| `EMBEDDED` | Direct API booking | Amadeus, Stripe-integrated |
| `HYBRID` | API hold + partner payment | Some OTAs |

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
| `PENDING_PAYMENT` | Awaiting payment (embedded flow) |
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
