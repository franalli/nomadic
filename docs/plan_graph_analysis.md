# Plan Graph Architecture Analysis

> **Generated**: December 25, 2025 (Updated: V32 Date Compatibility Consolidation)
> **Source File**: `backend/app/plan_graph.py` (~23,800 lines)
> **Pattern Module**: `backend/app/pattern_matching.py` (~1,700 lines)
> **Planner Package**: `backend/app/planner/` (new in V26)
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
17. [Cache Hardening & Provenance (V6)](#cache-hardening--provenance-v6)
    - [Node-Scoped Caches](#node-scoped-caches)
    - [CachePayload Dataclass](#cachepayload-dataclass)
    - [Cache Key V6 Components](#cache-key-v6-components)
    - [Validation & Eviction](#validation--eviction)
    - [Gate Invariants](#gate-invariants)
    - [Provenance Precedence System](#provenance-precedence-system)
    - [Unconditional Travelers Micro-Parser](#unconditional-travelers-micro-parser)
    - [Call-Site Token Accounting](#call-site-token-accounting)
18. [Routing Invariant Fixes (V7 Final v5)](#routing-invariant-fixes-v7-final-v5)
19. [Response Provenance Fix (V8)](#response-provenance-fix-v8)
20. [ErrorRecord & Destination-Known Gate (V9)](#errorrecord--destination-known-gate-v9)
21. [Stage0 Loop Fix & Fast Streaming (V10)](#stage0-loop-fix--fast-streaming-v10)
    - [Question-Target Ownership Invariant](#question-target-ownership-invariant)
    - [Signature-Scoped Lifecycle Suppression](#signature-scoped-lifecycle-suppression)
    - [Stage0 Suggestion Storage](#stage0-suggestion-storage)
    - [Fast LLM Streaming](#fast-llm-streaming)
22. [Execution Instrumentation (V12)](#execution-instrumentation-v12)
    - [NodeRun Journal](#noderun-journal)
    - [Duplication Classification](#duplication-classification)
    - [Response Writer Guard](#response-writer-guard)
    - [Tripwires](#tripwires)
    - [LLM Call Tracing](#llm-call-tracing)
23. [Stage0 Lifecycle & Fuzzy Normalization (V13)](#stage0-lifecycle--fuzzy-normalization-v13)
    - [Stage0 Lifecycle Suppression Fix](#stage0-lifecycle-suppression-fix)
    - [Origin-Aware Stage0 Signature](#origin-aware-stage0-signature)
    - [Fuzzy Place Name Matching](#fuzzy-place-name-matching)
    - [Local Language Synonym Expansion](#local-language-synonym-expansion)
24. [Pattern Matching Module (V14)](#pattern-matching-module-v14)
    - [Module Overview](#module-overview)
    - [Pattern Categories](#pattern-categories)
    - [Enhanced Flight/Hotel/Transport Patterns](#enhanced-flighthoteltransport-patterns)
    - [Helper Functions](#helper-functions)
25. [Gate Renumbering & Routing Fixes (V15)](#gate-renumbering--routing-fixes-v15)
    - [Gate Precedence Renumbering](#gate-precedence-renumbering)
    - [GENERATE_REQUEST_PATTERN](#generate_request_pattern)
    - [STRATEGY_EXPANSION Gate](#strategy_expansion-gate)
    - [JSON Recovery Fallback](#json-recovery-fallback)
    - [Empty Response Guard](#empty-response-guard)
26. [Hermetic Tier A Test Harness (V16)](#hermetic-tier-a-test-harness-v16)
    - [FakeLLM Harness](#fakellm-harness)
    - [Text Compatibility Table-Driven Tests](#text-compatibility-table-driven-tests)
    - [Gate Invariant Tests](#gate-invariant-tests)
    - [Tier A Trace Replay Tests](#tier-a-trace-replay-tests)
    - [Ownership Suppression Tests](#ownership-suppression-tests)
27. [Startup Validation & Build Info (V17)](#startup-validation--build-info-v17)
    - [Fail-Fast Template Validation](#fail-fast-template-validation)
    - [Build Info Logging](#build-info-logging)
    - [Health Endpoint Enhancement](#health-endpoint-enhancement)
    - [Startup Validation Tests](#startup-validation-tests)
    - [Test Summary](#test-summary)
28. [CachePayload V6 Everywhere (V18)](#cachepayload-v6-everywhere-v18)
    - [Unified CachePayload Schema](#unified-cachepayload-schema)
    - [Migrated Caches](#migrated-caches)
    - [Cache Event Observability](#cache-event-observability)
    - [Bounded Tile Cache](#bounded-tile-cache)
    - [V6 Migration Tests](#v6-migration-tests)
29. [LLM Budget CI (V19)](#llm-budget-ci-v19)
    - [Budget Enforcement Rules](#budget-enforcement-rules)
    - [Budget CI Tests](#budget-ci-tests)
    - [Observability & Tracking](#observability--tracking)
30. [Strategy Topics (V20)](#strategy-topics-v20)
    - [Topic Registry](#topic-registry)
    - [Topic Detection Patterns](#topic-detection-patterns)
    - [Strategy Gates](#strategy-gates)
    - [Strategy Topic Tests](#strategy-topic-tests)
31. [Debug/Config Snapshot (V21)](#debugconfig-snapshot-v21)
    - [Admin Planner Endpoint](#admin-planner-endpoint)
    - [Planner Snapshot Per Turn](#planner-snapshot-per-turn)
    - [Version Constants](#version-constants)
    - [Debug Endpoint Tests](#debug-endpoint-tests)
32. [Cache Summary Metrics (V22)](#cache-summary-metrics-v22)
    - [Cache Invalid Reason Constants](#cache-invalid-reason-constants)
    - [Summarize Cache Events](#summarize-cache-events)
    - [Process-Level Rolling Counters](#process-level-rolling-counters)
    - [Cache Summary Tests](#cache-summary-tests)
33. [Strategy Output Size Limits (V23)](#strategy-output-size-limits-v23)
    - [Truncation Helper Function](#truncation-helper-function)
    - [Strategy Node Integration](#strategy-node-integration)
    - [Configuration Settings](#configuration-settings)
    - [Strategy Output Tests](#strategy-output-tests)
34. [JSON Utilities Extraction (V24)](#json-utilities-extraction-v24)
    - [Extracted Functions](#extracted-functions)
    - [Backwards Compatibility](#backwards-compatibility)
    - [Extraction Tests](#extraction-tests)
35. [Debug Utilities Extraction (V25)](#debug-utilities-extraction-v25)
    - [Extracted Debug Functions](#extracted-debug-functions)
    - [Debug Backwards Compatibility](#debug-backwards-compatibility)
    - [Debug Extraction Tests](#debug-extraction-tests)
36. [Metadata Helpers & Turn Init (V26)](#metadata-helpers--turn-init-v26)
    - [Planner Package Structure](#planner-package-structure)
    - [Metadata Key Constants](#metadata-key-constants)
    - [Metadata Helper Functions](#metadata-helper-functions)
    - [Centralized Turn Initialization](#centralized-turn-initialization)
    - [Metadata Helpers Tests](#metadata-helpers-tests)
37. [Test-Mode Invariant Hard-Fails (V27)](#test-mode-invariant-hard-fails-v27)
    - [Test-Mode Detection](#test-mode-detection)
    - [Tripwire Hard-Fails](#tripwire-hard-fails)
    - [Response Writer Guard](#response-writer-guard)
    - [Gate Invariants](#gate-invariants)
    - [Invariant Failure Tests](#invariant-failure-tests)
38. [Cache Concurrency Safety (V28)](#cache-concurrency-safety-v28)
    - [Cache Access Module](#cache-access-module)
    - [Thread-Safe Accessors](#thread-safe-accessors)
    - [Counter Safety](#counter-safety)
    - [Cache Concurrency Tests](#cache-concurrency-tests)
39. [Import Surface Freeze (V29)](#import-surface-freeze-v29)
    - [Planner Facade Module](#planner-facade-module)
    - [Exported Symbols](#exported-symbols)
    - [Import Contract Enforcement](#import-contract-enforcement)
    - [Migration Path](#migration-path)
    - [Import Contract Tests](#import-contract-tests)
40. [Stable Hashing Utilities (V30)](#stable-hashing-utilities-v30)
    - [Hashing Module](#hashing-module)
    - [Stable Hash Functions](#stable-hash-functions)
    - [Canonicalization Helpers](#canonicalization-helpers)
    - [Hash Ban Enforcement](#hash-ban-enforcement)
    - [Stable Hashing Tests](#stable-hashing-tests)
41. [Telemetry Spine (V31)](#telemetry-spine-v31)
    - [Telemetry Module](#telemetry-module)
    - [TraceEnvelope](#traceenvelope)
    - [Event Types](#event-types)
    - [Sampling & Redaction](#sampling--redaction)
    - [Console Output](#console-output)
    - [Integration Points](#integration-points)
    - [Configuration Settings](#configuration-settings-1)
    - [Telemetry Tests](#telemetry-tests)
42. [Date Compatibility Consolidation (V32)](#date-compatibility-consolidation-v32)
    - [Problem](#problem)
    - [Solution: Single Source of Truth](#solution-single-source-of-truth)
    - [Files Changed](#files-changed)
    - [Patterns Now Recognized](#patterns-now-recognized)
    - [Test Coverage](#test-coverage-1)
    - [Ownership Suppression Now Works](#ownership-suppression-now-works)
43. [Stale Question Target Fix (V33)](#stale-question-target-fix-v33)
    - [Problem](#problem-1)
    - [Root Cause](#root-cause)
    - [Solution: Validate Before Use](#solution-validate-before-use)
    - [Debug Output](#debug-output)
    - [Files Changed](#files-changed-1)
    - [Invariant Enforced](#invariant-enforced)

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

**Gate Numbering (V15)**: Gates now use intuitive increments of 10 for easier insertion of future gates.
Lower numbers = higher priority.

**Gate Suppression**: Some gates explicitly yield to higher-priority paths:

- `SPECIALIST_PRE_CORE` yields to `STRATEGY_PRE_CORE_VALUE` when strategy topic detected without destinations
- `STRATEGY_PRE_CORE_VALUE_WITH_DEST` yields to question-target ownership (V10)
- This prevents "activities" keyword from shadowing open-ended strategy planning

| Precedence | Gate                                | Destination                 | Description                                            | Yields To                               |
| ---------- | ----------------------------------- | --------------------------- | ------------------------------------------------------ | --------------------------------------- |
| 10         | `STRATEGY_EXPANSION`                | `strategy_node`             | User requesting expansion on existing strategy content | —                                       |
| 20         | `GENERATE_REQUESTED`                | `generate_responder`        | Explicit generate request (pattern match)              | —                                       |
| 30         | `SHORT_CIRCUIT`                     | `short_circuit_responder`   | Greetings, confirmations, off-topic                    | —                                       |
| 40         | `READY_NO_FIELDS`                   | `summarize`                 | Plan ready, no fields to ask                           | —                                       |
| 50         | `FAST_PATH`                         | Specialists/validate        | LQA pre-pass success or initial extraction             | — (bootstrap-only after turn 1)         |
| 60         | `SPECIALIST_PRE_CORE`               | Specialists (pre-core mode) | Domain keyword detected, core fields missing           | `STRATEGY_PRE_CORE_VALUE`               |
| 70         | `STRATEGY_TOPIC_SWITCH`             | `strategy_{topic}`          | Mid-session strategy topic switch (new activity)       | — (deferred if blocking errors)         |
| 80         | `STRATEGY_PRE_CORE_VALUE`           | `strategy_node` (stage 0)   | Strategy topic + no destinations → value-first         | —                                       |
| 85         | `STRATEGY_PRE_CORE_VALUE_WITH_DEST` | `strategy_node` (stage 0)   | Strategy topic + destination known → dest-aware stage0 | Ownership + Lifecycle suppression (V10) |
| 90         | `CORE_COLLECTION`                   | `required_fields_node`      | Core fields missing, no domain keyword                 | —                                       |
| 100        | `HIGH_CONFIDENCE`                   | Based on parsed data        | High extraction confidence + short input               | —                                       |
| 110        | `QUESTION_KEYWORD`                  | Based on keyword            | User answering question with domain keyword            | —                                       |
| 120        | `KEYWORD_HEURISTIC`                 | Based on keyword            | Unambiguous domain keywords detected                   | —                                       |
| 130        | `SCORING_ROUTER`                    | Deterministic scoring       | Multi-signal scoring-based routing                     | —                                       |
| 999        | `ROUTER_LLM`                        | `router` node               | Fallback to LLM-based intent classification            | —                                       |

### New Gates (V15)

#### STRATEGY_EXPANSION (Precedence 10)

Handles "Show more details", "expand", "tell me more" requests when a strategy is already in progress.
Triggers when:

- `pending_strategy_expansion` is set in metadata, OR
- Generic expansion pattern detected AND strategy context exists

This gate has highest priority to ensure expansion requests don't get routed to required_fields or other nodes.

#### GENERATE_REQUESTED (Precedence 20)

Handles explicit plan generation requests like "Yes, generate my itinerary!", "I'm ready", "let's go".
Uses `GENERATE_REQUEST_PATTERN` from `pattern_matching.py` with careful exclusion of multi-city intent
phrases like "do it all together".

**Pattern exclusions to avoid false positives:**

- "do it" alone (too ambiguous) - requires "do it now" or "make it happen"
- "one trip" (multi-city intent phrase)

### Key Helper Functions

| Function                                   | Purpose                                                                     |
| ------------------------------------------ | --------------------------------------------------------------------------- |
| `_is_strategy_pre_core_eligible`           | Checks if strategy pre-core conditions met (topic + no dest + core missing) |
| `_check_specialist_pre_core`               | Detects specialist keywords, yields to strategy when topic also detected    |
| `_check_strategy_pre_core_value`           | Detects strategy topic and determines question_target priority              |
| `_check_strategy_pre_core_value_with_dest` | Detects strategy topic with destination known → dest-aware stage0 response  |
| `_check_strategy_topic_switch`             | Detects mid-session strategy topic changes with intent verbs and cooldowns  |
| `is_text_date_compatible` (V32)            | **Single source of truth** for date compatibility (pattern_matching.py)     |
| `text_is_compatible_with_target` (V10)     | Checks if user input looks like an answer to `question_target`              |
| `_compute_stage0_signature` (V10)          | Computes unique signature for stage0 lifecycle tracking                     |
| `_extract_message_from_malformed_json`     | JSON recovery: extracts message field from malformed LLM JSON responses     |

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
that must be resolved before plan generation. Errors are stored as `ErrorRecord` instances in
`GraphState.errors` and blocking codes are derived from records with `severity="blocking"`:

```python
# ErrorRecord model (schemas.py)
class ErrorRecord(BaseModel):
    code: str                      # Error code (e.g., "AMBIGUOUS_YEAR")
    node: str                      # Node that recorded the error
    severity: Literal["blocking", "warning", "info"]
    message: str                   # Human-readable description

# GraphState.errors now uses ErrorRecord
class GraphState(TypedDict):
    errors: List[ErrorRecord]      # Structured error records

@dataclass
class TripReadiness:
    missing_core: List[str]        # Missing core fields (destinations, dates, etc.)
    question_target: Optional[str] # Next field to ask about
    ready_to_generate: bool        # True only when all conditions met
    blocking_errors: List[str]     # Blocking error codes derived from ErrorRecord.severity

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.blocking_errors)

# compute_trip_readiness() derives blocking_errors from ErrorRecord
def compute_trip_readiness(state: GraphState) -> TripReadiness:
    blocking_errors = [
        err.code for err in state.get("errors", [])
        if err.severity == "blocking"
    ]
    # ...
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

| Check               | Function                              | Purpose                                        |
| ------------------- | ------------------------------------- | ---------------------------------------------- |
| Is date-like text?  | `_is_date_like_text()` → delegates to | Detects months, "next/this", digits+separators |
|                     | `is_text_date_compatible()` (V32)     | **Consolidated single source of truth**        |
| Is place-like text? | `_is_place_like_text()`               | Detects capitals, multi-word proper nouns      |

**V32 Consolidation:** `_is_date_like_text()` now delegates to `is_text_date_compatible()` from
`pattern_matching.py`, which is the single source of truth for date detection. This ensures
consistency between LQA skip heuristics, gate ownership suppression, and text compatibility checks.

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
# Parse provenance: set at point of data extraction
set_parse_provenance(state, "deterministic")

# Response generation provenance: set by response-producing nodes
state.metadata["response_writer_node"] = "strategy_node:stage0"
state.metadata["response_generation_provenance"] = "llm"

# Check in _should_skip_polish uses response_generation_provenance
response_gen_provenance = state.metadata.get("response_generation_provenance")
if response_gen_provenance in ("template", "deterministic", "codegen", "cached"):
    return True, f"provenance:{response_gen_provenance}"
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

The system tracks two orthogonal provenance concepts:

1. **Parse Provenance** (`parse_provenance`): How data was EXTRACTED/PARSED from user input

   - Uses precedence-based semantics via `set_parse_provenance_once()`
   - Values: `cached`, `deterministic`, `template`, `codegen`, `llm`, `unknown`

2. **Response Generation Provenance** (`response_generation_provenance`): How the FINAL user-facing response was generated
   - Uses final-writer-wins semantics
   - Values: `template`, `llm`, `deterministic`, `codegen`, `cached`, `unknown`
   - Set alongside `response_writer_node` by response-producing nodes

The `set_response_source(state, node_name, provenance)` helper records:

- **First node** to produce a user-facing response this turn
- **Provenance type**: `"template"`, `"llm"`, `"codegen"`, `"cached"`, etc.

Write-once semantics ensure only the first caller wins:

```python
def set_response_source(state: GraphState, node_name: str, provenance: str) -> None:
    if state.metadata.get("response_source_node") is None:
        state.metadata["response_source_node"] = node_name
        state.metadata["response_generation_provenance"] = provenance
```

### Per-Turn State Reset

At the start of each turn, `run_turn()` resets observability fields:

```python
metadata["llm_call_blocked_reason"] = {}           # Per-node blocking reasons
metadata["llm_nodes_called_this_turn"] = []        # LLM call tracking
metadata["deltas_applied_this_turn"] = []          # Field change tracking
metadata["response_source_node"] = None            # First response producer
metadata["response_generation_provenance"] = None  # Response generation type
metadata.pop("response_writer_node", None)         # Final response writer
metadata.pop("parse_provenance", None)             # Parse provenance
metadata.pop("response_text_hash", None)           # Response hash for change detection
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
    response_generation_provenance="llm",
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

---

## Cache Hardening & Provenance (V6)

> **Added**: V6 implementation introduces thread-isolated caching, contract validation, and precedence-based provenance tracking to eliminate stale response cascades.

### Problem Statement

Prior to V6, several cache-related bugs caused incorrect behavior:

| Issue                                                     | Root Cause                                               | Impact                                 |
| --------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------- |
| Stale cached response returned                            | Cache key didn't include `thread_id` or `user_text` hash | Wrong answer for different users       |
| Suggestion/summary mismatch                               | Cache stored response text without contract validation   | Pills didn't match displayed question  |
| Gate routed to `required_fields` when `missing_all == []` | No gate invariant enforcing readiness                    | Redundant clarification questions      |
| Full extractor LLM call on trivially-parsable phrase      | Travelers micro-parser only ran with conditions          | Wasted tokens on "just me"             |
| Response provenance appears wrong                         | No precedence enforcement                                | Incorrect attribution in observability |

### V6 Architecture

#### Node-Scoped Caches

Each caching node now has its own TTLCache instance:

```python
_required_fields_cache: TTLCache = TTLCache(maxsize=100, ttl=30)
_router_cache: TTLCache = TTLCache(maxsize=100, ttl=30)
# ... additional node-specific caches
```

**Benefits**:

- Namespace isolation prevents cross-node collisions
- Independent TTL/eviction per node type
- Simpler key computation (no node prefix needed)

#### CachePayload Dataclass

Every cached response stores full validation context:

```python
@dataclass
class CachePayload:
    # Identity
    response_text: str
    cached_at: float
    schema_version: int
    node_logic_version: int
    prompt_bundle_hash: str
    planner_build_id: str

    # Hard constraints (must match exactly)
    thread_id: str
    user_text_hash: str
    question_target: Optional[str]
    question_id: int

    # Soft constraints (checked for compatibility)
    missing_all_hash: str
    core_fields_hash: str
    ready_state: bool
    model_id: str
    intent: str

    # Contract validation
    suggestion_kind: Optional[str]
    suggestion_count: int
```

#### Cache Key V6 Components

```python
def _compute_cache_key_v6(state: PlanState, node_name: str) -> str:
    """
    Hash components:
    - thread_id (HARD: isolates users/sessions)
    - user_text_hash (HARD: different input = different response)
    - question_target (HARD: determines expected answer type)
    - question_id (HARD: disambiguates repeated questions)
    - missing_all_hash (readiness changes invalidate)
    - core_fields_hash (field changes matter)
    - ready_state (before/after readiness threshold)
    - model_id (different models = different responses)
    - CACHE_SCHEMA_VERSION (code changes = invalidate all)
    - NODE_LOGIC_VERSION[node_name] (per-node invalidation)
    """
```

#### Validation & Eviction

On cache hit, `_validate_cache_payload()` applies:

1. **Version checks**: Reject if schema/logic/prompt versions changed
2. **Hard constraint checks**: thread_id, user_text_hash, question_target, question_id
3. **Contract validation**: suggestion_kind matches expected category for question_target

```python
def _validate_cache_payload(payload: CachePayload, state: PlanState) -> bool:
    # Schema version mismatch → evict
    if payload.schema_version != CACHE_SCHEMA_VERSION:
        return False

    # Hard constraint: user_text must match
    current_hash = _hash_text(state.user_text or "")
    if payload.user_text_hash != current_hash:
        return False

    # Contract: suggestion_kind must match expected category
    expected_category = _question_target_to_category(state.question_target)
    if payload.suggestion_kind and payload.suggestion_kind != expected_category:
        _evict_stale_entry(state, "contract_mismatch")
        return False

    return True
```

### Gate Invariants

#### Missing-All Empty Blocks Required Fields

When `missing_all == []`, the plan is complete—`required_fields` should never be reached:

```python
class GateEvaluator:
    def evaluate(self, state: PlanState) -> GateResult:
        missing_all = get_missing_fields(state)

        # Store in metadata for downstream invariant checks
        state.metadata["readiness_pre"] = {
            "missing_all": missing_all,
            "missing_core": get_missing_core(state)
        }

        # INVARIANT: empty missing_all blocks required_fields routing
        if not missing_all:
            # Cannot route to CORE_COLLECTION—skip to next precedence
            pass
```

This invariant is enforced and tested:

```python
def test_required_fields_unreachable_when_missing_all_empty():
    """Gate must not route to required_fields if missing_all is empty."""
    state = make_complete_state()  # All fields filled
    result = GateEvaluator().evaluate(state)
    assert result.destination != "required_fields"
```

### Provenance Precedence System

**Parse provenance** uses a **precedence hierarchy** to track how data was extracted:

```python
PARSE_PROVENANCE_PRECEDENCE = {
    "cached": 5,        # Highest—data came from validated cache
    "deterministic": 4, # Regex/pattern matching or micro-parser
    "template": 3,      # Template-based extraction
    "codegen": 2,       # Generated code (rare)
    "llm": 1,           # LLM-based extraction
    "unknown": 0,       # Fallback
}

def set_parse_provenance_once(state: PlanState, provenance: str, source_node: str):
    """
    Write-once with precedence: higher precedence wins over lower.
    Only applies to PARSE provenance (how data was extracted).
    """
    current = state.metadata.get("parse_provenance")
    current_rank = PARSE_PROVENANCE_PRECEDENCE.get(current, 0)
    new_rank = PARSE_PROVENANCE_PRECEDENCE.get(provenance, 0)

    if new_rank > current_rank:
        state.metadata["parse_provenance"] = provenance
        state.metadata["parse_provenance_source_node"] = source_node
```

**Response generation provenance** uses **final-writer-wins** semantics:

```python
# Each node that produces a response sets both fields:
state.metadata["response_writer_node"] = "strategy_node:stage0"
state.metadata["response_generation_provenance"] = "llm"

# At end of turn, set_final_response() uses hash-guarded overwrite
def set_final_response(state, response, node_name, provenance):
    response_text_hash = hashlib.sha256(response.encode()).hexdigest()[:16]
    prev_hash = state.metadata.get("response_text_hash")
    if prev_hash is None or prev_hash != response_text_hash:
        state.metadata["response_source_node"] = node_name
        state.metadata["response_generation_provenance"] = provenance
    state.metadata["response_text_hash"] = response_text_hash
```

**Usage pattern**:

```python
# In cache hit path
if cached_response := get_cached_response_v6(state, "required_fields"):
    set_parse_provenance_once(state, "cached", "cache_hit:required_fields")
    state.metadata["response_writer_node"] = "specialist:required_fields:cache"
    state.metadata["response_generation_provenance"] = "cached"
    return cached_response

# In template path
if template_response := generate_from_template(state):
    set_parse_provenance_once(state, "template", "template:required_fields")
    state.metadata["response_writer_node"] = "specialist:required_fields:template"
    state.metadata["response_generation_provenance"] = "template"
    return template_response

# In LLM fallback
response = call_llm(state)
set_parse_provenance_once(state, "llm", "llm:required_fields")
state.metadata["response_writer_node"] = "specialist:required_fields"
state.metadata["response_generation_provenance"] = "llm"
return response
```

#### End-of-Turn Provenance Summary

A single debug line is emitted at end of turn for easy grep/correlation:

```python
_debug(
    "PROVENANCE_SUMMARY",
    response_writer_node=result.metadata.get("response_writer_node"),
    response_generation_provenance=result.metadata.get("response_generation_provenance"),
    response_text_hash_changed=(prev_hash is not None),
    parse_provenance=result.metadata.get("parse_provenance"),
)
```

### Unconditional Travelers Micro-Parser

Short inputs (≤20 characters) always trigger the travelers micro-parser:

```python
def _run_deterministic_pipeline(state: PlanState) -> PlanState:
    user_text = (state.user_text or "").strip().lower()

    # UNCONDITIONAL for short inputs: always try travelers extraction
    if len(user_text) <= 20:
        travelers = try_extract_travelers(user_text)
        if travelers:
            apply_travelers(state, travelers)
            set_parse_provenance_once(state, "deterministic", "travelers_micro_parser")
            return state
```

This eliminates wasted LLM calls for phrases like:

- "just me" → 1 adult
- "2 of us" → 2 adults
- "family of 4" → 4 adults
- "solo" → 1 adult

### Call-Site Token Accounting

Every LLM call is logged with model, node, and token counts:

```python
def _log_llm_call(state: PlanState, node: str, model: str,
                  prompt_tokens: int, completion_tokens: int):
    """Log LLM call for observability."""
    call_info = {
        "node": node,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "timestamp": time.time()
    }
    state.metadata.setdefault("llm_calls_this_turn", []).append(call_info)

def emit_turn_accounting(state: PlanState):
    """Emit turn-level token accounting summary."""
    calls = state.metadata.get("llm_calls_this_turn", [])
    total_prompt = sum(c["prompt_tokens"] for c in calls)
    total_completion = sum(c["completion_tokens"] for c in calls)
    _debug("TURN_ACCOUNTING",
           call_count=len(calls),
           total_prompt_tokens=total_prompt,
           total_completion_tokens=total_completion,
           calls=calls)
```

### Version Constants

```python
CACHE_SCHEMA_VERSION = 6          # Increment on cache format changes
NODE_LOGIC_VERSION = {            # Per-node logic version
    "required_fields": 3,
    "router": 2,
    "extractor": 2,
    # ...
}
PROMPT_BUNDLE_HASH = "..."        # Hash of all prompt files
PLANNER_BUILD_ID = "..."          # Git commit or build ID
```

### Test Coverage

V6 cache hardening is covered by dedicated regression tests:

| Test Class                     | Tests | Purpose                                 |
| ------------------------------ | ----- | --------------------------------------- |
| `TestUserTextHardConstraint`   | 2     | Different user_text must miss cache     |
| `TestGateInvariant`            | 2     | missing_all==[] blocks required_fields  |
| `TestContractMismatchEviction` | 2     | Mismatched suggestion_kind evicts entry |
| `TestLLMCallSiteAccounting`    | 1     | Token accounting tracks calls           |
| `TestProvenancePrecedence`     | 2     | Precedence ordering and finalization    |
| `TestCacheKeyComponents`       | 2     | Schema version and thread isolation     |
| `TestReadyStateFlip`           | 1     | Ready state mismatch = cache miss       |

**File**: `tests/langgraph/test_cache_hardening_v6.py` (12 tests)

---

## Routing Invariant Fixes (V7 Final v5)

> **Implemented**: January 2025
> **Issue Count**: 6 critical routing bugs fixed

### Overview

This section documents the Final v5 routing invariant fixes that address trace-observed bugs including:

- Routing to `required_fields` when `missing=[]` / `ready=True`
- Deterministic answers being re-asked via LLM fallback
- Loop guard switching fields when plan is complete
- Multi-intent false positive on comma-separated kid ages
- Topic switch causing expensive FULL extractor
- Provenance not resetting per turn

### Bug Summary Table

| #   | Bug                                     | Root Cause                                                      | Solution                                                                        |
| --- | --------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1   | Routing to `required_fields` when ready | Gate invariant uses fallthrough (`pass`) instead of hard return | Added `READY_NO_FIELDS` gate (precedence 0) with explicit three-guard condition |
| 2   | LLM re-asks deterministic answers       | No bypass for "answered this turn" in LQA fallback              | Added `answered_question_target_this_turn` metadata tracking                    |
| 3   | Loop guard fires when ready             | No ready check in `apply_loop_guard_mitigation()`               | Added `ready_to_generate` bypass check                                          |
| 4   | Multi-intent false positive on ages     | Age lists like "6, 9, 11" matching LQA bail patterns            | Added traveler-detail recognizer before bail pattern check                      |
| 5   | Topic switch pays for FULL extractor    | No early bypass for off-target strategy requests                | Added topic-switch bypass in extractor before mode selection                    |
| 6   | Provenance leaks across turns           | Per-turn metadata keys not cleared                              | Added 7 new keys to `run_turn()` metadata clearing                              |

### Fix 1: READY_NO_FIELDS Gate Invariant

**Problem:** When `missing=[]` and `ready_to_generate=True`, the gate evaluator would fall through to lower-precedence gates (like `HIGH_CONFIDENCE`) which could still route to `required_fields`.

**Solution:** Added `READY_NO_FIELDS` as precedence 0 gate with explicit three-guard condition and hard early return:

```python
class GatePrecedence(IntEnum):
    READY_NO_FIELDS = 0  # NEW: Ready state with no missing fields
    SHORT_CIRCUIT = 1
    # ... other gates

# In GateEvaluator.evaluate():
if gate == GatePrecedence.READY_NO_FIELDS:
    if not missing_all and not has_blocking_errors and not date_clarify_mode:
        return GateResult(
            destination="validate_and_merge",
            reason="ready_no_fields",
            gate_name="READY_NO_FIELDS",
            precedence=0,
        )
```

### Fix 2: Answered-This-Turn Bypass

**Problem:** When user provides answer to `question_target` (e.g., "6, 9, and 11" for kid ages), deterministic pipeline sets the field but LQA prepass could still bail to LLM fallback which re-asks the question.

**Solution:** Added `answered_question_target_this_turn` metadata tracking in deterministic pipeline:

```python
# In deterministic pipeline after successful parse:
if question_target and parsed_field == question_target:
    state.metadata["answered_question_target_this_turn"] = question_target

# In lqa_prepass bail pattern check:
if state.metadata.get("answered_question_target_this_turn") == question_target:
    return False  # Don't bail - already answered this turn
```

### Fix 3: Loop Guard Ready Check

**Problem:** Loop guard mitigation could fire and switch question targets even when `ready_to_generate=True`, causing confusion.

**Solution:** Added explicit ready check at start of `apply_loop_guard_mitigation()`:

```python
def apply_loop_guard_mitigation(state: GraphState, ...) -> GraphState:
    # Skip mitigation when ready - no field switching needed
    if state.ready_to_generate:
        _debug("Loop guard skipped - ready_to_generate=True")
        return state
    # ... existing mitigation logic
```

### Fix 4: Traveler-Detail Recognizer

**Problem:** Input like "6, 9, and 11" (kid ages) would trigger multi-intent bail patterns in LQA prepass due to comma detection.

**Solution:** Added `text_is_compatible_with_target()` pure function and traveler-detail recognizer:

```python
# Pattern for traveler details
_TRAVELER_DETAIL_PATTERN = re.compile(
    r"^[\d,\s]+(?:and\s+\d+)?$"  # Matches "6, 9, and 11"
    r"|^(?:ages?\s+)?[\d,\s]+"   # Matches "ages 6, 9"
    r"|^\d+\s*(?:year|yr|y/o)"   # Matches "6 year old"
)

def text_is_compatible_with_target(text: str, question_target: str) -> bool:
    """Pure function: returns True if text looks like a valid answer for target."""
    if question_target in ("travelers", "adults", "children"):
        if _TRAVELER_DETAIL_PATTERN.match(text.strip()):
            return True
    # ... other target checks
    return False
```

### Fix 5: Topic Switch Extractor Bypass

**Problem:** When user says "I wanna go diving" but `question_target` is "budget", extractor would still run in FULL mode (~3,755 tokens) before routing to `STRATEGY_TOPIC_SWITCH`.

**Solution:** Added early bypass check in extractor before mode selection:

```python
# In extractor, before _is_dense_input():
if question_target in ("budget", "dates", "travelers", "adults"):
    is_compatible = text_is_compatible_with_target(text, question_target)

    if not is_compatible:
        detected_topic = _detect_strategy_topic(text_lower)
        has_intent_verb = _has_intent_verb(text_lower)

        if detected_topic and has_intent_verb:
            state.metadata["extractor_skipped_reason"] = "topic_switch_bypass"
            state.strategy_topic = detected_topic
            return state  # Skip extractor entirely
```

### Fix 6: Per-Turn Provenance Reset

**Problem:** Metadata keys like `response_source_node`, `parse_provenance`, and `suggestion_target_override` were not being cleared per-turn, causing stale data to leak into routing decisions.

**Solution:** Added 7 new keys to metadata clearing in `run_turn()`:

```python
# In run_turn(), metadata clearing section:
metadata.pop("answered_question_target_this_turn", None)
metadata.pop("answered_question_id_this_turn", None)
metadata.pop("suggestion_target_override", None)
metadata.pop("extractor_skipped_reason", None)
metadata.pop("last_response_writer_node", None)
metadata.pop("last_response_provenance_kind", None)
metadata.pop("parse_provenance", None)
```

### Additional Helpers

#### `set_final_response()` for Provenance Finalization

Hash-guarded response provenance update at end of `run_turn()`:

```python
def set_final_response(state, response, node_name, provenance):
    """Finalize response provenance with hash-guarded overwrite."""
    response_hash = hash(response) if response else 0
    prev_hash = state.metadata.get("response_hash")

    if prev_hash is not None and prev_hash != response_hash:
        # Response was modified - update provenance
        state.metadata["response_source_node"] = node_name
        state.metadata["response_provenance"] = provenance

    state.metadata["response_hash"] = response_hash
```

#### `suggestion_target_override` in Validation

Updated `validate_suggestion_contract()` to support single-use override:

```python
def validate_suggestion_contract(question_target, suggestions, node_name, state):
    # Use override if set (single-use)
    effective_target = question_target
    if state and state.metadata.get("suggestion_target_override"):
        effective_target = state.metadata["suggestion_target_override"]
        del state.metadata["suggestion_target_override"]  # Clear after use
    # ... validation logic using effective_target
```

### Test Coverage

V7 Final v5 fixes are covered by existing test suite (1093 tests pass). Key areas:

| Test Area           | Description                                |
| ------------------- | ------------------------------------------ |
| Gate evaluation     | Tests for `READY_NO_FIELDS` precedence     |
| LQA prepass         | Tests for traveler-detail pattern matching |
| Loop guard          | Tests for ready state bypass               |
| Extractor           | Tests for topic-switch bypass              |
| Suggestion contract | Tests for target override behavior         |

---

## Response Provenance Fix (V8)

> **Issue**: Stream timeout after 15.0s due to LLM responses incorrectly triggering simulated streaming with artificial delays.
> **Root Cause**: `set_final_response()` never set provenance on first call because `prev_hash` was always `None` after turn-start reset.

### Problem Summary

The streaming logic in `run_turn_streaming()` used `simulate_streaming_budget_mode` to decide whether to add artificial delays. For deterministic/template responses, simulated streaming is correct. However, LLM responses were being incorrectly classified as "deterministic" because:

1. `set_final_response()` only updated provenance when `prev_hash is not None and prev_hash != response_hash`
2. After turn-start reset, `prev_hash` was always `None`, so the condition was never true
3. `response_provenance` remained at its reset value (empty), causing streaming logic to treat the response as non-LLM

### Solution: "Final Producer Wins" Pattern

The fix implements a clean "final producer wins" pattern with three key changes:

#### 1. Stable Hash with First-Call Detection

Changed `set_final_response()` to use stable `sha256` hash (instead of Python's `hash()` which is session-dependent) and set provenance on first call OR when content changes:

```python
def set_final_response(state, response, node_name, provenance):
    if not response or not response.strip():
        return  # Early return for empty response

    import hashlib
    response_hash = hashlib.sha256(response.encode()).hexdigest()
    prev_hash = state.metadata.get("response_hash")

    # Set provenance on first call OR when content changes
    if prev_hash is None or prev_hash != response_hash:
        state.metadata["response_source_node"] = node_name
        state.metadata["response_provenance"] = provenance

    state.metadata["response_hash"] = response_hash
```

#### 2. Turn-Start Metadata Fields

All response-producing nodes now set `last_response_writer_node` and `last_response_provenance_kind` when they produce a response. The finalization at turn end uses these values:

```python
# In response-producing nodes:
state.metadata["last_response_writer_node"] = f"strategy:{topic}:stage0"
state.metadata["last_response_provenance_kind"] = "llm"
```

#### 3. Finalization Before Streaming Decision

`run_turn_streaming()` now calls `set_final_response()` BEFORE the streaming decision, ensuring `response_provenance` is finalized:

```python
# Finalize provenance before streaming decision
set_final_response(
    state,
    state.response,
    state.metadata.get("last_response_writer_node", "unknown"),
    state.metadata.get("last_response_provenance_kind", "unknown")
)

# Streaming decision uses finalized provenance
if state.metadata.get("response_provenance") in ("llm", "cached"):
    # Real LLM streaming - no artificial delays
    ...
else:
    # Deterministic content - simulated streaming with delays
    ...
```

### Nodes Updated with Provenance Tracking

| Node                      | Path(s)                        | Provenance Kind                         |
| ------------------------- | ------------------------------ | --------------------------------------- |
| `_strategy_stage0`        | LLM success, fallback          | `llm`, `template`                       |
| `_specialist`             | template, LLM, cache, pre-core | `template`, `llm`, `cached`, `template` |
| `short_circuit_responder` | greeting/confirmation          | `deterministic`                         |
| `summarize`               | fallback responses             | `deterministic`                         |

### Reset Block Parity

`run_turn_streaming()` now has the same reset block as `run_turn()`, including:

```python
state.metadata["llm_calls_this_turn"] = 0
state.metadata["parse_provenance"] = None
state.metadata["response_provenance"] = None
state.metadata["response_source_node"] = None
state.metadata["response_hash"] = None
state.metadata["last_response_writer_node"] = None
state.metadata["last_response_provenance_kind"] = None
```

### Two Provenance Systems Clarified

| System                | Purpose                         | Pattern             |
| --------------------- | ------------------------------- | ------------------- |
| `parse_provenance`    | Tracks how fields were parsed   | Precedence-based    |
| `response_provenance` | Tracks response generation type | Final producer wins |

`PROVENANCE_PRECEDENCE` is used ONLY for `parse_provenance` (cached > llm > lqa > template > unknown).

### Test Coverage

All 1093 tests pass. The fix ensures:

- LLM responses stream in real-time without artificial delays
- Deterministic/template responses still use simulated streaming
- Provenance is always set correctly regardless of execution path

---

## ErrorRecord & Destination-Known Gate (V9)

### Overview

V9 introduces two key improvements:

1. **ErrorRecord Model**: Structured error tracking with severity levels
2. **STRATEGY_PRE_CORE_VALUE_WITH_DEST Gate**: Destination-aware strategy stage0 responses

### ErrorRecord Model

Previously, `GraphState.errors` was `List[str]` which caused Pydantic validation errors when
structured error dictionaries were appended. V9 introduces a proper `ErrorRecord` model:

```python
# backend/app/schemas.py
class ErrorRecord(BaseModel):
    """Structured error record with severity tracking."""
    code: str                                      # Error code (e.g., "AMBIGUOUS_YEAR")
    node: str                                      # Node that recorded the error
    severity: Literal["blocking", "warning", "info"]
    message: str                                   # Human-readable description
```

**Migration:**

| Before (V8)                            | After (V9)                                                |
| -------------------------------------- | --------------------------------------------------------- |
| `errors: List[str]`                    | `errors: List[ErrorRecord]`                               |
| `errors.append(f"{code} - {msg}")`     | `errors.append(ErrorRecord(code=..., severity=..., ...))` |
| String parsing to extract codes        | Direct access via `err.code`, `err.severity`              |
| `blocking_errors` from string patterns | `blocking_errors` from `err.severity == "blocking"`       |

**Backward Compatibility:**

Pydantic automatically coerces dictionaries to `ErrorRecord` during validation, so existing
code that creates error dicts continues to work.

### `_record_structured_error()` Helper

The centralized error recording function now creates `ErrorRecord` instances:

```python
def _record_structured_error(
    state: GraphState,
    code: str,
    node: str,
    severity: Literal["blocking", "warning", "info"],
    message: str,
) -> None:
    """Record a structured error in GraphState.errors."""
    error = ErrorRecord(code=code, node=node, severity=severity, message=message)
    state.setdefault("errors", []).append(error)
```

### STRATEGY_PRE_CORE_VALUE_WITH_DEST Gate

Addresses the UX issue where "diving in Maldives" would fall through to `CORE_COLLECTION`
instead of providing value-first strategy content with destination-specific details.

**Gate Precedence:** 55 (between `STRATEGY_PRE_CORE_VALUE` at 5 and `CORE_COLLECTION` at 6)

**Trigger Conditions:**

1. Strategy topic detected (hiking, diving, skiing, cycling, boating)
2. At least one destination known (`len(destinations) >= 1`)
3. Core fields still missing (dates, travelers, etc.)
4. Not already in strategy session (`last_strategy_topic` not set)
5. No blocking errors exist

**Stage0 Destination-Known Mode:**

When this gate fires, `_strategy_stage0()` enters "destination-known mode":

- Generates destination-specific activity archetypes
- Provides tailored suggestions based on known destination
- Asks for next missing core field (typically dates or travelers)

```python
# _check_strategy_pre_core_value_with_dest()
if strategy_topic and destinations and missing_core:
    return GateResult(
        gate=GatePrecedence.STRATEGY_PRE_CORE_VALUE_WITH_DEST,
        node="strategy_node",
        metadata={"strategy_stage": 0, "dest_known": True}
    )
```

**Example Flow:**

```
User: "I want to go diving in the Maldives"
  ↓
Gate 55 fires: STRATEGY_PRE_CORE_VALUE_WITH_DEST
  ↓
strategy_node (stage=0, dest_known=True)
  ↓
Response: "The Maldives offers world-class diving with..."
  + Destination-specific archetypes
  + Question: "When are you planning to visit?"
```

### Gate Result SSoT

The trace replay harness now reads from the canonical `gate_result` object stored in
`state.metadata["gate_result"]` rather than searching multiple metadata keys:

```python
# TraceReplayHarness._validate_turn()
gate_result = state_dict.get("metadata", {}).get("gate_result", {})
actual_gate = gate_result.get("gate")
actual_node = gate_result.get("node")
```

### Test Coverage

V9 adds comprehensive regression tests (1080 tests pass):

| Test                                         | Purpose                                        |
| -------------------------------------------- | ---------------------------------------------- |
| `test_error_record_creation`                 | ErrorRecord field access and validation        |
| `test_error_record_serialization`            | JSON serialization round-trip                  |
| `test_error_record_in_state`                 | Integration with GraphState.errors             |
| `test_diving_in_maldives_routes_to_strategy` | STRATEGY_PRE_CORE_VALUE_WITH_DEST gate routing |
| `test_date_ambiguity_records_error_record`   | ErrorRecord creation for date ambiguity        |
| `test_value_first_not_sticky`                | Strategy topic doesn't persist incorrectly     |
| `test_blocking_error_guards_dest_known`      | Blocking errors defer strategy routing         |

---

## Stage0 Loop Fix & Fast Streaming (V10)

### Overview

V10 fixes a critical routing bug where `STRATEGY_PRE_CORE_VALUE_WITH_DEST` would re-fire
after stage0 asked for dates, causing user date answers like "June to November" to be
ignored and stage0 to loop indefinitely. Also fixes 15s streaming timeout for LLM responses.

**Root Causes Addressed:**

1. **No question-target ownership**: Gate fired even when user was answering a date question
2. **No lifecycle tracking**: Gate had no memory that stage0 already ran for this topic+destination
3. **Suggestions not stored**: Stage0 suggestions weren't in the suggestion-echo store
4. **Slow streaming**: LLM responses used simulated streaming with artificial delays

### Question-Target Ownership Invariant

**New Invariant:** If `question_target` is set AND user input is compatible with that target,
strategy stage0 gates MUST NOT fire. The answer-collection path owns the turn.

**Implementation (V32 Consolidated):**

```python
# GateEvaluator.text_is_compatible_with_target() - now delegates to pattern_matching.py
@classmethod
def text_is_compatible_with_target(cls, user_text: str, question_target: Optional[str]) -> bool:
    """Check if user_text looks like an answer to the given question_target."""
    if question_target in ("dates", "start_date"):
        # Delegate to consolidated date compatibility check
        return is_text_date_compatible(user_text)
    elif question_target == "origin":
        # Check for city/place-like input
        ...
    return False
```

**Consolidated Date Compatibility (V32):**

The `is_text_date_compatible()` function in `pattern_matching.py` is the **single source of truth**
for determining if text answers a dates question. It consolidates:

- `DATES_COMPATIBILITY_PATTERN` regex
- `GateEvaluator.text_is_compatible_with_target()` dates branch
- `_is_date_like_text()` function

**Patterns Recognized:**

| Pattern                        | Example Matches                           | Purpose                          |
| ------------------------------ | ----------------------------------------- | -------------------------------- |
| `RELATIVE_DATE_WORDS_SIMPLE`   | "tomorrow", "today", "tonight", "weekend" | Standalone relative date words   |
| `MONTH_TO_MONTH_RANGE_PATTERN` | "June to November", "Jan-Dec"             | Detect date range answers        |
| `SINGLE_MONTH_PATTERN`         | "November", "next June"                   | Detect single month answers      |
| Season words                   | "spring", "summer", "fall", "winter"      | Detect season answers            |
| Relative phrases               | "next month", "this week", "next year"    | Detect non-specific date answers |
| Flexibility expressions        | "flexible", "whenever", "anytime"         | Detect open date answers         |

**Suppression Logic in `_check_strategy_pre_core_value_with_dest()`:**

```python
# OWNERSHIP SUPPRESSION
if question_target and cls.text_is_compatible_with_target(user_text, question_target):
    _debug("strategy_pre_core_value_with_dest skipped: ownership suppression")
    return None  # Let date collection handle this turn
```

### Signature-Scoped Lifecycle Suppression

**Problem:** A simple boolean `strategy_stage0_completed=True` is too coarse—it would
prevent stage0 from running after destination changes (e.g., user picks Nepal after
initially discussing Patagonia).

**Solution:** Use a signature that includes both topic AND destinations hash:

```python
# GateEvaluator._compute_stage0_signature()
@classmethod
def _compute_stage0_signature(cls, topic: str, destinations: List[str]) -> str:
    """Compute unique signature for stage0 completion tracking."""
    dest_str = "|".join(sorted(d.lower().strip() for d in destinations))
    dest_hash = hashlib.md5(dest_str.encode()).hexdigest()[:8]
    return f"{topic}:{dest_hash}"  # e.g., "hiking:abc123"
```

**Lifecycle State Written by `_strategy_stage0()`:**

```python
# On successful stage0 completion:
state.metadata["last_strategy_topic"] = topic
state.metadata["stage0_completed_sig"] = GateEvaluator._compute_stage0_signature(topic, destinations)
state.metadata["last_stage0_question_target"] = question_target
```

**Suppression Logic:**

```python
# LIFECYCLE SUPPRESSION
current_sig = cls._compute_stage0_signature(detected_topic, ti.destinations)
if metadata.get("stage0_completed_sig") == current_sig:
    _debug("strategy_pre_core_value_with_dest skipped: lifecycle suppression")
    return None  # Stage0 already ran for this topic+destinations
```

**Clearing Rules:**

| Event                                   | Action                       |
| --------------------------------------- | ---------------------------- |
| Topic changes (e.g., hiking → diving)   | Clear `stage0_completed_sig` |
| Destinations change (e.g., Nepal added) | Signature changes naturally  |
| Core complete + user requests expansion | Clear `stage0_completed_sig` |
| Session reset                           | Clear all lifecycle state    |

### Stage0 Suggestion Storage

**Problem:** Stage0 emitted suggestions (e.g., "June to November") but didn't store them
in the suggestion-echo store, so LQA prepass couldn't recognize them as valid answers.

**Solution:** Use the same `store_suggestions_with_field()` helper that `required_fields` uses:

```python
# In _strategy_stage0() after generating suggestions:
effective_field = canonicalize_question_target(question_target)  # "dates" not "start_date"
store_suggestions_with_field(state, state.suggested_responses, effective_field)
```

**Key Requirements:**

1. Use canonical field key (`"dates"` not `"start_date"`) to match LQA lookup
2. Increment same `question_id_counter` that `required_fields` uses
3. Store immediately after setting `state.suggested_responses`

**Now LQA prepass can match:**

```
User: "June to November"
  ↓
_try_suggestion_echo() finds match in last_suggestions
  ↓
Returns delta: {lqa_reason: "deterministic:suggestion_echo", ...}
  ↓
Skip extractor, route to normalize_inputs
```

### Fast LLM Streaming

**Problem:** For LLM responses with buffered text (e.g., strategy_stage0), the system used
`simulate_streaming()` which adds artificial delays (~15-35ms per token). For ~900 token
responses, this could exceed the 15s stream timeout.

**Solution:** Add `fast_stream_buffered()` for LLM provenance responses:

```python
# Fast streaming parameters
_FAST_STREAM_CHUNK_SIZE = 1500  # ~1.5KB chunks

async def fast_stream_buffered(text: str):
    """Fast streaming for LLM responses that are already buffered."""
    for i in range(0, len(text), _FAST_STREAM_CHUNK_SIZE):
        chunk = text[i : i + _FAST_STREAM_CHUNK_SIZE]
        yield chunk
        await asyncio.sleep(0)  # Yield for async context, no delay
```

**Streaming Decision in `run_turn_streaming()`:**

```python
if is_short_circuit or is_deterministic_response:
    # Simulated streaming with natural delays for template/codegen
    async for token in simulate_streaming(final_message):
        yield {"type": "token", "data": token}
else:
    # Fast streaming for LLM responses (no artificial delays)
    async for chunk in fast_stream_buffered(final_message):
        yield {"type": "token", "data": chunk}
```

**Timing Comparison:**

| Response Type   | Streamer                 | ~900 tokens | Notes                   |
| --------------- | ------------------------ | ----------- | ----------------------- |
| Template        | `simulate_streaming()`   | ~20-30s     | Natural LLM-like pacing |
| LLM (buffered)  | `fast_stream_buffered()` | <100ms      | Immediate delivery      |
| LLM (streaming) | Real streaming API       | Real-time   | Not yet implemented     |

### Updated Gate Conditions

`STRATEGY_PRE_CORE_VALUE_WITH_DEST` now fires only when ALL of:

| Condition                 | Check                                             |
| ------------------------- | ------------------------------------------------- |
| Topic detected            | Keywords or `activity_settings.categories`        |
| Destinations present      | `len(ti.destinations) >= 1`                       |
| Core fields missing       | `readiness.core_complete == False`                |
| No blocking errors        | `readiness.has_blocking_errors == False`          |
| **Ownership check (NEW)** | NOT (`question_target` set AND input compatible)  |
| **Lifecycle check (NEW)** | NOT (`stage0_completed_sig` == current signature) |

### Test Coverage

V10 maintains 1096 passing tests with no regressions. Key invariants verified:

| Invariant                      | Enforcement                                    |
| ------------------------------ | ---------------------------------------------- |
| Question-target ownership      | `text_is_compatible_with_target()` check       |
| Lifecycle scoping by signature | `_compute_stage0_signature()` + metadata check |
| Suggestion echo compatibility  | `store_suggestions_with_field()` in stage0     |
| No streaming timeout for LLM   | `fast_stream_buffered()` for `provenance=llm`  |

---

## Execution Instrumentation (V12)

V12 adds comprehensive instrumentation to detect and prevent duplicate node execution. This provides durable observability for debugging "slow response" issues caused by unintended graph cycles.

### Duplication Classification

Three classes of "duplication" are distinguished:

| Class   | Description                                  | Detection                                       |
| ------- | -------------------------------------------- | ----------------------------------------------- |
| Class A | Same node executed twice (true cycle)        | `visited_nodes` set + journal analysis          |
| Class B | Multiple nodes wrote response (double-write) | `response_claimed_by` guard + journal           |
| Class C | Logging/tracing artifact (not real dupe)     | Same `event_guid` appears in multiple log lines |

### NodeRun Journal

Each turn maintains an append-only journal (`metadata["node_run_journal"]`) with one entry per node execution:

```python
@dataclass
class NodeRunEntry:
    seq: int                      # Monotonic sequence number
    node_name: str                # Name of node executed
    event_guid: str               # Unique GUID for this execution
    router_decision: Optional[str]  # Edge/condition that led here
    question_target: Optional[str]  # Active question target
    missing_fields: Optional[List[str]]  # Missing core fields at entry
    produced_response: bool       # Did this node write assistant response?
    llm_calls_before: int         # LLM call count before node
    llm_calls_after: int          # LLM call count after node
    timestamp_ms: float           # Timestamp for timing analysis
```

**Journal Lifecycle:**

1. `init_turn_instrumentation()` - Called at turn start in `run_turn()` / `run_turn_streaming()`
2. `record_node_run()` - Called by `_debug_node_entry()` for each node
3. `update_node_exit()` - Called by `_debug_node_exit()` to record final LLM count
4. `dump_turn_journal()` - Called at end-of-turn to log summary and detect duplication

### Response Writer Guard

The `claim_response_writer()` function enforces single-response-writer invariant:

```python
def claim_response_writer(state: GraphState, node_name: str) -> bool:
    """
    Attempt to claim response writer for this turn.
    Returns True if claim successful, False if blocked.
    """
    if current_writer is None:
        meta["response_claimed_by"] = node_name
        return True
    if current_writer == node_name:
        return True  # Same node re-claiming
    # Block and log
    meta["duplication_class"] = DuplicationClass.DOUBLE_WRITER.value
    return False
```

This prevents user-visible response duplication even before the root cause is fixed.

### Tripwires

Two safety rails abort execution on anomalies:

| Tripwire        | Threshold         | Behavior                            |
| --------------- | ----------------- | ----------------------------------- |
| **Max Steps**   | 25 per turn       | Log error, set `tripwire_triggered` |
| **Repeat Node** | Any (+ allowlist) | Log error, classify as Class A      |

```python
MAX_STEPS_PER_TURN: int = 25
MULTI_EXEC_ALLOWLIST: frozenset = frozenset()  # Empty = no node allowed twice
```

### LLM Call Tracing

Each LLM call is assigned a unique `llm_call_id` for tracing:

```python
llm_call_id = f"{turn_canary[:8]}:{node_name}:{step_count}:{call_number}"
```

Example: `a1b2c3d4:strategy_stage0:3:1`

This enables correlation of LLM calls with journal entries and detection of multiple calls per node.

### End-of-Turn Summary

At turn end, `dump_turn_journal()` logs:

```
[PLAN_GRAPH DEBUG] TURN_JOURNAL_SUMMARY step_count=6 duplication_class=none llm_calls=1 tripwire=none node_sequence=lqa_prepass → normalize_inputs → strategy_node → validate_and_merge → branch_postprocess → summarize
```

If duplication detected, full journal is dumped for debugging.

### Metadata Keys (V12)

| Key                   | Type         | Description                             |
| --------------------- | ------------ | --------------------------------------- | -------------------------------------- |
| `node_run_journal`    | `List[dict]` | Append-only list of NodeRunEntry dicts  |
| `visited_nodes`       | `Set[str]`   | Nodes executed this turn                |
| `step_count`          | `int`        | Counter for tripwire                    |
| `response_claimed_by` | `str         | None`                                   | Node that claimed response writer      |
| `turn_canary`         | `str`        | UUID to verify state mutations persist  |
| `mutation_counter`    | `int`        | Monotonic counter for canary validation |
| `tripwire_triggered`  | `str         | None`                                   | Which tripwire fired (if any)          |
| `duplication_class`   | `str         | None`                                   | Classification if duplication detected |
| `blocked_writers`     | `List[str]`  | Nodes blocked from writing response     |

### Test Coverage

V12 maintains 1096 passing tests with no regressions. Instrumentation is non-breaking:

| Aspect                 | Behavior                                     |
| ---------------------- | -------------------------------------------- |
| Tripwires              | Log errors but don't raise (production-safe) |
| Journal initialization | Defensive: re-init if missing                |
| Response writer guard  | Returns False on conflict, doesn't raise     |
| End-of-turn dump       | Only logs if `_DEBUG_LOG` enabled            |

---

## Stage0 Lifecycle & Fuzzy Normalization (V13)

V13 fixes a bug where changing the origin city would incorrectly re-trigger stage0 with new destination suggestions, and adds fuzzy matching for typo correction in place names.

### Stage0 Lifecycle Suppression Fix

**Problem**: When routing through the router LLM path (not the gate path), stage0 would re-run even when it had already completed for the same topic+destinations.

**Root Cause**: The lifecycle suppression check existed only in `GateEvaluator._check_strategy_pre_core_value_with_dest()` (the gate), but when routing came through `router → strategy_node`, the stage0 logic inside `strategy_node` didn't check the lifecycle signature.

**Fix**: Added lifecycle suppression check directly in `strategy_node()` before calling `_strategy_stage0()`:

```python
# In strategy_node(), before calling _strategy_stage0():
if is_stage0:
    ti = state.trip_inputs
    destinations = ti.destinations or []
    origin = ti.origin
    current_sig = GateEvaluator._compute_stage0_signature(topic, destinations, origin)
    completed_sig = state.metadata.get("stage0_completed_sig")
    if completed_sig == current_sig:
        _debug("strategy_node stage0 skipped: lifecycle suppression (router path)")
        return await required_fields_node(state)
```

This ensures both routing paths (gate and router) respect the same lifecycle suppression invariant.

### Origin-Aware Stage0 Signature

**Enhancement**: The stage0 signature now includes the origin in addition to topic and destinations.

**Before**: `_compute_stage0_signature(topic, destinations)` → `"hiking:abc123"`

**After**: `_compute_stage0_signature(topic, destinations, origin)` → `"hiking:def456"`

**Rationale**: When the user changes their departure city (e.g., from Rome to Paris), stage0 should re-run to suggest destinations that are more accessible from the new origin. For example, "epic hiking from Paris" should suggest Swiss Alps and Vosges Mountains, not Patagonia.

**Signature computation**:

```python
dest_str = "|".join(sorted(d.lower().strip() for d in destinations)) if destinations else ""
origin_str = origin.lower().strip() if origin else ""
combined = f"{dest_str}|{origin_str}"
combined_hash = hashlib.md5(combined.encode()).hexdigest()[:8]
return f"{topic}:{combined_hash}"
```

### Fuzzy Place Name Matching

**Problem**: Place names with typos (e.g., "pariss", "londob") or lowercase (e.g., "paris") were not being normalized to their canonical forms.

**Solution**: Added fuzzy matching using `rapidfuzz` library (already in requirements.txt):

```python
from app.known_places import normalize_place_with_fuzzy

# "pariss" → "Paris" (fuzzy match, score=91%)
# "londob" → "London" (fuzzy match, score=83%)
# "roma" → "Rome" (synonym lookup)
# "wien" → "Vienna" (synonym lookup)
```

**Implementation** (`known_places.py`):

| Function                       | Purpose                                           | Threshold |
| ------------------------------ | ------------------------------------------------- | --------- |
| `fuzzy_match_place()`          | Low-level fuzzy matching against all known places | 80%       |
| `normalize_place_with_fuzzy()` | Combined synonym + fuzzy + title-case fallback    | 80%       |

**Matching order**:

1. Synonym map lookup (fast, exact match)
2. Canonical places lookup (exact match, case-insensitive)
3. Fuzzy matching using `rapidfuzz.fuzz.WRatio` scorer
4. Title-case fallback if no match

**Integration**: Applied to both `origin` and `destinations` normalization in `TripInputNormalizer.normalize_all()`.

### Local Language Synonym Expansion

**Enhancement**: Added common local-language city names to the synonym map:

| Local Name | English Name |
| ---------- | ------------ |
| roma       | Rome         |
| milano     | Milan        |
| firenze    | Florence     |
| venezia    | Venice       |
| napoli     | Naples       |
| torino     | Turin        |
| genova     | Genoa        |
| wien       | Vienna       |
| münchen    | Munich       |
| köln       | Cologne      |
| lisboa     | Lisbon       |
| praha      | Prague       |
| kobenhavn  | Copenhagen   |
| warszawa   | Warsaw       |
| moskva     | Moscow       |

These are checked before fuzzy matching, ensuring exact local names get their English equivalents.

### Test Coverage

V13 adds 28 new tests for fuzzy normalization in `test_place_normalization.py`:

| Test Class                    | Count | Coverage                                    |
| ----------------------------- | ----- | ------------------------------------------- |
| `TestFuzzyMatchPlace`         | 10    | Typos, synonyms, thresholds, edge cases     |
| `TestNormalizePlaceWithFuzzy` | 12    | Local language, typos, canonical, fallbacks |
| `TestNormalizePlaceSynonym`   | 3     | Legacy synonym function                     |
| `TestIsKnownPlace`            | 3     | Known place lookup                          |

Total test count: 1137 passed, 6 skipped.

---

## Pattern Matching Module (V14)

> **New File**: `backend/app/pattern_matching.py` (~900 lines)
> **Updated**: December 24, 2025 - Consolidation of regex patterns from plan_graph.py

### Module Overview

The `pattern_matching.py` module centralizes all regex patterns used for deterministic extraction of trip planning inputs. This refactoring:

1. **Reduces code duplication**: Patterns previously scattered across 22,500 lines in `plan_graph.py`
2. **Improves maintainability**: All patterns in one organized file with clear section headers
3. **Enables comprehensive matching**: Added 50+ new patterns for flights, hotels, transport, and activities
4. **Provides helper functions**: Ready-to-use extractors for common fields

### Pattern Categories

| Category          | Pattern Count | Purpose                                                    |
| ----------------- | ------------- | ---------------------------------------------------------- |
| **Utility**       | 5             | ANSI escape, sentence endings, article prefixes            |
| **Short-Circuit** | 5             | Greeting, yes/no, comma lists, multi-destination           |
| **Date**          | 5             | Relative dates, seasons, months, date compatibility        |
| **Traveler**      | 10            | Solo, couple, family, group, ages, compatibility           |
| **Budget**        | 5             | Currency, amounts, inline mentions, phrases                |
| **Duration**      | 1             | Days, nights, weeks with word-to-number mapping            |
| **Destination**   | 5             | Origin/destination, initial extraction, multi-field        |
| **Flight**        | 6             | Cabin class, layovers, trip type, airlines, times, baggage |
| **Hotel**         | 5             | Star ratings, types, amenities, rooms, location            |
| **Transport**     | 7             | Car rental, train, bus, ferry, taxi, transit, walking      |
| **Activity**      | 6             | Tours, museums, outdoor, wellness, food, entertainment     |
| **Infeasibility** | 6             | Past dates, seasonal impossibilities, corrections          |
| **LQA**           | 3             | Multi-intent bail patterns                                 |

### Enhanced Flight/Hotel/Transport Patterns

**NEW Flight Patterns** (previously missing):

```python
# Cabin class extraction
CABIN_CLASS_PATTERN = r"\b(economy|premium\s+economy|business|first\s+class|first)\b"

# Direct flight preference
DIRECT_FLIGHT_PATTERN = r"\b(direct|non[- ]?stop|nonstop|no\s+stops?|no\s+layovers?)\b"

# Layover tolerance
LAYOVER_PATTERN = r"\b(max(?:imum)?\s+)?(\d+)\s*(?:hour|hr)s?\s*layover\b"

# One-way vs round-trip
TRIP_TYPE_PATTERN = r"\b(one[- ]?way|single|round[- ]?trip|return|open[- ]?jaw)\b"
```

**NEW Hotel Patterns** (previously missing):

```python
# Star rating extraction (handles "4 star", "4-star", "4+ stars", "at least 4 stars")
HOTEL_STAR_PATTERN = r"(?:\b(\d)\s*[- ]?\s*stars?\b|\bat\s+least\s+(\d)\s*stars?\b)"

# Amenity extraction
HOTEL_AMENITY_PATTERN = r"\b(pool|spa|gym|breakfast|wifi|parking|pet[- ]?friendly|...)\b"

# Room preferences
ROOM_PREFERENCE_PATTERN = r"\b(king|queen|double|twin|suite|deluxe|connecting)\b"
```

**NEW Transport Patterns** (previously basic keyword matching):

```python
# Car rental intent
CAR_RENTAL_PATTERN = r"\b(rent\s+a?\s*car|car\s+rental|hire\s+(?:a\s+)?car)\b"

# Train travel
TRAIN_PATTERN = r"\b(by\s+train|high[- ]?speed\s+train|eurail|sleeper\s+train)\b"

# Ferry/boat
FERRY_PATTERN = r"\b(ferry|cruise|catamaran|water\s+taxi)\b"
```

### Helper Functions

The module provides ready-to-use extraction functions:

| Function                              | Returns       | Description                                       |
| ------------------------------------- | ------------- | ------------------------------------------------- |
| `extract_hotel_stars(text)`           | `int \| None` | Extracts star rating (1-5) from text              |
| `extract_cabin_class(text)`           | `str \| None` | Returns normalized cabin class                    |
| `extract_hotel_amenities(text)`       | `List[str]`   | Lists all mentioned amenities                     |
| `is_direct_flight_preferred(text)`    | `bool`        | Checks for non-stop preference                    |
| `extract_trip_type(text)`             | `str \| None` | Returns "one_way" or "round_trip"                 |
| `has_car_rental_intent(text)`         | `bool`        | Checks for car rental mention                     |
| `has_train_intent(text)`              | `bool`        | Checks for train travel mention                   |
| `parse_duration_text(text)`           | `int \| None` | Parses duration to days                           |
| `normalize_ansi(text)`                | `str`         | Strips ANSI escape codes                          |
| `is_traveler_detail_answer(...)`      | `bool`        | Detects age lists like "3, 6, 12"                 |
| `is_text_date_compatible(text)`       | `bool`        | **Single source of truth** for date answers (V32) |
| `text_is_compatible_with_target(...)` | `bool`        | Checks if text answers question                   |

### Constants Exported (V32)

| Constant                         | Type         | Description                                      |
| -------------------------------- | ------------ | ------------------------------------------------ |
| `RELATIVE_DATE_WORDS_SIMPLE`     | `frozenset`  | Standalone date words: "today", "tomorrow", etc. |
| `RELATIVE_DATE_WORDS_CONTEXTUAL` | `frozenset`  | Words requiring context: "week", "month", etc.   |
| `RELATIVE_DATE_WORDS_ALL`        | `frozenset`  | Combined set for general date detection          |
| `DATES_COMPATIBILITY_PATTERN`    | `re.Pattern` | Canonical regex for date answer detection        |

### Usage in plan_graph.py

The patterns are imported at the top of `plan_graph.py`:

```python
from app.pattern_matching import (
    # Utility patterns
    ANSI_ESCAPE_PATTERN,
    GREETING_PATTERN,
    YES_PATTERN,
    NO_PATTERN,
    # Date compatibility (consolidated - V32)
    is_text_date_compatible,
    RELATIVE_DATE_WORDS_ALL,
    # ... 80+ pattern imports ...
    # Helper functions
    extract_hotel_stars,
    extract_cabin_class,
    is_traveler_detail_answer,
    text_is_compatible_with_target,
)
```

Local aliases are created for backward compatibility:

```python
_GREETING_PATTERN = GREETING_PATTERN  # Alias for existing code
```

### Test Coverage

All 1093 langgraph tests pass with the refactored patterns. No behavior changes were introduced—this is a pure consolidation refactoring.

---

## Gate Renumbering & Routing Fixes (V15)

This section documents the routing fixes implemented to resolve three interconnected bugs:

1. "Yes, generate my itinerary!" not triggering plan generation
2. "I want a hiking plan" showing empty response due to JSON parse failure
3. "Show more details" not routing to strategy expansion

### Gate Precedence Renumbering

Gate precedence values were renumbered from sequential (1, 2, 3...) to intuitive increments of 10
to allow future insertions without reshuffling all values:

| Old Value | New Value | Gate Name                           |
| --------- | --------- | ----------------------------------- |
| —         | 10        | `STRATEGY_EXPANSION` (NEW)          |
| —         | 20        | `GENERATE_REQUESTED` (NEW)          |
| 1         | 30        | `SHORT_CIRCUIT`                     |
| —         | 40        | `READY_NO_FIELDS` (NEW POSITION)    |
| 2         | 50        | `FAST_PATH`                         |
| 3         | 60        | `SPECIALIST_PRE_CORE`               |
| 4         | 70        | `STRATEGY_TOPIC_SWITCH`             |
| 5         | 80        | `STRATEGY_PRE_CORE_VALUE`           |
| 55        | 85        | `STRATEGY_PRE_CORE_VALUE_WITH_DEST` |
| 6         | 90        | `CORE_COLLECTION`                   |
| 7-10      | 100-130   | Heuristic gates                     |
| 99        | 999       | `ROUTER_LLM`                        |

### GENERATE_REQUEST_PATTERN

New consolidated pattern in `pattern_matching.py` (~line 78-107) for detecting explicit plan
generation requests:

```python
GENERATE_REQUEST_PATTERN = re.compile(
    r"(?:"
    r"(?:yes[,!]?\s+)?(?:generate|create|build|make)\s+(?:my\s+|the\s+)?(?:itinerary|plan|trip)"
    r"|(?:show|give)\s+(?:me\s+)?(?:the\s+)?(?:plan|itinerary)"
    r"|(?:i'?m\s+)?ready(?:\s+to\s+(?:go|book|generate|plan))?"
    r"|(?:looks?|sounds?)\s+good[,!]?\s*(?:go\s+ahead|let'?s\s+(?:go|do\s+it))?"
    r"|let'?s\s+(?:go|do\s+it|book|plan|generate)"
    r"|go\s+ahead(?:\s+(?:and\s+)?(?:generate|create|book|plan))?"
    r"|book\s+it(?:\s+now)?"
    r"|(?:do|make)\s+it\s+(?:now|happen)"  # NOT "do it all together"
    r"|yes[,!]?\s*(?:please\s+)?generate"
    r")",
    re.IGNORECASE,
)
```

**Key exclusion**: "do it" alone is NOT matched (too ambiguous, often means multi-city intent).
Requires "do it now" or "make it happen" for explicit generation.

### STRATEGY_EXPANSION Gate

New highest-priority gate (precedence 10) for handling strategy expansion requests:

```python
# In GateEvaluator.evaluate():
if meta.get("pending_strategy_expansion"):
    return GateResult(
        gate_fired=GatePrecedence.STRATEGY_EXPANSION,
        destination="strategy_node",
        reason="pending_strategy_expansion_flag",
    )
```

Triggers on phrases like "Show more details", "expand", "tell me more", "elaborate", "go deeper".

### JSON Recovery Fallback

New helper function `_extract_message_from_malformed_json()` provides fallback extraction when
LLM returns malformed JSON that fails `json.loads()`:

```python
def _extract_message_from_malformed_json(raw: str) -> str | None:
    """
    Extract the 'message' field from malformed JSON response.
    Uses regex extraction as fallback when json.loads() fails.
    """
    if len(raw) < 50:
        return None  # Too short to be meaningful

    # Try to extract message field with regex
    for pattern in [
        r'"message"\s*:\s*"((?:[^"\\]|\\.)+)"',  # Standard quotes
        r'"message"\s*:\s*"([^"]+(?:\\"[^"]*)*)"',  # Escaped quotes
    ]:
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            content = match.group(1)
            # Unescape common sequences
            content = content.replace('\\"', '"').replace('\\n', '\n')
            if len(content) > 50:
                return content
    return None
```

Used in `strategy_node` to recover meaningful responses from JSON parse failures.

### Empty Response Guard

Added guard in `summarize` node to prevent empty responses:

```python
# In summarize():
if not state.get("last_summary") and not _get_pending_user_response(state):
    return {
        "last_summary": "I'm still working on understanding your request. Could you tell me more about your travel plans?",
        **_write_metadata_field("response_writer_node", "summarize:fallback"),
    }
```

This ensures users always receive a meaningful response even when upstream nodes fail silently.

### Test Coverage

54 new tests in `tests/langgraph/test_generate_request_routing.py` covering:

- `GENERATE_REQUEST_PATTERN` matching and non-matching
- `_detect_short_circuit` with generate requests (ready vs incomplete plans)
- `STRATEGY_EXPANSION` gate evaluation
- JSON recovery fallback behavior
- Gate precedence ordering invariants

All 1150 langgraph tests pass with these changes.

---

## Hermetic Tier A Test Harness (V16)

> **Added**: PR0 Implementation
> **Test Files**:
>
> - `tests/langgraph/fake_llm.py` (~100 lines)
> - `tests/langgraph/test_text_compatibility.py` (~290 lines)
> - `tests/langgraph/test_tier_a_trace_replay.py` (~240 lines)
> - `tests/langgraph/test_gate_invariants.py` (~300 lines)

### FakeLLM Harness

The `FakeLLM` class provides a hermetic test harness for Tier A (pure-logic) testing that guarantees
zero actual LLM calls during test execution:

```python
class FakeLLM:
    """
    Hermetic LLM stub for Tier A testing.

    Two modes:
    - strict: Raises AssertionError on ANY LLM call (zero-LLM invariant testing)
    - map: Returns keyed responses based on (node_name, callsite_name) tuple
    """

    def __init__(self, mode: str = "strict", response_map: dict = None):
        self.mode = mode
        self.response_map = response_map or {}
        self.call_log: List[LLMCallRecord] = []
```

**Key Design Decisions**:

1. **Keying by semantic identity**: Uses `(node_name, callsite_name)` tuple rather than prompt hash

   - Avoids brittleness when prompt text changes
   - Provides stable keys for test fixtures
   - Example: `("extractor", "main_extraction")` vs `hash("Extract fields from...")`

2. **Call logging**: Records all attempted LLM calls with full context:

   ```python
   @dataclass
   class LLMCallRecord:
       node_name: str
       callsite_name: str
       prompt_bundle_hash: str
       timestamp: float
   ```

3. **Context manager API**: Clean setup/teardown in tests:
   ```python
   with FakeLLM.patch_strict():
       # Any LLM call here raises AssertionError
       result = gate_evaluator.evaluate(state)
   ```

### Text Compatibility Table-Driven Tests

Comprehensive coverage for `text_is_compatible_with_target()` and `is_text_date_compatible()`:

| Target Category  | Test Cases | Coverage                                                                                      |
| ---------------- | ---------- | --------------------------------------------------------------------------------------------- |
| **dates**        | 35+        | ISO dates, relative dates, ranges, natural language, **tomorrow/today/tonight/weekend (V32)** |
| **origin**       | 15+        | City names, airports, countries, negatives                                                    |
| **destinations** | 20+        | Single/multi-city, known places, negatives                                                    |
| **travelers**    | 20+        | Adults, children, couples, groups, edge cases                                                 |
| **budget**       | 15+        | Currency symbols, numeric, per-person, negatives                                              |

**V32 Addition:** New `TestIsTextDateCompatible` class tests the consolidated date function directly:

```python
class TestIsTextDateCompatible:
    \"\"\"Direct tests for the consolidated is_text_date_compatible function.\"\"\"

    @pytest.mark.parametrize("text,expected", [
        # Standalone relative date words (P0 fix)
        ("tomorrow", True),
        ("Tomorrow", True),  # Case insensitive
        ("TOMORROW", True),  # All caps
        ("today", True),
        ("tonight", True),
        ("weekend", True),
        # Should not match non-date text
        ("Paris", False),
        ("Swiss Alps", False),
    ])
    def test_relative_date_words(self, text: str, expected: bool):
        result = is_text_date_compatible(text)
        assert result == expected
```

Example test structure:

```python
class TestTextIsCompatibleWithTargetDates:
    @pytest.mark.parametrize("text,expected", [
        ("2025-03-15", True),
        ("March 15th", True),
        ("next Friday", True),
        ("hello world", False),
        ("the date is great", False),  # "date" as word != date value
    ])
    def test_dates_compatibility(self, text, expected):
        result = _text_is_compatible_with_target(text, "dates")
        assert result == expected
```

### Gate Invariant Tests

Critical invariants enforced by test assertions:

1. **Complete State Never Routes to required_fields**:

   ```python
   def test_complete_state_never_routes_to_required_fields():
       """
       INVARIANT: When TripReadiness.core_complete is True,
       GateEvaluator MUST NOT return destination="required_fields".
       """
       state = make_complete_state()
       result = gate_evaluator.evaluate(state)
       assert result.destination != "required_fields"
   ```

2. **Gate Precedence Ordering**:

   ```python
   def test_gate_precedence_ordering():
       """Gates with lower precedence numbers fire first."""
       assert GatePrecedence.SHORT_CIRCUIT < GatePrecedence.FAST_PATH
       assert GatePrecedence.FAST_PATH < GatePrecedence.SPECIALIST_PRE_CORE
       # ... etc
   ```

3. **Question Target Canonicalization**:
   ```python
   def test_question_target_canonicalization():
       """Verify canonicalize_question_target() mappings."""
       assert canonicalize_question_target("start_date") == "dates"
       assert canonicalize_question_target("end_date") == "dates"
       assert canonicalize_question_target("adults") == "travelers"
       assert canonicalize_question_target("children") == "children"  # NOT travelers
   ```

### Tier A Trace Replay Tests

Zero-LLM trace replay tests for core routing logic:

```python
class TestZeroLLMInvariants:
    """Tests that verify no LLM calls for deterministic paths."""

    def test_complete_state_gate_zero_llm(self):
        """Complete state evaluation requires zero LLM calls."""
        with FakeLLM.patch_strict():
            state = make_complete_state()
            result = gate_evaluator.evaluate(state)
            # If we reach here, no LLM was called
            assert result.destination in ["validate_and_merge", "general_node"]

    def test_question_target_answer_zero_llm(self):
        """Answering an active question requires zero LLM calls."""
        with FakeLLM.patch_strict():
            state = make_state_with_active_question("dates")
            state["user_text"] = "March 15-20"
            result = lqa_prepass(state)
            # LQA handles simple date answers without LLM
            assert result.get("lqa_answered") == True
```

### Ownership Suppression Tests

Tests for the signature-scoped lifecycle suppression invariant:

```python
class TestOwnershipSuppressionInvariant:
    """
    INVARIANT: When a question_target is active, topic-switch gates
    are suppressed until the question is answered or explicitly abandoned.
    """

    def test_active_question_blocks_topic_switch(self):
        state = make_state_with_active_question("budget")
        state["user_text"] = "What about hotels in Paris?"

        result = gate_evaluator.evaluate(state)

        # Should NOT switch to hotels specialist while budget question pending
        assert result.destination != "hotels_node"
        assert result.gate_fired != GatePrecedence.SPECIALIST_PRE_CORE
```

### Test Summary

| Test File                   | Tests | Focus                               |
| --------------------------- | ----- | ----------------------------------- |
| test_text_compatibility.py  | 95+   | Pattern matching edge cases         |
| test_tier_a_trace_replay.py | 35+   | Zero-LLM invariants, trace replay   |
| test_gate_invariants.py     | 31+   | Gate precedence, routing invariants |

**Total**: 161 new tests added, all passing (1348 total langgraph tests).

---

## Startup Validation & Build Info (V17)

> **Added**: PR4 Implementation
> **Files Modified**:
>
> - `backend/app/main.py` (lifespan, health endpoint)
> - `backend/tests/test_startup.py` (new, 14 tests)

### Fail-Fast Template Validation

The application now calls `validate_template_coverage()` at startup and **fails fast** if template
validation fails. This prevents deploy-time prompt/template drift that causes hard-to-debug runtime behavior.

```python
# In lifespan() - main.py
template_validation = validate_template_coverage()
if not template_validation["valid"]:
    error_msg = (
        f"[FATAL] Template coverage validation failed: "
        f"missing_fields={template_validation['missing_fields']}, "
        f"errors={template_validation['errors'][:3]}"
    )
    logger.error(error_msg)
    raise RuntimeError(error_msg)
```

**Failure is fatal everywhere** (dev + prod). Silent drift is worse than a loud failure.

### Build Info Logging

At startup, the application logs critical build identifiers for cache debugging:

```python
logger.info(
    "[Startup] Build info: prompt_bundle_hash=%s, planner_build_id=%s, cache_schema_version=%s",
    PROMPT_BUNDLE_HASH,
    PLANNER_BUILD_ID,
    CACHE_SCHEMA_VERSION,
)
```

| Identifier             | Source                                     | Purpose                                  |
| ---------------------- | ------------------------------------------ | ---------------------------------------- |
| `PROMPT_BUNDLE_HASH`   | MD5 of normalized prompt files             | Cache invalidation across prompt changes |
| `PLANNER_BUILD_ID`     | `GIT_SHA` or `BUILD_ID` env var (12 chars) | Cross-deploy cache isolation             |
| `CACHE_SCHEMA_VERSION` | Integer constant in plan_graph.py          | Invalidate on payload format changes     |

### Health Endpoint Enhancement

The `/health` endpoint now returns build information for debugging:

```python
@app.get("/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
        "prompt_bundle_hash": PROMPT_BUNDLE_HASH,
        "planner_build_id": PLANNER_BUILD_ID,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
    }
```

This enables:

- Quick verification that correct build is deployed
- Cache debugging across multiple instances
- Detecting prompt drift between environments

### Startup Validation Tests

14 new tests in `tests/test_startup.py`:

| Test Class                | Tests | Coverage                                                                    |
| ------------------------- | ----- | --------------------------------------------------------------------------- |
| `TestStartupValidation`   | 3     | Template coverage validation structure, pass, and fail detection            |
| `TestPromptBundleHash`    | 4     | Hash stability, format, content change detection, line ending normalization |
| `TestHealthEndpoint`      | 1     | Health endpoint returns build info                                          |
| `TestBuildIdentifiers`    | 2     | PLANNER_BUILD_ID and CACHE_SCHEMA_VERSION format                            |
| `TestStartupFailFast`     | 1     | Invalid templates trigger fail-fast                                         |
| `TestExpectedPromptFiles` | 3     | Critical prompt files and templates.json exist and are valid                |

**DoD**: Deploys with missing/mismatched prompt bundle fail immediately at startup, not at first request.

---

## CachePayload V6 Everywhere (V18)

Addresses the top remaining product risk: **stale-but-valid cache behavior**. All node-specific caches now use unified V6 validation with version tracking and event observability.

### Unified CachePayload Schema

Extended `CachePayload` dataclass with V6 fields:

```python
@dataclass
class CachePayload:
    # V6 Fields (new)
    payload_kind: str       # "required_fields", "router", "extractor", "strategy", "tile"
    node_name: str          # Matches payload_kind for consistency
    schema_version: int     # CACHE_SCHEMA_VERSION (currently 1)
    logic_version: int      # NODE_LOGIC_VERSION[node_name]
    prompt_bundle_hash: str # PROMPT_BUNDLE_HASH for prompt drift detection
    planner_build_id: str   # PLANNER_BUILD_ID for build isolation
    extra: Dict[str, Any]   # Node-specific payload data

    # Existing fields remain unchanged...
```

The `from_dict()` method is backward-compatible, defaulting V6 fields for legacy payloads.

### Migrated Caches

All 5 caches now use V6 validation:

| Cache                    | Key Components                                                                                              | Validation                |
| ------------------------ | ----------------------------------------------------------------------------------------------------------- | ------------------------- |
| `_required_fields_cache` | thread_id, user_text_hash, question_target, question_id, intent, core_hash, ready_state, model_id           | Full V6                   |
| `_router_cache`          | thread_id, user_text_hash, intent, core_hash, ready_state, model_id                                         | Full V6                   |
| `_extractor_cache`       | session_id, text_hash, core_hash, mode, model_id, schema_version, prompt_bundle_hash, build_id              | V6 key + validation       |
| `_strategy_cache`        | session_id, topic, core_hash, user_text_hash, model_id, stage0_lifecycle_hash, prompt_bundle_hash, build_id | V6 key + lifecycle hash   |
| `_tile_cache`            | intent, destinations, start_date, origin, schema_version, prompt_bundle_hash, build_id                      | V6 key + TTLCache bounded |

### Cache Event Observability

Per-turn cache event tracking:

```python
_cache_events_this_turn: List[Dict[str, Any]] = []

def _record_cache_event(node: str, action: str, reason: str = "") -> None:
    """Record cache event for observability."""
    _cache_events_this_turn.append({
        "node": node,
        "action": action,  # "hit", "miss", "discard", "evict"
        "reason": reason,
        "timestamp": time.time(),
    })
```

Events are cleared at turn start and included in `get_cache_stats()`:

```python
{
    "cache_events_this_turn": [
        {"node": "extractor", "action": "hit", "reason": ""},
        {"node": "strategy", "action": "miss", "reason": ""},
        {"node": "tile", "action": "discard", "reason": "schema_version_mismatch"},
    ],
    ...
}
```

### Bounded Tile Cache

Fixed memory leak risk in tile cache:

```python
# Before (unbounded, memory leak risk):
_tile_cache: Dict[str, Any] = {}

# After (bounded with TTL):
_TILE_CACHE_MAXSIZE = 100
_TILE_CACHE_TTL = 300  # 5 minutes
_tile_cache: TTLCache = TTLCache(maxsize=_TILE_CACHE_MAXSIZE, ttl=_TILE_CACHE_TTL)
```

### NODE_LOGIC_VERSION

Extended to include all cache-using nodes:

```python
NODE_LOGIC_VERSION: Dict[str, int] = {
    "required_fields": 1,
    "router": 1,
    "extractor": 1,
    "strategy": 1,
    "tile": 1,
}
```

Bumping a node's version invalidates all cached entries for that node.

### V6 Migration Tests

20 new tests in `tests/langgraph/test_cache_v6_migration.py`:

| Test Class                 | Tests | Coverage                                                                   |
| -------------------------- | ----- | -------------------------------------------------------------------------- |
| `TestExtractorCacheV6`     | 5     | Hit path, miss on text/hash change, prompt_bundle mismatch, stats tracking |
| `TestStrategyCacheV6`      | 3     | Hit path, miss on topic change, stats tracking                             |
| `TestTileCacheV6`          | 3     | Bounded TTLCache, set/get, schema_version in stats                         |
| `TestCachePayloadV6Fields` | 2     | V6 field presence, backward-compatible from_dict                           |
| `TestCacheEventTracking`   | 2     | Event recording, clearing between turns                                    |
| `TestCacheValidationV6`    | 2     | Schema version mismatch, ready state mismatch rejection                    |
| `TestNodeLogicVersion`     | 1     | All cache nodes included                                                   |
| `TestGetCacheStats`        | 2     | All caches included, size per cache                                        |

**DoD**: No code path reads from any cache without V6 validation. Cache events visible in metadata every turn.

---

## LLM Budget CI (V19)

CI tests to verify that any single turn respects the MAX_LLM_CALLS_PER_TURN budget. These tests should fail CI if any node path allows budget violations.

### Budget Enforcement Rules

The `can_call_llm()` function enforces these rules:

| Condition                                           | Max LLM Calls | Enforcement              |
| --------------------------------------------------- | ------------- | ------------------------ |
| `ready_to_generate=False` AND `question_target` set | 1 (default)   | Blocked after first call |
| `ready_to_generate=True`                            | No limit      | Tracked but not capped   |
| No `question_target` set                            | No limit      | Tracked but not capped   |

```python
MAX_LLM_CALLS_PER_TURN = 1  # Default during core field collection

# Key invariants:
# 1. Counter is increment-only (never decremented on error)
# 2. All blocked calls tracked in llm_call_blocked_reason dict
# 3. llm_nodes_called_this_turn tracks all nodes that called LLM
```

### Budget CI Tests

16 tests in `tests/langgraph/test_llm_budget_ci.py`:

| Test Class                 | Tests | Coverage                                                                                        |
| -------------------------- | ----- | ----------------------------------------------------------------------------------------------- |
| `TestLLMBudgetEnforcement` | 5     | First call allowed, second blocked, no cap when ready, no cap when no target, fallback response |
| `TestLLMBudgetPerNodePath` | 3     | required_fields, router, strategy paths respect budget                                          |
| `TestLLMCallTracking`      | 2     | Nodes tracked, blocked counts tracked                                                           |
| `TestBudgetWithFakeLLM`    | 2     | Short-circuit patterns skip LLM, confirmation patterns skip LLM                                 |
| `TestBudgetInvariants`     | 3     | Counter never decremented, blocked reason preserved, constant matches settings                  |
| `TestCIFailureConditions`  | 1     | Detects budget violation when simulated                                                         |

### Observability & Tracking

Budget tracking in `metadata`:

```python
state.metadata = {
    "llm_calls_this_turn": 1,          # Current count
    "llm_nodes_called_this_turn": ["required_fields"],  # Which nodes called LLM
    "llm_call_blocked_reason": {       # Why each node was blocked
        "extractor": "budget_exhausted",
        "router": "budget_exhausted",
    },
    "llm_call_blocked_count": {        # How many times each was blocked
        "extractor": 2,
        "router": 1,
    },
}
```

**DoD**: CI fails if any single turn exceeds MAX_LLM_CALLS_PER_TURN. All non-short-circuit paths tested.

---

## Strategy Topics (V20)

Comprehensive testing for all 5 strategy topics: hiking, diving, skiing, cycling, boating.

### Topic Registry

All strategy topics are registered in `STRATEGY_TOPIC_TO_NODE`:

```python
STRATEGY_TOPIC_TO_NODE: Dict[str, str] = {
    "hiking": "strategy_node",
    "diving": "strategy_node",
    "skiing": "strategy_node",
    "cycling": "strategy_node",
    "boating": "strategy_node",
}
```

Each topic has:

- Detection pattern in `_STRATEGY_TOPIC_PATTERNS`
- Prompt file at `prompts/strategy_{topic}.txt`
- Shared base at `prompts/_strategy_base.txt`

### Topic Detection Patterns

| Topic   | Pattern                               | Examples                                    |
| ------- | ------------------------------------- | ------------------------------------------- |
| hiking  | `hik(e\|ing)\|trek(king)?`            | "I want to go hiking", "trekking adventure" |
| diving  | `div(e\|ing)\|scuba\|snorkel(ing)?`   | "scuba diving", "snorkeling"                |
| skiing  | `ski(ing)?\|snowboard(ing)?`          | "ski vacation", "snowboarding"              |
| cycling | `cycl(e\|ing)\|bik(e\|ing)\|bicycle`  | "cycling tour", "biking"                    |
| boating | `boat(ing)?\|sail(ing)?\|yacht(ing)?` | "sailing", "yacht trip"                     |

Word boundaries prevent false positives (e.g., "skippered" doesn't match "ski").

### Strategy Gates

| Gate                                | Precedence | Purpose                                     |
| ----------------------------------- | ---------- | ------------------------------------------- |
| `STRATEGY_TOPIC_SWITCH`             | 70         | Mid-session topic changes with intent verbs |
| `STRATEGY_PRE_CORE_VALUE`           | 80         | Pre-core strategy topic handling            |
| `STRATEGY_PRE_CORE_VALUE_WITH_DEST` | 85         | Strategy with destination known             |
| `STRATEGY_EXPANSION`                | 100        | Expand strategy after core complete         |

### Strategy Topic Tests

59 tests in `tests/langgraph/test_strategy_topics.py`:

| Test Class                     | Tests | Coverage                                                      |
| ------------------------------ | ----- | ------------------------------------------------------------- |
| `TestStrategyTopicRegistry`    | 3     | All 5 topics registered, map to strategy_node, patterns exist |
| `TestTopicDetectionHiking`     | 8     | Hiking positive cases, edge cases                             |
| `TestTopicDetectionDiving`     | 5     | Diving positive cases                                         |
| `TestTopicDetectionSkiing`     | 6     | Skiing positive cases, skippered false positive               |
| `TestTopicDetectionCycling`    | 5     | Cycling positive cases                                        |
| `TestTopicDetectionBoating`    | 5     | Boating positive cases                                        |
| `TestTopicDetectionNegative`   | 8     | Non-strategy texts don't detect                               |
| `TestStrategyTopicSwitchGate`  | 3     | Gate precedence, intent verb detection                        |
| `TestStrategyTopicPersistence` | 2     | Topic stored in metadata, survives state copy                 |
| `TestStrategyPromptFiles`      | 7     | Prompt files exist for all topics                             |
| `TestStrategyGateIntegration`  | 3     | Gate existence and ordering                                   |
| `TestMultiTopicDetection`      | 2     | First topic wins                                              |
| `TestStrategyTopicValidation`  | 2     | Valid and unknown topics handled                              |

**DoD**: All 5 strategy topics have detection patterns, prompt files, and gate integration tests.

---

## Debug/Config Snapshot (V21)

Planner debug information and configuration snapshot for ops debugging and observability.

### Admin Planner Endpoint

New endpoint `GET /v1/admin/planner` exposes behavioral config and build identifiers:

```python
@app.get("/v1/admin/planner")
def admin_planner_debug():
    return get_planner_debug_info()
```

**Response Schema** (stable, versioned via `admin_endpoint_version`):

| Field                            | Type         | Description                                   |
| -------------------------------- | ------------ | --------------------------------------------- |
| `admin_endpoint_version`         | string       | Schema version (`"planner_v1"`)               |
| `prompt_bundle_hash`             | string       | 16-char hash of prompt templates              |
| `planner_build_id`               | string       | Git SHA or BUILD_ID (max 12 chars)            |
| `cache_schema_version`           | int          | Cache payload schema version (1)              |
| `enabled_strategy_topics`        | list[string] | Enabled strategy topics (sorted)              |
| `enabled_strategy_topics_source` | string       | `"defaults"` or `"env_override"`              |
| `enable_all_strategy_topics`     | bool         | Whether ENABLE_ALL_STRATEGY_TOPICS is set     |
| `llm_budget_max_calls_non_ready` | int          | Max LLM calls per non-ready turn (1)          |
| `cache_ttl_map_seconds`          | dict         | TTL per cache type (response, extractor, etc) |
| `cache_ttl_map_source`           | string       | Source of TTL config (`"config"`)             |
| `gate_precedence_version`        | string       | Gate logic version (`"v15"`)                  |
| `node_logic_version`             | dict         | Per-node logic versions                       |
| `strategy_output_caps`           | dict         | `{max_chars, expansion_max_chars}`            |

### Planner Snapshot Per Turn

Every turn carries a minimal planner config stamp in `state.metadata["planner_snapshot"]`:

```python
# Set once at start of run_turn()
metadata["planner_snapshot"] = get_planner_snapshot()
```

**Snapshot Fields**:

- `prompt_bundle_hash`
- `planner_build_id`
- `cache_schema_version`
- `enabled_strategy_topics`
- `llm_budget_max_calls_non_ready`
- `gate_precedence_version`

This enables trace replay with config verification and debugging of cache invalidation.

### Version Constants

New constants in `plan_graph.py`:

| Constant                  | Value    | Description                          |
| ------------------------- | -------- | ------------------------------------ |
| `GATE_PRECEDENCE_VERSION` | `"v15"`  | Gate logic version (V15 renumbering) |
| `CACHE_SCHEMA_VERSION`    | `1`      | Cache payload schema version         |
| `NODE_LOGIC_VERSION`      | dict     | Per-node logic versions              |
| `PLANNER_BUILD_ID`        | env      | GIT_SHA or BUILD_ID (max 12 chars)   |
| `PROMPT_BUNDLE_HASH`      | computed | Hash of prompt templates             |

**Strategy Output Caps** (in `config.py`):

| Setting                               | Default | Description                     |
| ------------------------------------- | ------- | ------------------------------- |
| `strategy_max_output_chars`           | 4000    | Max chars for strategy response |
| `strategy_expansion_max_output_chars` | 8000    | Max chars for expansion         |

### Debug Endpoint Tests

Tests in `tests/langgraph/test_debug_endpoints.py`:

| Test Class                 | Tests | Coverage                                    |
| -------------------------- | ----- | ------------------------------------------- |
| `TestAdminPlannerEndpoint` | 3     | Schema keys, values match constants, topics |
| `TestPlannerSnapshot`      | 3     | Exists in metadata, required keys, values   |
| `TestPlannerSnapshotTierA` | 1     | Snapshot consistent across turns            |

**Acceptance Criteria**:

- [x] `/v1/admin/planner` returns required keys
- [x] `planner_snapshot` emitted per turn
- [x] Tier A fixtures assert snapshot exists

---

## Cache Summary Metrics (V22)

Aggregate per-turn cache metrics and standardized discard/eviction reasons for analytics.

### Cache Invalid Reason Constants

New `CacheInvalidReason` class with standardized reason constants:

| Constant                      | Value                         | Description                    |
| ----------------------------- | ----------------------------- | ------------------------------ |
| `SCHEMA_VERSION_MISMATCH`     | `schema_version_mismatch`     | Cache schema version changed   |
| `LOGIC_VERSION_MISMATCH`      | `logic_version_mismatch`      | Node logic version changed     |
| `PROMPT_BUNDLE_HASH_MISMATCH` | `prompt_bundle_hash_mismatch` | Prompt templates changed       |
| `PLANNER_BUILD_ID_MISMATCH`   | `planner_build_id_mismatch`   | Deploy/build changed           |
| `HARD_CONSTRAINT_MISMATCH`    | `hard_constraint_mismatch`    | Core field constraint violated |
| `READY_STATE_FLIP`            | `ready_state_flip`            | Ready state changed            |
| `CONTRACT_MISMATCH`           | `contract_mismatch`           | Suggestion contract violated   |
| `TTL_EXPIRED`                 | `ttl_expired`                 | Cache entry TTL expired        |
| `PAYLOAD_KIND_MISMATCH`       | `payload_kind_mismatch`       | Wrong payload type             |
| `THREAD_MISMATCH`             | `thread_mismatch`             | Thread/session changed         |
| `USER_TEXT_MISMATCH`          | `user_text_mismatch`          | User input changed             |
| `QUESTION_TARGET_MISMATCH`    | `question_target_mismatch`    | Question target changed        |
| `QUESTION_ID_MISMATCH`        | `question_id_mismatch`        | Question ID changed            |
| `MISSING_ALL_MISMATCH`        | `missing_all_mismatch`        | Missing fields changed         |
| `CORE_HASH_MISMATCH`          | `core_hash_mismatch`          | Core fields hash changed       |
| `UNKNOWN`                     | `unknown`                     | Unclassified reason            |

### Summarize Cache Events

New `summarize_cache_events()` function converts raw cache events to dashboard-friendly summaries:

```python
def summarize_cache_events(cache_events: List[Dict]) -> Dict:
    return {
        "by_node": {node: {hit, miss, discard, evict}},
        "by_reason": {reason: count},
        "hit_rate_by_node": {node: float},
    }
```

**Output Structure**:

| Field              | Type                       | Description                        |
| ------------------ | -------------------------- | ---------------------------------- |
| `by_node`          | `Dict[str, Dict[str,int]]` | Per-node action counts             |
| `by_reason`        | `Dict[str, int]`           | Per-reason discard/eviction counts |
| `hit_rate_by_node` | `Dict[str, float]`         | Hit rate per node (0.0-1.0)        |

### Process-Level Rolling Counters

Module-level counters updated on each cache event:

```python
_cache_counters = {
    "hits_total": int,
    "misses_total": int,
    "discards_total": int,
    "evictions_total": int,
}
_cache_counters_by_node: Dict[str, Dict[str, int]]
_cache_counters_by_reason: Dict[str, int]
```

Exposed via `/v1/admin/planner` endpoint with scope documentation:

- `cache_counters_scope: "process"` - Counters are per-process
- `cache_counters_reset_on_restart: true` - Not persisted

### Cache Summary Tests

Tests in `tests/langgraph/test_cache_hardening_v6.py`:

| Test Class                        | Tests | Coverage                                    |
| --------------------------------- | ----- | ------------------------------------------- |
| `TestCacheInvalidReasonConstants` | 2     | All constants defined, lowercase snake_case |
| `TestSummarizeCacheEvents`        | 5     | Empty, single, multiple nodes, reasons      |
| `TestCacheCounters`               | 2     | Structure, admin endpoint inclusion         |

**Acceptance Criteria**:

- [x] `cache_summary_this_turn` emitted when `cache_events` exists
- [x] Standardized reasons implemented + tests cover all
- [x] `/v1/admin/planner` includes `cache_counters`

---

## Strategy Output Size Limits (V23)

Hard caps on strategy node output to prevent runaway LLM responses from bloating
the response payload or causing downstream issues.

### Truncation Helper Function

Located near `GATE_PRECEDENCE_VERSION` constant:

```python
def truncate_preserving_newlines(
    text: str,
    cap: int,
    footer: str = _STRATEGY_TRUNCATION_FOOTER,
) -> Tuple[str, bool]:
```

**Behavior**:

1. Returns `(text, False)` if text length <= cap
2. Finds last newline before `cap - len(footer)`
3. Falls back to word boundary if no newline found
4. Closes unclosed markdown code blocks (counts ` ``` ` occurrences)
5. Appends footer: `"\n\nAsk if you want me to expand any section."`
6. Returns `(truncated_text, True)`

### Strategy Node Integration

Applied in `strategy_node` after LLM response processing:

```python
# Determine cap based on stage
_strategy_cap = (
    settings.strategy_expansion_max_output_chars
    if stage_name == "stage2"
    else settings.strategy_max_output_chars
)

# Apply truncation
state.last_summary, _was_truncated = truncate_preserving_newlines(
    state.last_summary, _strategy_cap
)

# Set metadata flags
if _was_truncated:
    state.metadata["strategy_truncated"] = True
    state.metadata["strategy_truncate_cap"] = _strategy_cap
```

**Integration Points**:

1. Normal LLM response path (after `state.last_summary = j.get("assistant_message", "")`)
2. JSON recovery fallback path (after message extraction)

### Configuration Settings

In `config.py`:

```python
strategy_max_output_chars: int = 4000       # Stage 0/1 cap
strategy_expansion_max_output_chars: int = 8000  # Stage 2 (full itinerary)
```

Rationale:

- Stage 1 outline: 4000 chars (~1000 tokens)
- Stage 2 expansion: 8000 chars (~2000 tokens) for full itinerary

### Strategy Output Tests

Tests in `tests/langgraph/test_strategy_output_caps.py`:

| Test Class                       | Tests | Coverage                                 |
| -------------------------------- | ----- | ---------------------------------------- |
| `TestTruncatePreservingNewlines` | 7     | Unit tests for truncation helper         |
| `TestStrategyCapSettings`        | 3     | Config values and relationships          |
| `TestStrategyNodeTruncation`     | 3     | Integration with strategy node, metadata |

**Acceptance Criteria**:

- [x] `truncate_preserving_newlines()` helper added
- [x] Truncation applied in strategy_node LLM response path
- [x] Truncation applied in JSON recovery fallback path
- [x] `state.metadata["strategy_truncated"]` set when truncated
- [x] `state.metadata["strategy_truncate_cap"]` records the cap used
- [x] Stage 2 uses `strategy_expansion_max_output_chars` (8000)
- [x] Stage 0/1 uses `strategy_max_output_chars` (4000)

---

## JSON Utilities Extraction (V24)

PR-D: Mechanical extraction of JSON parsing utilities from `plan_graph.py` to
`graph_plan_utils.py` for better code organization.

### Extracted Functions

The following functions were moved to `graph_plan_utils.py`:

| Original Name                            | New Public Name                         | Purpose                                    |
| ---------------------------------------- | --------------------------------------- | ------------------------------------------ |
| `_truncate_to_balanced_json()`           | `truncate_to_balanced_json()`           | Extract balanced JSON from malformed text  |
| `jloads_safe()`                          | `jloads_safe()` (unchanged)             | Multi-fallback JSON parsing                |
| `_extract_message_from_malformed_json()` | `extract_message_from_malformed_json()` | Extract assistant_message from broken JSON |

### Backwards Compatibility

To maintain backwards compatibility, `plan_graph.py` imports these functions
from `graph_plan_utils.py` and re-exports them:

```python
from app.graph_plan_utils import (
    # PR-D: JSON utilities extracted to graph_plan_utils
    _extract_message_from_malformed_json,
    _truncate_to_balanced_json,
    jloads_safe,
)
```

Private aliases are also available in `graph_plan_utils.py`:

```python
# Backwards compatibility aliases
_truncate_to_balanced_json = truncate_to_balanced_json
_extract_message_from_malformed_json = extract_message_from_malformed_json
```

### Extraction Tests

Tests in `tests/langgraph/test_json_utils_extraction.py`:

| Test Class                    | Tests | Coverage                                 |
| ----------------------------- | ----- | ---------------------------------------- |
| `TestJsonUtilitiesExtraction` | 7     | Import paths, aliases, backwards compat  |
| `TestJloadsSafeFunctionality` | 4     | Valid JSON, empty, malformed, extra text |
| `TestTruncateToBalancedJson`  | 5     | Simple, prefix, nested, strings, no JSON |

**Acceptance Criteria**:

- [x] `jloads_safe()` moved to `graph_plan_utils.py`
- [x] `truncate_to_balanced_json()` moved with public name
- [x] `extract_message_from_malformed_json()` moved with public name
- [x] Private aliases (`_truncate_to_balanced_json`, etc.) preserved
- [x] `plan_graph.py` imports from `graph_plan_utils.py`
- [x] Existing tests in `test_error_handling.py` continue to pass
- [x] New extraction verification tests added

---

## Debug Utilities Extraction (V25)

PR-E: Mechanical extraction of debug logging utilities from `plan_graph.py` to
new `debug_utils.py` module for better code organization.

### Extracted Debug Functions

The following functions were moved to `debug_utils.py`:

| Function               | Purpose                                     |
| ---------------------- | ------------------------------------------- |
| `_debug()`             | Conditional debug logging (non-fatal)       |
| `_debug_error()`       | Error logging with ❌ emoji prefix          |
| `_debug_suggestions()` | Log user prompt suggestions                 |
| `safe_debug()`         | Guaranteed non-throwing debug wrapper       |
| `safe_debug_error()`   | Guaranteed non-throwing error debug wrapper |
| `is_debug_enabled()`   | New: Check if debug logging is enabled      |

### Debug Backwards Compatibility

To maintain backwards compatibility, `plan_graph.py` imports these functions
from `debug_utils.py` and re-exports them:

```python
from app.debug_utils import (
    # PR-E: Debug utilities extracted to debug_utils.py
    _debug,
    _debug_error,
    _debug_suggestions,
    is_debug_enabled,
    safe_debug,
    safe_debug_error,
)
```

### Debug Extraction Tests

Tests in `tests/langgraph/test_debug_utils_extraction.py`:

| Test Class                     | Tests | Coverage                                   |
| ------------------------------ | ----- | ------------------------------------------ |
| `TestDebugUtilitiesExtraction` | 9     | Import paths, aliases, backwards compat    |
| `TestDebugFunctionality`       | 8     | Non-fatal behavior, truncation, edge cases |

**Acceptance Criteria**:

- [x] `_debug()` moved to `debug_utils.py`
- [x] `_debug_error()` moved to `debug_utils.py`
- [x] `_debug_suggestions()` moved to `debug_utils.py`
- [x] `safe_debug()` moved to `debug_utils.py`
- [x] `safe_debug_error()` moved to `debug_utils.py`
- [x] `is_debug_enabled()` added for checking debug state
- [x] `plan_graph.py` imports from `debug_utils.py`
- [x] All functions remain non-fatal (never raise exceptions)
- [x] New extraction verification tests added

---

## Metadata Helpers & Turn Init (V26)

PR2: Centralized metadata key constants and helper functions to prevent string-literal
drift and ensure consistent per-turn initialization across `run_turn()` and
`run_turn_streaming()`.

### Planner Package Structure

New `backend/app/planner/` package structure:

```
backend/app/planner/
├── __init__.py       # Facade module (PR1 will formalize exports)
├── meta_keys.py      # Metadata key constants
└── meta.py           # Metadata helper functions
```

### Metadata Key Constants

Defined in `meta_keys.py`:

| Constant                         | Value                              | Scope      | Purpose                              |
| -------------------------------- | ---------------------------------- | ---------- | ------------------------------------ |
| `LLM_CALLS_THIS_TURN`            | `"llm_calls_this_turn"`            | Per-turn   | Integer counter for LLM budget       |
| `LLM_CALL_SITES`                 | `"llm_nodes_called_this_turn"`     | Per-turn   | List of nodes that called LLM        |
| `LLM_CALL_BLOCKED_REASON`        | `"llm_call_blocked_reason"`        | Per-turn   | Dict of blocked nodes → reasons      |
| `NODE_RUN_JOURNAL`               | `"node_run_journal"`               | Per-turn   | Append-only list of NodeRunEntry     |
| `VISITED_NODES`                  | `"visited_nodes"`                  | Per-turn   | Set of nodes executed this turn      |
| `STEP_COUNT`                     | `"step_count"`                     | Per-turn   | Counter for tripwire                 |
| `RESPONSE_CLAIMED_BY`            | `"response_claimed_by"`            | Per-turn   | Guard for single response writer     |
| `PLANNER_SNAPSHOT`               | `"planner_snapshot"`               | Per-turn   | Version/build info snapshot          |
| `CACHE_EVENTS`                   | `"cache_events_this_turn"`         | Per-turn   | Cache event list for observability   |
| `DUPLICATION_CLASS`              | `"duplication_class"`              | Per-turn   | Duplication detection classification |
| `TURN_CANARY`                    | `"turn_canary"`                    | Per-turn   | UUID for state mutation validation   |
| `MUTATION_COUNTER`               | `"mutation_counter"`               | Per-turn   | Counter for canary checks            |
| `TRIPWIRE_TRIGGERED`             | `"tripwire_triggered"`             | Per-turn   | Tripwire detection flag              |
| `DELTAS_APPLIED_THIS_TURN`       | `"deltas_applied_this_turn"`       | Per-turn   | Field change tracking list           |
| `RESPONSE_SOURCE_NODE`           | `"response_source_node"`           | Per-turn   | First node to produce response       |
| `RESPONSE_GENERATION_PROVENANCE` | `"response_generation_provenance"` | Per-turn   | Response generation provenance       |
| `LLM_CALL_BLOCKED_COUNT`         | `"llm_call_blocked_count"`         | Cross-turn | Cumulative blocked count by node     |
| `TODAY_ISO`                      | `"today_iso"`                      | Cross-turn | Today's date (set once per session)  |

Validation tuples:

- `ALL_META_KEYS`: Tuple of all metadata keys for uniqueness validation
- `PER_TURN_KEYS`: Tuple of keys that reset at start of each turn

### Metadata Helper Functions

Defined in `meta.py`:

| Function           | Signature                                                | Purpose                                |
| ------------------ | -------------------------------------------------------- | -------------------------------------- |
| `meta_get()`       | `(state, key, default=None) → Any`                       | Safe getter with default               |
| `meta_set()`       | `(state, key, value) → None`                             | Set value on metadata                  |
| `meta_set_once()`  | `(state, key, value, *, allow_overwrite_in_prod) → bool` | Set-once with test-mode assertion      |
| `meta_append()`    | `(state, key, item) → None`                              | Append to list (creates if missing)    |
| `meta_increment()` | `(state, key, amount=1) → int`                           | Increment counter (creates if missing) |
| `is_test_mode()`   | `() → bool`                                              | Check if PYTEST_RUNNING env var is set |

### Centralized Turn Initialization

`init_turn_metadata(metadata, *, planner_snapshot_fn=None)`:

Consolidates all per-turn metadata resets into a single function called at the
start of both `run_turn()` and `run_turn_streaming()`.

Initializes:

- LLM budget tracking (`LLM_CALLS_THIS_TURN=0`, `LLM_CALL_SITES=[]`, etc.)
- Node execution journal (`NODE_RUN_JOURNAL=[]`, `VISITED_NODES=set()`, etc.)
- Response writer guard (`RESPONSE_CLAIMED_BY=None`)
- Turn validation (`TURN_CANARY=uuid`, `MUTATION_COUNTER=0`)
- Response provenance (`RESPONSE_SOURCE_NODE=None`, etc.)
- Cache events (`CACHE_EVENTS=[]`)

Clears (via `pop()`):

- `TRIPWIRE_TRIGGERED`
- `DUPLICATION_CLASS`

Returns: `turn_canary` UUID for state mutation validation.

`validate_turn_metadata(metadata) → List[str]`:

Validates that all required per-turn keys exist with correct types.
Returns list of error messages (empty if valid).

### Metadata Helpers Tests

Tests in `tests/langgraph/test_meta_keys.py`:

| Test Class                 | Tests | Coverage                                       |
| -------------------------- | ----- | ---------------------------------------------- |
| `TestMetaKeysUniqueness`   | 4     | Key uniqueness, subset validation, type checks |
| `TestInitTurnMetadata`     | 12    | All per-turn key initialization                |
| `TestValidateTurnMetadata` | 3     | Validation of required keys and types          |
| `TestMetaHelpers`          | 9     | meta_get/set/append/increment functionality    |
| `TestMetaSetOnce`          | 4     | Set-once semantics with test-mode detection    |
| `TestIsTestMode`           | 2     | PYTEST_RUNNING env var detection               |

**Acceptance Criteria**:

- [x] `backend/app/planner/` package created
- [x] `meta_keys.py` with all frequently used constants
- [x] `meta.py` with helper functions
- [x] `ALL_META_KEYS` tuple for uniqueness validation
- [x] `init_turn_metadata()` consolidates per-turn resets
- [x] `plan_graph.py` imports and uses constants
- [x] `can_call_llm()` updated to use constants
- [x] `record_node_run()` updated to use constants
- [x] `claim_response_writer()` updated to use constants
- [x] Tests verify key uniqueness and initialization shapes

---

## Test-Mode Invariant Hard-Fails (V27)

PR4: Converts logged anomalies into immediate test failures when `PYTEST_RUNNING=1`
is set. This makes trace replay results trustworthy by failing fast on invariant
violations instead of silently logging and continuing.

### Test-Mode Detection

`conftest.py` sets `PYTEST_RUNNING=1` before any test imports:

```python
# backend/tests/conftest.py
import os
os.environ["PYTEST_RUNNING"] = "1"
```

Detection helper in `backend/app/planner/test_mode.py`:

| Function               | Signature                 | Purpose                                |
| ---------------------- | ------------------------- | -------------------------------------- |
| `is_test_mode()`       | `() → bool`               | Check if PYTEST_RUNNING env var is set |
| `raise_if_test_mode()` | `(message: str) → None`   | Raise AssertionError if in test mode   |
| `assert_invariant()`   | `(condition, message, *)` | Assert in tests, log in prod           |

### Tripwire Hard-Fails

The following tripwires now raise `AssertionError` in test mode:

| Tripwire               | Condition                                 | Test-Mode Behavior      |
| ---------------------- | ----------------------------------------- | ----------------------- |
| `MAX_STEPS_TRIPWIRE`   | `step_count > MAX_STEPS_PER_TURN`         | Raises `AssertionError` |
| `REPEAT_NODE_TRIPWIRE` | Node in `visited_nodes` (non-allowlisted) | Raises `AssertionError` |

Production behavior unchanged: logs error and continues.

### Response Writer Guard

Single-response-writer invariant in `claim_response_writer()`:

| Scenario              | Test-Mode Behavior                            | Prod Behavior         |
| --------------------- | --------------------------------------------- | --------------------- |
| First claim           | Returns `True`, sets `response_claimed_by`    | Same                  |
| Same node re-claim    | Returns `True`                                | Same                  |
| Different node claims | Raises `AssertionError("DOUBLE_WRITER: ...")` | Logs, returns `False` |

### Gate Invariants

Invariant: `ready_to_generate=True` implies no routing to `required_fields` via
`MISSING_CORE` gate.

Enforced in test via assertion in `test_gate_routing.py`.

### Invariant Failure Tests

Tests in `tests/langgraph/test_invariant_failures.py`:

| Test Class                  | Tests | Coverage                                   |
| --------------------------- | ----- | ------------------------------------------ |
| `TestTestModeDetection`     | 2     | PYTEST_RUNNING detection                   |
| `TestRaiseIfTestMode`       | 1     | raise_if_test_mode helper                  |
| `TestDoubleWriterInvariant` | 3     | Double-claim raises, same-node allowed     |
| `TestTripwireInvariants`    | 2     | Repeat node raises, allowlisted nodes pass |
| `TestGateInvariants`        | 1     | ready_to_generate implies no MISSING_CORE  |

**Acceptance Criteria**:

- [x] `PYTEST_RUNNING=1` set in `conftest.py`
- [x] `is_test_mode()` helper in `test_mode.py`
- [x] `raise_if_test_mode()` helper for conditional raising
- [x] `claim_response_writer()` raises on double-claim in tests
- [x] `record_node_run()` raises on repeat-node tripwire in tests
- [x] `record_node_run()` raises on max-steps tripwire in tests
- [x] Production behavior unchanged (log+skip)
- [x] Test cases for all invariant violations

---

## Cache Concurrency Safety (V28)

PR3: Thread-safe cache accessors to prevent race conditions in FastAPI async/threaded
environments. Introduces per-cache locks and safe counter updates.

### Cache Access Module

New module: `backend/app/planner/cache_access.py`

Provides thread-safe wrappers around cache operations without relocating the cache
instances (which remain in `plan_graph.py`).

```python
from app.planner.cache_access import (
    init_cache_handles,  # Call once at startup
    cache_get,           # Thread-safe get
    cache_set,           # Thread-safe set
    cache_pop,           # Thread-safe pop
    cache_delete,        # Thread-safe delete
    cache_clear,         # Thread-safe clear
    update_counters_safe,        # Thread-safe counter increment
    update_nested_counters_safe, # Thread-safe nested counter increment
)
```

### Thread-Safe Accessors

Each cache gets a `CacheHandle` wrapping the TTLCache with a `threading.Lock`:

| Function           | Signature                                        | Purpose                           |
| ------------------ | ------------------------------------------------ | --------------------------------- |
| `cache_get()`      | `(name, key, *, record_event_fn) → Any`          | Get with lock, optional event     |
| `cache_set()`      | `(name, key, value, *, record_event_fn) → None`  | Set with lock                     |
| `cache_pop()`      | `(name, key, *, reason, record_event_fn) → Any`  | Pop with lock and eviction reason |
| `cache_delete()`   | `(name, key, *, reason, record_event_fn) → bool` | Delete with lock                  |
| `cache_clear()`    | `(name) → None`                                  | Clear cache                       |
| `cache_len()`      | `(name) → int`                                   | Get cache size                    |
| `cache_contains()` | `(name, key) → bool`                             | Check key existence               |

Supported cache names: `"follow_up"`, `"router"`, `"required_fields"`, `"extractor"`, `"strategy"`, `"tile"`

### Counter Safety

Global `_cache_counters_lock` protects counter updates:

| Function                        | Purpose                                      |
| ------------------------------- | -------------------------------------------- |
| `update_counters_safe()`        | Thread-safe increment of flat counter dict   |
| `update_nested_counters_safe()` | Thread-safe increment of nested counter dict |

### Cache Concurrency Tests

Tests in `tests/langgraph/test_cache_concurrency.py`:

| Test Class            | Tests | Coverage                                         |
| --------------------- | ----- | ------------------------------------------------ |
| `TestCacheHandleInit` | 4     | Handle creation, lock types, get_cache_handle    |
| `TestCacheOperations` | 10    | get/set/pop/delete/len/contains/clear operations |
| `TestConcurrency`     | 2     | Multi-thread get/set loops, mixed operations     |
| `TestCounterSafety`   | 2     | Concurrent flat and nested counter updates       |
| `TestEventRecording`  | 4     | record_event_fn callback on hit/miss/set/evict   |

**Acceptance Criteria**:

- [x] `cache_access.py` module created with lock wrappers
- [x] `CacheHandle` dataclass with lock per cache
- [x] `init_cache_handles()` for startup registration
- [x] `cache_get/set/pop/delete/clear/len/contains` accessors
- [x] `update_counters_safe()` for thread-safe counter updates
- [x] `update_nested_counters_safe()` for nested counters
- [x] Concurrent get/set tests with no exceptions
- [x] Counter consistency tests under concurrent load

---

## Import Surface Freeze (V29)

**PR1: Import surface freeze** - Defines a stable public API surface for the planner package, enabling internal refactoring without breaking external consumers.

### Planner Facade Module

Location: `backend/app/planner/__init__.py`

The facade module exports the stable public API. External code should import from here rather than directly from `plan_graph.py`.

```python
# Correct usage:
from app.planner import run_turn, run_turn_streaming
from app.planner import GateEvaluator, GateResult, GatePrecedence

# Banned (enforced by CI test):
from app.plan_graph import run_turn  # ❌
```

### Exported Symbols

| Category         | Symbols                                                                                        |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| **Entry Points** | `run_turn`, `run_turn_streaming`                                                               |
| **Gate Types**   | `GateEvaluator`, `GatePrecedence`, `GateResult`                                                |
| **State Types**  | `GraphState`, `TripInputs`                                                                     |
| **Debug**        | `get_planner_debug_info`, `get_planner_snapshot`                                               |
| **Cache Utils**  | `clear_all_caches`, `clear_all_checkpoints`, etc.                                              |
| **Cache Stats**  | `checkpoint_stats`, `response_cache_stats`, `get_graph_stats`                                  |
| **Build Meta**   | `CACHE_SCHEMA_VERSION`, `PLANNER_BUILD_ID`, `PROMPT_BUNDLE_HASH`                               |
| **Utilities**    | `condense_long_message`, `prewarm_prompts`, `validate_template_coverage`                       |
| **Metadata**     | `meta_get`, `meta_set`, `meta_set_once`, `meta_append`, `meta_increment`, `init_turn_metadata` |
| **Test Mode**    | `is_test_mode`, `raise_if_test_mode`                                                           |
| **Cache Access** | `cache_get`, `cache_set`, `cache_pop`, `cache_delete`, etc.                                    |

Full export list: ~50 symbols in `__all__`

### Import Contract Enforcement

**Banned patterns** (checked by `test_import_contract.py`):

```python
BANNED_IMPORT_PATTERNS = [
    r"from\s+app\.plan_graph\s+import",
    r"from\s+\.\.?plan_graph\s+import",
    r"import\s+app\.plan_graph",
]
```

**Allowlist** (files that MAY import directly):

| Path                   | Reason                                   |
| ---------------------- | ---------------------------------------- |
| `backend/app/planner/` | Facade package itself                    |
| `backend/tests/`       | Test files (temporary, for trace replay) |
| `tests/`               | Root-level tests                         |

### Migration Path

1. **Phase 1** (complete): Create facade with exports from `plan_graph.py`
2. **Phase 2** (complete): Migrate `main.py` to use facade imports
3. **Phase 3** (future): Add allowlist entries for trace replay tests
4. **Phase 4** (future): Remove allowlist, all external code uses facade

### Import Contract Tests

Tests in `backend/tests/test_import_contract.py`:

| Test Class                 | Tests | Coverage                             |
| -------------------------- | ----- | ------------------------------------ |
| `TestImportContract`       | 2     | Grep-based ban on direct imports     |
| `TestPlannerFacadeExports` | 12    | Smoke tests for each export category |

**Key tests**:

- `test_no_direct_plan_graph_imports_outside_allowlist`: Scans all `.py` files in `app/` for banned patterns
- `test_main_py_uses_planner_facade`: Specific check that `main.py` imports from facade
- `test_facade_exports_*`: Verify each symbol is accessible from `app.planner`
- `test_facade_all_exports`: Verify `__all__` contains expected exports

**Acceptance Criteria**:

- [x] `planner/__init__.py` exports all public symbols
- [x] `__all__` list with all exported symbols
- [x] Grep-based test to ban direct `plan_graph.py` imports
- [x] `main.py` migrated to use facade imports
- [x] Smoke tests for each export category
- [x] Allowlist for planner package and tests

---

## Stable Hashing Utilities (V30)

**PR5: Stable hashing utilities** - Replaces Python's built-in `hash()` with stable alternatives that produce consistent results across processes.

### Hashing Module

Location: `backend/app/planner/hashing.py`

**Problem**: Python's `hash()` uses `PYTHONHASHSEED` randomization by default, making cache keys non-reproducible across test runs and causing flaky tests.

**Solution**: Use blake2s for fast, stable hashing with canonical JSON serialization.

### Stable Hash Functions

| Function              | Purpose                                       | Example                                       |
| --------------------- | --------------------------------------------- | --------------------------------------------- |
| `stable_hash()`       | String hash of any value (default 16 chars)   | `stable_hash("hello")` → `"9c22ff5f21f0b81b"` |
| `stable_hash_short()` | Short 8-char hash for compact display         | `stable_hash_short(data)` → `"4f4e3e0b"`      |
| `stable_hash_int()`   | Integer hash for cohort assignment            | `stable_hash_int(id, modulo=100)` → `42`      |
| `stable_hash_index()` | Index into a list for deterministic selection | `stable_hash_index(msg, len(items))` → `3`    |

**Key properties**:

- Uses blake2s (faster than sha256 for short inputs)
- Canonical JSON serialization with sorted keys
- Stable across Python processes and restarts
- Thread-safe (no shared state)

### Canonicalization Helpers

| Function                        | Purpose                                    |
| ------------------------------- | ------------------------------------------ |
| `canonicalize_destinations()`   | Sort/normalize destination lists           |
| `canonicalize_missing_fields()` | Sort/normalize field name lists            |
| `canonicalize_dict()`           | Canonical JSON with sorted keys            |
| `make_cache_key()`              | Build stable cache key from multiple parts |

**Example**:

```python
# Old (unstable):
key = f"router::{hash(tuple(destinations))}"

# New (stable):
key = make_cache_key("router", "v6", destinations)
# Result: "router::v6::london|paris"
```

### Hash Ban Enforcement

The test file `test_hash_ban.py` enforces the ban on `hash()` in planner code:

**Banned pattern**: `(?<![_a-zA-Z])hash\(` (matches `hash(` not preceded by identifier chars)

**Scanned files**:

- `plan_graph.py`
- `planner/*.py` (except `hashing.py`)
- `pattern_matching.py`
- `graph_plan_utils.py`

**Allowlist**: The `_hash_value()` function is allowlisted as a fallback for non-JSON-serializable types.

### Migrated Usages

| Location              | Old Pattern                      | New Pattern                                  |
| --------------------- | -------------------------------- | -------------------------------------------- |
| A/B cohort assignment | `hash(session_id) % 100`         | `stable_hash_int(session_id, modulo=100)`    |
| Warm opener selection | `hash(msg) % len(_WARM_OPENERS)` | `stable_hash_index(msg, len(_WARM_OPENERS))` |
| Warm closer selection | `hash(msg) % len(_WARM_CLOSERS)` | `stable_hash_index(msg, len(_WARM_CLOSERS))` |

### Stable Hashing Tests

Tests in `backend/tests/langgraph/test_stable_hashing.py`:

| Test Class                      | Tests | Coverage                                    |
| ------------------------------- | ----- | ------------------------------------------- |
| `TestStableHash`                | 12    | String/dict/list hashing, length, stability |
| `TestStableHashShort`           | 3     | Short hash format                           |
| `TestStableHashInt`             | 6     | Integer hash, modulo, distribution          |
| `TestStableHashIndex`           | 4     | List index selection                        |
| `TestCanonicalizeDestinations`  | 7     | Destination normalization                   |
| `TestCanonicalizeMissingFields` | 3     | Field normalization                         |
| `TestCanonicalizeDict`          | 4     | Dict to JSON canonicalization               |
| `TestMakeCacheKey`              | 5     | Cache key building                          |
| `TestConcurrency`               | 2     | Thread safety                               |
| `TestRealWorldPatterns`         | 3     | End-to-end usage patterns                   |

Tests in `backend/tests/test_hash_ban.py`:

| Test Class      | Tests | Coverage                                 |
| --------------- | ----- | ---------------------------------------- |
| `TestHashBan`   | 4     | Grep-based ban on hash() in planner code |
| `TestAllowlist` | 1     | Verify allowlist entries still exist     |

**Acceptance Criteria**:

- [x] `hashing.py` module created with stable hash functions
- [x] `stable_hash()` using blake2s
- [x] `stable_hash_int()` for cohort assignment
- [x] `stable_hash_index()` for list indexing
- [x] Canonicalization helpers for destinations/fields/dicts
- [x] `make_cache_key()` for building stable cache keys
- [x] Grep-based test banning `hash(` in planner code
- [x] Migrated hash() usages in plan_graph.py
- [x] Thread safety tests for concurrent usage

---

## Telemetry Spine (V31)

**PR-T: Telemetry instrumentation** - Implements live trace capture for production debugging and latency analysis, following the three-tier plan (PR-T1, PR-T2, PR-T3).

### Telemetry Module

Location: `backend/app/planner/telemetry.py`

**Purpose**: Structured JSON logging with correlation IDs, sampling, and redaction for production-safe observability.

**Key features**:

- W3C traceparent header parsing for distributed tracing correlation
- Per-request sampling decisions (standard vs verbose)
- Automatic force-verbose on anomalies (tripwire, duplication, exception)
- Console output matching `[PLAN_GRAPH DEBUG]` visibility pattern
- Prompt/input redaction for PII protection

### TraceEnvelope

A `@dataclass` that carries trace context through the entire request lifecycle:

```python
@dataclass
class TraceEnvelope:
    trace_id: str          # 32-char hex from traceparent or generated
    span_id: str           # 16-char hex, generated per request
    parent_span_id: str    # From traceparent or empty
    thread_id: str         # Conversation thread ID
    session_id: str        # Session ID from cookie
    request_id: str        # Unique request ID
    trace_enabled: bool    # Whether to emit events at all
    trace_verbose: bool    # Whether to include full payloads
    redaction_mode: str    # "hash_only" | "verbose"
    created_at_ns: int     # Request start time in nanoseconds
```

**Header precedence**:

1. `traceparent` header (W3C format: `00-{trace_id}-{span_id}-{flags}`)
2. `X-Request-ID` header
3. Generate UUID-based trace_id

### Event Types

| Event                   | Stage  | Verbose Data                              |
| ----------------------- | ------ | ----------------------------------------- |
| `planner_request_start` | PR-T1  | message_length, redacted_preview          |
| `planner_request_end`   | PR-T1  | latency_ms, cache_summary                 |
| `gate_eval_end`         | PR-T2  | gate_name, fired, suppressed_by           |
| `node_start`            | PR-T2  | node_name, step_count, router_decision    |
| `node_end`              | PR-T2  | node_name, duration_ms, produced_response |
| `llm_call_end`          | PR-T3  | model, prompt_tokens, completion_tokens   |
| `cache_event`           | PR-T3  | cache_name, hit/miss, key_preview         |
| `anomaly_bundle`        | Always | anomaly_type, full context                |

### Sampling & Redaction

**Sampling decision** (computed once at request start):

- `trace_enabled` = `random() < TRACE_SAMPLE_RATE` (default 1.0 = 100%)
- `trace_verbose` = `trace_enabled && random() < TRACE_VERBOSE_SAMPLE_RATE` (default 0.0 = 0%)

**Force verbose trigger**:

```python
def force_verbose_on_anomaly(envelope: TraceEnvelope) -> None:
    """Force verbose mode when anomaly detected."""
    envelope.trace_enabled = True
    envelope.trace_verbose = True
```

Called when:

- `TRIPWIRE_TRIGGERED` set (max_steps or repeat_node)
- `DUPLICATION_CLASS` set (same_node_twice or double_writer)
- Exception caught in `run_turn`

**Redaction modes**:

- `hash_only`: Replace text with blake2s hash prefix (default)
- `verbose`: Include full text (for debugging only)

```python
def redact_text(text: str, mode: str = "hash_only") -> str:
    if mode == "verbose":
        return text
    return f"[redacted:{stable_hash_short(text)}]"
```

### Console Output

Events print to console when `settings.trace_console_output` is True (default):

```
[TRACE] planner_request_start trace_id=abc123 thread_id=xyz session_id=def
[TRACE] node_start node=extractor step=1
[TRACE] node_end node=extractor duration_ms=42
[TRACE:VERBOSE] llm_call_end model=gpt-4o prompt_tokens=1200
[TRACE:ANOMALY] anomaly_bundle type=tripwire triggered=max_steps
```

Prefix rules:

- `[TRACE]` - Standard events (always when trace_enabled)
- `[TRACE:VERBOSE]` - Verbose-only events (when trace_verbose)
- `[TRACE:ANOMALY]` - Anomaly events (always, regardless of sampling)

### Integration Points

**main.py** (request boundary):

```python
# Create envelope after session_id is available
trace_envelope = create_envelope(
    request=request,
    thread_id=thread_id,
    session_id=session_id,
    redaction_mode=settings.trace_redaction_mode,
)
session_state["metadata"][TRACE_ENVELOPE] = trace_envelope.to_dict()

# Emit request start
request_start_ns = emit_request_start(trace_envelope, req.message)

# After run_turn...
emit_request_end(trace_envelope, request_start_ns, cache_summary)
```

**plan_graph.py** (node/gate boundary):

```python
# At node entry
_, start_ns = _debug_node_entry("extractor", state)

# At node exit
_debug_node_exit("extractor", state, start_ns, produced_response=True)
```

The `_debug_node_entry` function calls `record_node_run` which emits `node_start`.
The `_debug_node_exit` function calls `mark_node_end` which emits `node_end`.

### Configuration Settings

Added to `backend/app/config.py`:

| Setting                     | Type  | Default     | Description                           |
| --------------------------- | ----- | ----------- | ------------------------------------- |
| `trace_sample_rate`         | float | 1.0         | Fraction of requests to trace         |
| `trace_verbose_sample_rate` | float | 0.0         | Fraction of traces with full payloads |
| `trace_redaction_mode`      | str   | "hash_only" | How to redact sensitive text          |
| `trace_console_output`      | bool  | True        | Print trace events to console         |

### Metadata Key

Added to `backend/app/planner/meta_keys.py`:

```python
TRACE_ENVELOPE = "trace_envelope"  # Cross-turn telemetry context
```

### Telemetry Tests

Tests to be added in `backend/tests/langgraph/test_telemetry.py`:

| Test Class          | Tests | Coverage                                |
| ------------------- | ----- | --------------------------------------- |
| `TestTraceEnvelope` | 5     | Creation, serialization, header parsing |
| `TestEventEmission` | 8     | All event types emit correct JSON       |
| `TestSampling`      | 4     | Sample rate logic, force verbose        |
| `TestRedaction`     | 4     | hash_only vs verbose mode               |
| `TestConsoleOutput` | 3     | Console print when enabled/disabled     |
| `TestAnomalyBundle` | 3     | Anomaly detection triggers verbose      |

**Acceptance Criteria**:

- [x] `telemetry.py` module created with TraceEnvelope dataclass
- [x] W3C traceparent header parsing
- [x] Sampling decisions computed once per request
- [x] Force verbose on anomaly (tripwire, duplication, exception)
- [x] `redact_text()` with hash_only and verbose modes
- [x] Console output with `[TRACE]` prefix
- [x] Integration in `main.py` for request boundary events
- [x] Integration in `plan_graph.py` for node events
- [x] Configuration settings in `config.py`
- [x] `TRACE_ENVELOPE` added to `meta_keys.py`
- [ ] Test coverage for telemetry module

---

## Date Compatibility Consolidation (V32)

This section documents the consolidation of date compatibility checking into a single source of truth.

### Problem

When user answered "Tomorrow" to a dates question, the system incorrectly regenerated the
hiking pitch with destination suggestions instead of acknowledging the date and transitioning
to ask about the next missing field (origin). Root cause: **three separate implementations**
of date compatibility checking that had drifted out of sync.

| Location                          | Function                           | Missing "tomorrow"                   |
| --------------------------------- | ---------------------------------- | ------------------------------------ |
| `pattern_matching.py`             | `DATES_COMPATIBILITY_PATTERN`      | ❌ Yes                               |
| `plan_graph.py` → `GateEvaluator` | `text_is_compatible_with_target()` | ❌ Yes                               |
| `plan_graph.py`                   | `_is_date_like_text()`             | ✅ Had it via `_RELATIVE_DATE_WORDS` |

### Solution: Single Source of Truth

**New Architecture:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                     pattern_matching.py                              │
├─────────────────────────────────────────────────────────────────────┤
│  RELATIVE_DATE_WORDS_SIMPLE = {"today", "tomorrow", "tonight", "weekend"}    │
│  RELATIVE_DATE_WORDS_CONTEXTUAL = {"week", "month", "year", ...}    │
│  RELATIVE_DATE_WORDS_ALL = SIMPLE | CONTEXTUAL | {"next", "this"}   │
│                                                                      │
│  DATES_COMPATIBILITY_PATTERN = re.compile(                          │
│      r"(?:"                                                          │
│      r"\b(?:today|tomorrow|tonight|weekend)\b|"  # Standalone       │
│      r"\b(?:january|february|...)\b|"            # Month names      │
│      r"\bnext\s+(?:week|month|...)\b|"           # Relative phrases │
│      r"\b(?:spring|summer|fall|...)\b|"          # Seasons          │
│      r"\b(?:flexible|whenever|anytime)\b"        # Flexibility      │
│      r")"                                                            │
│  )                                                                   │
│                                                                      │
│  def is_text_date_compatible(text: str) -> bool:  # ← SINGLE SOURCE │
│      return DATES_COMPATIBILITY_PATTERN.search(text) or ...         │
│                                                                      │
│  def text_is_compatible_with_target(text, target) -> bool:          │
│      if target in ("dates", "start_date"):                          │
│          return is_text_date_compatible(text)  # ← DELEGATES        │
└─────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ imports
                              │
┌─────────────────────────────────────────────────────────────────────┐
│                        plan_graph.py                                 │
├─────────────────────────────────────────────────────────────────────┤
│  from app.pattern_matching import (                                  │
│      is_text_date_compatible,                                        │
│      RELATIVE_DATE_WORDS_ALL,                                        │
│  )                                                                   │
│                                                                      │
│  _RELATIVE_DATE_WORDS = RELATIVE_DATE_WORDS_ALL  # Alias for compat │
│                                                                      │
│  def _is_date_like_text(text: str) -> bool:                         │
│      return is_text_date_compatible(text)  # ← DELEGATES            │
│                                                                      │
│  class GateEvaluator:                                                │
│      def text_is_compatible_with_target(cls, text, target):         │
│          if target in ("dates", "start_date"):                      │
│              return is_text_date_compatible(text)  # ← DELEGATES    │
└─────────────────────────────────────────────────────────────────────┘
```

### Files Changed

| File                                                 | Change                                          |
| ---------------------------------------------------- | ----------------------------------------------- |
| `backend/app/pattern_matching.py`                    | Added constants, `is_text_date_compatible()`    |
| `backend/app/plan_graph.py`                          | Refactored to delegate to consolidated function |
| `backend/tests/langgraph/test_text_compatibility.py` | Added 10+ test cases for relative date words    |

### Patterns Now Recognized

| Pattern              | Examples                          | Status  |
| -------------------- | --------------------------------- | ------- |
| Standalone relatives | "tomorrow", "today", "tonight"    | **NEW** |
| Weekend              | "weekend"                         | **NEW** |
| Months               | "November", "next June"           | ✅      |
| Seasons              | "spring", "summer", "fall"        | ✅      |
| Relative phrases     | "next month", "this week"         | ✅      |
| Date formats         | "12/25/2024", "2024-12-25"        | ✅      |
| Flexibility          | "flexible", "whenever", "anytime" | **NEW** |
| Preposition + month  | "in December", "by March"         | ✅      |

### Test Coverage

New test class `TestIsTextDateCompatible`:

```python
@pytest.mark.parametrize("text,expected", [
    ("tomorrow", True),
    ("Tomorrow", True),   # Case insensitive
    ("TOMORROW", True),   # All caps
    ("today", True),
    ("tonight", True),
    ("weekend", True),
    ("Paris", False),     # Not a date
    ("Swiss Alps", False),
])
def test_relative_date_words(self, text, expected):
    result = is_text_date_compatible(text)
    assert result == expected
```

### Ownership Suppression Now Works

With this fix, when `question_target="dates"` and user says "Tomorrow":

```
[PLAN_GRAPH DEBUG] strategy_pre_core_value_with_dest skipped: ownership suppression
                   question_target=dates
                   user_text_preview=Tomorrow
                   reason=input compatible with question_target
```

The answer-collection path now owns the turn, and stage 0 does not re-fire.

---

## Stale Question Target Fix (V33)

> **Added**: December 26, 2025
> **Location**: `backend/app/plan_graph.py` - `_specialist()` function, `required_fields` block (~line 18110)

### Problem

When a user answered a `question_target` (e.g., origin), the stale `question_target` from the previous turn was not cleared. This caused the `required_fields` specialist to ask about an already-populated field.

**Example bug flow:**

1. System asks "Where's home base for this trip?" with `question_target=origin`
2. User clicks suggestion "New York"
3. Extractor correctly sets `origin="New York"` ✅
4. Gate routes to `required_fields_node` with HIGH_CONFIDENCE
5. **Bug:** `required_fields` uses stale `question_target=origin` and asks "Where will you be traveling from?" even though origin is already set

### Root Cause

The `required_fields` specialist at line ~18110 prioritized the stale `state.question_target` from the previous turn without validating whether the referenced field was actually still missing:

```python
# OLD CODE (buggy)
question_target = state.question_target or state.metadata.get("last_question_field")
if not question_target:
    # Only computed from missing fields if question_target was empty
    ...
```

### Solution: Validate Before Use

Added validation to check if the `question_target` field is already populated before using it:

```python
# NEW CODE (fixed)
# FIRST: Get candidate from state (may be stale from previous turn)
question_target_candidate = state.question_target or state.metadata.get("last_question_field")

# THEN: Validate that the candidate field is actually still missing
if question_target_candidate:
    field_values = {
        "destinations": ti.destinations,
        "origin": ti.origin,
        "dates": ti.start_date,
        "travelers": ti.adults,
    }
    # Check if the candidate field is already populated
    if field_values.get(question_target_candidate):
        _debug(
            "🔄 STALE_TARGET: question_target was set but field is populated, clearing",
            stale_target=question_target_candidate,
            field_value=field_values.get(question_target_candidate),
        )
        # Clear stale target from state and metadata
        state.question_target = None
        state.metadata.pop("last_question_field", None)
        question_target_candidate = None

# If no valid candidate, compute from actual missing fields
question_target = question_target_candidate
if not question_target:
    # ... existing logic to find next missing field
```

### Debug Output

When the fix activates:

```
[PLAN_GRAPH DEBUG] 🔄 STALE_TARGET: question_target was set but field is populated, clearing
                   stale_target=origin
                   field_value=New York
```

### Files Changed

| File                        | Change                                                                            |
| --------------------------- | --------------------------------------------------------------------------------- |
| `backend/app/plan_graph.py` | Added stale `question_target` validation in `_specialist()` required_fields block |

### Invariant Enforced

**Stale Question Target Guard:** Before using `state.question_target` in `required_fields`, validate that the referenced field is actually still missing. If populated, clear the stale target and recompute from actual missing fields.
