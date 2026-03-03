# Plan: Address Architecture Audit Claims

## Context

An architecture audit made 20+ claims about cost waste, intelligence gaps, and state bugs. This investigation cross-referenced every claim against the actual codebase. Several high-profile claims are **FALSE** — the codebase is more optimized than the audit suggests. The real gaps are concentrated in the **conversationalist intelligence** layer, where verified issues limit response quality.

---

## Audit Verdict: What's TRUE vs FALSE

### FALSE Claims (No Action Needed)

| Claim | Reality | Evidence |
|-------|---------|---------|
| Hotel tile cache uses exact dates, causing cache misses | Hotels pass `("", "")` for dates — **zero date sensitivity** | `logistics_node.py:906-908` |
| 1-day date shift triggers fresh hotel search (~$0.03) | Cache key has no dates at all | `tile_cache.py:53-78`, `logistics_node.py:898` |
| "Coarsen hotel keys to ISO month" is a 30-min fix | Already done — nothing to fix | Activity keys already use `[:7]` month at `logistics_node.py:1020` |
| Post-build enrichment costs ~$0.45/plan (14 calls) | Cap is **3** (not 14). Cost is ~$0.10/plan max on cache miss | `config.py:185` default=3, `google_places_provider.py:1766` |
| `_pending_enrichments` dict is fragile | Has async lock, TTL tuples, max-50 cap, eviction, inflight dedup | `local_expert.py:51-58,692-699,1228-1231` |
| Specialist findings are "heavily truncated" | Intentional: 3 constraints + 3 activities per specialist, 150 char/activity | By design for prompt budget |

### TRUE Claims (Action Items Below)

| Claim | Severity | Evidence |
|-------|----------|---------|
| No pre-change diff passed to conversationalist | HIGH | `coordinator.py:3600-3604` captures snapshots but deletes at `:3067-3068`, never passes to conversationalist |
| No budget utilization in outcome block | HIGH | `conversationalist.py:349-427` — outcome block has itinerary counts, hotel, density, but zero budget data |
| "What the User Sees" is a static string | MEDIUM | `conversationalist.py:782-789` — literal static text regardless of actual UI state |
| INITIAL_PLAN limited to 2 sentences | MEDIUM | `conversationalist.py:604` maps `initial_plan` → `_VOICE_DESTINATION_SET` (2-sentence limit) |
| "Already Said" dedup truncated to 300 chars | LOW | `conversationalist.py:824` — `[:300]` cuts mid-sentence on 400-600 char responses |
| No `advisory_level` field in LocalExpertOutput | MEDIUM | `expert_constraints.py:104-111` — `SafetyHealth` has `overall_safety` string but no discrete advisory level or reason |
| State restoration truthiness guard edge case | LOW | `streaming.py:431,435` — empty list from DB skips override, preserving stale session data |

---

## Implementation Plan

### Task 1: Add diff block to conversationalist context
**Files:** `coordinator.py`, `conversationalist.py`

1. In `coordinator.py`, before the `_pre_change_briefs` are popped at line 3067, compute a compact diff dict:
   ```python
   diff = {}
   pre = state.get("_pre_change_briefs", {})
   for key in ("trip_plan", "trip_settings"):
       pre_val = pre.get(key, {})
       post_val = state.get(key, {})
       for field in set(list(pre_val.keys()) + list(post_val.keys())):
           if pre_val.get(field) != post_val.get(field):
               diff[f"{key}.{field}"] = {"from": pre_val.get(field), "to": post_val.get(field)}
   ```
   Store as `state["turn_meta"]["field_diffs"] = diff` (turn_meta survives to conversationalist).

2. In `conversationalist.py`, add `_build_diff_block(state)` that reads `state["turn_meta"].get("field_diffs")` and formats as:
   ```
   ## What Changed This Turn
   - dates: Feb 1-7 → Mar 15-21
   - budget: $3,000 → $5,000
   ```
   Insert after the turn context block (line 820). Cap at 200 tokens. Skip if no diffs.

### Task 2: Add budget health summary to outcome block
**Files:** `conversationalist.py`

1. In `_build_outcome_block()` (line 349), after the density calculation, compute budget utilization from tiles:
   - Read `state["trip_plan"].get("budget")` for total
   - Sum selected hotel price * nights, cheapest flight price * adults, activity estimates
   - Append one line: `"Budget: ~$3,200 of $5,000 (64%) — Hotels: $1,800, Flights: $800, Activities: $600"`
   - Only include if budget > 0 and tiles exist with price data

### Task 3: Make "What the User Sees" block dynamic
**File:** `conversationalist.py`

1. Replace the static string at lines 782-789 with a dynamic builder:
   - If `day_cards` exist: `"User sees: {n}-day timeline with {activity_count} activities across {specialist_topics}"`
   - If only `strategy_sections`: `"User sees: specialist plans for {topics}, no itinerary yet"`
   - If `tiles.hotels`: append `", {n} hotel options"`
   - Keep the "NEVER describe what's visible" instruction

### Task 4: Add INITIAL_PLAN voice block with higher sentence limit
**File:** `conversationalist.py`

1. Add a new `_VOICE_INITIAL_PLAN` constant:
   ```python
   _VOICE_INITIAL_PLAN: str = """\
   ## Voice: First Plan Reveal
   Sentence count: 4-5 MAX.
   1. Open with one editorial hook — the boldest or most unexpected thing about this itinerary.
   2. Highlight 1-2 standout activities by name.
   3. One actionable nudge — what to customize or explore further.
   Constraints and day-by-day details are visible in the UI — don't list them.
   Tone: excited but opinionated travel editor revealing something special.\
   """
   ```
2. Add `_SENTENCE_LIMIT[_VOICE_INITIAL_PLAN] = 5`
3. Change line 604: `"initial_plan": _VOICE_INITIAL_PLAN`

### Task 5: Increase dedup block truncation to 500 chars
**File:** `conversationalist.py`

1. Line 824: Change `[:300]` to `[:500]`
2. This aligns with the message history truncation (also 500 chars at line 844-846)

### Task 6: Add advisory_level to local expert
**Files:** `expert_constraints.py`, `local_expert.py`, `prompts/specialists/local_expert.txt`, `conversationalist.py`

**Schema change** — `backend/app/planner/nodes/expert_constraints.py`:
1. Add two fields to `SafetyHealth` (line 104-111):
   ```python
   advisory_level: str = Field(default="none", description="none | caution | warning | avoid")
   advisory_reason: str = Field(default="", description="Brief reason for advisory")
   ```
   Adding to `SafetyHealth` (not `LocalExpertOutput`) keeps it nested where safety data already lives. No new top-level field needed.

**Prompt change** — `backend/app/prompts/specialists/local_expert.txt`:
2. In the `safety_health` output format section (around line 128-137), add:
   ```json
   "advisory_level": "none | caution | warning | avoid",
   "advisory_reason": "Brief reason if caution or higher (e.g., 'Active travel advisory due to regional instability')"
   ```
3. Add one instruction line in the SAFETY & HEALTH category (around line 19-26):
   ```
   - Travel advisory assessment: Rate advisory_level as none/caution/warning/avoid based on current geopolitical, health, or natural disaster risks for the travel dates. Be specific about the concern.
   ```

**Conversationalist surfacing** — `backend/app/planner/conversationalist.py`:
4. In `_build_from_strategy_sections` (line 167), within the `topic == "local_expert"` branch (line 179-198):
   - After reading `constraints` and `travel_intelligence`, also check `s.get("travel_intelligence", {})` for advisory data
   - The local expert section's `travel_intelligence` dict already carries safety data. After Phase B enrichment, the `SafetyHealth` fields are serialized into the strategy section. Read `advisory_level` from the safety_health sub-dict.
   - If `advisory_level` in `("warning", "avoid")`, prepend a bold line:
     ```python
     advisory = ti.get("safety_health", {}) if isinstance(ti, dict) else {}
     level = advisory.get("advisory_level", "none")
     reason = advisory.get("advisory_reason", "")
     if level in ("warning", "avoid"):
         lines.insert(0, f"**TRAVEL ADVISORY ({level.upper()}):** {reason}")
     ```

**No extra API calls.** This piggybacks on the existing Phase B LLM call — the LLM already generates all `SafetyHealth` fields; we're just adding two more fields to the schema it fills.

### Task 7: Fix state restoration truthiness guard
**File:** `streaming.py`

1. Lines 431, 435: Change `if document_data.strategy_sections:` to `if document_data.strategy_sections is not None:`
2. Same for `day_cards`: `if document_data.day_cards is not None:`
3. This ensures intentional resets (empty list) properly overwrite stale session data

---

## Execution Order

1. **Task 4** — INITIAL_PLAN voice block (isolated, highest UX impact on demos)
2. **Task 5** — Dedup truncation bump (one-line change)
3. **Task 7** — Truthiness guard fix (streaming.py only, small)
4. **Task 1** — Diff block (touches coordinator + conversationalist)
5. **Task 3** — Dynamic UI awareness block (conversationalist only)
6. **Task 2** — Budget health summary (conversationalist only)
7. **Task 6** — Advisory level (schema + prompt + surfacing)

Tasks 1-5 and 7 are conversationalist-focused, delegated to backend-specialist.
Task 6 touches 3 files (schema, prompt, conversationalist) — same backend-specialist pass.

---

## Files Modified (6 files, within 8-file limit)

- `backend/app/planner/conversationalist.py` — Tasks 1-5, 6 (surfacing)
- `backend/app/planner/coordinator.py` — Task 1 (diff computation)
- `backend/app/streaming.py` — Task 7
- `backend/app/planner/nodes/expert_constraints.py` — Task 6 (schema)
- `backend/app/prompts/specialists/local_expert.txt` — Task 6 (prompt)

---

## Verification

1. **Diff block**: Send a date-change message → verify conversationalist response references the old vs new dates
2. **Budget health**: Generate a plan with budget set → verify outcome block includes budget utilization line
3. **Dynamic UI block**: Log the system prompt on a plan-generated turn → verify it mentions actual day count and specialist topics
4. **INITIAL_PLAN voice**: Trigger initial plan generation → verify response is 4-5 sentences (not 2)
5. **Dedup**: Run a 4-turn conversation → verify no repeated insights
6. **Truthiness guard**: Reset a plan (clear strategy_sections) → verify next turn doesn't carry stale sections
7. **Advisory level**: Generate a plan for a destination with known safety concerns → verify advisory appears in specialist findings block
8. **Run backend tests**: `cd backend && pytest` + `rm -f backend/test_plan_document_pytest.db*`
9. **Run ruff**: `cd backend && ruff check . --fix`
