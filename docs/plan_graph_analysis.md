# Plan Graph Architecture

> **Source**: `backend/app/plan_graph.py` > **Planner Package**: `backend/app/planner/` > **Prompt Files**: `backend/app/prompts/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Package Structure](#package-structure)
3. [Node Architecture Diagram](#node-architecture-diagram)
4. [Node Inventory](#node-inventory)
5. [Key Node Details](#key-node-details)
   - [LQA Prepass](#lqa-prepass)
   - [Extractor](#extractor)
   - [Router](#router)
   - [Required Fields](#required-fields)
   - [Specialists](#specialists)
6. [Strategy Stages](#strategy-stages)
7. [Gate Precedence](#gate-precedence)
8. [Short Circuits & Caching](#short-circuits--caching)
9. [Streaming Architecture](#streaming-architecture)
10. [Prompt Files](#prompt-files)

---

## Architecture Overview

LangGraph-based conversational trip planning system with **18 nodes**.

| Category            | Count | Description                       |
| ------------------- | ----- | --------------------------------- |
| LLM-Powered Nodes   | 10    | Use OpenAI API for generation     |
| Deterministic Nodes | 8     | Pure Python logic, no LLM         |
| Short Circuit Types | 7     | Bypass patterns for fast response |
| Caching Strategies  | 4     | Token-saving cache mechanisms     |

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
├── streaming.py             # Streaming infrastructure
├── telemetry.py             # Telemetry instrumentation
├── test_mode.py             # Test mode detection
├── cache/                   # Unified caching framework (consolidated)
│   ├── __init__.py          # Cache exports
│   ├── framework.py         # CacheNode ABC + ResponseCache, ExtractorCache, StrategyCache, TileCache
│   └── compat.py            # Backward-compatible function signatures for plan_graph.py
├── normalization/           # Trip input normalization
│   ├── __init__.py          # Normalization exports
│   ├── types.py             # NormalizationError dataclass
│   ├── date.py              # DateNormalizer, DateProvenance (~580 lines)
│   └── trip_inputs.py       # TripInputNormalizer (~890 lines)
├── parsing/                 # Parse functions consolidation
│   ├── __init__.py          # Parsing exports
│   ├── provenance.py        # Parse provenance tracking (precedence-based)
│   └── lqa_parsers.py       # LQA field parsers (~500 lines)
├── gates/
│   ├── __init__.py          # Gate exports
│   ├── precedence.py        # GatePrecedence IntEnum (10-999)
│   ├── result.py            # GateResult dataclass
│   ├── constants.py         # DateErrorCode, CORE_FIELD_PRIORITY, CANONICAL_FIELD_ORDER
│   ├── readiness.py         # TripReadiness dataclass + compute_trip_readiness()
│   ├── evaluator.py         # GateEvaluator orchestrator (~400 lines, decomposed)
│   ├── types.py             # GraphMetadata TypedDict (70+ keys)
│   ├── suppression.py       # SuppressionPredicates (bridge, lifecycle, etc.)
│   ├── checks/
│   │   ├── __init__.py      # Check function exports
│   │   ├── strategy.py      # Strategy expansion checks (StrategyTier, etc.)
│   │   └── short_circuit.py # Vague affirmation detection
│   └── implementations/     # Individual gate classes (Phase 2 extraction)
│       ├── __init__.py      # Gate class exports + GATE_REGISTRY
│       ├── short_circuit.py # ShortCircuitGate (30), InfeasibilityGate (30)
│       ├── generate_requested.py # GenerateRequestedGate (precedence 20)
│       ├── ready_no_fields.py # ReadyNoFieldsGate (precedence 40)
│       ├── fast_path.py     # FastPathGate (precedence 50)
│       ├── specialist_pre_core.py # SpecialistPreCoreGate (precedence 60)
│       ├── strategy_topic_switch.py # StrategyTopicSwitchGate (precedence 70)
│       ├── strategy_pre_core.py # StrategyPreCoreValueGate (80), WithDestGate (85)
│       ├── strategy_expansion.py # StrategyExpansionGate (precedence 10)
│       ├── strategy_post_core.py # StrategyPostCoreGate (precedence 35)
│       ├── core_collection.py # CoreCollectionGate (precedence 90)
│       ├── heuristic_gates.py # HighConfidenceGate (100), QuestionKeywordGate (110), KeywordHeuristicGate (120)
│       └── router_llm.py    # RouterLLMGate (precedence 999, fallback)
├── gates/base.py            # Gate ABC, GateContext, build_result() factory
├── gates/topic_detection.py # detect_strategy_topic_from_text()
├── state/
│   ├── __init__.py          # State exports
│   └── writer.py            # StateWriter class (SSoT enforcement)
└── nodes/
    ├── __init__.py          # Node exports
    ├── base.py              # NodeContext, node_decorator
    ├── confidence.py        # build_extraction_confidence(), high_confidence(), low_confidence_error()
    ├── llm_utils.py         # measure_llm_call() context manager, LLMCallTimer
    ├── lqa_prepass.py       # LQA pre-pass node (~439 lines)
    ├── router.py            # Router node (~130 lines)
    ├── extractor.py         # Extractor node (~480 lines)
    ├── specialist_main.py   # Shared specialist handler (decomposed, uses guards.py/templates.py)
    ├── strategy_main.py     # Strategy nodes (decomposed, uses base.py/stage0.py)
    ├── specialist/          # Specialist subpackage (Phase 3 extraction - fully wired)
    │   ├── __init__.py      # Re-exports from specialist_main.py + submodules
    │   ├── base.py          # CORE_FIELDS, SPECIALIST_TYPES, prompt selection
    │   ├── guards.py        # check_core_field_guard, check_default_adults_gate, check_noop_gate
    │   └── templates.py     # determine_question_target, apply_template_response, handle_loop_guard
    └── strategy/            # Strategy subpackage (Phase 3 extraction - fully wired)
        ├── __init__.py      # Re-exports from strategy_main.py + submodules
        ├── base.py          # STRATEGY_KEYWORDS, is_strategy_enabled, has_strategy_keyword, detect_*
        └── stage0.py        # strategy_stage0(), STAGE0_FALLBACK_TEMPLATES, get_dest_known_fallback
```

### Key Exports

| Module                       | Exports                                                                                        |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| `planner`                    | `run_turn`, `run_turn_streaming`, `GateEvaluator`                                              |
| `planner`                    | `StreamingMode`, `INTERNAL_PROCESSING_NODES`, `get_streaming_mode`, `should_use_true_streaming`|
| `planner.gates`              | `GatePrecedence`, `GateResult`, `TripReadiness`, `compute_trip_readiness`, `GateEvaluator`     |
| `planner.gates`              | `GraphMetadata`, `SuppressionPredicates`                                                       |
| `planner.gates.checks`       | `is_strategy_expansion_request`, `is_vague_affirmation`, `StrategyTier`                        |
| `planner.gates.implementations` | `Gate`, `GateContext`, `GATE_REGISTRY`, all 15 individual gate classes                      |
| `planner.cache`              | `CacheNode`, `ResponseCache`, `ExtractorCache`, `StrategyCache`, `TileCache`                   |
| `planner.cache`              | `CacheStats`, `CachePayload`, `DiscardReason`, `clear_all_caches`, `get_all_cache_stats`       |
| `planner.cache.compat`       | `get_extractor_cached`, `set_extractor_cached`, `get_strategy_cached`, `set_strategy_cached`   |
| `planner.normalization`      | `DateNormalizer`, `DateProvenance`, `TripInputNormalizer`, `NormalizationError`, `normalize_str`|
| `planner.parsing`            | `set_parse_provenance_once`, `finalize_parse_provenance`, `get_parse_provenance`               |
| `planner.parsing`            | `LQA_FIELD_PARSERS`, `_parse_destination_answer`, `_parse_date_answer`, `_parse_budget_answer` |
| `planner.state`              | `StateWriter`                                                                                  |
| `planner.nodes`              | `extractor`, `lqa_prepass`, `router`, `_specialist`, `strategy_node`                           |
| `planner.nodes`              | `build_extraction_confidence`, `high_confidence`, `low_confidence_error`, `measure_llm_call`   |
| `planner.nodes.specialist`   | `CORE_FIELDS`, `check_core_field_guard`, `check_noop_gate`, `apply_template_response`          |
| `planner.nodes.strategy`     | `STRATEGY_KEYWORDS`, `has_strategy_keyword`, `detect_topic_switch`, `strategy_stage0`          |

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
│  • Max input: 80 chars                                                       │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                 ┌─────────────────┴─────────────────┐
                 │ LQA success                       │ LQA skip/fail
                 ▼                                   ▼
┌────────────────────────────┐    ┌────────────────────────────────────────────┐
│  normalize_inputs          │    │  extractor                                  │
│  ─────────────────         │    │  ─────────                                  │
│  Deterministic cleanup     │    │  LLM-based trip data extraction             │
│  • Date normalization      │    │  • Light mode: 128 tokens (turns 0-2)       │
│  • City name cleanup       │    │  • Full mode: 400 tokens (complex input)    │
│  • Field validation        │    │  • Cache: 60s TTL, keyed by input+fields    │
│  • Error detection         │    │  • Bypasses: greeting, initial extraction,  │
│  No LLM                    │    │    strategy bootstrap                       │
└────────────┬───────────────┘    └──────────────────┬─────────────────────────┘
             │                                       │
             └───────────────────┬───────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  GateEvaluator                                                               │
│  ─────────────                                                               │
│  Centralized routing logic - checks 15 gates in precedence order             │
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
│No LLM   │ │origin/etc │ │512 tok each │ │Cache:  │ │300-2048  │ │No LLM    │
│         │ │           │ │             │ │follow- │ │tokens    │ │          │
│         │ │256 tok    │ │Cache:       │ │up cache│ │          │ │          │
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
│  • Cache: session-scoped       │                │
│  • Keys: intent+dest+dates     │                │
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
│  Message tone and formatting                                                 │
│  • Deterministic-first: safe transforms without LLM                          │
│  • LLM fallback: response_polish.txt (512 tokens)                           │
│  • Skips: template responses, short-circuit messages                         │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
                              ┌─────────┐
                              │   END   │
                              └─────────┘
```

### Special Routing Paths

| Path               | Trigger                              | Flow                                      |
| ------------------ | ------------------------------------ | ----------------------------------------- |
| Short-circuit      | "hi", "thanks", "yes", "no"          | lqa → short_circuit_responder → summarize |
| LQA fast path      | Simple answer to question_target     | lqa → normalize → validate → summarize    |
| Strategy pre-core  | "plan hiking trip" + no destinations | extractor → strategy_node(stage0)         |
| Strategy post-core | core complete + last_strategy_topic  | GateEvaluator → strategy_node(stage1)     |
| Strategy expansion | "show more" + pending expansion      | GateEvaluator → strategy_node(stage2)     |
| Generate request   | "generate my itinerary"              | GateEvaluator → generate_responder        |
| Intent-only        | "what hotels?" (no context)          | GateEvaluator → summarize (template)      |

---

## Node Inventory

| Node                      | Prompt File            | LLM Model   | Max Tokens | Purpose                        |
| ------------------------- | ---------------------- | ----------- | ---------- | ------------------------------ |
| `lqa_prepass`             | —                      | —           | —          | Zero-LLM answer extraction     |
| `extractor`               | `extractor.txt`        | gpt-4o-mini | 400        | Extract trip data from text    |
| `normalize_inputs`        | —                      | —           | —          | Normalize extracted inputs     |
| `router`                  | `router.txt`           | gpt-4o-mini | 256        | Intent classification          |
| `required_fields_node`    | `required_fields.txt`  | gpt-4o-mini | 256        | Collect missing core fields    |
| `flights_node`            | `flights.txt`          | gpt-4o-mini | 512        | Flight preferences             |
| `hotels_node`             | `hotels.txt`           | gpt-4o-mini | 512        | Hotel preferences              |
| `transport_node`          | `transport.txt`        | gpt-4o-mini | 512        | Ground transport               |
| `activities_node`         | `activities.txt`       | gpt-4o-mini | 512        | Activity preferences           |
| `correction_node`         | `correction.txt`       | gpt-4o-mini | 512        | Handle corrections             |
| `general_node`            | `general.txt`          | gpt-4o-mini | 512        | Multi-domain queries           |
| `strategy_node`           | `strategy_{topic}.txt` | gpt-4o-mini | 300-2048   | Adventure activity planning    |
| `validate_and_merge`      | —                      | —           | —          | Compute readiness              |
| `branch_postprocess`      | —                      | —           | —          | Split multi-city branches      |
| `tile_search`             | —                      | —           | —          | Search for tiles               |
| `short_circuit_responder` | —                      | —           | —          | Handle greetings/confirmations |
| `generate_responder`      | —                      | —           | —          | Handle generation requests     |
| `summarize`               | —                      | —           | —          | Generate follow-ups            |
| `response_polish`         | `response_polish.txt`  | gpt-4o-mini | 512        | Polish message tone            |

---

## Key Node Details

### LQA Prepass

Zero-LLM pre-pass that attempts to parse simple answers to the last question asked.

**Function**: `lqa_prepass(state)`

| Condition                 | Action                                      |
| ------------------------- | ------------------------------------------- |
| Input ≤ 80 chars          | Attempt LQA parsing                         |
| Matches `question_target` | Skip extractor, route to `normalize_inputs` |
| Suggestion echo           | Direct match to suggested response          |
| Date-like input           | Parse via `is_text_date_compatible()`       |
| Number input              | Parse as travelers/budget                   |
| City name                 | Parse as destination/origin                 |

**Bypass conditions** (skip LQA):

- Input too long (> `LQA_MAX_LENGTH`)
- No `question_target` set
- Complex multi-field input detected

### Extractor

Extracts structured trip data from user text. Operates in two modes.

**Function**: `extractor(state)`

#### Light Mode vs Full Mode

| Mode  | Prompt                | Max Tokens | Trigger                                   |
| ----- | --------------------- | ---------- | ----------------------------------------- |
| Light | `extractor_light.txt` | 128        | `turn_number < 3` OR simple input         |
| Full  | `extractor.txt`       | 400        | Complex input OR multiple fields detected |

**Light mode selection** (`_should_use_light_extractor`):

- First 2 turns (bootstrapping phase)
- Short input (< 50 chars)
- Single field update detected
- No complex date ranges
- No multi-city indicators

**Full mode triggers**:

- Multi-city phrases ("and then", "after that")
- Complex date expressions ("from X to Y")
- Multiple field types in single message
- Correction/amendment language

#### Extraction Pipeline

1. **Short-circuit check**: Greeting/ack patterns → skip extraction
2. **Initial extraction**: `_try_initial_message_extraction()` for first message
3. **Strategy bootstrap**: `_try_strategy_bootstrap_bypass()` for simple strategy prompts
4. **Cache check**: Return cached result if same input recently
5. **LLM call**: Light or full mode based on complexity
6. **Merge**: Combine with existing `trip_inputs`

#### Key Functions

| Function                          | Purpose                                    |
| --------------------------------- | ------------------------------------------ |
| `_should_use_light_extractor`     | Determine light vs full mode               |
| `_try_initial_message_extraction` | Parse first message without LLM            |
| `_try_strategy_bootstrap_bypass`  | Skip extractor for simple strategy prompts |
| `_merge_extraction_result`        | Merge new extraction with existing state   |
| `_compute_extraction_confidence`  | Confidence score for routing decisions     |

### Router

Intent classification node that routes to appropriate specialists.

**Function**: `router(state)`

**Routing hierarchy** (checked in order):

1. **Gate bypass**: `GateEvaluator` already decided → skip router LLM
2. **Scoring router**: Deterministic multi-signal scoring
3. **High confidence**: `extraction_confidence > 0.92` + short input
4. **LLM fallback**: Use `router.txt` prompt

#### Scoring Router

Deterministic scoring based on multiple signals:

| Signal               | Weight | Description                     |
| -------------------- | ------ | ------------------------------- |
| Domain keywords      | High   | "flight", "hotel", "activities" |
| Question + keyword   | High   | "what hotels?" pattern          |
| Extraction fields    | Medium | Which fields were extracted     |
| User intent          | Medium | From extraction confidence      |
| Conversation context | Low    | Previous node, question_target  |

**Output**: Intent classification → specialist node routing

### Required Fields

Collects missing core fields (destinations, dates, origin, travelers, budget).

**Function**: `required_fields_node(state)` → `_specialist("required_fields", state)`

#### Core Fields Priority

Fields are collected in priority order (defined in `CORE_FIELD_PRIORITY`):

1. `destinations` - Where to go
2. `start_date` - When to depart
3. `end_date` - When to return
4. `origin` - Where traveling from
5. `adults` - Number of travelers
6. `budget` - Trip budget

#### Response Generation

| Condition            | Response Type                                                |
| -------------------- | ------------------------------------------------------------ |
| Template match       | Deterministic template from `required_fields_templates.json` |
| Ambiguous input      | Use `required_fields_confirm.txt` (typo detection)           |
| Complex situation    | LLM with `required_fields.txt`                               |
| Blocking date errors | Date clarification template                                  |

#### Key Functions

| Function                       | Purpose                                    |
| ------------------------------ | ------------------------------------------ |
| `compute_trip_readiness`       | Canonical missing fields computation       |
| `set_question_target`          | SSoT for question_target state             |
| `canonicalize_question_target` | Normalize field names (start_date → dates) |
| `_generate_date_suggestions`   | Generate relative date options             |

### Specialists

Domain-specific nodes for flights, hotels, transport, activities, corrections, and general queries.

**Shared function**: `_specialist(name, state)`

#### Specialist Gating

| Gate                | Condition                     | Behavior                           |
| ------------------- | ----------------------------- | ---------------------------------- |
| Core fields missing | `ready_to_generate = False`   | Block, redirect to required_fields |
| Pre-core mode       | Domain keyword + core missing | Template response + core question  |
| Full mode           | All core fields present       | Full LLM response                  |

#### Pre-Core Mode

When user asks domain question but core fields are missing:

1. Acknowledge the domain interest
2. Provide brief template response
3. Ask for missing core field
4. Set `question_target` appropriately

#### Specialist Prompts

Each specialist has specific includes:

- `_scope_specialist.txt` - Domain boundaries
- `_json_output.txt` - Response format
- `_never_invent.txt` - No hallucination rule
- `_markdown_rules.txt` - Formatting rules

---

## Strategy Stages

The `strategy_node` operates in three progressive stages for adventure activity planning (hiking, diving, skiing, cycling, boating).

### Stage Overview

| Stage | Name      | Trigger                          | Max Tokens | Output                                 |
| ----- | --------- | -------------------------------- | ---------- | -------------------------------------- |
| 0     | Pre-Core  | Strategy topic + no destinations | 300        | Destination archetypes + 1 question    |
| 1     | Outline   | Core fields complete             | 512        | Activity outline with sections         |
| 2     | Expansion | User requests "show more"        | 768-2048   | Expanded section or full detailed plan |

### Stage 0: Pre-Core Value

Provides immediate value before core fields are collected.

- **Gate**: `STRATEGY_PRE_CORE_VALUE` (precedence 80) or `STRATEGY_PRE_CORE_VALUE_WITH_DEST` (precedence 85)
- **Function**: `_strategy_stage0(state, topic)`
- **Prompt**: `strategy_pre_core.txt`
- **Output**: Destination archetypes, mini itinerary, exactly 1 clarifying question
- **Lifecycle**: Tracked via `stage0_completed_sig` to prevent re-firing

### Stage 1: Initial Strategy

Generates activity outline when core fields are complete.

- **Gate**: `STRATEGY_POST_CORE` (precedence 35) - fires when core complete + `last_strategy_topic` set
- **Function**: `_strategy_stage1(state, topic)`
- **Prompt**: `strategy_{topic}.txt`
- **Output**: Structured outline with expandable sections
- **Sets**: `pending_strategy_expansion = True` for stage 2
- **Lifecycle**: Tracked via `stage1_completed_sig` to prevent re-firing

### Stage 2: Expansion

Expands sections on user request ("show more", "tell me about X").

- **Gate**: `STRATEGY_EXPANSION` (precedence 10 - highest priority)
- **Function**: `_strategy_stage2(state, topic, expansion_target)`
- **Prompt**: `strategy_{topic}.txt` with expansion context
- **Targets**: Specific section, tier, or full expansion
- **Output**: Detailed content for requested section

### Key Functions

| Function                            | Purpose                           |
| ----------------------------------- | --------------------------------- |
| `_strategy_stage0`                  | Pre-core value-first response     |
| `_strategy_stage1`                  | Initial strategy outline          |
| `_strategy_stage2`                  | Section/full expansion            |
| `_is_strategy_expansion_request`    | Detect expansion triggers         |
| `_check_strategy_pre_core_value`    | Check stage 0 eligibility         |
| `_check_strategy_topic_switch`      | Detect mid-session topic changes  |
| `compute_stage0_signature`          | Lifecycle tracking for stage 0    |
| `compute_stage1_signature`          | Lifecycle tracking for stage 1    |
| `_track_strategy_pre_core_question` | Loop guard for repeated questions |

### Topic Switching

Mid-session topic changes (e.g., "I wanna go diving too") are handled by:

- **Gate**: `STRATEGY_TOPIC_SWITCH` (precedence 70)
- **Trigger**: Intent verb + new strategy keyword + cooldown expired
- **Deferred**: If blocking errors exist, stores `pending_strategy_topic` for next turn

---

## Gate Precedence

`GateEvaluator` checks gates in strict precedence order. First match wins.

| Precedence | Gate                                | Destination               | Description                        |
| ---------- | ----------------------------------- | ------------------------- | ---------------------------------- |
| 10         | `STRATEGY_EXPANSION`                | `strategy_node`           | Expansion on existing strategy     |
| 20         | `GENERATE_REQUESTED`                | `generate_responder`      | Explicit generate request          |
| 30         | `SHORT_CIRCUIT`                     | `short_circuit_responder` | Greetings, confirmations           |
| 35         | `STRATEGY_POST_CORE`                | `strategy_node` (stage 1) | Stage 1 trigger after core complete|
| 40         | `READY_NO_FIELDS`                   | `summarize`               | Plan ready, no fields to ask       |
| 50         | `FAST_PATH`                         | Specialists/validate      | LQA success or initial extraction  |
| 60         | `SPECIALIST_PRE_CORE`               | Specialists (pre-core)    | Domain keyword, core missing       |
| 70         | `STRATEGY_TOPIC_SWITCH`             | `strategy_{topic}`        | Mid-session topic switch           |
| 80         | `STRATEGY_PRE_CORE_VALUE`           | `strategy_node` (stage 0) | Strategy topic + no destinations   |
| 85         | `STRATEGY_PRE_CORE_VALUE_WITH_DEST` | `strategy_node` (stage 0) | Strategy topic + destination known |
| 90         | `CORE_COLLECTION`                   | `required_fields_node`    | Core fields missing                |
| 100        | `HIGH_CONFIDENCE`                   | Based on parsed data      | High extraction confidence         |
| 110        | `QUESTION_KEYWORD`                  | Based on keyword          | Answer with domain keyword         |
| 120        | `KEYWORD_HEURISTIC`                 | Based on keyword          | Unambiguous domain keywords        |
| 130        | `SCORING_ROUTER`                    | Deterministic scoring     | Multi-signal scoring               |
| 999        | `ROUTER_LLM`                        | `router` node             | Fallback to LLM classification     |

### Gate Suppression

- `SPECIALIST_PRE_CORE` yields to `STRATEGY_PRE_CORE_VALUE` when strategy topic detected
- `STRATEGY_PRE_CORE_VALUE_WITH_DEST` yields to question-target ownership

---

## Short Circuits & Caching

### Short Circuit Types

| Type                 | Pattern                 | Handler                   | Tokens Saved |
| -------------------- | ----------------------- | ------------------------- | ------------ |
| `greeting`           | hi, hello, hey          | `short_circuit_responder` | ~800-1500    |
| `acknowledgment`     | ok, thanks, got it      | `short_circuit_responder` | ~800-1500    |
| `confirmation_yes`   | yes, yeah, yep          | `short_circuit_responder` | ~800-1500    |
| `confirmation_no`    | no, nope, cancel        | `short_circuit_responder` | ~800-1500    |
| `off_topic`          | Non-travel queries      | `summarize`               | ~500         |
| `strategy_bootstrap` | Simple strategy prompts | Skip extractor LLM        | ~500-1000    |
| `initial_extraction` | First message parsing   | Skip extractor LLM        | ~500-1000    |

### Global Cache Overview

| Cache               | TTL     | Scope   | Purpose                              |
| ------------------- | ------- | ------- | ------------------------------------ |
| `_extractor_cache`  | 60s     | Session | Avoid re-extracting same input       |
| `_follow_up_cache`  | Config  | Session | Reuse specialist follow-up responses |
| `_strategy_cache`   | 5 min   | Session | Reuse strategy content               |
| `_tile_cache`       | Session | Session | Avoid duplicate tile API calls       |
| `_checkpoint_cache` | Session | Session | State checkpoints for error recovery |

### Per-Node Caching Strategy

#### lqa_prepass

- **Cache**: None (stateless parser)
- **Optimization**: Pattern matching, no LLM

#### extractor

- **Cache**: `_extractor_cache`
- **TTL**: 60 seconds
- **Key**: `(session_id, user_text_hash, core_fields_hash, mode)`
- **Hit condition**: Same input text with same core field state
- **Invalidation**: Core fields change, TTL expires

#### router

- **Cache**: `_follow_up_cache` (shared with specialists)
- **TTL**: Configurable (default session)
- **Key**: `(node_name, core_fields_hash, user_intent, user_text_hash)`
- **Optimization**: Scoring router bypasses LLM when deterministic

#### required_fields_node

- **Cache**: Template responses (no LLM cache needed)
- **Optimization**:
  - Template matching for common patterns
  - `required_fields_templates.json` for deterministic responses
  - LLM only for ambiguous/complex situations

#### Specialist Nodes (flights, hotels, transport, activities, general, correction)

- **Cache**: `_follow_up_cache`
- **TTL**: Session-scoped
- **Key**: `(specialist_name, core_fields_hash, user_intent, settings_hash)`
- **Hit condition**: Same intent with same trip context
- **Invalidation**: Core fields change, settings change
- **Pre-core optimization**: Template responses avoid LLM entirely

#### strategy_node

- **Cache**: `_strategy_cache`
- **TTL**: 5 minutes
- **Key**: `(session_id, topic, stage, core_fields_hash, section_id)`
- **Per-stage caching**:
  - Stage 0: Cached by topic + core fields
  - Stage 1: Cached by topic + complete core fields
  - Stage 2: Cached by topic + section_id
- **Invalidation**: Topic switch, core fields change, TTL expires

#### tile_search

- **Cache**: `_tile_cache`
- **TTL**: Session-scoped
- **Key**: `(intent, destinations, start_date, end_date, origin, booking_types)`
- **Optimization**: External API call avoided on cache hit

#### response_polish

- **Cache**: None
- **Optimization**:
  - Deterministic transforms first (no LLM)
  - Skip entirely for template/short-circuit responses
  - MVP mode: deterministic-only (no LLM fallback)

### Cache Invalidation Triggers

| Trigger               | Caches Invalidated                   |
| --------------------- | ------------------------------------ |
| Core fields change    | extractor, follow-up, strategy, tile |
| Strategy topic switch | strategy                             |
| Session timeout       | All                                  |
| Explicit clear        | All (via `clear_all_caches()`)       |
| Error recovery        | Restored from checkpoint             |

### Token Savings by Optimization

| Optimization          | Tokens Saved | Frequency     |
| --------------------- | ------------ | ------------- |
| LQA prepass success   | ~500-1000    | ~30% of turns |
| Light extractor mode  | ~270         | ~60% of turns |
| Template responses    | ~500-1500    | ~40% of turns |
| Cache hits            | ~500-2000    | ~20% of turns |
| Scoring router bypass | ~256         | ~50% of turns |
| Strategy bootstrap    | ~500-1000    | ~10% of turns |
| Response polish skip  | ~512         | ~50% of turns |

---

## Streaming Architecture

### Overview

The backend graph runs **synchronously first** (complete execution), then streams to the frontend. Streaming mode is determined by `get_streaming_mode()` based on node type and response provenance.

**Module**: `backend/app/planner/streaming.py`

### Streaming Modes

| Mode                      | Symbol | Function                                | Behavior                            | When Used                      |
| ------------------------- | ------ | --------------------------------------- | ----------------------------------- | ------------------------------ |
| `true_stream`             | 🌊     | `call_llm_streaming_with_accumulator()` | Real-time tokens from OpenAI        | User-facing LLM nodes (future) |
| `simulated:template`      | ✨     | `simulate_streaming()`                  | Token-by-token 15-35ms delays       | Template responses             |
| `simulated:cached`        | ✨     | `simulate_streaming()`                  | Token-by-token 15-35ms delays       | Cached responses               |
| `simulated:deterministic` | ✨     | `simulate_streaming()`                  | Token-by-token 15-35ms delays       | Deterministic/codegen          |
| `simulated:buffered`      | ✨     | `simulate_streaming()`                  | Token-by-token after error fallback | Error recovery                 |
| `buffered:internal`       | 🔒     | N/A                                     | No streaming                        | Internal processing nodes      |
| `buffered:postproc`       | 🔒     | N/A                                     | Runs after stream completes         | Post-processing (polish)       |
| `fast:llm`                | ⚡     | `fast_stream_buffered()`                | 1500-byte chunks, zero delay        | Default for buffered LLM       |

> **Note**: `fast:llm` is the default delivery mode in `run_turn_streaming()` for LLM responses that have already been buffered during synchronous graph execution. It uses large chunks (1.5KB) with minimal delay to avoid frontend timeout issues.

### Streaming Decision Logic

**Location**: `run_turn_streaming()` + `get_streaming_mode()`

Streaming mode is determined by two sources:
1. **`streaming.py:get_streaming_mode()`** - Canonical mode detector based on node type and provenance
2. **`plan_graph.py:run_turn_streaming()`** - Has strategy-specific override logic for `simulated:strategy` mode

```
1. Get response_writer and provenance from metadata
2. Call get_streaming_mode(state, response_writer, provenance)
3. Apply strategy override if strategy_prediction.will_execute
4. Route to appropriate streaming function based on mode
```

### Complete Node Streaming Table

#### Internal Processing Nodes (🔒 No Streaming)

| Node                 | Type      | Provenance      | Streaming Mode      | Notes                        |
| -------------------- | --------- | --------------- | ------------------- | ---------------------------- |
| `extractor`          | Internal  | `llm`           | `buffered:internal` | JSON output, not user-facing |
| `extractor:light`    | Internal  | `llm`           | `buffered:internal` | Light mode extraction        |
| `extractor:cache`    | Internal  | `cached`        | `buffered:internal` | Cached extraction            |
| `extractor:bypass`   | Internal  | `deterministic` | `buffered:internal` | Greeting/ack bypass          |
| `router`             | Internal  | `llm`           | `buffered:internal` | Intent classification        |
| `router:scoring`     | Internal  | `deterministic` | `buffered:internal` | Scoring router bypass        |
| `router:cache`       | Internal  | `cached`        | `buffered:internal` | Cached routing               |
| `lqa_prepass`        | Internal  | `deterministic` | `buffered:internal` | Zero-LLM parsing             |
| `normalize_inputs`   | Internal  | `deterministic` | `buffered:internal` | Input normalization          |
| `validate_and_merge` | Internal  | `deterministic` | `buffered:internal` | Readiness computation        |
| `branch_postprocess` | Internal  | `deterministic` | `buffered:internal` | Multi-city splitting         |
| `tile_search`        | Internal  | `deterministic` | `buffered:internal` | External API calls           |
| `response_polish`    | Post-proc | `llm`/`det`     | `buffered:postproc` | Applied after stream         |

#### Strategy Nodes (✨ Simulated / 🌊 True Stream)

| Node                             | Type | Provenance     | Streaming Mode       | UX                |
| -------------------------------- | ---- | -------------- | -------------------- | ----------------- |
| `strategy_node:stage0`           | User | `llm`          | `true_stream`        | 🌊 Real-time      |
| `strategy_node:stage0:fallback`  | User | `template`     | `simulated:template` | ✨ Token-by-token |
| `strategy_node:guard1.5`         | User | `template`     | `simulated:template` | ✨ Token-by-token |
| `strategy_node:relevance_gate`   | User | `template`     | `simulated:template` | ✨ Token-by-token |
| `strategy_node:no_prompt`        | User | `template`     | `simulated:template` | ✨ Token-by-token |
| `strategy_node:{topic}:cache`    | User | `cached`       | `simulated:cached`   | ✨ Token-by-token |
| `strategy_node:{topic}:stage1`   | User | `llm`          | `true_stream`        | 🌊 Real-time      |
| `strategy_node:{topic}:stage2`   | User | `llm`          | `true_stream`        | 🌊 Real-time      |
| `strategy:{topic}:json_recovery` | User | `llm_fallback` | `simulated:buffered` | ✨ Token-by-token |

#### Specialist Nodes (🌊 True Stream / ✨ Simulated)

| Node                           | Type | Provenance | Streaming Mode       | UX                |
| ------------------------------ | ---- | ---------- | -------------------- | ----------------- |
| `required_fields:template`     | User | `template` | `simulated:template` | ✨ Token-by-token |
| `required_fields:llm`          | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `required_fields:cache`        | User | `cached`   | `simulated:cached`   | ✨ Token-by-token |
| `flights:pre_core`             | User | `template` | `simulated:template` | ✨ Token-by-token |
| `flights:template`             | User | `template` | `simulated:template` | ✨ Token-by-token |
| `flights:cache`                | User | `cached`   | `simulated:cached`   | ✨ Token-by-token |
| `flights:llm`                  | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `hotels:pre_core`              | User | `template` | `simulated:template` | ✨ Token-by-token |
| `hotels:template`              | User | `template` | `simulated:template` | ✨ Token-by-token |
| `hotels:cache`                 | User | `cached`   | `simulated:cached`   | ✨ Token-by-token |
| `hotels:llm`                   | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `activities:pre_core`          | User | `template` | `simulated:template` | ✨ Token-by-token |
| `activities:template`          | User | `template` | `simulated:template` | ✨ Token-by-token |
| `activities:cache`             | User | `cached`   | `simulated:cached`   | ✨ Token-by-token |
| `activities:llm`               | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `transport:pre_core`           | User | `template` | `simulated:template` | ✨ Token-by-token |
| `transport:template`           | User | `template` | `simulated:template` | ✨ Token-by-token |
| `transport:cache`              | User | `cached`   | `simulated:cached`   | ✨ Token-by-token |
| `transport:llm`                | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `correction:llm`               | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `general:llm`                  | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `missing_fields_guard:llm`     | User | `llm`      | `true_stream`        | 🌊 Real-time      |
| `missing_fields_guard:blocked` | User | `template` | `simulated:template` | ✨ Token-by-token |

#### Other User-Facing Nodes (✨ Simulated)

| Node                            | Type | Provenance      | Streaming Mode            | UX                |
| ------------------------------- | ---- | --------------- | ------------------------- | ----------------- |
| `short_circuit_responder`       | User | `deterministic` | `simulated:deterministic` | ✨ Token-by-token |
| `generate_responder`            | User | `deterministic` | `simulated:deterministic` | ✨ Token-by-token |
| `summarize:ready`               | User | `deterministic` | `simulated:deterministic` | ✨ Token-by-token |
| `summarize`                     | User | `deterministic` | `simulated:deterministic` | ✨ Token-by-token |
| `summarize:strategy_fallback`   | User | `template`      | `simulated:template`      | ✨ Token-by-token |
| `summarize:dest_fallback`       | User | `template`      | `simulated:template`      | ✨ Token-by-token |
| `summarize:generic_fallback`    | User | `template`      | `simulated:template`      | ✨ Token-by-token |
| `llm_blocked_fallback:{source}` | User | `template`      | `simulated:template`      | ✨ Token-by-token |

#### Error Recovery (✨ Simulated)

| Node                           | Type | Provenance  | Streaming Mode       | UX                  |
| ------------------------------ | ---- | ----------- | -------------------- | ------------------- |
| `{node}:stream_error_fallback` | User | `llm_retry` | `simulated:buffered` | ✨ Retry → simulate |

### Streaming Mode Summary

| Mode                   | Count | Description                                |
| ---------------------- | ----- | ------------------------------------------ |
| `buffered:internal` 🔒 | 13    | Internal processing nodes                  |
| `simulated:*` ✨       | 25+   | Templates, cached, deterministic responses |
| `true_stream` 🌊       | 15+   | Real-time LLM streaming for user-facing    |

### Key Observations

1. **All LLM responses use true streaming** - When `provenance == "llm"`, the `get_streaming_mode()` function returns `true_stream`, enabling real-time token delivery

2. **Strategy nodes stream in real-time** - All three stages (stage0, stage1, stage2) use `true_stream` when calling the LLM

3. **Specialist LLM responses stream in real-time** - flights, hotels, activities, transport, correction, general nodes all use `true_stream` for LLM paths

4. **Templates and cached use simulated streaming** - Token-by-token animation for deterministic/cached responses

5. **Internal nodes don't stream** - Extractor, router, and other internal nodes are correctly excluded from streaming

6. **Error recovery uses simulated streaming** - On mid-stream failure, fallback to buffered → simulated streaming

### Provenance Types

| Provenance      | Description                         | Streaming Mode   |
| --------------- | ----------------------------------- | ---------------- |
| `llm`           | Direct LLM response                 | 🌊 `true_stream` |
| `template`      | Template-generated response         | ✨ Simulated     |
| `deterministic` | Pure Python logic response          | ✨ Simulated     |
| `codegen`       | Code-generated response             | ✨ Simulated     |
| `cached`        | Retrieved from cache                | ✨ Simulated     |
| `llm_fallback`  | LLM recovery after parse failure    | ✨ Simulated     |
| `llm_retry`     | Buffered retry after stream failure | ✨ Simulated     |
| `unknown`       | Provenance not set                  | ✨ Simulated     |

---

## Prompt Files

### Main Prompts

| File                    | Used By                | Max Tokens |
| ----------------------- | ---------------------- | ---------- |
| `extractor.txt`         | `extractor`            | 400        |
| `extractor_light.txt`   | `extractor` (light)    | 128        |
| `router.txt`            | `router`               | 256        |
| `required_fields.txt`   | `required_fields_node` | 256        |
| `flights.txt`           | `flights_node`         | 512        |
| `hotels.txt`            | `hotels_node`          | 512        |
| `transport.txt`         | `transport_node`       | 512        |
| `activities.txt`        | `activities_node`      | 512        |
| `correction.txt`        | `correction_node`      | 512        |
| `general.txt`           | `general_node`         | 512        |
| `response_polish.txt`   | `response_polish`      | 512        |
| `strategy_pre_core.txt` | `strategy_node` (s0)   | 300        |

### Strategy Prompts

| File                   | Topic   |
| ---------------------- | ------- |
| `strategy_hiking.txt`  | hiking  |
| `strategy_diving.txt`  | diving  |
| `strategy_skiing.txt`  | skiing  |
| `strategy_cycling.txt` | cycling |
| `strategy_boating.txt` | boating |

### Shared Includes

| File                    | Purpose                |
| ----------------------- | ---------------------- |
| `_json_output.txt`      | JSON output format     |
| `_scope_specialist.txt` | Specialist scope rules |
| `_never_invent.txt`     | Never invent data      |
| `_markdown_rules.txt`   | Markdown formatting    |
| `_strategy_base.txt`    | Strategy base template |
