# LangGraph Plan Architecture Analysis

> **Generated**: June 2025
> **File**: `backend/app/plan_graph.py` (~12,025 lines)
> **Prompts**: `backend/app/prompts/` (24 files)

---

## 1. Node Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                              LangGraph StateGraph                                    │
│                                                                                      │
│  ┌─────────┐                                                                         │
│  │  START  │                                                                         │
│  └────┬────┘                                                                         │
│       │                                                                              │
│       ▼                                                                              │
│  ┌────────────────┐                                                                  │
│  │  lqa_prepass   │ ──── Zero-LLM: Parse simple field answers                        │
│  │     🚀        │      (Amsterdam, 2 adults, next month)                           │
│  └───────┬────────┘                                                                  │
│          │ [route_after_lqa_prepass]                                                │
│    ┌─────┴─────┐                                                                    │
│    │           │                                                                    │
│    ▼           ▼                                                                    │
│ ┌──────────────────────┐  ┌─────────────┐                                           │
│ │  normalize_inputs    │  │  extractor  │ ──── LLM: small                           │
│ │       📐            │  │   🔍        │      (extractor.txt / extractor_light.txt) │
│ └──────────┬───────────┘  └──────┬──────┘                                           │
│            │                     │ [route_after_extractor]                          │
│            │               ┌─────┴─────┐                                            │
│            │               │           │                                            │
│            │◄──────────────┘           ▼                                            │
│            │                    ┌────────────────────────┐                          │
│            │                    │ short_circuit_responder│ ◄─ Pure short-circuits   │
│            │                    │          ⚡            │    (greeting, off_topic) │
│            │                    └───────────┬────────────┘                          │
│            ▼ [route_after_normalize]        │                                       │
│    ┌───────┴───────────┐                    │                                       │
│    │                   │                    │                                       │
│    ▼                   ▼                    │                                       │
│ ┌────────┐      ┌──────────────────┐        │                                       │
│ │ router │      │ required_fields  │        │ ◄─ Deterministic gates bypass router  │
│ │   🧭   │      │   _node 📋       │        │                                       │
│ └────┬───┘      └────────┬─────────┘        │                                       │
│      │                   │                  │                                       │
│      ▼ [route_after_router]                 │                                       │
│ ┌────┴─────────────────────────────┐        │                                       │
│ │                                  │        │                                       │
│ ▼          ▼         ▼         ▼   ▼        │                                       │
│ ┌────────┐ ┌───────┐ ┌───────┐ ┌───────┐    │                                       │
│ │flights │ │hotels │ │trans- │ │activ- │    │                                       │
│ │_node ✈️│ │_node🏨│ │port🚗 │ │ities🎭│    │                                       │
│ └────┬───┘ └───┬───┘ └───┬───┘ └───┬───┘    │                                       │
│      │         │         │         │        │                                       │
│      └─────────┴─────────┴─────────┘        │                                       │
│                    │                        │                                       │
│ ┌────────────┐     │     ┌────────────┐     │                                       │
│ │ strategy   │     │     │ correction │     │                                       │
│ │  _node 🎯  │     │     │  _node 🔧  │     │                                       │
│ └─────┬──────┘     │     └─────┬──────┘     │                                       │
│       │            │           │            │                                       │
│       └────────────┼───────────┘            │                                       │
│                    │                        │                                       │
│                    ▼                        │                                       │
│           ┌──────────────────┐              │                                       │
│           │ validate_and_   │              │                                       │
│           │     merge ✅     │              │                                       │
│           └────────┬─────────┘              │                                       │
│                    │                        │                                       │
│                    ▼                        │                                       │
│           ┌──────────────────┐              │                                       │
│           │ branch_postproc │              │                                       │
│           │      🌿         │              │                                       │
│           └────────┬─────────┘              │                                       │
│                    │                        │                                       │
│                    ▼ [route_after_branch]   │                                       │
│            ┌───────┴───────┐                │                                       │
│            ▼               ▼                │                                       │
│     ┌─────────────┐        │                │                                       │
│     │ tile_search │        │                │                                       │
│     │     🗺️      │        │                │                                       │
│     └──────┬──────┘        │                │                                       │
│            │               │                │                                       │
│            └───────┬───────┘                │                                       │
│                    │                        │                                       │
│                    ▼                        │                                       │
│           ┌──────────────────┐              │                                       │
│           │    summarize    │◄─────────────┘                                       │
│           │       📝        │                                                       │
│           └────────┬─────────┘                                                      │
│                    │                                                                │
│                    ▼                                                                │
│           ┌──────────────────┐                                                      │
│           │ response_polish │                                                      │
│           │       ✨        │                                                       │
│           └────────┬─────────┘                                                      │
│                    │                                                                │
│                    ▼                                                                │
│               ┌─────────┐                                                           │
│               │   END   │                                                           │
│               └─────────┘                                                           │
└──────────────────────────────────────────────────────────────────────────────────────┘

Legend:
  🚀 lqa_prepass     - Zero-LLM pre-pass for simple answers
  🔍 extractor       - LLM-based extraction (fallback after LQA bail)
  📐 normalize       - Normalization & delta merge (sync)
  ⚡ short_circuit   - Template responses (zero-LLM)
  🧭 router          - Intent classification (LLM)
  📋 required_fields - Core field collection (template-first, LLM fallback)
  ✈️🏨🚗🎭 specialists - Domain-specific preferences (LLM)
  🎯 strategy        - Deep planning: hiking/diving/skiing/boating/cycling (LLM)
  🔧 correction      - Infeasibility correction (LLM)
  ✅ validate        - Ready-to-generate computation (sync)
  🌿 branch_postproc - Branch splitting/normalization (sync)
  🗺️ tile_search     - Tile service integration (sync)
  📝 summarize       - Fallback question generation (sync)
  ✨ response_polish - Tone polishing (deterministic-first, LLM fallback)
```

---

## 2. Node → Prompt Mapping Table

| Node                           | Prompt File                      | Purpose/Role                                   | Wired? | Est. Input Tokens | Inputs Enabled                                            | Inputs Blocked  | LLM Model | Max Output |
| ------------------------------ | -------------------------------- | ---------------------------------------------- | ------ | ----------------- | --------------------------------------------------------- | --------------- | --------- | ---------- |
| `lqa_prepass`                  | _(no prompt)_                    | Zero-LLM pre-pass: parse simple field answers  | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `extractor`                    | `extractor.txt`                  | Extract ALL trip data (full/dense mode)        | ✅ Yes | ~1,684            | `{today}`, `{trip_inputs}`, `{user_text}`                 | -               | small     | 400        |
| `extractor`                    | `extractor_light.txt`            | Extract CORE fields only (light mode)          | ✅ Yes | ~548              | `{today}`, `{user_text}`                                  | `{trip_inputs}` | small     | 128        |
| `normalize_inputs`             | _(no prompt)_                    | Apply normalization, merge deltas              | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `short_circuit_responder`      | _(no prompt)_                    | Template responses for greetings/confirmations | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `router`                       | `router.txt`                     | Intent classification (8 intents)              | ✅ Yes | ~914              | `{trip_inputs}`, `{parsed_inputs}`, `{user_intent_hint}`  | -               | small     | 256        |
| `required_fields_node`         | `required_fields.txt`            | Collect missing trip details                   | ✅ Yes | ~785              | `{trip_inputs}`, `{tone_instruction}`, `{missing_fields}` | -               | small     | 256        |
| `required_fields_node`         | `required_fields_confirm.txt`    | Confirm typos/ambiguities                      | ✅ Yes | ~500              | `{trip_inputs}`, `{typo_suggestions}`                     | -               | small     | 256        |
| `required_fields_node`         | `required_fields_templates.json` | Template questions (LLM bypass)                | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `_invoke_missing_fields_guard` | `missing_fields_guard.txt`       | Guard when specialists lack core fields        | ✅ Yes | ~310              | `{missing_fields}`, `{trip_inputs}`, `{tone_instruction}` | -               | small     | 100        |
| `flights_node`                 | `flights.txt`                    | Flight preferences (cabin, direct, round-trip) | ✅ Yes | ~487              | `{trip_inputs}`, `{parsed_inputs}`, `{tone_instruction}`  | -               | small     | 512        |
| `hotels_node`                  | `hotels.txt`                     | Hotel preferences (stars, amenities)           | ✅ Yes | ~441              | `{trip_inputs}`, `{parsed_inputs}`, `{tone_instruction}`  | -               | small     | 512        |
| `transport_node`               | `transport.txt`                  | Ground transport preferences                   | ✅ Yes | ~472              | `{trip_inputs}`, `{parsed_inputs}`, `{tone_instruction}`  | -               | small     | 512        |
| `activities_node`              | `activities.txt`                 | Activity preferences                           | ✅ Yes | ~592              | `{trip_inputs}`, `{parsed_inputs}`, `{tone_instruction}`  | -               | small     | 512        |
| `correction_node`              | `correction.txt`                 | Fix infeasible/contradictory plans             | ✅ Yes | ~387              | `{trip_inputs}`, `{parsed_inputs}`, `{tone_instruction}`  | -               | small     | 512        |
| `strategy_node`                | `strategy_hiking.txt`            | Hiking trip planning                           | ✅ Yes | ~441 + ~264       | `{trip_inputs}`, `{topic}`, `{tone_instruction}`          | -               | medium    | 512 / 2048 |
| `strategy_node`                | `strategy_diving.txt`            | Diving trip planning                           | ✅ Yes | ~435 + ~264       | `{trip_inputs}`, `{topic}`, `{tone_instruction}`          | -               | medium    | 512 / 2048 |
| `strategy_node`                | `strategy_skiing.txt`            | Skiing trip planning                           | ✅ Yes | ~419 + ~264       | `{trip_inputs}`, `{topic}`, `{tone_instruction}`          | -               | medium    | 512 / 2048 |
| `strategy_node`                | `strategy_boating.txt`           | Boating/sailing trip planning                  | ✅ Yes | ~448 + ~264       | `{trip_inputs}`, `{topic}`, `{tone_instruction}`          | -               | medium    | 512 / 2048 |
| `strategy_node`                | `strategy_cycling.txt`           | Cycling trip planning                          | ✅ Yes | ~442 + ~264       | `{trip_inputs}`, `{topic}`, `{tone_instruction}`          | -               | medium    | 512 / 2048 |
| `validate_and_merge`           | _(no prompt)_                    | Compute ready_to_generate                      | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `branch_postprocess`           | _(no prompt)_                    | Split/normalize branches                       | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `tile_search`                  | _(no prompt)_                    | Search tiles via tile_service                  | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `summarize`                    | _(no prompt)_                    | Generate fallback questions                    | ✅ Yes | 0                 | -                                                         | -               | -         | -          |
| `response_polish`              | `response_polish.txt`            | Polish response tone                           | ✅ Yes | ~518              | `{assistant_message}`, `{user_tone}`, `{destinations}`    | -               | small     | 512        |
| `condense_long_message`        | `condense.txt`                   | Shorten overly long responses                  | ✅ Yes | ~257              | `{message}`, `{target_length}`                            | -               | small     | 512        |

### Include Files (Shared Components)

| Include File            | Est. Tokens | Used By              | Purpose                  |
| ----------------------- | ----------- | -------------------- | ------------------------ |
| `_strategy_base.txt`    | ~264        | All strategy prompts | Common strategy policies |
| `_scope_specialist.txt` | ~191        | Domain specialists   | Scope boundaries         |
| `_json_output.txt`      | ~111        | All LLM prompts      | JSON output format       |
| `_never_invent.txt`     | ~67         | Domain specialists   | Anti-hallucination rules |
| `_markdown_rules.txt`   | ~131        | Strategy prompts     | Markdown formatting      |

---

## 3. Short-Circuits, Triggers, and Caching Logic

### 3.1 LQA Pre-Pass Node

| Field Target   | Parser Function             | Patterns Matched                    | Tokens Saved |
| -------------- | --------------------------- | ----------------------------------- | ------------ |
| `destinations` | `_parse_destination_answer` | Known places via `is_known_place()` | ~548-1684    |
| `origin`       | `_parse_origin_answer`      | "from X" or bare place name         | ~548-1684    |
| `dates`        | `_parse_date_answer`        | ISO dates, "next month", relative   | ~548-1684    |
| `travelers`    | `_parse_travelers_answer`   | "2 adults", "solo", "family of 4"   | ~548-1684    |
| `budget`       | `_parse_budget_answer`      | "$2000", "2k euros", "5 thousand"   | ~548-1684    |
| `duration`     | `_parse_duration_answer`    | "5 days", "2 weeks"                 | ~548-1684    |

**LQA Bail Conditions**:

| Bail Reason          | Condition                                     | Example                        |
| -------------------- | --------------------------------------------- | ------------------------------ |
| `pending_action`     | `metadata.pending_action` set                 | Typo confirmation pending      |
| `no_question_target` | No `question_target` or `last_question_field` | First turn message             |
| `too_long`           | Input > 50 chars                              | "I want to go to Paris and..." |
| `multi_intent`       | `also\|and book\|plus` pattern                | "Paris and also book hotels"   |
| `negation`           | `not\|instead\|change\|actually` detected     | "not Paris, somewhere else"    |
| `validation_fail`    | Parser returns None                           | Unknown place name             |

### 3.2 Short-Circuit Detection

| Type               | Pattern/Trigger                                  | Response                               | Action                     | Bypasses LLM? |
| ------------------ | ------------------------------------------------ | -------------------------------------- | -------------------------- | ------------- |
| `greeting`         | `^(hi\|hello\|hey\|howdy\|good morning\|...)$`   | Random greeting + destination question | None                       | ✅ Yes        |
| `confirmation_yes` | `^(yes\|yeah\|yep\|sure\|ok\|sounds good\|...)$` | Contextual follow-up                   | `generate_plan` if pending | ✅ Yes        |
| `confirmation_no`  | `^(no\|nope\|nah\|never mind\|cancel\|...)$`     | "No problem. What instead?"            | `clear_pending`            | ✅ Yes        |
| `confirm_typo`     | Yes + `pending_action=confirm_typo`              | None                                   | `apply_typo_corrections`   | ✅ Yes        |

**Short-Circuit Length Threshold**: Configurable via `SHORT_CIRCUIT_MAX_LENGTH` (default: 200 chars)

### 3.3 Deterministic Gates (GateEvaluator)

| Gate                | Priority | Trigger Condition                             | Routes To                 | Tokens Saved |
| ------------------- | -------- | --------------------------------------------- | ------------------------- | ------------ |
| `SHORT_CIRCUIT`     | 1        | `state.flags.short_circuit` set               | `short_circuit_responder` | ~1000-2000   |
| `INFEASIBILITY`     | 2        | Infeasible plan detected                      | `correction_node`         | ~800         |
| `FAST_PATH`         | 3        | `state.flags.fast_path` (simple field answer) | `required_fields_node`    | ~500-700     |
| `CORE_COLLECTION`   | 4        | Missing destinations/origin/start_date        | `required_fields_node`    | ~800-1500    |
| `QUESTION_KEYWORD`  | 4.5      | "What/Which + flights/hotels/etc?"            | Specialist node           | ~650         |
| `HIGH_CONFIDENCE`   | 5        | Extraction confidence ≥0.8                    | `required_fields_node`    | ~500         |
| `KEYWORD_HEURISTIC` | 6        | Domain keywords match specialist              | Specialist node           | ~650         |
| `SCORING_ROUTER`    | 60       | Score-based intent classification             | Based on scores           | ~400         |
| `ROUTER_LLM`        | 99       | No gate matched                               | `router`                  | 0 (LLM call) |

### 3.4 Node-Level Guards

| Guard                   | Location          | Trigger                               | Action                           | Tokens Saved |
| ----------------------- | ----------------- | ------------------------------------- | -------------------------------- | ------------ |
| Specialist Hard Gate    | `_specialist()`   | Core fields missing                   | Invoke `missing_fields_guard`    | ~1000-2000   |
| No-Op Specialist Gate   | `_specialist()`   | Vague affirmation + no missing fields | Skip LLM, return canned response | ~800-1500    |
| Strategy Relevance Gate | `strategy_node()` | Topic keywords not in user text       | Fallback response                | ~2000-3000   |
| Strategy Core Gate      | `strategy_node()` | Core fields missing                   | Invoke `missing_fields_guard`    | ~2000-3000   |

### 3.5 Caching Logic

| Cache                 | TTL  | Max Size | Key Components                                              | What's Cached                       | Used By                    |
| --------------------- | ---- | -------- | ----------------------------------------------------------- | ----------------------------------- | -------------------------- |
| `_extractor_cache`    | 60s  | 100      | `session_id`, `user_text_hash`, `core_fields_hash`, `mode`  | Parsed inputs, confidence           | `extractor`                |
| `_follow_up_cache`    | 1hr  | 200      | `node`, `core_fields`, `user_intent`, `user_text_hash`      | Router result, specialist responses | `router`, specialists      |
| `_strategy_cache`     | 5min | 50       | `session_id`, `topic`, `core_fields_hash`, `user_text_hash` | Strategy response, settings         | `strategy_node`            |
| Template cache        | ∞    | N/A      | `question_target`, `strategy_topic`                         | Pre-built questions                 | `_get_template_response()` |
| `_load_prompt_cached` | ∞    | 32       | Prompt name                                                 | Loaded prompt text                  | All `load_prompt()` calls  |

---

## 4. Duplicated Logic Analysis

### 4.1 Place Normalization Pattern (⚠️ Minor Duplication)

The `normalize_place_synonym() + is_known_place()` pattern appears in 6+ locations:

| Location                                  | Context                 |
| ----------------------------------------- | ----------------------- |
| `_parse_destination_answer()`             | LQA prepass             |
| `_parse_origin_answer()`                  | LQA prepass             |
| `_initial_extraction_prepass()` Pattern 1 | Initial extraction      |
| `_initial_extraction_prepass()` Pattern 2 | Origin/destination pair |
| `_initial_extraction_prepass()` Pattern 3 | Multi-field pattern     |
| `_initial_extraction_prepass()` Bare city | Bare city lookup        |

**Recommendation**: Create helper `_try_parse_place(text, field)` to consolidate.

### 4.2 Strategy Topics Definition (⚠️ Minor Duplication)

Same set defined in 3 locations:

| Location              | Code                                                                     |
| --------------------- | ------------------------------------------------------------------------ |
| Gate routing          | `strategy_topics = {"hiking", "skiing", "diving", "cycling", "boating"}` |
| Intent keywords       | Same topics in tuple form                                                |
| `_INTENT_KEYWORD_MAP` | Strategy keywords mapped to topics                                       |

**Recommendation**: Define once as `STRATEGY_TOPICS = frozenset({...})`.

### 4.3 LLM Response Extraction Pattern (⚠️ Minor Duplication)

The pattern for extracting JSON from LLM response appears 7 times:

```python
# Pattern: Parse content, try JSON, handle None/failure
if hasattr(result, 'content'):
    content = result.content
    # ... parse JSON ...
```

**Recommendation**: Consider `_extract_llm_json(response)` helper.

### 4.4 Centralized Logic (✅ No Duplication)

| Pattern                    | Status             | Single Source                                |
| -------------------------- | ------------------ | -------------------------------------------- |
| Missing fields computation | ✅ Centralized     | `compute_trip_readiness()`                   |
| Normalization              | ✅ Centralized     | `normalize_inputs()` → `TripInputNormalizer` |
| Extraction                 | ✅ Hierarchical    | LQA → Initial → Light → Full                 |
| Booking types auto-enable  | ✅ Single location | `validate_and_merge()`                       |

---

## 5. Unused Logic Analysis

### 5.1 Prompt Files

| Status                  | Notes                  |
| ----------------------- | ---------------------- |
| ✅ All 19 prompts wired | No unused prompt files |

### 5.2 Graph Nodes

| Status                | Notes                                           |
| --------------------- | ----------------------------------------------- |
| ✅ All 17 nodes wired | All registered nodes are connected in the graph |

### 5.3 Removed/Dead Code

| Pattern                       | Status     | Notes                                                                    |
| ----------------------------- | ---------- | ------------------------------------------------------------------------ |
| `_try_fast_path_extraction()` | ✅ Removed | Migrated to `lqa_prepass()`                                              |
| Off-topic in short-circuit    | ✅ Removed | Moved to router                                                          |
| Bare input detection          | ✅ Removed | LLM handles for accuracy                                                 |
| Deprecated wrappers           | ⚠️ Present | `_has_required_core_fields()` wrappers at L5523, L5856 should be removed |

---

## 6. Per-Node Detailed Analysis

### 6.1 LQA Pre-Pass

| Property           | Value                                                       |
| ------------------ | ----------------------------------------------------------- |
| **Function**       | `lqa_prepass()`                                             |
| **Purpose**        | Zero-LLM parsing of simple field answers                    |
| **LLM**            | None                                                        |
| **Tokens**         | 0 (zero-LLM)                                                |
| **Hit Condition**  | `question_target` set + input ≤50 chars + parser success    |
| **Bail Condition** | Pending action, no target, too long, multi-intent, negation |
| **Routing**        | HIT → `normalize_inputs`, BAIL → `extractor`                |

### 6.2 Extractor

| Property           | Value                                             |
| ------------------ | ------------------------------------------------- |
| **Function**       | `extractor()`                                     |
| **Purpose**        | Extract trip data from natural language           |
| **LLM**            | small (gpt-4o-mini)                               |
| **Light Mode**     | ~548 tokens, max output 128                       |
| **Full Mode**      | ~1684 tokens, max output 400                      |
| **Mode Selection** | Light for simple input, Full for dense/near-ready |
| **Bypass Paths**   | Short-circuit, Initial extraction, Cache hit      |

### 6.3 Router

| Property         | Value                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------------- |
| **Function**     | `router()`                                                                               |
| **Purpose**      | Intent classification (8 intents)                                                        |
| **LLM**          | small                                                                                    |
| **Tokens**       | ~914 input, 256 max output                                                               |
| **Bypass Gates** | 7 deterministic gates before LLM                                                         |
| **Intents**      | required_fields, flights, hotels, transport, activities, strategy, correction, off_topic |

### 6.4 Required Fields Node

| Property          | Value                                       |
| ----------------- | ------------------------------------------- |
| **Function**      | `required_fields_node()`                    |
| **Purpose**       | Collect missing core trip details           |
| **LLM**           | small (fallback only)                       |
| **Template Path** | Uses `required_fields_templates.json`       |
| **LLM Path**      | Typos, low confidence, multi-city ambiguity |
| **Topic-Aware**   | Suggestions vary by `strategy_topic`        |

### 6.5 Domain Specialists

| Node              | Prompt           | Tokens | Purpose                          |
| ----------------- | ---------------- | ------ | -------------------------------- |
| `flights_node`    | `flights.txt`    | ~487   | Flight cabin, direct, round-trip |
| `hotels_node`     | `hotels.txt`     | ~441   | Star rating, amenities           |
| `transport_node`  | `transport.txt`  | ~472   | Car, train, bus preferences      |
| `activities_node` | `activities.txt` | ~592   | Activity categories, validation  |

**Guards**: Hard gate (core missing), No-op gate (vague affirmation)

### 6.6 Strategy Node

| Property     | Value                                                  |
| ------------ | ------------------------------------------------------ |
| **Function** | `strategy_node()`                                      |
| **Purpose**  | Deep planning for hiking/diving/skiing/boating/cycling |
| **LLM**      | medium                                                 |
| **Stage 1**  | Shortlist + skeleton, 512 max output                   |
| **Stage 2**  | Full itinerary, 2048 max output                        |
| **Cache**    | 5min TTL                                               |
| **Guards**   | Core gate, Relevance gate                              |

### 6.7 Response Polish

| Property            | Value                                                                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Function**        | `response_polish()`                                                                                                                        |
| **Purpose**         | Polish response tone for natural conversation                                                                                              |
| **LLM**             | small                                                                                                                                      |
| **Tokens**          | ~518 input, 512 max output                                                                                                                 |
| **Skip Conditions** | 12 conditions including: feature_disabled, short_circuit, cache_hit, fast_path, template_response, short_with_warmth, question_with_warmth |

---

## 7. Token Budget Summary

### 7.1 Per-Turn Worst Case (All LLM Calls)

| Stage            | Input Tokens     | Output Tokens |
| ---------------- | ---------------- | ------------- |
| Extractor (full) | ~1,684           | 400           |
| Router           | ~914             | 256           |
| Specialist       | ~500-700         | 512           |
| Response Polish  | ~518             | 512           |
| **Total**        | **~3,600-3,800** | **~1,680**    |

### 7.2 Per-Turn Best Case (All Bypasses)

| Stage                      | Tokens |
| -------------------------- | ------ |
| LQA Pre-Pass (hit)         | 0      |
| Extractor (skipped)        | 0      |
| Router (gate bypass)       | 0      |
| Required Fields (template) | 0      |
| Response Polish (skip)     | 0      |
| **Total**                  | **0**  |

### 7.3 Typical Turn Estimates

| Path                                          | Est. Input Tokens | Est. Output Tokens |
| --------------------------------------------- | ----------------- | ------------------ |
| Simple answer via LQA                         | 0                 | 0                  |
| First turn (light extractor → template)       | ~548              | ~128               |
| Domain question (keyword gate → specialist)   | ~500              | ~300               |
| Complex question (full → router → specialist) | ~2,500            | ~800               |
| Strategy planning (2-stage)                   | ~2,500-4,000      | ~2,000             |

---

## 8. Observability Metrics

### 8.1 Available Stats

| Stat Category      | Metrics                                       |
| ------------------ | --------------------------------------------- |
| `_lqa_stats`       | attempts, hits, bails, hit_rate, bail reasons |
| `_routing_stats`   | gate_bypasses, router_calls, bypass_rate      |
| `_gate_stats`      | per-gate fire counts                          |
| `_template_stats`  | template_hits, template_misses, hit_rate      |
| `_strategy_stats`  | stage1_count, stage2_count, stage1_rate       |
| `_polish_stats`    | skips, calls, skip_rate                       |
| `_extractor_stats` | light*mode, full_mode, dense_input*\*         |

### 8.2 Target Metrics

| Metric             | Target | Notes                           |
| ------------------ | ------ | ------------------------------- |
| LQA hit rate       | >40%   | For simple field-answer turns   |
| Router call rate   | <30%   | With gate bypasses              |
| Template hit rate  | >85%   | First-turn and simple questions |
| Polish skip rate   | >50%   | When AI text is short/simple    |
| Strategy Stage 1:2 | >3:1   | Stage 2 = follow-up only        |

---

## 9. Recommendations

### 9.1 Consolidation Opportunities (Low Priority)

1. **Place normalization helper**: Create `_try_parse_place(text, field)` to consolidate 6+ similar patterns
2. **Strategy topics constant**: Define `STRATEGY_TOPICS = frozenset({...})` once
3. **LLM response extraction**: Create `_extract_llm_json(response)` helper for 7 occurrences
4. **Remove deprecated wrappers**: Clean up `_has_required_core_fields()` wrappers

### 9.2 Token Optimization Opportunities (Future)

1. **Router prompt compression**: ~914 tokens could be reduced with more concise rules
2. **Strategy Stage 2 output cap**: 2048 tokens is high; consider streaming or pagination
3. **Include file consolidation**: `_scope_specialist.txt` + `_never_invent.txt` could merge (~258 combined)

### 9.3 Architecture Strengths

1. **Zero-LLM paths**: LQA pre-pass, initial extraction, templates, short-circuits
2. **Hierarchical extraction**: LQA → initial → light → full (escalation)
3. **8 deterministic gates**: Before LLM router for maximum bypass
4. **3 cache layers**: Extractor 60s, follow-up 1hr, strategy 5min
5. **Centralized normalization**: Single `normalize_inputs()` pass
6. **Single source of truth**: `compute_trip_readiness()` for field status
7. **Topic-aware templates**: Strategy topic influences destination suggestions

---

## 10. Graph Edge Definitions

```python
# Entry point
START → lqa_prepass

# After LQA pre-pass
lqa_prepass → [route_after_lqa_prepass] → {
    "hit":  normalize_inputs,
    "bail": extractor
}

# After extractor
extractor → [route_after_extractor] → {
    "short_circuit":  short_circuit_responder,
    "extracted":      normalize_inputs
}

# After short-circuit
short_circuit_responder → summarize

# After normalize
normalize_inputs → [route_after_normalize] → {
    "fast_path":      required_fields_node,
    "core_missing":   required_fields_node,
    "high_conf":      required_fields_node,
    "flights":        flights_node,
    "hotels":         hotels_node,
    "transport":      transport_node,
    "activities":     activities_node,
    "strategy":       strategy_node,
    "correction":     correction_node,
    "router":         router
}

# After router
router → [route_after_router] → {
    "required_fields": required_fields_node,
    "flights":         flights_node,
    "hotels":          hotels_node,
    "transport":       transport_node,
    "activities":      activities_node,
    "strategy":        strategy_node,
    "correction":      correction_node,
    "off_topic":       summarize
}

# All specialist/domain nodes → validate_and_merge
{required_fields_node, flights_node, hotels_node,
 transport_node, activities_node, strategy_node,
 correction_node} → validate_and_merge

# After validate
validate_and_merge → branch_postprocess

# After branch
branch_postprocess → [route_after_branch] → {
    "tile_search": tile_search,
    "summarize":   summarize
}

# After tile search
tile_search → summarize

# Final steps
summarize → response_polish → END
```

---

## 12. Model Mapping Reference

| Hint     | Model         | Notes                          |
| -------- | ------------- | ------------------------------ |
| `small`  | `gpt-4o-mini` | Default for most nodes         |
| `medium` | `gpt-4o-mini` | Strategy nodes                 |
| `large`  | `gpt-4o`      | Reserved for complex reasoning |

---

## 13. Key Classes and Utilities

| Class/Function             | Purpose                                         |
| -------------------------- | ----------------------------------------------- |
| `GateEvaluator`            | Centralized routing with gate precedence        |
| `GatePrecedence`           | Enum defining gate priority (1-99)              |
| `DateNormalizer`           | Parse relative/absolute dates with timezone     |
| `TripInputNormalizer`      | Single-pass field normalization                 |
| `StateViewBuilder`         | Create minimal state views per node type        |
| `ToneAdapter`              | Generate tone instructions based on user intent |
| `SuggestionBuilder`        | Context-aware suggestion generation             |
| `TripReadiness`            | Dataclass for readiness computation             |
| `compute_trip_readiness()` | Canonical missing fields calculation            |
| `_apply_llm_delta()`       | Apply LLM output to trip_inputs safely          |
| `_write_trip_inputs()`     | Audit-logged trip_inputs updates                |

---

## 14. Configuration Reference

| Setting                    | Env Var                    | Default | Purpose                               |
| -------------------------- | -------------------------- | ------- | ------------------------------------- |
| `short_circuit_max_length` | `SHORT_CIRCUIT_MAX_LENGTH` | 200     | Max chars for short-circuit detection |
| `lqa_max_length`           | `LQA_MAX_LENGTH`           | 50      | Max chars for LQA pre-pass            |
| `response_polish_enabled`  | `RESPONSE_POLISH_ENABLED`  | true    | Enable/disable polishing              |
| `tile_search_enabled`      | `TILE_SEARCH_ENABLED`      | true    | Enable/disable tile search            |

---

## 15. Test Coverage Alignment

### Tests ↔ Architecture Mapping

| Test File                              | Tested Component                | Architecture Element                                      |
| -------------------------------------- | ------------------------------- | --------------------------------------------------------- |
| `test_lqa_prepass.py`                  | LQA field parsers, prepass node | `lqa_prepass()`, `_parse_*_answer()`                      |
| `test_routing_logic.py`                | Routing functions               | `route_after_*` functions, `GateEvaluator`                |
| `test_short_circuit_confirmations.py`  | Short-circuit patterns          | `_GREETING_PATTERN`, `_YES_PATTERN`, etc.                 |
| `test_caching.py`                      | Cache layers                    | `_extractor_cache`, `_strategy_cache`, `_follow_up_cache` |
| `test_confidence_routing.py`           | Confidence-based routing        | `GateEvaluator`, `HIGH_CONFIDENCE` gate                   |
| `test_date_normalization.py`           | Date parsing                    | `DateNormalizer` class                                    |
| `test_trip_input_normalizer.py`        | Normalization                   | `TripInputNormalizer` class                               |
| `test_strategy_expansion_tiers.py`     | Strategy tiers                  | Stage 1/2 max_tokens, `StrategyTier`                      |
| `test_destination_normalization.py`    | Place handling                  | `normalize_place_synonym()`, `is_known_place()`           |
| `test_extractor_full_triggers.py`      | Extractor mode selection        | Light vs Full mode switching                              |
| `test_suggestion_relevance.py`         | Suggestion generation           | `SuggestionBuilder`                                       |
| `test_multicity_intent.py`             | Multi-city detection            | `multi_city_intent` field handling                        |
| `test_error_handling.py`               | Error recovery                  | `_record_llm_failure()`, retry logic                      |
| `test_graph_plan.py`                   | Full graph execution            | `run_turn()`, `plan_trip_graph()`                         |
| `test_graph_plan_conversation_flow.py` | Multi-turn conversations        | Session state persistence                                 |

### Coverage Verification ✅

All major components from the architecture are covered:

- ✅ **LQA Pre-pass**: `test_lqa_prepass.py` (563 lines)
- ✅ **Gate Evaluation**: `test_routing_logic.py` (452 lines)
- ✅ **Short-circuits**: `test_short_circuit_confirmations.py`
- ✅ **Caching**: `test_caching.py`
- ✅ **Normalization**: `test_trip_input_normalizer.py`, `test_date_normalization.py`
- ✅ **Strategy Tiers**: `test_strategy_expansion_tiers.py`
- ✅ **Confidence Routing**: `test_confidence_routing.py`
- ✅ **Suggestions**: `test_suggestion_relevance.py`
