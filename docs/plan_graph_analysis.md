# Plan Graph Architecture Analysis

> **Generated**: December 21, 2025 (Updated: V5 Routing & Delta Observability)
> **Source File**: `backend/app/plan_graph.py` (~20,130 lines)
> **Prompt Files**: 26 files in `backend/app/prompts/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Node Architecture Diagram](#node-architecture-diagram)
3. [Node Inventory Table](#node-inventory-table)
4. [Short Circuits & Caching by Node](#short-circuits--caching-by-node)
5. [Prompt File Mapping](#prompt-file-mapping)
6. [Duplication Analysis](#duplication-analysis)
7. [Unused/Dead Code Analysis](#unuseddead-code-analysis)
8. [Gate Precedence Reference](#gate-precedence-reference)
9. [Strategy Bootstrap Bypass](#strategy-bootstrap-bypass)
10. [Date Handling Architecture](#date-handling-architecture)
11. [Startup Warmup](#startup-warmup)
12. [Observability & Stats](#observability--stats)
13. [Routing Correctness Fixes](#routing-correctness-fixes)
14. [Invariants & Contract Validation](#invariants--contract-validation)
    - [LLM Budget Enforcement](#llm-budget-enforcement)
    - [question_target SSoT](#question_target-ssot-single-source-of-truth)
    - [Suggestion Contract Invariant](#suggestion-contract-invariant)
    - [No-Stale-Summary Invariant](#no-stale-summary-invariant)
15. [Trace Replay Testing](#trace-replay-testing)
16. [Routing & Delta Observability (V5)](#routing--delta-observability-v5)
    - [RoutingDecisionFinal](#routingdecisionfinal)
    - [Canonical Field Ordering](#canonical-field-ordering)
    - [Question ID Lifecycle](#question-id-lifecycle)
    - [Response Provenance Tracking](#response-provenance-tracking)

---

## Architecture Overview

The `plan_graph.py` implements a LangGraph-based conversational trip planning system with **18 wired nodes**:

| Category                | Count | Description                        |
| ----------------------- | ----- | ---------------------------------- |
| **LLM-Powered Nodes**   | 10    | Use OpenAI API for generation      |
| **Deterministic Nodes** | 8     | Pure Python logic, no LLM          |
| **Conditional LLM**     | 2     | LLM fallback when templates fail   |
| **Short Circuit Types** | 7     | Bypass patterns for fast responses |
| **Caching Strategies**  | 4     | Token-saving cache mechanisms      |

### Design Principles

1. **Template-First**: Use templates before LLM calls (saves ~900-1500 tokens)
2. **Gated Specialists**: Block domain specialists until core fields collected
3. **Pre-Core Mode**: Answer domain questions while still collecting core fields
4. **Value-First Strategy**: Provide destination inspiration before asking for core fields
5. **Gate Precedence with Suppression**: Lower-precedence gates explicitly yield to higher-priority paths
6. **Deterministic Polish**: Apply safe transforms without LLM (MVP mode)
7. **LQA Pre-pass**: Zero-LLM extraction of simple answers to known questions
8. **Strategy Bootstrap Bypass**: Skip extractor LLM for simple strategy prompts (first-turn optimization)
9. **LLM Budget Enforcement**: Max 1 LLM call per non-ready turn with deterministic fallback
10. **question_target SSoT**: Single source of truth for question_target via `set_question_target()` helper

---

## Node Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              PLAN GRAPH ARCHITECTURE                                      │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                                        ┌─────────┐
                                        │  START  │
                                        └────┬────┘
                                             │
                                             ▼
                                   ┌─────────────────┐
                                   │   lqa_prepass   │ ◄─── Zero-LLM pre-pass
                                   │   (no LLM)      │      Parses simple answers
                                   └────────┬────────┘
                                            │
                          ┌─────────────────┼─────────────────┐
                          │ LQA success     │ LQA skip        │
                          ▼                 ▼                 │
              ┌─────────────────┐  ┌─────────────────┐        │
              │ normalize_inputs│  │    extractor    │ ◄──────┤
              │   (no LLM)      │  │  extractor.txt  │        │
              └────────┬────────┘  │extractor_light  │        │
                       │           └────────┬────────┘        │
                       │                    │                 │
                       ▼                    ▼                 │
              ┌────────────────────────────────────────┐      │
              │            GateEvaluator               │      │
              │  (Centralized routing logic)           │      │
              │                                        │      │
              │  Precedence order:                     │      │
              │  1. SHORT_CIRCUIT → short_circuit_resp │      │
              │  2. FAST_PATH → specialists/validate   │      │
              │  3. SPECIALIST_PRE_CORE → specialists  │      │
              │  4. STRATEGY_PRE_CORE_VALUE → strategy │      │
              │  5. CORE_COLLECTION → required_fields  │      │
              │  6-8. HEURISTIC gates                  │      │
              │  9. SCORING_ROUTER (deterministic)     │      │
              │  99. ROUTER_LLM (fallback)             │      │
              └────────────────────┬───────────────────┘      │
                                   │                          │
      ┌────────────────────────────┼────────────────────────┐ │
      │                            │                        │ │
      ▼                            ▼                        ▼ │
┌──────────────┐          ┌────────────────┐      ┌────────────────────┐
│short_circuit │          │     router     │      │ required_fields    │
│  _responder  │          │   router.txt   │      │ required_fields.txt│
│  (no LLM)    │          │   (256 tok)    │      │ + templates.json   │
└──────┬───────┘          └───────┬────────┘      └─────────┬──────────┘
       │                          │                         │
       │                          ▼                         │
       │           ┌─────────────────────────────────────────────────┐
       │           │              SPECIALIST NODES                    │
       │           │                                                  │
       │           │  ┌──────────┐ ┌──────────┐ ┌───────────┐        │
       │           │  │ flights  │ │  hotels  │ │ transport │        │
       │           │  │  _node   │ │   _node  │ │   _node   │        │
       │           │  │flights.  │ │ hotels.  │ │transport. │        │
       │           │  │   txt    │ │   txt    │ │   txt     │        │
       │           │  └────┬─────┘ └────┬─────┘ └─────┬─────┘        │
       │           │       │            │             │              │
       │           │  ┌────┴────┐  ┌────┴────┐  ┌─────┴─────┐       │
       │           │  │activiti │  │correctio│  │  general  │       │
       │           │  │  _node  │  │   _node │  │   _node   │       │
       │           │  │activiti │  │correctio│  │ general.  │       │
       │           │  │  es.txt │  │   n.txt │  │   txt     │       │
       │           │  └────┬────┘  └────┬────┘  └─────┬─────┘       │
       │           │       │            │             │              │
       │           │  ┌────┴────────────┴─────────────┴─────┐       │
       │           │  │           strategy_node             │       │
       │           │  │   strategy_{topic}.txt              │       │
       │           │  │   (boating|hiking|diving|skiing|    │       │
       │           │  │    cycling)                         │       │
       │           │  └──────────────────┬──────────────────┘       │
       │           └─────────────────────┼───────────────────────────┘
       │                                 │
       │                                 ▼
       │                      ┌─────────────────────┐
       │                      │  validate_and_merge │
       │                      │      (no LLM)       │
       │                      │  Computes readiness │
       │                      └──────────┬──────────┘
       │                                 │
       │                                 ▼
       │                      ┌─────────────────────┐
       │                      │  branch_postprocess │
       │                      │      (no LLM)       │
       │                      │ Splits multi-city   │
       │                      └──────────┬──────────┘
       │                                 │
       │              ┌──────────────────┼──────────────────┐
       │              │ tiles needed     │ no tiles         │
       │              ▼                  │                  │
       │     ┌────────────────┐          │                  │
       │     │   tile_search  │          │                  │
       │     │    (no LLM)    │          │                  │
       │     │ Search hotels/ │          │                  │
       │     │ flights/activ. │          │                  │
       │     └───────┬────────┘          │                  │
       │             │                   │                  │
       │             ▼                   ▼                  │
       └────────────►┌─────────────────────┐◄───────────────┘
                     │     summarize       │
                     │      (no LLM)       │
                     │ Safety snippets     │
                     │ Default follow-ups  │
                     └──────────┬──────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │   response_polish   │
                     │  response_polish.txt│
                     │ Deterministic-first │
                     │ LLM fallback (opt.) │
                     └──────────┬──────────┘
                                │
                                ▼
                          ┌───────────┐
                          │    END    │
                          └───────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                            SPECIAL PATHS                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  SHORT-CIRCUIT PATH:                                                          │
│  ───────────────────                                                          │
│  lqa_prepass ──► detect_short_circuit ──► short_circuit_responder             │
│                          │                        │                           │
│                          ▼                        ▼                           │
│                    (greeting|ack|yes|no)   summarize ──► response_polish      │
│                                                                               │
│  GENERATE PATH:                                                               │
│  ──────────────                                                               │
│  "show me the plan" ──► generate_responder ──► validate_and_merge ──► ...    │
│                                                                               │
│  INTENT-ONLY FAST PATH:                                                       │
│  ─────────────────────                                                        │
│  "what hotels?" (no context) ──► GateEvaluator.INTENT_ONLY ──► summarize     │
│                                                                               │
│  PRE-CORE SPECIALIST PATH:                                                    │
│  ────────────────────────                                                     │
│  "hotel options?" + missing core ──► specialist (pre_core=True)              │
│                                   ──► Template response + core field ask      │
│                                                                               │
│  STRATEGY PRE-CORE VALUE PATH (NEW):                                          │
│  ───────────────────────────────────                                          │
│  "plan a hiking trip" + no destinations ──► strategy_node (stage=0)          │
│                                          ──► Destination archetypes +         │
│                                              mini itinerary + one question    │
│                                                                               │
│  STRATEGY TOPIC SWITCH PATH (NEW):                                            │
│  ─────────────────────────────────                                            │
│  "I wanna go diving too" (mid-session) ──► STRATEGY_TOPIC_SWITCH gate        │
│                                        ──► strategy_diving (stage=1)          │
│                                                                               │
│  If blocking_errors exist:                                                    │
│  ─────────────────────────                                                    │
│  "I wanna go diving" + ambiguous dates ──► Store pending_strategy_topic      │
│                                        ──► Route to date clarification        │
│                                        ──► Next turn: auto-fire topic switch  │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Node Inventory Table

| Node                      | Prompt File                                              | Purpose                                                            | Wired | LLM Model              | Max Output Tokens        | Inputs Required                       | Inputs Blocked      |
| ------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------ | ----- | ---------------------- | ------------------------ | ------------------------------------- | ------------------- |
| `lqa_prepass`             | —                                                        | Zero-LLM pre-pass for simple answers to last question              | ✅    | —                      | —                        | `user_text`, `question_target`        | —                   |
| `extractor`               | `extractor.txt` / `extractor_light.txt`                  | Extract structured trip data from user text                        | ✅    | gpt-4o-mini            | 128 (light) / 400 (full) | `user_text`, `trip_inputs`            | —                   |
| `normalize_inputs`        | —                                                        | Single-pass normalization of all extracted inputs                  | ✅    | —                      | —                        | `parsed_inputs`, `trip_inputs`        | —                   |
| `router`                  | `router.txt`                                             | Intent classification to route to specialists                      | ✅    | gpt-4o-mini            | 256                      | `parsed_inputs`, `trip_inputs` (view) | —                   |
| `required_fields_node`    | `required_fields.txt` / `required_fields_templates.json` | Collect missing core fields (destinations, dates, etc.)            | ✅    | gpt-4o-mini (fallback) | 256                      | `trip_inputs`, `missing_fields`       | —                   |
| `flights_node`            | `flights.txt`                                            | Flight preferences (cabin, direct, round_trip)                     | ✅    | gpt-4o-mini            | 512                      | `trip_inputs`, `flight_settings`      | Core fields missing |
| `hotels_node`             | `hotels.txt`                                             | Hotel/accommodation preferences                                    | ✅    | gpt-4o-mini            | 512                      | `trip_inputs`, `hotel_settings`       | Core fields missing |
| `transport_node`          | `transport.txt`                                          | Ground transport preferences (car, train, bus)                     | ✅    | gpt-4o-mini            | 512                      | `trip_inputs`, `transport_settings`   | Core fields missing |
| `activities_node`         | `activities.txt`                                         | Activity/attraction preferences                                    | ✅    | gpt-4o-mini            | 512                      | `trip_inputs`, `activity_settings`    | Core fields missing |
| `correction_node`         | `correction.txt`                                         | Handle infeasibility and corrections                               | ✅    | gpt-4o-mini            | 512                      | `trip_inputs`, `user_text`            | — (exempt)          |
| `general_node`            | `general.txt`                                            | Multi-domain query handling                                        | ✅    | gpt-4o-mini            | 512                      | `trip_inputs`, `parsed_inputs`        | —                   |
| `strategy_node`           | `strategy_{topic}.txt` / `strategy_pre_core.txt`         | Adventure activity planning (boating/hiking/diving/skiing/cycling) | ✅    | gpt-4o-mini            | 300 (stage0) / 512-2048  | `trip_inputs`, `strategy_topic`       | — (stage0 exempt)   |
| `validate_and_merge`      | —                                                        | Compute ready_to_generate, auto-enable booking types               | ✅    | —                      | —                        | `trip_inputs`, `errors`               | —                   |
| `branch_postprocess`      | —                                                        | Split multi-city branches, normalize specs, generate IDs           | ✅    | —                      | —                        | `branches`, `trip_inputs`             | —                   |
| `tile_search`             | —                                                        | Search for tiles (hotels, flights, activities)                     | ✅    | —                      | —                        | `branches`, `booking_types`           | Core fields missing |
| `short_circuit_responder` | —                                                        | Handle greetings, confirmations without LLM                        | ✅    | —                      | —                        | `flags.short_circuit`                 | —                   |
| `generate_responder`      | —                                                        | Handle explicit plan generation requests                           | ✅    | —                      | —                        | `flags.generate_requested`            | —                   |
| `summarize`               | —                                                        | Generate default follow-ups, append safety snippets                | ✅    | —                      | —                        | `last_summary`, `trip_inputs`         | —                   |
| `response_polish`         | `response_polish.txt`                                    | Polish messages for natural tone                                   | ✅    | gpt-4o-mini (fallback) | 512                      | `last_summary`                        | —                   |

---

## Short Circuits & Caching by Node

### Short Circuit Types

| Type                 | Pattern                              | Trigger                           | Handler                   | Tokens Saved |
| -------------------- | ------------------------------------ | --------------------------------- | ------------------------- | ------------ |
| `greeting`           | `hi`, `hello`, `hey`, `good morning` | Regex match on input              | `short_circuit_responder` | ~800-1500    |
| `acknowledgment`     | `ok`, `thanks`, `got it`, `sure`     | Regex match on input              | `short_circuit_responder` | ~800-1500    |
| `confirmation_yes`   | `yes`, `yeah`, `yep`, `sure`         | Regex match + pending action      | `short_circuit_responder` | ~800-1500    |
| `confirmation_no`    | `no`, `nope`, `cancel`               | Regex match + pending action      | `short_circuit_responder` | ~800-1500    |
| `off_topic`          | Non-travel queries                   | Router classification             | `summarize`               | ~500         |
| `initial_extraction` | Simple first messages                | `_try_initial_message_extraction` | Skip full extractor       | ~500-1000    |
| `strategy_bootstrap` | Simple strategy prompts              | `_try_strategy_bootstrap_bypass`  | Skip extractor LLM        | ~500-1000    |

### Caching Mechanisms

| Cache              | TTL        | Key Components                                          | Used By                          | Tokens Saved |
| ------------------ | ---------- | ------------------------------------------------------- | -------------------------------- | ------------ |
| `_extractor_cache` | 60s        | `session_id`, `user_text`, `core_fields_hash`, `mode`   | `extractor`                      | ~500-1000    |
| `_follow_up_cache` | Configured | `node`, `core_fields`, `user_intent`, `user_text_hash`  | `router`, `required_fields_node` | ~500-1500    |
| `_strategy_cache`  | 5 min      | `session_id`, `topic`, `core_fields_hash`, `section_id` | `strategy_node`                  | ~2000-3000   |
| `_tile_cache`      | Session    | `intent`, `destinations`, `start_date`, `origin`        | `tile_search`                    | N/A (API)    |

### Per-Node Short Circuits

#### `lqa_prepass`

| Condition   | Trigger                            | Action                             |
| ----------- | ---------------------------------- | ---------------------------------- |
| LQA success | Simple answer to `question_target` | Skip extractor, route to normalize |
| Short input | `len(user_text) <= LQA_MAX_LENGTH` | Attempt LQA parse                  |

#### `extractor`

| Condition              | Trigger                                    | Action                                 |
| ---------------------- | ------------------------------------------ | -------------------------------------- |
| Short-circuit detected | Greeting/ack/confirmation pattern          | Skip to `short_circuit_responder`      |
| Initial extraction     | `_try_initial_message_extraction` succeeds | Skip LLM call                          |
| Cache hit              | Same user_text + core_fields recently      | Return cached result                   |
| Light mode             | `turn_number < 3` or simple input          | Use `extractor_light.txt` (128 tokens) |

#### `router`

| Condition       | Trigger                                      | Action          |
| --------------- | -------------------------------------------- | --------------- |
| Gate bypass     | GateEvaluator fires KEYWORD_HEURISTIC        | Skip router LLM |
| Scoring router  | Deterministic scoring succeeds               | Skip router LLM |
| High confidence | `extraction_confidence > 0.92` + short input | Skip router LLM |

#### `required_fields_node`

| Condition      | Trigger                            | Action                            |
| -------------- | ---------------------------------- | --------------------------------- |
| Template hit   | Simple missing field, no ambiguity | Return template response          |
| Typo detection | Low-confidence extraction          | Use `required_fields_confirm.txt` |
| Pre-core mode  | Domain intent + missing core       | Template + core field question    |

#### `flights_node` / `hotels_node` / `transport_node` / `activities_node`

| Condition       | Trigger                             | Action                                    |
| --------------- | ----------------------------------- | ----------------------------------------- |
| Specialist gate | Core fields missing                 | Block node, redirect to `required_fields` |
| No-op gate      | Vague affirmation without specifics | Skip LLM, continue flow                   |
| Pre-core mode   | Domain keyword + missing core       | Template response + core ask              |

#### `strategy_node`

| Condition    | Trigger                                  | Action                                |
| ------------ | ---------------------------------------- | ------------------------------------- |
| Stage 0      | STRATEGY_PRE_CORE_VALUE gate + no dests  | 300 tokens (value-first + 1 question) |
| Stage 1      | Initial strategy request (core complete) | 512 tokens (outline only)             |
| Stage 2      | Expansion request                        | 768-2048 tokens (section/full)        |
| Cache hit    | Same topic + core fields                 | Return cached strategy                |
| Topic guard  | Topic not in enabled strategies          | Skip node                             |
| Loop guard   | Stage 0 question ignored 2x              | Escalate to required_fields           |
| Output guard | Stage 0 output lacks bullets/question    | Add fallback question, log metric     |

**Stage 0 Implementation Notes:**

- Uses `_strategy_stage0()` function with `call_llm_with_timeout()` for LLM invocation
- Prompt uses Jinja2 templating (`{{ variable }}` syntax) to avoid conflicts with JSON includes
- JSON response parsed via `jloads_safe()` for safe extraction
- Output validated for bullet points (≥2) and exactly 1 clarifying question

#### `response_polish`

| Condition         | Trigger                                | Action             |
| ----------------- | -------------------------------------- | ------------------ |
| Template response | Message is template-generated          | Skip polish        |
| Short-circuit     | Message from `short_circuit_responder` | Skip polish        |
| Already formatted | Message has markdown headers           | Skip polish        |
| Deterministic     | Safe transforms available              | Apply without LLM  |
| MVP mode          | `enable_response_polish_mvp=False`     | Deterministic only |

#### `tile_search`

| Condition           | Trigger                            | Action              |
| ------------------- | ---------------------------------- | ------------------- |
| Core fields missing | `should_run_tile_search()=False`   | Skip tile search    |
| No booking types    | `booking_types` all False          | Skip tile search    |
| Cache hit           | Same intent + destinations + dates | Return cached tiles |

---

## Prompt File Mapping

### Main Prompts

| File                          | Nodes Using It                 | Est. Input Tokens | Max Output | Includes                                                                                |
| ----------------------------- | ------------------------------ | ----------------- | ---------- | --------------------------------------------------------------------------------------- |
| `extractor.txt`               | `extractor` (full mode)        | ~200              | 400        | —                                                                                       |
| `extractor_light.txt`         | `extractor` (light mode)       | ~80               | 128        | —                                                                                       |
| `router.txt`                  | `router`                       | ~150              | 256        | —                                                                                       |
| `required_fields.txt`         | `required_fields_node`         | ~150              | 256        | `_json_output.txt`                                                                      |
| `required_fields_confirm.txt` | `required_fields_node` (typo)  | ~120              | 256        | `_json_output.txt`                                                                      |
| `missing_fields_guard.txt`    | `_invoke_missing_fields_guard` | ~80               | 128        | —                                                                                       |
| `strategy_pre_core.txt`       | `strategy_node` (stage 0)      | ~120              | 300        | `_json_output.txt` (Jinja2 syntax)                                                      |
| `flights.txt`                 | `flights_node`                 | ~150              | 512        | `_scope_specialist.txt`, `_json_output.txt`, `_never_invent.txt`, `_markdown_rules.txt` |
| `hotels.txt`                  | `hotels_node`                  | ~200              | 512        | `_scope_specialist.txt`, `_json_output.txt`, `_never_invent.txt`, `_markdown_rules.txt` |
| `activities.txt`              | `activities_node`              | ~150              | 512        | `_scope_specialist.txt`, `_json_output.txt`, `_never_invent.txt`, `_markdown_rules.txt` |
| `transport.txt`               | `transport_node`               | ~150              | 512        | `_scope_specialist.txt`, `_json_output.txt`, `_never_invent.txt`, `_markdown_rules.txt` |
| `correction.txt`              | `correction_node`              | ~150              | 512        | `_json_output.txt`, `_markdown_rules.txt`                                               |
| `general.txt`                 | `general_node`                 | ~150              | 512        | `_json_output.txt`, `_markdown_rules.txt`                                               |
| `response_polish.txt`         | `response_polish`              | ~100              | 512        | —                                                                                       |
| `condense.txt`                | `condense_long_message`        | ~80               | 512        | —                                                                                       |

### Strategy Prompts

| File                   | Topic               | Est. Input Tokens | Max Output | Includes                                                        |
| ---------------------- | ------------------- | ----------------- | ---------- | --------------------------------------------------------------- |
| `strategy_boating.txt` | Boating/sailing     | ~200              | 512-2048   | `_strategy_base.txt`, `_json_output.txt`, `_markdown_rules.txt` |
| `strategy_hiking.txt`  | Hiking/trekking     | ~200              | 512-2048   | `_strategy_base.txt`, `_json_output.txt`, `_markdown_rules.txt` |
| `strategy_diving.txt`  | Diving/snorkeling   | ~200              | 512-2048   | `_strategy_base.txt`, `_json_output.txt`, `_markdown_rules.txt` |
| `strategy_skiing.txt`  | Skiing/snowboarding | ~200              | 512-2048   | `_strategy_base.txt`, `_json_output.txt`, `_markdown_rules.txt` |
| `strategy_cycling.txt` | Cycling/biking      | ~200              | 512-2048   | `_strategy_base.txt`, `_json_output.txt`, `_markdown_rules.txt` |

### Shared Includes (Jinja2)

| File                    | Purpose                                       | Est. Tokens | Used By              |
| ----------------------- | --------------------------------------------- | ----------- | -------------------- |
| `_json_output.txt`      | JSON output format with `suggested_responses` | ~30         | All specialists      |
| `_markdown_rules.txt`   | Markdown formatting rules                     | ~50         | All specialists      |
| `_never_invent.txt`     | Guard against value invention                 | ~20         | Domain specialists   |
| `_scope_specialist.txt` | Scope limiting for specialists                | ~100        | Domain specialists   |
| `_strategy_base.txt`    | Shared strategy rules                         | ~100        | All strategy prompts |

**Jinja2 Templating Note:** Prompts that include `_json_output.txt` must use Jinja2 syntax
(`{{ variable }}`) instead of Python `.format()` syntax (`{variable}`) to avoid conflicts
with JSON curly braces in the included content.

### Data Files

| File                             | Purpose                        | Used By                |
| -------------------------------- | ------------------------------ | ---------------------- |
| `required_fields_templates.json` | Template questions/suggestions | `required_fields_node` |

---

## Duplication Analysis

### No Major Duplications Found ✅

The codebase is well-organized with single sources of truth:

| Pattern                    | Location                              | Status                 |
| -------------------------- | ------------------------------------- | ---------------------- |
| Core field priority        | `CORE_FIELD_PRIORITY` constant        | ✅ Single definition   |
| Missing fields calculation | `compute_trip_readiness()`            | ✅ Canonical function  |
| Specialist prompt loading  | `_specialist()` function              | ✅ Centralized handler |
| Date normalization         | `TripInputNormalizer.normalize_all()` | ✅ Single pass         |
| Gate evaluation            | `GateEvaluator.evaluate()`            | ✅ Centralized logic   |
| Trip extraction            | `extractor` node only                 | ✅ Not duplicated      |

### Minor Patterns (Not Issues)

| Pattern                                         | Note                                                 |
| ----------------------------------------------- | ---------------------------------------------------- |
| `CORE_FIELD_PRIORITY` referenced multiple times | Intentional - single constant used by many functions |
| Specialist nodes share structure                | Intentional - all go through `_specialist()` factory |
| Short-circuit patterns                          | Compiled once, reused via module-level constants     |

---

## Unused/Dead Code Analysis

### Potentially Unused Functions

| Function                       | Location            | Status           | Notes                                             |
| ------------------------------ | ------------------- | ---------------- | ------------------------------------------------- |
| `validate_template_coverage()` | plan_graph.py ~9300 | ⚠️ Check startup | Should be called at startup to validate templates |
| `clear_tile_cache()`           | plan_graph.py       | ⚠️ Utility       | Exposed for testing/debugging                     |
| `ensure_tiles()`               | plan_graph.py       | ⚠️ Utility       | Exposed for external callers                      |

### Conditionally Used

| Item                    | Condition                                  | Notes                           |
| ----------------------- | ------------------------------------------ | ------------------------------- |
| `_scope_specialist.txt` | Stripped by `_strip_specialist_includes()` | Removed in Phase 6 optimization |
| LLM polish              | `enable_response_polish_mvp=False`         | Disabled in MVP mode            |
| Strategy prompts        | `enable_strategy_{topic}` config flags     | Can be disabled per-topic       |

### All Prompt Files Used ✅

All 26 prompt files are actively wired:

- 5 shared includes (via Jinja2)
- 15 main prompts (including `strategy_pre_core.txt`)
- 5 strategy topic prompts
- 1 JSON template file

---

## Gate Precedence Reference

The `GateEvaluator` checks gates in strict precedence order. First match wins.

**Gate Suppression**: Some gates explicitly yield to higher-priority paths:

- `SPECIALIST_PRE_CORE` yields to `STRATEGY_PRE_CORE_VALUE` when strategy topic detected without destinations
- This prevents "activities" keyword from shadowing open-ended strategy planning

| Precedence | Gate                      | Destination                 | Description                                      | Yields To                       |
| ---------- | ------------------------- | --------------------------- | ------------------------------------------------ | ------------------------------- |
| 1          | `SHORT_CIRCUIT`           | `short_circuit_responder`   | Greetings, confirmations, generate triggers      | —                               |
| 2          | `FAST_PATH`               | Specialists/validate        | LQA pre-pass success or initial extraction       | — (bootstrap-only after turn 1) |
| 3          | `SPECIALIST_PRE_CORE`     | Specialists (pre-core mode) | Domain keyword detected, core fields missing     | `STRATEGY_PRE_CORE_VALUE`       |
| 4          | `STRATEGY_TOPIC_SWITCH`   | `strategy_{topic}`          | Mid-session strategy topic switch (new activity) | — (deferred if blocking errors) |
| 5          | `STRATEGY_PRE_CORE_VALUE` | `strategy_node` (stage 0)   | Strategy topic + no destinations → value-first   | —                               |
| 6          | `CORE_COLLECTION`         | `required_fields_node`      | Core fields missing, no domain keyword           | —                               |
| 7          | `HIGH_CONFIDENCE`         | Based on parsed data        | High extraction confidence + short input         | —                               |
| 8          | `QUESTION_KEYWORD`        | Based on keyword            | User answering question with domain keyword      | —                               |
| 9          | `KEYWORD_HEURISTIC`       | Based on keyword            | Unambiguous domain keywords detected             | —                               |
| 10         | `SCORING_ROUTER`          | Deterministic scoring       | Multi-signal scoring-based routing               | —                               |
| 99         | `ROUTER_LLM`              | `router` node               | Fallback to LLM-based intent classification      | —                               |

### Key Helper Functions

| Function                         | Purpose                                                                     |
| -------------------------------- | --------------------------------------------------------------------------- |
| `_is_strategy_pre_core_eligible` | Checks if strategy pre-core conditions met (topic + no dest + core missing) |
| `_check_specialist_pre_core`     | Detects specialist keywords, yields to strategy when topic also detected    |
| `_check_strategy_pre_core_value` | Detects strategy topic and determines question_target priority              |
| `_check_strategy_topic_switch`   | Detects mid-session strategy topic changes with intent verbs and cooldowns  |

### STRATEGY_TOPIC_SWITCH Gate Details

The `STRATEGY_TOPIC_SWITCH` gate handles mid-session activity changes like "I wanna go diving in Argentina too"
when the session already has hiking as the strategy topic.

**Trigger Conditions (all must be met):**

1. Strategy keyword detected in user text (diving, skiing, hiking, cycling, boating)
2. Intent verb present ("wanna", "want to", "go", "plan", "try", "would like to")
3. Topic differs from `last_strategy_topic` OR explicit re-request with override phrase
4. Cooldown expired OR override phrase used ("actually", "instead", "rather", "on second thought")
5. Auto-fire mode: `pending_strategy_topic` stored from previous turn

**Deferred Switching (Pending Topic):**

When topic switch is detected but `blocking_errors` exist (e.g., ambiguous dates):

1. Store `pending_strategy_topic` in metadata
2. Route to date clarification first
3. On next turn when blocking errors clear, auto-fire the pending topic switch

**Cooldown Mechanism:**

After a successful topic switch, `topic_switch_cooldown_until_turn` is set to prevent rapid oscillation.
Default cooldown is 2 turns. Override phrases bypass the cooldown.

**Category Canonicalization:**

Activity categories are canonicalized to lowercase keys (no emojis) for consistent routing:

- "🤿 Diving" → "diving"
- "scuba diving" → "diving" (via ACTIVITY_ALIAS_MAP)
- "HIKING" → "hiking"

This ensures `STRATEGY_TOPIC_TO_NODE["diving"]` lookups work correctly regardless of how the
category was originally extracted.

---

## Strategy Bootstrap Bypass

### Overview

The **Strategy Bootstrap Bypass** is a first-turn latency optimization that eliminates one LLM call
for simple strategy prompts like "Plan an adventure trip with hiking". Instead of running both
`extractor` LLM and `strategy_node:stage0` LLM, we deterministically set strategy fields and skip
straight to `strategy_node:stage0`.

### Performance Impact

| Scenario               | Before (LLM calls)   | After (LLM calls) | Latency Saved |
| ---------------------- | -------------------- | ----------------- | ------------- |
| Simple strategy prompt | 2 (extractor+stage0) | 1 (stage0 only)   | ~500-1000ms   |
| Strategy + place       | 2                    | 2 (no bypass)     | 0             |
| Strategy + constraints | 2                    | 2 (no bypass)     | 0             |

### Safety Gates

The bypass is protected by 9 safety gates. ALL must pass for bypass to trigger:

| Gate                       | Check                                                   | Rationale                            |
| -------------------------- | ------------------------------------------------------- | ------------------------------------ |
| 1. Feature flag            | `settings.enable_strategy_bootstrap_bypass`             | Kill switch for rollback             |
| 2. Sample rate             | Deterministic hash-based cohort                         | A/B testing support                  |
| 3. No question_target      | `question_target` not set                               | Indicates open-ended prompt          |
| 4. Core fields empty       | No destinations/dates extracted                         | First turn detection                 |
| 5. Strategy topic detected | Regex patterns for hiking/skiing/diving/cycling/boating | Must match known topic               |
| 6. No place entities       | `_is_place_like_text()` returns False                   | Place requires full extraction       |
| 7. Short text              | `len(text) <= 150` chars                                | Long text may have hidden complexity |
| 8. No constraint tokens    | No dates/budget/travelers patterns                      | Constraints need LLM extraction      |
| 9. No multi-intent         | < 2 specialist keywords                                 | Multi-intent needs router            |

### Bypass Flow

```
User: "Plan an adventure trip with hiking"
       │
       ▼
┌──────────────────────────────────┐
│ extractor (start)                │
│  ├─ _try_strategy_bootstrap_bypass()
│  │   ├─ Gate 1: feature enabled? ✅
│  │   ├─ Gate 2: sample rate? ✅
│  │   ├─ Gate 3: no question_target? ✅
│  │   ├─ Gate 4: core fields empty? ✅
│  │   ├─ Gate 5: topic detected? ✅ → "hiking"
│  │   ├─ Gate 6: no place entities? ✅
│  │   ├─ Gate 7: short text? ✅
│  │   ├─ Gate 8: no constraints? ✅
│  │   └─ Gate 9: no multi-intent? ✅
│  │
│  └─ BYPASS TRIGGERED
│     ├─ Set state.strategy_topic = "hiking"
│     ├─ Set trip_style = "adventure_outdoors"
│     ├─ Set activity_categories = ["hiking", "trekking"]
│     ├─ Set question_target = "dates"
│     └─ Record observability metadata
│
└──────────────────────────────────┘
       │
       ▼ (skip extractor LLM)
┌──────────────────────────────────┐
│ strategy_node:stage0             │
│  └─ Single LLM call for value-   │
│     first response               │
└──────────────────────────────────┘
```

### Deterministic Fields Set by Bypass

| Field                 | Value                               | Source                               |
| --------------------- | ----------------------------------- | ------------------------------------ |
| `strategy_topic`      | Detected topic (hiking/skiing/etc.) | `_detect_strategy_topic_from_text()` |
| `trip_style`          | `adventure_outdoors`                | Topic-to-style mapping               |
| `activity_categories` | Topic-specific list                 | Topic-to-activities mapping          |
| `question_target`     | `dates`                             | Always ask for dates first           |
| `bypass_variant`      | `bypass`                            | Observability tag                    |

### Stage0 Fallback Template

If `_strategy_stage0()` LLM call fails (timeout, JSON error, etc.), a deterministic fallback
template is used instead of calling `required_fields_node`:

```python
# Example for hiking topic:
"Great choice! Hiking adventures are incredibly rewarding.

Here are some amazing destinations to consider:
- **Swiss Alps** - Iconic trails like the Haute Route
- **Patagonia, Chile** - Torres del Paine circuit
- **New Zealand** - Milford Track and Routeburn
- **Nepal** - Classic Annapurna or Everest base camp

When are you thinking of going?"
```

Fallback templates exist for all 5 strategy topics (hiking, skiing, diving, cycling, boating).
Date suggestions are generated dynamically relative to today's date.

### Configuration

| Setting                                 | Default | Purpose                   |
| --------------------------------------- | ------- | ------------------------- |
| `enable_strategy_bootstrap_bypass`      | `True`  | Master kill switch        |
| `strategy_bootstrap_bypass_sample_rate` | `1.0`   | A/B test sample (0.0-1.0) |

### Observability

Bypass decisions are logged with:

- `bypass_variant`: "bypass" or "control"
- `bypass_reject_reasons`: List of failed gates (if rejected)
- `strategy_stage0_deterministic`: True if fallback template used

---

## Date Handling Architecture

### Overview

Date handling involves multiple nodes with distinct responsibilities. This section documents the
contract between nodes to prevent loops and ensure correct date range parsing.

### Date Error Codes

| Code                  | Constant                       | Trigger                                          | Blocking |
| --------------------- | ------------------------------ | ------------------------------------------------ | -------- |
| `DATE_AMBIGUOUS_YEAR` | `DateErrorCode.AMBIGUOUS_YEAR` | Date range straddles today (Dec 20-27 on Dec 21) | ✅       |
| `DATE_RANGE_INVALID`  | `DateErrorCode.RANGE_INVALID`  | Dates reversed after all corrections             | ✅       |
| `DATE_PARSE_FAILED`   | `DateErrorCode.PARSE_FAILED`   | Unparseable date string                          | ❌       |

Blocking errors prevent `GENERATE_PLAN_NOW` from proceeding until resolved.

### Blocking Errors and TripReadiness

The `TripReadiness` dataclass includes a `blocking_errors` field that tracks date-related errors
that must be resolved before plan generation:

```python
@dataclass
class TripReadiness:
    missing_core: List[str]       # Missing core fields (destinations, dates, etc.)
    question_target: Optional[str] # Next field to ask about
    ready_to_generate: bool        # True only when all conditions met
    blocking_errors: List[str]     # Blocking error codes (e.g., "AMBIGUOUS_YEAR")

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.blocking_errors)
```

**Blocking Error Codes:**

- `AMBIGUOUS_YEAR`: Date range year is ambiguous
- `RANGE_INVALID`: Dates remain reversed after correction attempts

**Impact on Routing:**

1. **CORE_COLLECTION gate**: Forces `question_target = "dates"` when `has_blocking_errors`
2. **STRATEGY_TOPIC_SWITCH gate**: Defers topic switch, stores as `pending_strategy_topic`
3. **compute_trip_readiness()**: Sets `ready_to_generate = False` when blocking errors exist

**Loop Guard Enforcement:**

The `_invoke_missing_fields_guard()` function now refuses field switching when `date_clarify_mode`
or `blocking_errors` exist:

```python
# In _invoke_missing_fields_guard():
if in_date_clarify_mode or has_blocking_errors:
    if llm_question_target not in ("dates", "start_date", "end_date"):
        state.question_target = "dates"  # Force dates, ignore LLM suggestion
```

This prevents the loop guard from switching to travelers/other fields when date errors are unresolved.

### Ownership Hierarchy

Date parsing has a strict ownership chain - later stages ONLY enforce invariants, never guess:

| Stage | Component               | Role                                                     |
| ----- | ----------------------- | -------------------------------------------------------- |
| 1     | LQA pre-pass            | Zero-LLM deterministic parse of simple date answers      |
| 2     | FULL extractor (LLM)    | Authoritative extraction, can interpret complex phrasing |
| 3     | `validate_date_range()` | Invariant enforcement ONLY - never stores reversed dates |

### Question Target Contract

The `question_target` field is canonicalized at the start of `run_turn()`:

| Raw Target           | Canonical Target | Notes                              |
| -------------------- | ---------------- | ---------------------------------- |
| `start_date`         | `dates`          | LQA and templates keyed by "dates" |
| `end_date`           | `dates`          | Same as above                      |
| `dates`              | `dates`          | Already canonical                  |
| `travelers (adults)` | `travelers`      | Normalized for template lookup     |
| `adults`             | `travelers`      | Same as above                      |

The `canonicalize_question_target()` function ensures consistent mapping across all nodes.

### Date Clarify Mode

When date ambiguity is detected, the system enters `date_clarify_mode`:

#### Lifecycle

| Transition     | Trigger                                                       |
| -------------- | ------------------------------------------------------------- |
| **Set True**   | `DATE_AMBIGUOUS_YEAR` or `DATE_RANGE_INVALID` error generated |
| **Stays True** | Valid range not stored AND date errors still present          |
| **Set False**  | Valid ordered range stored AND no date errors remain          |

#### Storage

- Flag stored in `state.metadata["date_clarify_mode"]`
- Pending dates stored in `state.metadata["pending_date_range"]`
- NOT stored in `trip_inputs` until resolved

#### Template Response

When in clarify mode, the `dates_clarify` template is used:

```json
{
  "dates_clarify": {
    "questions": [
      "I got {date_range}, but which year did you mean?",
      "Just to confirm—did you mean {date_range} this year or next?"
    ],
    "suggestions": [
      "This {month} ({current_year})",
      "Next {month} ({next_year})",
      "Different dates"
    ]
  }
}
```

### LQA Skip Heuristic

When `question_target == "dates"`, LQA applies a skip heuristic to avoid misfiring on non-date text:

| Check               | Function                | Purpose                                        |
| ------------------- | ----------------------- | ---------------------------------------------- |
| Is date-like text?  | `_is_date_like_text()`  | Detects months, "next/this", digits+separators |
| Is place-like text? | `_is_place_like_text()` | Detects capitals, multi-word proper nouns      |

If text is NOT date-like AND IS place-like (e.g., "Swiss Alps"), LQA bails with reason
`"not_date_like"` instead of `"validation_fail"`. This prevents spurious error accumulation.

### LQA Clarify Response Parser

During `date_clarify_mode`, LQA can parse year-clarifying responses:

| Pattern                           | Parsing                                   |
| --------------------------------- | ----------------------------------------- |
| `"This December"`                 | Apply pending range to current year       |
| `"Next December"` / `"Next year"` | Apply pending range to next year          |
| `"This December (2025)"`          | Explicit year extraction from parentheses |
| `"2026"`                          | Explicit year for pending range           |

### Loop Guard Escalation

The loop guard has special handling for date errors and includes cooldown/max trigger enforcement:

| Condition                                                  | Mitigation        | Suggestion Count |
| ---------------------------------------------------------- | ----------------- | ---------------- |
| Field is `"dates"` AND `date_clarify_mode=True`            | `dates_clarify`   | 3                |
| Field is `"dates"` AND `DATE_AMBIGUOUS_YEAR` error present | `dates_clarify`   | 3                |
| Standard field loop                                        | `different_field` | —                |

#### Cooldown Enforcement

After a loop guard triggers, a cooldown period prevents immediate re-triggering:

```python
# Check if still in cooldown
cooldown_until = state.metadata.get("loop_guard_cooldown_until", 0)
if state.turn_number < cooldown_until:
    # Skip mitigation, return None
    return None
```

Configuration: `loop_guard_cooldown_turns` (default: 2)

#### Max Triggers Per Conversation

To prevent infinite mitigation loops, there's a per-conversation trigger limit:

```python
# Check if max triggers exceeded
triggers_this_convo = state.metadata.get("loop_guard_triggers_this_convo", 0)
if triggers_this_convo >= settings.loop_guard_max_triggers_per_convo:
    # Log and skip mitigation
    _debug("Loop guard max triggers exceeded, skipping")
    return None
```

Configuration: `loop_guard_max_triggers_per_convo` (default: 5)

### Generation Blocking

Gate 0 (`GENERATE_REQUESTED`) blocks when date errors exist:

```python
# In GateEvaluator.evaluate()
if flags.get("generate_requested"):
    has_blocking_date_errors = (
        state.metadata.get("date_clarify_mode") or
        any(code in err for err in state.errors for code in DATE_BLOCKING_ERROR_CODES)
    )
    if has_blocking_date_errors:
        # Redirect to dates clarification instead of generate
        return GateResult(destination="dates_clarify", reason="date_errors")
```

### Observability

Date handling metrics are tracked in `_date_stats`:

| Counter                        | Description                            |
| ------------------------------ | -------------------------------------- |
| `date_ambiguous_year_count`    | Times straddle-today detected          |
| `date_range_invalid_count`     | Times reversed range couldn't be fixed |
| `dates_clarify_shown_count`    | Times dates_clarify template shown     |
| `dates_clarify_resolved_count` | Times clarify successfully resolved    |
| `turns_in_date_clarify_mode`   | Total turns spent in clarify mode      |
| `lqa_skip_not_date_like`       | Times LQA skipped non-date text        |

### Example Flow: December 20-27 on December 21

1. **User**: "December 20-27"
2. **DateNormalizer.parse_date_range()**: Returns `(2025-12-20, 2025-12-27)`
3. **validate_date_range()**: Detects straddle-today (start=past, end=future)
4. **Error generated**: `DATE_AMBIGUOUS_YEAR`
5. **State updated**: `metadata["date_clarify_mode"]=True`, dates cleared
6. **Response**: "I got December 20-27, but which year did you mean?"
7. **Suggestions**: `["This December (2025)", "Next December (2026)", "Different dates"]`
8. **User**: "Next December"
9. **LQA `_parse_date_answer()`**: Applies pending range to 2026
10. **Result**: `start_date=2026-12-20`, `end_date=2026-12-27`
11. **validate_date_range()**: Range is valid (both future)
12. **State updated**: `metadata["date_clarify_mode"]=False`

---

## Startup Warmup

### Overview

The `prewarm_prompts()` function is called during application startup (via FastAPI lifespan) to
pre-load and compile all Jinja2 templates. This reduces first-request latency by avoiding
template loading overhead during the first user turn.

### Implementation

```python
async def prewarm_prompts() -> Dict[str, Any]:
    """Pre-load and compile all prompt templates at startup."""
    start = time.perf_counter()
    loaded = []

    # Load all prompt files via Jinja2 environment
    for template_name in _JINJA_ENV.list_templates():
        try:
            _JINJA_ENV.get_template(template_name)
            loaded.append(template_name)
        except Exception as e:
            _debug_error(f"Failed to load {template_name}", error=str(e))

    elapsed_ms = (time.perf_counter() - start) * 1000
    return {"loaded": len(loaded), "elapsed_ms": elapsed_ms}
```

### Lifespan Integration

```python
# In main.py lifespan
async with lifespan(app):
    await prewarm_cache()      # Existing cache warmup
    await prewarm_prompts()    # NEW: Template warmup
    yield
```

### Monitoring

Use `get_warmup_stats()` to check warmup status:

```python
stats = get_warmup_stats()
# Returns: {"prompts_loaded": 26, "warmup_elapsed_ms": 12.5}
```

---

## Observability & Stats

### Metrics Dictionaries

| Dict                         | Purpose                                |
| ---------------------------- | -------------------------------------- |
| `_routing_stats`             | Gate hits, router calls, bypasses      |
| `_template_stats`            | Template hit/miss rates                |
| `_strategy_stats`            | Strategy cache hits, stage transitions |
| `_polish_stats`              | Polish bypasses, deterministic hits    |
| `_extractor_stats`           | Light/full mode usage, cache hits      |
| `_gate_stats`                | Per-gate trigger counts                |
| `_lqa_stats`                 | LQA pre-pass success rates             |
| `_router_stats`              | Router LLM call frequency              |
| `_state_integrity_counters`  | Invariant violations                   |
| `_date_stats`                | Date ambiguity, clarify mode tracking  |
| `_deterministic_parse_stats` | MVP deterministic pipeline hits        |

### Key Histograms

| Metric                       | Purpose                          |
| ---------------------------- | -------------------------------- |
| `trip_inputs_keycount_delta` | Fields changed per turn          |
| `llm_calls_per_turn`         | LLM invocations per user message |

---

## MVP Extractor Optimization

> **Implemented**: January 2025
> **Optimization Target**: Eliminate ~552 tokens for single-place/season/suggestion-click answers

### Overview

The MVP optimization introduces a **deterministic parsing pipeline** that runs BEFORE the extractor LLM. When the system asks a simple question like "When would you like to travel?" and the user gives a straightforward answer like "next summer" or clicks a suggestion, we can parse it without any LLM call.

### Deterministic Pipeline

**Pipeline order** (each stage returns immediately on hit):

1. **Suggestion echo** - User clicked/typed exact match to a suggestion
2. **Season/date parser** - "next summer", "spring", "next month"
3. **Travelers micro-parser** - "solo", "couple", "family of 4"
4. **Multi-place splitter** - "Paris and Rome" → ["Paris", "Rome"]
5. **Single place parser** - Known place detection

### Key Changes

| Change                         | Description                                                 | Tokens Saved  |
| ------------------------------ | ----------------------------------------------------------- | ------------- |
| Deterministic pipeline         | Parse simple answers without LLM                            | ~550 per hit  |
| Suggestion echo channel        | Store suggestions with field type for deterministic match   | N/A           |
| Season date parser             | Parse "summer", "spring" to date ranges                     | ~550          |
| Travelers micro-parser         | Parse "solo", "couple" to adults/children                   | ~550          |
| extractor_light prompt trimmed | Reduced from ~70 to ~35 lines                               | ~100-150      |
| Response provenance tracking   | Single-source-of-truth for polish skip decisions            | Cleaner logic |
| Bootstrap flag fix             | Set `strategy_bootstrap_active = True` explicitly (was bug) | Correctness   |

### Implementation Details

#### 1. Suggestion Type Hint Channel

```python
# When setting suggestions, also store field type
store_suggestions_with_field(state, ["Paris", "Tokyo"], "destinations")

# Creates metadata structure:
state.metadata["last_suggestions"] = [
    {"text": "Paris", "field": "destinations"},
    {"text": "Tokyo", "field": "destinations"},
]
```

#### 2. Season/Month Date Parser

Handles expressions like:

- `"next month"` → First to last day of next month
- `"this summer"` → June 1 to August 31
- `"spring"` → March 15 to May 31
- `"next weekend"` → Saturday-Sunday

**Ambiguity detection**: When a date range straddles today (e.g., "December 20-27" on December 22), sets `date_clarify_mode` instead of guessing the year.

#### 3. Travelers Micro-Parser

| Input               | Output                 |
| ------------------- | ---------------------- |
| `"solo"`, `"alone"` | `adults=1`             |
| `"couple"`          | `adults=2`             |
| `"family of 4"`     | `adults=2, children=2` |
| `"3 people"`        | `adults=3`             |

#### 4. Multi-Place Splitter

Guards:

- Only splits if separator present (`,` / `and` / `&` / `/`)
- Requires at least one segment to be a known place
- Rejects if verbs present (it's a sentence, not a list)
- Caps at 3 places

#### 5. Response Provenance Tracking

```python
# Set at point of response generation
set_response_provenance(state, "deterministic")

# Check in _should_skip_polish
provenance = get_response_provenance(state)
if provenance in ("template", "deterministic", "codegen"):
    return True, f"provenance:{provenance}"
```

### Observability

New stats exposed via `get_deterministic_pipeline_stats()`:

| Metric                            | Description                                  |
| --------------------------------- | -------------------------------------------- |
| `suggestion_echo_hits`            | User clicked/typed exact match to suggestion |
| `season_date_hits`                | Parsed "summer", "spring", etc.              |
| `relative_date_hits`              | Parsed "next month", "next week", etc.       |
| `travelers_hits`                  | Parsed "solo", "couple", "family of N"       |
| `place_single_hits`               | Parsed single known place                    |
| `place_multi_hits`                | Parsed multi-place list                      |
| `date_ambiguous_count`            | Straddle-today dates requiring clarification |
| `extractor_light_blocked_trivial` | LLM calls blocked by pipeline                |
| `total_hits`                      | Sum of all hit counters                      |

### Expected Impact

For the trace pattern:

```
Assistant: "When would you like to travel?"
User: "Patagonia"  # 9 characters, clicked suggestion
```

**Before optimization**: 552 tokens (extractor_light LLM call)
**After optimization**: 0 tokens (deterministic suggestion echo)

---

## Summary

### Token Optimization Strategy

| Optimization               | Est. Savings      | Mechanism                                      |
| -------------------------- | ----------------- | ---------------------------------------------- |
| **Deterministic pipeline** | **~550 tokens**   | **MVP: Parse simple answers without LLM**      |
| LQA Pre-pass               | ~500-2000 tokens  | Skip extractor for simple answers              |
| Light extractor            | ~270 tokens       | 128 vs 400 token limit                         |
| Template responses         | ~900-1500 tokens  | No LLM for simple missing fields               |
| Gate bypasses              | ~256 tokens       | Skip router LLM                                |
| Strategy stage 0           | ~1000 tokens      | 564 tokens (stage 0) vs 1654 (required_fields) |
| Deterministic polish       | ~200-400 tokens   | Safe transforms without LLM                    |
| Strategy caching           | ~2000-3000 tokens | Reuse complex itineraries                      |
| Extractor caching          | ~500-1000 tokens  | Dedupe same inputs                             |

### Architecture Strengths

1. **Single source of truth** for all major computations
2. **Progressive disclosure** - simple cases handled simply
3. **Graceful degradation** - fallbacks at every level
4. **Observability** - comprehensive stats for tuning
5. **Testability** - deterministic paths for unit tests

### Architecture Considerations

1. **File size** - 16,600 lines is large; consider splitting
2. **Startup validation** - `validate_template_coverage()` should be called
3. **Cache coherence** - multiple caches with different TTLs
4. **Gate complexity** - 10 precedence levels with suppression require careful ordering

---

## Routing Correctness Fixes

> **Implemented**: January 2025
> **Issue Count**: 15 fixes (12 bugs + 3 structural guardrails)

### Overview

This section documents routing correctness fixes that address trace-observed symptoms including:

- Guard abort instead of route behavior
- Stage0 suggestion/question_target mismatch
- STRATEGY_TOPIC_SWITCH firing on turn 1
- Multi-city over-inference
- Stale summary propagation

### Fix Summary Table

| #   | Fix                                | Symptom                                            | Solution                                                         |
| --- | ---------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------- |
| 1   | `_debug()` signature collision     | `multiple values for argument 'message'`           | Renamed `message=` to `response_preview=` in guard fallback      |
| 2   | Guard routing                      | Guard logs error and aborts                        | Changed to route with `blocking_errors` + flag                   |
| 3   | `question_target` canonicalization | `start_date` vs `dates` mismatch                   | Added `canonicalize_question_target()` at turn start             |
| 4   | Stage0 suggestion alignment        | Suggestions invite destination when dates expected | Changed `_STRATEGY_PRE_CORE_QUESTION_GUIDANCE` keys to `"dates"` |
| 5   | Turn 1 topic switch guard          | STRATEGY_TOPIC_SWITCH fires on first turn          | Added explicit `turn_number < 2` bypass                          |
| 6   | Deterministic place parsing        | LQA fails for place when asking dates              | Added `_ALL_KNOWN_PLACES_LOWER` matching in lqa_prepass          |
| 7   | `fast_path` flag pollution         | Polish skipped incorrectly                         | Refined `_should_skip_polish()` to check explicit conditions     |
| 8   | Error accounting                   | Mixed error types (str vs dict)                    | Created `_record_structured_error()` helper                      |
| 9   | Multi-city over-inference          | Single "also" word triggers multi_city             | Require TWO signals with confidence scoring                      |
| 10  | `pending_strategy_topic`           | Topic switch blocked by errors                     | Already implemented - store pending, auto-fire on clear          |
| 11  | Activity canonicalization          | "🤿 Diving" not matching "diving"                  | Already implemented - `ACTIVITY_ALIAS_MAP` + lowercase           |
| 12  | Selected specialist logging        | Unknown which specialist ran                       | Added `metadata["selected_specialist"]` in strategy_node         |
| 13  | Suggestion contract validation     | Suggestions don't match question_target            | Added `validate_suggestion_contract()` at turn exit              |
| 14  | No-stale-summary invariant         | Summary from wrong turn persists                   | Added `last_response_turn` tracking and validation               |
| 15  | Trace replay harness               | No regression testing                              | Created `test_trace_replay.py` with fixtures                     |

### Fix 1: Guard Signature Collision

**Before:**

```python
_debug("msg", message=preview)  # Collision with first positional arg
```

**After:**

```python
_debug("msg", response_preview=preview)  # Renamed kwarg
```

### Fix 3: Question Target Canonicalization

The `canonicalize_question_target()` function normalizes target names:

| Raw Input            | Canonical Output |
| -------------------- | ---------------- |
| `start_date`         | `dates`          |
| `end_date`           | `dates`          |
| `travelers (adults)` | `travelers`      |
| `adults`             | `travelers`      |

Called at:

1. Start of `run_turn()` and `run_turn_streaming()`
2. Entry of `_strategy_stage0()`
3. Exit of nodes that set `question_target`

### Fix 5: Turn 1 Topic Switch Guard

STRATEGY_TOPIC_SWITCH gate now includes explicit check:

```python
# In _check_strategy_topic_switch():
if state.turn_number < 2 and not state.metadata.get("last_strategy_topic"):
    return None  # Skip - this is first-turn selection, not a switch
```

This prevents the topic switch gate (precedence 4) from firing before STRATEGY_PRE_CORE_VALUE
(precedence 5) on the first turn.

### Fix 6: Deterministic Place Parsing

When `question_target == "dates"` but user text is a known place:

```python
# In lqa_prepass():
if question_target == "dates":
    lower_text = normalized_text.lower()
    if lower_text in _ALL_KNOWN_PLACES_LOWER:
        # Deterministically parse as destination, skip LLM
        state.parsed_inputs = {"destinations": [matched_place]}
        state.metadata["deterministic_place_parse"] = True
        return GateResult(destination="normalize_inputs")
```

This handles the case where user clicks a destination suggestion when dates were asked.

### Fix 9: Multi-City Two-Signal Requirement

Multi-city inference now requires additive pattern AND destination count increase:

```python
def _infer_multi_city_intent(state: GraphState) -> Optional[str]:
    signals = []
    confidence = 0.0

    # Signal 1: Additive pattern ("also", "too", "as well")
    if _has_additive_pattern(state.user_text):
        signals.append("additive_pattern")
        confidence += 0.4

    # Signal 2: Destination count increase
    old_count = len(state.trip_inputs.get("destinations", []))
    new_count = len(state.parsed_inputs.get("destinations", []))
    if new_count > old_count:
        signals.append("destination_increase")
        confidence += 0.5

    # Require at least 2 signals
    if len(signals) >= 2 and confidence >= 0.8:
        state.metadata["multi_city_confidence"] = confidence
        return "multi_city"

    return None
```

---

## Invariants & Contract Validation

### LLM Budget Enforcement

**Rule:** At most 1 LLM call per turn when `ready_to_generate=False` and `question_target` is set.

The `can_call_llm()` function enforces this budget:

```python
def can_call_llm(state: GraphState, node_name: str) -> bool:
    """
    Check if an LLM call is allowed for this turn.
    Increments counter before returning True.
    """
    # Budget only enforced when collecting core fields
    if readiness.ready_to_generate or not question_target:
        state.metadata["llm_calls_this_turn"] += 1
        return True

    current_calls = state.metadata["llm_calls_this_turn"]
    if current_calls >= settings.max_llm_calls_per_turn:  # Default: 1
        state.metadata["llm_call_blocked_reason"] = node_name
        return False

    state.metadata["llm_calls_this_turn"] += 1
    return True
```

**Budget Reset:** Counter resets at start of each turn in `run_turn()`:

```python
state.metadata["llm_calls_this_turn"] = 0
```

**Fallback on Block:** When budget exhausted, `llm_blocked_fallback()` provides deterministic response:

```python
def llm_blocked_fallback(state, asked_target, *, source):
    """
    Produce a deterministic template response when LLM blocked.
    Guarantees non-empty assistant_message.
    """
    target = canonicalize_question_target(asked_target) or "destinations"
    template_resp = _get_template_response(target, state.strategy_topic)

    state.last_summary = template_resp["question"]
    state.suggested_responses = template_resp["suggestions"]
    set_question_target(state, target, source=source)
    set_response_provenance(state, "template")
```

**Guarded Nodes:**

- `missing_fields_guard` - Guard before LLM call
- `specialist` (all variants) - Guard before LLM call
- `strategy_stage0` - Guard before LLM call
- `strategy_node` main - Guard before LLM call
- `response_polish` - Skips if budget exhausted (optional enhancement)

### question_target SSoT (Single Source of Truth)

**Rule:** All question_target writes go through `set_question_target()` for canonicalization.

The SSoT helpers:

```python
def set_question_target(state, target, *, source):
    """
    Safe setter for question_target.
    - Canonicalizes value (e.g., 'start_date' -> 'dates')
    - Syncs both metadata and state
    - Tracks source for debugging
    """
    canonical = canonicalize_question_target(target)
    state.metadata["question_target"] = canonical
    state.question_target = canonical
    state.metadata["question_target_source"] = source

def get_question_target(state) -> Optional[str]:
    """Read canonical value from metadata SSoT."""
    return state.metadata.get("question_target")
```

**Canonicalization Rules:**

| Input Value  | Canonical Output |
| ------------ | ---------------- |
| `start_date` | `dates`          |
| `end_date`   | `dates`          |
| `timing`     | `dates`          |
| `when`       | `dates`          |
| `adults`     | `travelers`      |
| `party_size` | `travelers`      |
| Other values | Unchanged        |

**Turn Boundary Sync:** At start of `run_turn()`, metadata is synced to state:

```python
# Canonicalize question_target at turn boundary (SSoT)
if state.metadata.get("question_target"):
    canonical = canonicalize_question_target(state.metadata["question_target"])
    state.metadata["question_target"] = canonical
    state.question_target = canonical
```

**Tripwire Detection:** At turn exit, mismatch between state and metadata is logged:

```python
if state.question_target != state.metadata.get("question_target"):
    _debug(
        "TRIPWIRE: question_target mismatch",
        state_value=state.question_target,
        metadata_value=state.metadata.get("question_target"),
    )
```

### Suggestion Contract Invariant

**Rule:** At turn exit, `suggested_responses` should align with `question_target`.

The `validate_suggestion_contract()` function checks and repairs mismatches:

```python
def validate_suggestion_contract(state: GraphState) -> None:
    """
    Validate that suggestions match question_target.
    If mismatch detected, rewrite suggestions from templates.
    """
    target = state.question_target
    suggestions = state.last_summary.get("suggested_responses", [])

    if not target or not suggestions:
        return

    # Check alignment using heuristics
    aligned = _suggestions_match_target(suggestions, target)

    if not aligned:
        state.metadata["suggestion_contract_violation"] = {
            "target": target,
            "original_suggestions": suggestions,
            "reason": "mismatch_detected",
        }
        # Rewrite from templates
        state.last_summary["suggested_responses"] = _get_template_suggestions(target)
```

**Heuristics for alignment:**

- `dates` target: suggestions should contain month names, "this/next", or date patterns
- `destinations` target: suggestions should be capitalized proper nouns (place names)
- `origin` target: suggestions should include origin indicators or common cities
- `travelers` target: suggestions should contain numbers or "couple", "family", etc.

### No-Stale-Summary Invariant

**Rule:** At turn exit, the summary must have been generated during this turn.

The invariant is enforced at the end of `run_turn()`:

```python
# At end of run_turn():
last_response_turn = state.metadata.get("last_response_turn")
current_turn = state.turn_number

if last_response_turn is not None and last_response_turn != current_turn:
    # Stale summary detected! Generate recovery message.
    state.metadata["stale_summary_recovered"] = True
    state.last_summary = _generate_deterministic_recovery_message(state)
    state.metadata["last_response_turn"] = current_turn
```

**Tracking:** Every node that generates a response sets:

```python
state.metadata["last_response_turn"] = state.turn_number
```

### Structured Error Recording

All errors now follow a structured format:

```python
{
    "code": "DATE_AMBIGUOUS_YEAR",    # Machine-readable code
    "node": "normalize_inputs",        # Node that generated error
    "severity": "blocking",            # "blocking" | "warning" | "info"
    "message": "Date range year is ambiguous"  # Human-readable description
}
```

The `_record_structured_error()` helper ensures consistent format:

```python
def _record_structured_error(
    state: GraphState,
    code: str,
    node: str,
    severity: str = "warning",
    message: Optional[str] = None,
) -> None:
    error = {
        "code": code,
        "node": node,
        "severity": severity,
        "message": message or code,
    }
    state.errors.append(error)
```

---

## Trace Replay Testing

### Overview

The trace replay harness (`tests/langgraph/test_trace_replay.py`) provides a framework for
validating routing decisions against production traces.

### Fixture Format

```python
@dataclass
class TurnExpectation:
    user_text: str
    expected_gate: Optional[str] = None
    expected_destination: Optional[str] = None
    expected_question_target: Optional[str] = None
    expected_selected_specialist: Optional[str] = None
    check_no_stale_summary: bool = True
    check_suggestion_contract: bool = True
    expected_state_updates: Dict[str, Any] = field(default_factory=dict)
    expected_error_codes: List[str] = field(default_factory=list)
```

### Example Fixture

```python
DIVING_SPECIALIST_TRACE = TraceFixture(
    name="diving_specialist_routing",
    description="User requests diving trip, verifies specialist is executed",
    turns=[
        TurnExpectation(
            user_text="I want to plan a diving trip",
            expected_gate="STRATEGY_PRE_CORE_VALUE",
            expected_destination="strategy_node",
            expected_question_target="dates",
            expected_selected_specialist="strategy_diving",
        ),
        TurnExpectation(
            user_text="March 2025",
            expected_question_target="origin",
        ),
    ],
)
```

### Running Tests

```bash
# Run all trace replay tests
pytest backend/tests/langgraph/test_trace_replay.py -v

# Run with specific fixture
pytest backend/tests/langgraph/test_trace_replay.py -k "diving_specialist"
```

### Loading Production Traces

Production traces can be loaded from JSON files:

```python
trace = load_trace_from_json("traces/failing_conversation_2025_01_15.json")
harness = TraceReplayHarness(trace)
success = await harness.replay()
```

### Invariant Validation

The harness automatically validates:

1. **No-stale-summary**: `last_response_turn == turn_number` at each turn exit
2. **Suggestion contract**: suggestions align with question_target
3. **Gate correctness**: actual gate matches expected gate
4. **Specialist selection**: actual specialist matches expected

Violations are collected in `harness.violations` for analysis.

---

## Success Metrics

### Expected Improvements

| Metric                      | Before  | Expected After | Measurement                         |
| --------------------------- | ------- | -------------- | ----------------------------------- |
| Guard abort rate            | >0      | 0              | No "multiple values" errors in logs |
| Suggestion/target alignment | ~60%    | 100%           | Trace replay validation             |
| Turn 1 topic switch fires   | >0      | 0              | Gate stats counter                  |
| Multi-city false positives  | ~15%    | <5%            | Manual trace review                 |
| Stale summary occurrences   | Unknown | 0              | Invariant check counter             |
| Specialist identification   | 0%      | 100%           | `selected_specialist` always set    |

---

## Routing & Delta Observability (V5)

### Overview

V5 introduces end-to-end routing observability to support analytics, debugging, and trace replay.
The key addition is `RoutingDecisionFinal`, a structured summary emitted at the end of every `run_turn()`.

### RoutingDecisionFinal

```python
@dataclass
class RoutingDecisionFinal:
    """End-of-turn routing summary for observability and analytics."""
    gate_result: GateResult          # Immutable snapshot of gate evaluation
    executed_node: str               # First response-producing node
    redirect_reason: Optional[str]   # Why executed_node differs from gate destination
    response_provenance: str         # "template", "llm", "codegen", etc.
    question_target_out: Optional[str]  # Canonical question_target at turn end
    deltas_applied: List[str]        # Fields written via _write_trip_inputs (stable sorted)
    llm_nodes_called_this_turn: List[str]  # LLM nodes that called can_call_llm()
    llm_budget_used: int             # LLM calls consumed this turn
    errors_count: int                # Number of errors emitted
    schema_version: int              # ROUTING_DECISION_SCHEMA_VERSION
    build_git_sha: str               # Git SHA for trace correlation
    request_id: str                  # LangSmith run ID for E2E tracing
```

**Redirect Reason Values:**

| Value                | Meaning                                                    |
| -------------------- | ---------------------------------------------------------- |
| `llm_budget_blocked` | Gate destination couldn't run due to LLM budget exhaustion |
| `blocking_errors`    | Date clarification mode or blocking validation errors      |
| `missing_core`       | Missing core fields triggered deterministic recovery       |
| `guard_redirect`     | Guard logic redirected to different node                   |
| `null`               | `executed_node == gate_result.destination` (no redirect)   |

### Canonical Field Ordering

All delta tracking uses `CANONICAL_FIELD_ORDER` for stable, deterministic output:

```python
CANONICAL_FIELD_ORDER = [
    "origin", "destinations", "start_date", "end_date", "dates",
    "travelers", "budget", "hotel_preferences", "flight_preferences",
    "activity_preferences", "transport_preferences", "meal_preferences",
    "special_requests", "additional_info",
]
```

This ensures `deltas_applied` is always sorted consistently for:

- Analytics aggregation (e.g., "which fields change together?")
- Trace replay comparison
- Debugging across different runs

### Question ID Lifecycle

Suggestions are now tagged with `question_id` to enable staleness detection:

```python
# When storing suggestions:
store_suggestions_with_field(state, suggestions, question_target)
# Increments question_id and stores it with each suggestion

# When user clicks suggestion:
_try_suggestion_echo() checks if suggestion's question_id matches current
# Stale suggestions (mismatched question_id) are rejected
```

**Flow:**

```
Turn N: set_question_target("destinations")
        → _increment_question_id() → question_id = 5
        → store_suggestions_with_field() stores id=5 on each suggestion

Turn N+1: User provides different input
          → set_question_target("dates")
          → _increment_question_id() → question_id = 6

Turn N+2: User clicks suggestion from Turn N
          → _try_suggestion_echo() detects id=5 != current(6)
          → Returns None (suggestion rejected as stale)
```

### Response Provenance Tracking

The `set_response_source(state, node_name, provenance)` helper records:

- **First node** to produce a user-facing response this turn
- **Provenance type**: `"template"`, `"llm"`, `"codegen"`, `"cached"`, etc.

Write-once semantics ensure only the first caller wins:

```python
def set_response_source(state: GraphState, node_name: str, provenance: str) -> None:
    if state.metadata.get("response_source_node") is None:
        state.metadata["response_source_node"] = node_name
        state.metadata["response_provenance"] = provenance
```

### Per-Turn State Reset

At the start of each turn, `run_turn()` resets observability fields:

```python
metadata["llm_call_blocked_reason"] = {}      # Per-node blocking reasons
metadata["llm_nodes_called_this_turn"] = []   # LLM call tracking
metadata["deltas_applied_this_turn"] = []     # Field change tracking
metadata["response_source_node"] = None       # First response producer
metadata["response_provenance"] = None        # Response type
```

### GateResult Enhancement

`GateResult` now includes additional context:

```python
@dataclass
class GateResult:
    gate: GatePrecedence
    destination: str
    lqa_reason: Optional[str] = None      # Why LQA path was taken/skipped
    llm_budget_used: int = 0              # Budget at gate evaluation time
    date_clarify_mode: bool = False       # Whether date clarification is active
    # ... existing fields ...
```

### Immutable Snapshots

Gate results are captured as immutable `deepcopy()` snapshots:

1. **At gate evaluation**: Stored in `state.metadata["gate_result"]`
2. **At turn end**: Embedded in `RoutingDecisionFinal`
3. **In metadata**: Stored as `metadata["last_routing_decision_final"]`

This prevents in-flight mutations from corrupting observability data.

### JSON-Lines Logging

Each turn emits a structured log entry for analytics pipelines:

```
_debug("ROUTING_DECISION_FINAL",
    schema_version=1,
    gate_destination="hotels_node",
    executed_node="hotels_node",
    redirect_reason=None,
    response_provenance="llm",
    question_target_out="dates",
    deltas_applied=["destinations", "travelers"],
    llm_nodes_called=["extractor", "hotels_node"],
    llm_budget_used=2,
    errors_count=0,
    request_id="abc123..."
)
```

### Schema Versioning

`ROUTING_DECISION_SCHEMA_VERSION` tracks breaking changes:

- **Version 1** (initial): All fields as documented above
- Increment only for field name/type changes or algorithm changes to `redirect_reason`

### Key Helpers

| Helper                           | Purpose                                                 |
| -------------------------------- | ------------------------------------------------------- |
| `set_response_source()`          | Write-once response source + provenance                 |
| `get_response_source_node()`     | Read current response source                            |
| `apply_lqa_like_deltas()`        | Unified delta application with canonical ordering       |
| `_increment_question_id()`       | Increment and return new question_id                    |
| `should_increment_question_id()` | Check if question changed to warrant new ID             |
| `store_suggestions_with_field()` | Store suggestions with question_id binding              |
| `can_call_llm()`                 | LLM budget enforcement with per-node tracking           |
| `_write_trip_inputs()`           | State mutation with provenance + returns fields_changed |
