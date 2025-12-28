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
├── node_utils.py            # P2: Simple utilities for module-level imports (ti_short, today_iso)
├── cache/                   # Unified caching framework (consolidated)
│   ├── __init__.py          # Cache exports
│   ├── framework.py         # CacheNode ABC + ResponseCache, ExtractorCache, StrategyCache, TileCache, GateEvaluationCache
│   └── compat.py            # Backward-compatible function signatures for plan_graph.py
├── normalization/           # Trip input normalization
│   ├── __init__.py          # Normalization exports
│   ├── types.py             # NormalizationError dataclass
│   ├── date.py              # DateNormalizer, DateProvenance (~580 lines)
│   └── trip_inputs.py       # TripInputNormalizer (~890 lines)
├── parsing/                 # Parse functions consolidation
│   ├── __init__.py          # Parsing exports
│   ├── provenance.py        # Parse provenance tracking (precedence-based)
│   └── lqa_parsers.py       # LQA field parsers (~923 lines, includes P4.1/P2.3)
├── gates/
│   ├── __init__.py          # Gate exports
│   ├── precedence.py        # GatePrecedence IntEnum (10-999)
│   ├── result.py            # GateResult dataclass
│   ├── constants.py         # DateErrorCode, CORE_FIELD_PRIORITY, CANONICAL_FIELD_ORDER
│   ├── readiness.py         # TripReadiness dataclass + compute_trip_readiness()
│   ├── evaluator_v2.py      # GateEvaluator orchestrator (~550 lines, class-based gates)
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
│       ├── strategy_pre_core.py # StrategyPreCoreValueGate (80, consolidated)
│       ├── strategy_expansion.py # StrategyExpansionGate (precedence 10)
│       ├── strategy_post_core.py # StrategyPostCoreGate (precedence 35)
│       ├── core_collection.py # CoreCollectionGate (precedence 90)
│       ├── heuristic_gates.py # QuestionKeywordGate (110, consolidated)
│       └── router_llm.py    # RouterLLMGate (precedence 999, fallback)
├── gates/base.py            # Gate ABC, GateContext, build_result() factory
├── gates/keyword_utils.py   # keyword_match() - unified keyword matching
├── gates/intent_detection.py # check_intent_only_input(), check_question_keyword_combo()
├── gates/topic_detection.py # detect_strategy_topic_from_text()
├── state/
│   ├── __init__.py          # State exports
│   └── writer.py            # StateWriter class (SSoT enforcement)
└── nodes/
    ├── __init__.py          # Node exports
    ├── base.py              # NodeContext, node_decorator
    ├── confidence.py        # build_extraction_confidence(), high_confidence(), low_confidence_error()
    ├── llm_utils.py         # measure_llm_call() context manager, LLMCallTimer
    ├── lqa_prepass.py       # LQA pre-pass node (~469 lines, includes P4.1 negation handling)
    ├── router.py            # Router node (~130 lines)
    ├── extractor.py         # Extractor node (~504 lines)
    ├── specialist_main.py   # Shared specialist handler (~765 lines, includes P4.2 confirmation)
    ├── strategy_main.py     # Strategy nodes (decomposed, uses base.py/stage0.py)
    ├── specialist/          # Specialist subpackage (P3 extraction - ~700 lines extracted)
    │   ├── __init__.py      # Re-exports from specialist_main.py + submodules
    │   ├── base.py          # CORE_FIELDS, SPECIALIST_TYPES, field validation
    │   ├── guards.py        # check_core_field_guard, check_default_adults_gate, check_noop_gate
    │   ├── templates.py     # ~597 lines: question_target, templates, P4.2 confirmation templates
    │   ├── groundedness.py  # P3: check_groundedness_guardrail for tile-based specialists
    │   └── response_processor.py  # P3: process_llm_response, validate_question_target
    └── strategy/            # Strategy subpackage (P4: Stage0 consolidated)
        ├── __init__.py      # Re-exports from strategy_main.py + submodules
        ├── base.py          # STRATEGY_KEYWORDS, is_strategy_enabled, has_strategy_keyword, detect_*
        └── stage0.py        # Stage0Coordinator, strategy_stage0(), STAGE0_FALLBACK_TEMPLATES
```

### Key Exports

| Module                       | Exports                                                                                        |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| `planner`                    | `run_turn`, `run_turn_streaming`, `GateEvaluator`                                              |
| `planner`                    | `StreamingMode`, `INTERNAL_PROCESSING_NODES`, `get_streaming_mode`, `should_use_true_streaming`|
| `planner.gates`              | `GatePrecedence`, `GateResult`, `TripReadiness`, `compute_trip_readiness`, `GateEvaluator`     |
| `planner.gates`              | `GraphMetadata`, `SuppressionPredicates`, `keyword_match`, `check_intent_only_input`, `check_question_keyword_combo` |
| `planner.gates.checks`       | `is_strategy_expansion_request`, `is_vague_affirmation`, `StrategyTier`                        |
| `planner.gates.implementations` | `Gate`, `GateContext`, `GATE_REGISTRY`, all 13 individual gate classes                      |
| `planner.cache`              | `CacheNode`, `ResponseCache`, `ExtractorCache`, `StrategyCache`, `TileCache`, `GateEvaluationCache` |
| `planner.cache`              | `CacheStats`, `CachePayload`, `DiscardReason`, `clear_all_caches`, `get_all_cache_stats`       |
| `planner.cache.compat`       | `get_extractor_cached`, `set_extractor_cached`, `get_strategy_cached`, `set_strategy_cached`   |
| `planner.normalization`      | `DateNormalizer`, `DateProvenance`, `TripInputNormalizer`, `NormalizationError`, `normalize_str`|
| `planner.parsing`            | `set_parse_provenance_once`, `finalize_parse_provenance`, `get_parse_provenance`               |
| `planner.parsing`            | `LQA_FIELD_PARSERS`, `_parse_destination_answer`, `_parse_date_answer`, `_parse_budget_answer` |
| `planner.parsing`            | `_extract_negation_alternative` (P4.1), `_parse_compound_travelers_date` (P2.3)               |
| `planner.state`              | `StateWriter`                                                                                  |
| `planner.nodes`              | `extractor`, `lqa_prepass`, `router`, `_specialist`, `strategy_node`                           |
| `planner.nodes`              | `build_extraction_confidence`, `high_confidence`, `low_confidence_error`, `measure_llm_call`   |
| `planner.nodes.specialist`   | `CORE_FIELDS`, `check_core_field_guard`, `check_noop_gate`, `apply_template_response`          |
| `planner.nodes.specialist`   | `process_llm_response`, `validate_question_target`, `check_groundedness_guardrail` (P3)        |
| `planner.nodes.specialist`   | `select_confirmation_template`, `apply_confirmation_template` (P4.2)                           |
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
│  • Max input: 80 chars (increased from 50)                                   │
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
│No LLM   │ │origin/etc │ │512 tok each │ │Cache:  │ │300-1536  │ │No LLM    │
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
│  • Cache: TileCache v2         │                │
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
| Negation with alt. | "not Paris, maybe Barcelona" (P4.1)  | lqa → parse alternative → normalize       |
| Compound parsing   | "2 adults for next month" (P2.3)     | deterministic_pipeline → compound parse   |
| Confirmation       | Low confidence/ambiguity (P4.2)      | specialist → confirmation template        |

---

## Node Inventory

| Node                      | Prompt File            | LLM Model   | Max Tokens | Purpose                        |
| ------------------------- | ---------------------- | ----------- | ---------- | ------------------------------ |
| `lqa_prepass`             | —                      | —           | —          | Zero-LLM answer extraction     |
| `extractor`               | `extractor.txt`        | gpt-4o-mini | 400        | Extract trip data from text    |
| `normalize_inputs`        | —                      | —           | —          | Normalize extracted inputs     |
| `router`                  | `router.txt`           | gpt-4o-mini | 256        | Intent classification          |
| `required_fields_node`    | `required_fields.txt`  | gpt-4o-mini | 180        | Collect missing core fields    |
| `flights_node`            | `flights.txt`          | gpt-4o-mini | 512        | Flight preferences             |
| `hotels_node`             | `hotels.txt`           | gpt-4o-mini | 512        | Hotel preferences              |
| `transport_node`          | `transport.txt`        | gpt-4o-mini | 512        | Ground transport               |
| `activities_node`         | `activities.txt`       | gpt-4o-mini | 512        | Activity preferences           |
| `correction_node`         | `correction.txt`       | gpt-4o-mini | 512        | Handle corrections             |
| `general_node`            | `general.txt`          | gpt-4o-mini | 512        | Multi-domain queries           |
| `strategy_node`           | `strategy_{topic}.txt` | gpt-4o-mini | 300-1536   | Adventure activity planning    |
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

**P4.1 Negation Handling** (before generic bail):

When input contains negation patterns, LQA attempts to extract alternatives:
- `"not Paris, maybe Barcelona"` → parse "Barcelona"
- `"instead of Rome, try Venice"` → parse "Venice"
- `"actually Tokyo"` → parse "Tokyo"

If alternative is parsable → treat as LQA hit, skip extractor.
If simple rejection → set `needs_clarification` flag.

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
| 2     | Expansion | User requests "show more"        | 600-1536   | Expanded section or full detailed plan |

### Stage 0: Pre-Core Value

Provides immediate value before core fields are collected.

- **Gate**: `STRATEGY_PRE_CORE_VALUE` (precedence 80) - handles both with/without destinations
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

| Precedence | Gate                      | Destination               | Description                                      |
| ---------- | ------------------------- | ------------------------- | ------------------------------------------------ |
| 10         | `STRATEGY_EXPANSION`      | `strategy_node`           | Expansion on existing strategy                   |
| 20         | `GENERATE_REQUESTED`      | `generate_responder`      | Explicit generate request                        |
| 30         | `SHORT_CIRCUIT`           | `short_circuit_responder` | Greetings, confirmations                         |
| 30         | `INFEASIBILITY_DETECTION` | `correction_node`         | Infeasibility signals, conflicts detected        |
| 35         | `STRATEGY_POST_CORE`      | `strategy_node` (stage 1) | Stage 1 trigger after core complete              |
| 40         | `READY_NO_FIELDS`         | `summarize` or specialist | Ready; routes to specialist if keyword           |
| 50         | `FAST_PATH`               | `required_fields_node`    | Bootstrap optimization (strategy_bootstrap only) |
| 60         | `SPECIALIST_PRE_CORE`     | Specialists (pre-core)    | Domain keyword, core missing                     |
| 70         | `STRATEGY_TOPIC_SWITCH`   | `strategy_{topic}`        | Mid-session topic switch                         |
| 80         | `STRATEGY_PRE_CORE_VALUE` | `strategy_node` (stage 0) | Strategy topic (with or without destinations)    |
| 90         | `CORE_COLLECTION`         | `required_fields_node`    | Core fields missing                              |
| 110        | `QUESTION_KEYWORD`        | Based on keyword          | Question + domain keyword combo + heuristic      |
| 999        | `ROUTER_LLM`              | `router` node             | Fallback to LLM classification                   |

### Gate Consolidation (v2)

The following gates were consolidated to reduce complexity:

| Original Gates (16)                       | Consolidated To (13)        | Rationale                                     |
| ----------------------------------------- | --------------------------- | --------------------------------------------- |
| `STRATEGY_PRE_CORE_VALUE` (80)            | `STRATEGY_PRE_CORE_VALUE`   | Single gate handles both with/without dest    |
| `STRATEGY_PRE_CORE_VALUE_WITH_DEST` (85)  | (merged into 80)            | Logic consolidated into parent gate           |
| `HIGH_CONFIDENCE` (100)                   | (removed)                   | `READY_NO_FIELDS` handles core_complete cases |
| `QUESTION_KEYWORD` (110)                  | `QUESTION_KEYWORD`          | Now includes keyword heuristic fallback       |
| `KEYWORD_HEURISTIC` (120)                 | (merged into 110)           | Logic consolidated into QUESTION_KEYWORD      |

**Note:** Backward compatibility aliases for consolidated gates have been fully removed. Gate class aliases
(`StrategyPreCoreValueWithDestGate`, `HighConfidenceGate`, `KeywordHeuristicGate`) and keyword aliases
(`SPECIALIST_PRE_CORE_KEYWORDS`, `_SPECIALIST_KEYWORDS`) are no longer exported.

### Gate Suppression

- `SPECIALIST_PRE_CORE` yields to `STRATEGY_PRE_CORE_VALUE` when strategy topic detected
- `READY_NO_FIELDS` includes SPECIALIST_REQUEST logic - routes to specialist nodes when explicit domain keywords detected (hotels, flights, etc.)

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

| Cache                   | TTL       | Max Size | Purpose                                         |
| ----------------------- | --------- | -------- | ----------------------------------------------- |
| `ExtractorCache`        | 300s*     | 100      | Avoid re-extracting same input                  |
| `ResponseCache`         | 1 hour*   | 200      | Reuse specialist follow-up responses            |
| `StrategyCache`         | 5 min     | 100      | Reuse strategy content                          |
| `TileCache` (v2)        | 5 min     | 100      | Avoid duplicate tile API calls; budget filtered |
| `GateEvaluationCache`   | 5 min     | 200      | Cache gate routing decisions                    |

*TTL values from `config.py` override framework defaults.

### Per-Node Caching Strategy

#### lqa_prepass

- **Cache**: None (stateless parser)
- **Optimization**: Pattern matching, no LLM

#### extractor

- **Cache**: `ExtractorCache`
- **TTL**: 300 seconds (configurable, increased from 60s for better multi-turn reuse)
- **Key**: `(session_id, user_text_hash, core_fields_hash, extractor_mode, model_id)`
- **Hit condition**: Same input text with same core field state and model
- **Invalidation**: Core fields change, model change, TTL expires

#### router

- **Cache**: `ResponseCache` (shared with specialists)
- **TTL**: 1 hour (configurable)
- **Key**: `(node_name, core_fields_hash, follow_up_hash, user_text_hash, model_id)`
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

- **Cache**: `StrategyCache`
- **TTL**: 5 minutes
- **Key**: `(session_id, topic, core_fields_hash, user_text_hash, section_id, stage0_lifecycle_hash, model_id)`
- **Per-stage caching**:
  - Stage 0: Cached by topic + core fields + lifecycle hash
  - Stage 1: Cached by topic + complete core fields
  - Stage 2: Cached by topic + section_id
- **Invalidation**: Topic switch, core fields change, model change, TTL expires

#### tile_search

- **Cache**: `TileCache` (v2)
- **TTL**: 5 minutes
- **Key**: `(session_id, tile_type, query_hash)` where `query_hash` includes:
  - `intent` (hotel/flight/activity)
  - `destinations` (sorted, comma-joined)
  - `start_date`
  - `end_date` (v2)
  - `origin`
  - `adults` (v2)
  - `children` (v2)
  - Note: `budget` excluded from key - filtered client-side
- **Optimization**: External API call avoided on cache hit
- **Budget filtering**: Client-side via `filter_tiles_by_budget()` for instant budget changes without refetch
- **Allocation**: Hotels 40%, Flights 30%, Activities 30% of total budget

#### response_polish

- **Cache**: None
- **Optimization**:
  - Deterministic transforms first (no LLM)
  - Skip entirely for template/short-circuit responses
  - MVP mode: deterministic-only (no LLM fallback)

### Cache Invalidation Triggers

| Trigger                  | Caches Invalidated                          |
| ------------------------ | ------------------------------------------- |
| Core fields change       | extractor, follow-up, strategy, tile        |
| `end_date` change        | tile (v2: end_date in cache key)            |
| `adults/children` change | tile (v2: traveler count in cache key)      |
| `budget` change          | None (client-side filtering, no invalidation) |
| Strategy topic switch    | strategy                                    |
| Session timeout          | All                                         |
| Explicit clear           | All (via `clear_all_caches()`)              |
| Error recovery           | Restored from checkpoint                    |

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

| File                         | Used By                | Max Tokens | In Hash |
| ---------------------------- | ---------------------- | ---------- | ------- |
| `extractor.txt`              | `extractor`            | 400        | ✓       |
| `extractor_light.txt`        | `extractor` (light)    | 80         | ✓       |
| `router.txt`                 | `router`               | 256        | ✓       |
| `required_fields.txt`        | `required_fields_node` | 180        | ✓       |
| `required_fields_confirm.txt`| `required_fields_node` | 180        | ✗       |
| `flights.txt`                | `flights_node`         | 512        | ✓       |
| `hotels.txt`                 | `hotels_node`          | 512        | ✓       |
| `transport.txt`              | `transport_node`       | 512        | ✓       |
| `activities.txt`             | `activities_node`      | 512        | ✓       |
| `correction.txt`             | `correction_node`      | 512        | ✓       |
| `general.txt`                | `general_node`         | 512        | ✓       |
| `response_polish.txt`        | `response_polish`      | 512        | ✓       |
| `strategy_pre_core.txt`      | `strategy_node` (s0)   | 300        | ✓       |
| `condense.txt`               | `condense_long_message`| 256        | ✗       |
| `missing_fields_guard.txt`   | `_invoke_guard`        | 180        | ✗       |

### Strategy Prompts

| File                   | Topic   | In Hash |
| ---------------------- | ------- | ------- |
| `strategy_hiking.txt`  | hiking  | ✓       |
| `strategy_diving.txt`  | diving  | ✓       |
| `strategy_skiing.txt`  | skiing  | ✓       |
| `strategy_cycling.txt` | cycling | ✓       |
| `strategy_boating.txt` | boating | ✓       |

### Shared Includes

| File                    | Purpose                | In Hash |
| ----------------------- | ---------------------- | ------- |
| `_json_output.txt`      | JSON output format     | ✗       |
| `_scope_specialist.txt` | Specialist scope rules | ✗       |
| `_never_invent.txt`     | Never invent data      | ✗       |
| `_markdown_rules.txt`   | Markdown formatting    | ✗       |
| `_strategy_base.txt`    | Strategy base template | ✗       |

> **Note:** Helper prompts prefixed with `_` are included by other prompts and not directly in the prompt bundle hash.
> Prompts marked with ✗ in "In Hash" column will not invalidate cache when changed.

---

## Recent Improvements (MVP)

### Thread-Safe Cache Statistics
**Location:** `cache/framework.py`

`CacheStats` now uses `threading.Lock` for thread-safe counter operations. Critical for multi-worker deployments (gunicorn/uvicorn).

### Complete Prompt Hash Coverage
**Location:** `plan_graph.py:_compute_prompt_bundle_hash()`

Prompt bundle hash now includes all 17 prompt files (was 2). Changes to any prompt file will invalidate cached responses.

Prompts included:
- Core: `extractor.txt`, `extractor_light.txt`, `router.txt`, `required_fields.txt`
- Specialists: `flights.txt`, `hotels.txt`, `transport.txt`, `activities.txt`, `correction.txt`, `general.txt`
- Strategy: `strategy_pre_core.txt`, `strategy_{hiking,diving,skiing,cycling,boating}.txt`
- Post-processing: `response_polish.txt`

### Model ID in Cache Keys
**Location:** `cache/framework.py`, `cache/compat.py`

`ResponseCache` key now includes `model_id` to prevent cross-model cache hits when LLM model configuration changes.

### Token Optimization: Disabled JSON Retry
**Location:** `nodes/specialist_main.py`

Default `retry_on_json_error=False` in specialists. Saves ~40% tokens on error paths by relying on deterministic fallbacks instead of LLM retry.

### Unified Keyword Matching
**Location:** `gates/keyword_utils.py`

New `keyword_match()` utility provides consistent word-boundary matching across gates:
- Single-word keywords: Uses regex word boundaries (`\b`) to prevent false positives
- Multi-word phrases: Uses substring matching

Used by:
- `ReadyNoFieldsGate` (precedence 40)
- `SpecialistPreCoreGate` (precedence 60)

### Removed Backward Compatibility Shims
**Location:** `gates/evaluator_v2.py`

Backward compatibility shims have been fully removed (~234 lines deleted). Tests now use gate classes directly:

| Removed Shim | Replacement |
|--------------|-------------|
| `_check_intent_only_input` | `check_intent_only_input()` utility in `gates/intent_detection.py` |
| `_is_strategy_pre_core_eligible` | `StrategyPreCoreValueGate.evaluate()` |
| `_check_strategy_pre_core_value` | `StrategyPreCoreValueGate.evaluate()` |
| `_check_specialist_pre_core` | `SpecialistPreCoreGate.evaluate()` |
| `_check_strategy_topic_switch` | `StrategyTopicSwitchGate._check_strategy_topic_switch()` |
| `_check_question_keyword_combo` | `check_question_keyword_combo()` utility in `gates/intent_detection.py` |

### New Intent Detection Utilities
**Location:** `gates/intent_detection.py`

Two new utility functions extracted for reuse:
- `check_intent_only_input(text_lower, ti)` - Detects pure intent inputs (topic keywords without extractable entities)
- `check_question_keyword_combo(text_lower)` - Detects question word + domain keyword patterns

### Template-Based Missing Fields Guard (P1 Optimization)
**Location:** `nodes/specialist_main.py`

The `_invoke_missing_fields_guard` function now uses deterministic templates by default instead of LLM calls:

| Setting | Value | Behavior |
|---------|-------|----------|
| `guard_use_templates` | `True` (default) | Template-based response, saves ~200-250 tokens |
| `guard_use_templates` | `False` | Original LLM-based response with tone adaptation |

**Template questions (same as LLM would generate):**
| Field | Question | Suggestions |
|-------|----------|-------------|
| destinations | "Where are you dreaming of going?" | Bali, Paris, Tokyo |
| origin | "Where will you be flying from?" | New York, London, Los Angeles |
| dates | "When are you looking to travel?" | Next month, December 20-27, First week of January |
| adults | "How many travelers will be joining?" | Just me, 2 adults, Family of 4 |
| budget | "What's your approximate budget?" | $2,000, $5,000, Flexible |

**Features preserved:**
- `date_clarify_mode` enforcement (forces dates question when blocking errors exist)
- Suggestion storage for LQA matching
- `question_target` and `last_question_field` metadata

### Module-Level Imports Refactoring (P2 Optimization)
**Location:** `planner/nodes/*.py`

Node files now use module-level imports for non-circular dependencies, reducing function startup time and improving code clarity.

**New module:** `planner/node_utils.py`
Simple utilities extracted for module-level import:
- `ti_short(ti)` - Convert TripInputs to compact dict
- `today_iso(timezone_name)` - Get today's date in ISO format

**Imports moved to module level:**
| Module | Imports Now at Module Level |
|--------|----------------------------|
| `extractor.py` | `settings`, `_debug`, `jloads_safe`, `text_is_compatible_with_target`, `ti_short`, `today_iso`, confidence utilities |
| `router.py` | `settings`, `_debug`, `jloads_safe`, `measure_llm_call` |
| `lqa_prepass.py` | `settings`, `_debug`, `LQA_BAIL_PATTERNS`, parsing utilities, confidence utilities |
| `specialist_main.py` | `settings`, `_debug`, `jloads_safe`, `measure_llm_call`, gate constants/readiness, specialist guards |
| `strategy_main.py` | `settings`, `_debug`, `jloads_safe`, gate checks/readiness/suppression, `measure_llm_call`, strategy base utilities |

**Remaining late imports:** Functions from `plan_graph.py` that have circular dependencies (e.g., `_debug_node_entry`, `call_llm_with_timeout`, caching utilities) remain as late imports inside function bodies.

### Specialist Module Extraction (P3 Optimization)
**Location:** `planner/nodes/specialist/`

The monolithic `specialist_main.py` (previously 1098 lines) has been refactored into modular components, reducing it to ~750 lines (~32% reduction).

**New modules extracted:**
| Module | Lines | Purpose |
|--------|-------|---------|
| `response_processor.py` | ~316 | LLM response parsing, delta application, question target validation |
| `groundedness.py` | ~122 | Groundedness guardrail for tile-based specialists |
| `templates.py` (updated) | ~360 | Added `apply_pre_core_template_response` for deterministic pre-core mode |

**Key functions extracted:**
| Function | Module | Purpose |
|----------|--------|---------|
| `process_llm_response()` | response_processor | Parse JSON, apply delta, validate question target, handle suggestions |
| `validate_question_target()` | response_processor | Prevent LLM from asking about already-set fields |
| `cache_required_fields_response()` | response_processor | Cache responses for required_fields node |
| `check_groundedness_guardrail()` | groundedness | Block invented details when no tiles available |
| `apply_pre_core_template_response()` | templates | Deterministic template for pre-core mode |

**Constants consolidated:**
- `QUESTION_TARGET_FIELD_CHECK` - Field validation map
- `TILE_BASED_SPECIALISTS` - Specialists requiring groundedness checks
- `TOPIC_ACKNOWLEDGMENTS` - Pre-core mode acknowledgment text

### Post-MVP P1: Merge Specialist + Guard (Superseded)
**Status:** Achieved via template approach - no additional work needed

The original P1 optimization proposed merging the guard LLM call with the specialist LLM call into a single combined call to save ~200-400 tokens per turn.

This optimization is now **superseded** by the Template-Based Missing Fields Guard:

| Approach | Guard Tokens | Specialist Tokens | Total |
|----------|-------------|-------------------|-------|
| Original (2 LLM calls) | ~100-200 | ~500+ | ~600-700+ |
| P1 Proposal (combined) | 0 (merged) | ~300-400 | ~300-400 |
| **Current (template guard)** | **0** | ~500+ | **~500+** |

The template approach is superior because:
1. Guard uses 0 tokens (deterministic templates)
2. No combined prompt complexity needed
3. Specialist prompt remains focused on domain logic
4. Template questions are identical to what LLM would generate

**Flow comparison:**
```
Original:      Guard LLM (#1) → User answer → Specialist LLM (#2)
P1 Proposal:   Combined LLM (#1) → User answer → (specialist logic inlined)
Current:       Guard Template (0) → User answer → Specialist LLM (#1)
```

### Strategy Stage 0 Consolidation (P4 Partial)
**Location:** `planner/nodes/strategy/`

Stage 0 logic has been consolidated to eliminate duplication:

**Before:** Two separate implementations existed:
- `strategy_main.py:_strategy_stage0()` - 408 lines
- `strategy/stage0.py:strategy_stage0()` - 408 lines (duplicate)

**After:** Single authoritative implementation:
- `strategy/stage0.py` contains `strategy_stage0()` and `Stage0Coordinator` class
- `strategy_main.py:_strategy_stage0()` reduced to 20-line delegation

```python
# strategy_main.py - Now delegates to Stage0Coordinator
async def _strategy_stage0(state: "GraphState", topic: str) -> "GraphState":
    from app.planner.nodes.strategy.stage0 import Stage0Coordinator
    return await Stage0Coordinator.execute(state, topic)
```

**Key components in `stage0.py`:**
| Component | Purpose |
|-----------|---------|
| `Stage0Coordinator` | Class wrapper for stage 0 execution |
| `strategy_stage0()` | Pre-core value-first response generation |
| `STAGE0_FALLBACK_TEMPLATES` | Deterministic fallback templates per topic |
| `get_dest_known_fallback()` | Destination-specific fallback when dest already chosen |

**P4 Cleanup - Removed Unused Code:**

The following utility modules were created during P4 Phase 1-3 planning but never integrated and have been removed:

| Removed File | Original Purpose | Reason Removed |
|--------------|------------------|----------------|
| `strategy/llm_handler.py` | Shared LLM call pattern | Not used - Stage 1/2 use inline logic |
| `strategy/output_processor.py` | Response parsing utilities | Not used - Stage 1/2 use inline logic |
| `strategy/lifecycle.py` | Stage signature management | Not used - `SuppressionPredicates` used directly |
| `strategy/stage1_coordinator.py` | Stage 1 coordinator class | Not integrated - Stage 1 logic remains in strategy_main.py |
| `strategy/stage2_coordinator.py` | Stage 2 coordinator class | Not integrated - Stage 2 logic remains in strategy_main.py |

**Current Strategy Package Structure:**
```
strategy/
├── __init__.py    # Re-exports from strategy_main.py + submodules
├── base.py        # Constants, feature flags, topic detection helpers
└── stage0.py      # Stage0Coordinator, strategy_stage0(), fallback templates
```

**Future Work (Deferred):**

Full Stage 1/2 coordinator extraction remains available if needed:
- Inline logic in `strategy_main.py` is well-organized (~780 lines for Stage 1+2)
- Coordinators could be re-implemented using the same pattern as Stage0Coordinator
- Current architecture is simpler and avoids over-abstraction

---

## Optimization Summary (P1-P4)

| Priority | Optimization | Status | Impact |
|----------|-------------|--------|--------|
| P1 | Template-Based Missing Fields Guard | ✅ Complete | Saves ~200-250 tokens per guard call |
| P2 | Module-Level Imports | ✅ Complete | Faster function startup, cleaner code |
| P2.3 | Compound Travelers+Date Parsing | ✅ Complete | ~500-1000 tokens per compound parse |
| P3 | Specialist Module Extraction | ✅ Complete | ~32% LOC reduction in specialist_main.py |
| P4 | Strategy Stage 0 Consolidation | ✅ Complete | Eliminated 408 lines of duplication |
| P4 | Strategy Stage 1/2 Coordinators | ⏸️ Deferred | Created but not integrated; dead code removed |
| P4.1 | Parse Negation Alternatives | ✅ Complete | ~500 tokens per successful extraction |
| P4.2 | Confirmation Templates | ✅ Complete | ~900-1500 tokens per confirmation |
| P5 | Tile Cache V2 (Wiring + Key Expansion) | ✅ Complete | Correct tiles for travelers/dates; instant budget changes |

---

## MVP Optimization Pass (December 2024)

Additional optimizations focused on token savings and performance:

### Config Tuning

| Setting | Before | After | Impact |
|---------|--------|-------|--------|
| `lqa_max_length` | 50 | 80 | ~38 tokens/turn (captures 5% more LQA successes) |
| `extractor_cache_ttl_seconds` | 60 | 300 | ~50-150 tokens/turn (better multi-turn reuse) |
| `strategy_cache_maxsize` | 50 | 100 | ~50-100 tokens/turn (reduced evictions) |

### Code Consolidation

| Change | Files | Impact |
|--------|-------|--------|
| Centralized `SPECIALIST_NODE_MAP` | `gates/constants.py` | Eliminated 4x duplication, prevents future bugs |
| Pre-compiled regex patterns | `gates/keyword_utils.py` | ~5-10% speedup on keyword-heavy gates |
| Expanded inquiry patterns | `gates/implementations/heuristic_gates.py` | ~5-8% reduction in router LLM calls |

### Template Enhancements

| Enhancement | File | Impact |
|-------------|------|--------|
| Domain-specific pre-core templates | `nodes/specialist/templates.py` | ~200-400 tokens per pre-core specialist call |
| Strategy-aware suggestions | `prompts/required_fields_templates.json` | ~150-300 tokens per strategy template hit |
| Template hash in cache keys | `plan_graph.py` | Prevents stale cached responses after template changes |

### New Constants

**`gates/constants.py`** now exports:
```python
SPECIALIST_NODE_MAP: Dict[str, str] = {
    "flights": "flights_node",
    "hotels": "hotels_node",
    "activities": "activities_node",
    "transport": "transport_node",
}
SPECIALIST_NODE_MAP_EXTENDED: Dict[str, str] = {
    **SPECIALIST_NODE_MAP,
    "strategy": "strategy_node",
}
```

### Pre-compiled Keyword Matching

**`gates/keyword_utils.py`** now caches compiled regex patterns:
- Single-word keywords: Pre-compiled with word boundaries (`\b`)
- Multi-word phrases: Cached as frozenset for substring matching
- Cache keyed by frozenset identity for O(1) lookup

### Expanded Question Detection

**`QuestionKeywordGate`** now detects:
1. Question word at start: "What hotels are available?"
2. Question word in first 3 words: "So what flights?"
3. Inquiry patterns: "Tell me about hotels", "Can you show me flights?"
4. "Looking for" pattern: "Looking for hotel recommendations"

New inquiry patterns:
```python
_INQUIRY_PATTERNS = frozenset({
    "tell me about", "tell me more about", "want to know about",
    "wanna know about", "like to know about", "can you tell me",
    "could you tell me", "i'd like to know", "show me", "looking for",
})
```

### Domain Pre-Core Templates

**`DOMAIN_PRE_CORE_TEMPLATES`** in `nodes/specialist/templates.py`:
- Hotels: "I'd love to help you find the perfect accommodation! Where are you dreaming of staying?"
- Flights: "I can definitely help with your flight search! Where would you like to fly to?"
- Activities: "Great choice - I'd love to help plan some amazing experiences! Where are you headed?"
- Transport: "I can help with your ground transportation! Where are you going?"

### Strategy-Aware Suggestions

**`required_fields_templates.json`** now includes topic-specific suggestions:
- Hiking dates: "Best season for trails", "Spring or Fall"
- Skiing dates: "Powder season", "Winter months"
- Diving dates: "Best visibility season", "When water is warmest"
- Similar variations for travelers and budget fields

### Estimated Total Impact

| Metric | Savings |
|--------|---------|
| Token usage | ~15-25% reduction |
| Gate evaluation | ~31% speedup |
| LLM call reduction | ~8-13% |
| Cache hit rate | Improved via longer TTL + larger maxsize |

---

## Deferred Optimizations (P2.3, P4.1, P4.2)

These optimizations were planned but deferred from the initial MVP pass, then implemented in a follow-up phase.

### P4.2: Confirmation Templates for Ambiguity

**Goal**: Add deterministic templates for common ambiguities instead of using LLM calls.

**Files Modified**:
- `nodes/specialist/templates.py` - Added `select_confirmation_template()` and `apply_confirmation_template()`
- `nodes/specialist_main.py` - Integrated confirmation templates before regular template path
- `prompts/required_fields_templates.json` - Added `multiple_destinations` template type

**Template Types**:

| Type | Trigger | Example Question |
|------|---------|------------------|
| `multiple_destinations` | >1 destination, no multi_city_intent | "Are you planning to visit Paris, Rome on the same trip?" |
| `typo_detected` | extraction_confidence has typo_suggestions | "Did you mean Paris?" |
| `low_confidence` | confidence 0.3-0.7 with extracted value | "Just to make sure - you want to go to Paris?" |

**Key Functions**:

| Function | Purpose |
|----------|---------|
| `select_confirmation_template(state, question_target)` | Select appropriate template based on extraction state |
| `apply_confirmation_template(state, confirmation)` | Apply template to state (deterministic response) |
| `_get_extracted_value_for_field(state, field)` | Get extracted value for field from trip_inputs |

**Token Savings**: ~900-1500 tokens per confirmation (LLM call avoided)

### P4.1: Parse Negation Alternatives in LQA

**Goal**: Extract alternative value from "not X, maybe Y" patterns instead of bailing to LLM.

**Files Modified**:
- `pattern_matching.py` - Added `NEGATION_ALTERNATIVE_PATTERN` and `SIMPLE_NEGATION_PATTERN`
- `planner/parsing/lqa_parsers.py` - Added `_extract_negation_alternative()` function
- `planner/nodes/lqa_prepass.py` - Integrated negation handling before generic bail

**Patterns Matched**:

| Pattern | Example | Negation Type |
|---------|---------|---------------|
| not X, maybe Y | "not Paris, maybe Barcelona" | `not_maybe` |
| instead of X, Y | "instead of Rome, try Venice" | `instead_of` |
| not X but Y | "not Dubai but Abu Dhabi" | `not_but` |
| change/switch to Y | "change to London" | `change_to` |
| actually Y | "actually Tokyo" | `actually` |
| Y instead | "Barcelona instead" | `x_instead` |
| Simple rejection | "no thanks", "not that" | `simple_rejection` |

**Regex Patterns**:
```python
NEGATION_ALTERNATIVE_PATTERN = re.compile(
    r"(?:"
    r"\bnot\s+[\w\s]+[,\-]\s*(?:maybe|try|how\s*about|instead)\s+(.+)|"
    r"\binstead\s+of\s+[\w\s]+[,\s]+(?:try\s+)?(.+)|"
    r"\bnot\s+([\w\s]+)\s*(?:,\s*|\s+)but\s+(.+)|"
    r"\b(?:change|switch)\s+(?:from\s+[\w\s]+\s+)?to\s+(.+)|"
    r"\bactually[,\s]+(.+)|"
    r"^(.+?)\s+instead$"
    r")",
    re.IGNORECASE,
)

SIMPLE_NEGATION_PATTERN = re.compile(
    r"^(?:no(?:\s+thanks?)?|not\s+(?:that|this)|(?:I\s+)?don'?t\s+want|never\s*mind)[\s\.\!\?]*$",
    re.IGNORECASE,
)
```

**Flow**:
1. Before bail patterns, call `_extract_negation_alternative()`
2. If alternative found and parsable → treat as LQA hit
3. If alternative found but unparsable → store for extractor
4. If simple rejection → set `needs_clarification` flag

**Token Savings**: ~500 tokens per successful alternative extraction

### P2.3: Compound Travelers+Date Parsing

**Goal**: Parse "2 adults for next month" in single LQA pass (both travelers and dates).

**Files Modified**:
- `pattern_matching.py` - Added `COMPOUND_TRAVELERS_DATE_PATTERN`, `COMPOUND_DATE_TRAVELERS_PATTERN`, `COMPOUND_KEYWORDS`
- `planner/parsing/lqa_parsers.py` - Added `_parse_compound_travelers_date()` function
- `plan_graph.py` - Integrated into `_run_deterministic_pipeline()`

**Patterns Matched**:

| Pattern | Example | Parsed Result |
|---------|---------|---------------|
| Travelers-first | "2 adults for next month" | adults=2 + date hint |
| Date-first | "next month for 3 people" | adults=3 + date hint |
| Family compound | "family of 4 in December" | adults=2, children=2 + date |
| Couple compound | "couple for next week" | adults=2 + date |
| Solo compound | "just me in January" | adults=1 + date |

**Regex Patterns**:
```python
COMPOUND_TRAVELERS_DATE_PATTERN = re.compile(
    r"^(?P<travelers>...)"
    r"\s+(?:for|in|during)\s+"
    r"(?P<date>.+)$",
    re.IGNORECASE,
)

COMPOUND_DATE_TRAVELERS_PATTERN = re.compile(
    r"^(?P<date>...)"
    r"\s+(?:for|with)\s+"
    r"(?P<travelers>...)$",
    re.IGNORECASE,
)

COMPOUND_KEYWORDS = frozenset({"for", "in", "during", "with"})
```

**Integration**:
```python
# In _run_deterministic_pipeline() after suggestion echo:
compound_result = _parse_compound_travelers_date(text, state)
if compound_result:
    return compound_result  # Contains both travelers and date fields
```

**Token Savings**: ~500-1000 tokens per compound parse (captures both fields in single pass)

### Test Coverage

| Feature | Test File | Test Count |
|---------|-----------|------------|
| P4.2 | `test_confirmation_templates.py` | 28 tests |
| P4.1 | `test_negation_alternatives.py` | 25 tests |
| P2.3 | `test_compound_parsing.py` | 19 tests |
| P5 | `test_tile_cache_v2.py` | 18 tests |

### Rollback Strategy

Each feature has independent rollback via removal of integration points:

1. **P4.2**: Remove `select_confirmation_template` call from `specialist_main.py`
2. **P4.1**: Remove `_extract_negation_alternative` call from `lqa_prepass.py`
3. **P2.3**: Remove compound parsing block from `_run_deterministic_pipeline()`

---

## P5: Tile Cache V2 (Wiring + Key Expansion)

### Overview

Tile caching infrastructure was implemented but never wired up. P5 integrates the caching layer and expands the cache key to include all fields that affect tile generation.

### Problem Statement

| Issue | Impact |
|-------|--------|
| `ensure_tiles()` never called | Every tile search hit the API (mock or real) |
| `set_tile_cached()` never called | No caching of API results |
| Cache key missing fields | `end_date`, `adults`, `children` not in key - stale tiles |
| Budget in cache key | Budget change would require refetch |

### Solution

**Files Modified**:
- [plan_graph.py](backend/app/plan_graph.py) - Wire caching into `tile_search`, expand cache key, add `filter_tiles_by_budget()`
- [cache/compat.py](backend/app/planner/cache/compat.py) - Update function signatures

**Cache Key V2**:
```python
query_str = (
    f"{intent}|"
    f"{','.join(sorted(ti.destinations or []))}|"
    f"{ti.start_date or 'none'}|"
    f"{ti.end_date or 'none'}|"       # NEW in v2
    f"{ti.origin or 'none'}|"
    f"{ti.adults or 0}|"              # NEW in v2
    f"{ti.children or 0}"             # NEW in v2
)
# Note: budget excluded - filtered client-side
```

**Budget Filtering**:
```python
_TILE_BUDGET_ALLOCATIONS = {
    "hotel": 0.40,      # 40% of budget
    "flight": 0.30,     # 30% of budget
    "activity": 0.30,   # 30% of budget
}

def filter_tiles_by_budget(tiles_dict, budget):
    # Client-side filtering enables instant budget changes without refetch
```

**tile_search Node Changes**:
1. Check cache per vertical via `ensure_tiles()`
2. Only fetch cache misses via `search_tiles()`
3. Cache results per vertical via `set_tile_cached()`
4. Apply budget filter via `filter_tiles_by_budget()`

### Version Bump

```python
NODE_LOGIC_VERSION = {
    ...
    "tile": 2,  # v2: Cache key includes end_date, adults, children; budget filtered client-side
}
```

### Test Coverage

| Test File | Tests | Purpose |
|-----------|-------|---------|
| `test_tile_cache_v2.py` | 18 tests | Cache wiring, key expansion, budget filtering, version migration |

### Impact

| Metric | Before | After |
|--------|--------|-------|
| Cache hit rate | 0% (never used) | ~60-80% on repeated queries |
| API calls saved | None | ~5 min saved per repeated query |
| Budget change latency | Requires refetch | Instant (client-side filter) |
| Traveler change | Stale prices | Correct prices (cache miss → refetch) |
