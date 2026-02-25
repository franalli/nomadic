# Diagnostic & Streaming Bug Fixes

## Context

Diagnostic tracing revealed 5 actionable bugs (3 critical, 2 moderate) in the backend planner. These cause: blank responses on itinerary-build turns, inflated tool call counts corrupting auto-build logic, incorrect LLM diagnostic output, and duplicate activity categories. All fixes are in 3 files.

## Files Modified (3)

1. `backend/app/planner/plan_graph.py` — fixes C1, C2, D1, M1
2. `backend/app/planner/middleware.py` — fixes C3
3. `backend/app/planner/nodes/router_extraction.py` — fixes M2

---

## Fix 1: C3 — `tools_called` duplication (middleware.py)

**Root cause:** `awrap_tool_call` at line 894-898 reads the current accumulated `tools_called` list from state, appends the new tool name, then returns the FULL list. The `_merge_turn_meta` reducer then concatenates left (existing state) + right (full accumulated list), causing exponential duplication: after 3 tools, you get ~7 entries instead of 3.

**Fix:** Return only the delta (single tool name) in the state update. The reducer already concatenates left + right, so returning `[tool_name]` gives correct behavior.

```python
# Lines 893-898 — REPLACE the turn_meta counter logic:
# OLD:
turn_meta = dict(state_dict.get("turn_meta", {}))
turn_meta["tool_call_count"] = turn_meta.get("tool_call_count", 0) + 1
tools_called = list(turn_meta.get("tools_called", []))
tools_called.append(tool_name)
turn_meta["tools_called"] = tools_called
state_updates["turn_meta"] = turn_meta

# NEW — return delta only; reducer handles concatenation:
turn_meta_update: dict[str, Any] = {"tools_called": [tool_name]}
state_updates["turn_meta"] = turn_meta_update
```

**Note:** The tool merger at lines 908-912 also writes to `turn_meta`. The existing code at line 910-912 does `merged_turn_meta = dict(state_updates["turn_meta"]); merged_turn_meta.update(tool_updates.pop("turn_meta"))` which will work correctly since it merges into whatever `state_updates["turn_meta"]` contains.

---

## Fix 2: C2 — Blank response on auto-build turns (plan_graph.py)

**Root cause:** The assistant text extraction (lines 889-924) runs BEFORE `_build_complete_envelope` (line 926) which triggers auto-build. The canned text check at line 914 only matches `"build_itinerary" in tools_called`, but auto-build doesn't add to `tools_called`. So blank response.

**Fix:** After `_build_complete_envelope` returns, check if auto-build produced a `builder_result` and emit a canned response.

```python
# After line 926 (envelope = _build_complete_envelope(...)):
# Add:
if not assistant_message and result_state.get("turn_meta", {}).get("builder_result"):
    assistant_message = "Your itinerary has been built!"
    yield {"type": "token", "data": assistant_message}
    # Update envelope with the canned message
    if "assistant_message" in envelope:
        envelope["assistant_message"] = assistant_message
```

---

## Fix 3: C1 — LLM_INVOKE diagnostic reading wrong field (plan_graph.py)

**Root cause:** Lines 823-825 read `event["data"]["messages"][0]`, but LangGraph's `on_chat_model_start` event uses `event["data"]["input"]` (which is the messages list or a dict with `messages` key). So `total_messages` is always 0.

**Fix:** Try `data.input.messages`, `data.input` (if list), then fall back to `data.messages[0]`.

```python
# Lines 823-825 — REPLACE:
_inv_data = event.get("data", {})
_inv_input = _inv_data.get("input", {})
if isinstance(_inv_input, dict):
    _last_msgs = _inv_input.get("messages", [])
elif isinstance(_inv_input, list):
    _last_msgs = _inv_input
else:
    _inv_batched = _inv_data.get("messages", [[]])
    _last_msgs = _inv_batched[0] if _inv_batched else []
```

---

## Fix 4: D1 — `will_auto_build` shows None instead of bool (plan_graph.py)

**Root cause:** Python's `and` chain returns the first falsy VALUE, not False. When `tiles.get('hotels')` is None and `tiles.get('activities')` is None, `None or None` returns `None`, and the `and` chain short-circuits to `None`.

**Fix:** Wrap the expression in `bool()` at line 290.

```python
# Line 290 — wrap in bool():
f"  will_auto_build: {bool(has_core and not day_cards and not has_blocking_validation and (tiles.get('hotels') or tiles.get('activities')) and 'build_itinerary' not in tools_called)}"
```

---

## Fix 5: M2 — Category extraction uses non-canonical strings (router_extraction.py)

**Root cause:** The LLM invents freeform labels like `culture`, `cultural`, `food` instead of Google Places canonical types. The mismatch is at the extraction boundary.

**Fix:** LLM prompt only — update the `RouterOutput.activity_categories` field description and the extraction prompt (Task 4 section) to instruct canonical Google Places types. Zero code logic change.

**Change 1 — Field description** (line 90-94):
```python
# OLD:
activity_categories: List[str] = Field(
    default_factory=list,
    description="Activity categories mentioned. Common: "
    + _TIER2_EXAMPLES_CSV
    + ". But accept ANY activity the user mentions.",
)

# NEW:
activity_categories: List[str] = Field(
    default_factory=list,
    description="Activity categories mentioned. Use Google Places canonical types "
    "(e.g. 'museum', 'restaurant', 'park', 'tourist_attraction', 'spa', 'gym', "
    "'night_club', 'amusement_park', 'art_gallery', 'church'). "
    "Never use abstract labels like 'cultural', 'food', 'culture'. "
    "Also accept: " + _TIER2_EXAMPLES_CSV + ".",
)
```

**Change 2 — Extraction prompt Task 4** (lines 396-413):
Add instruction: "Prefer Google Places types (museum, restaurant, park, tourist_attraction, spa, etc.). Avoid abstract/adjective forms like 'cultural', 'food', 'culture' — use the noun form or Places type instead."

Update examples:
- `"explore local cuisine"` → `["restaurant", "cooking"]` (not `["cooking", "food"]`)
- `"temple tours and wine tasting"` → `["tourist_attraction", "wine"]` (not `["temples", "wine"]`)

---

## Fix 6: M1 — plan_view_state not persisted to agent state (plan_graph.py)

**Root cause:** `plan_view_state` is computed at line 441-457 in `_build_complete_envelope`, but `serialize_agent_state(state)` is called at line 438 — BEFORE the computation. So `persistent_meta` in the serialized state never has the current turn's `plan_view_state`. On the next turn, `persistent_meta.get('plan_view_state', '?')` returns `'?'`.

**Fix:** Move `plan_view_state` computation BEFORE `serialize_agent_state(state)` at line 438. Write it to `state["persistent_meta"]` before serializing.

```python
# BEFORE line 438 (serialize call), move the plan_view_state computation from lines 441-457:
# Compute plan_view_state
if not has_core:
    plan_view_state = "S0_BOOTSTRAP"
elif day_cards:
    plan_view_state = _compute_s3_view_state(turn_meta, day_cards)
elif strategy_sections:
    plan_view_state = "S2_STRATEGY_READY"
elif tiles.get("hotels") or tiles.get("activities"):
    plan_view_state = "S2_STRATEGY_READY"
else:
    plan_view_state = "S0_BOOTSTRAP"

# Write to persistent_meta so it survives serialization
persistent_meta = dict(state.get("persistent_meta", {}))
persistent_meta["plan_view_state"] = plan_view_state
state["persistent_meta"] = persistent_meta

# NOW serialize (captures the updated persistent_meta)
serialized = serialize_agent_state(state)
```

Then REMOVE the duplicate plan_view_state computation block that was at lines 441-457.

---

## Verification

1. `cd backend && ruff check app/planner/plan_graph.py app/planner/middleware.py app/planner/nodes/router_extraction.py --fix`
2. `cd backend && pytest tests/ -x -q`
3. Manual test: Send "rome → Mar 1-7" flow and verify:
   - `[DIAG:LLM_INVOKE]` shows non-zero `total_messages`
   - `[DIAG:AUTO_BUILD]` shows `will_auto_build: True` or `False` (not None)
   - `[DIAG:STATE_INIT]` shows `plan_view_state: S3_ITINERARY_READY` on subsequent turns
   - No blank response after auto-build
   - `tools_called` has no duplicates
