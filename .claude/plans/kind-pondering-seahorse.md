# Comprehensive Code Health Remediation Plan

## Context

Two independent code health audits identified overlapping findings across the full stack. This plan merges and deduplicates both reports, dismisses false positives after deep exploration, and organizes remaining issues into actionable tasks respecting the 8-file-per-task limit.

### Dismissed After Exploration (no action needed)
- **Toast message quality (6+ callsites):** Variables contain complete user-friendly messages — no raw backend keys leak to users
- **Unused variables (34):** Intentional `_` prefixed destructured props, not dead code
- **DS tokens in TripPdfDocument:** `@react-pdf/renderer` requires concrete hex values; colors map to DS naming in comments
- **Hardcoded world data duplication:** Tier 1/2 specialist lists are properly separated; `patterns_registry.py` regex lists are pre-filters before LLM (acceptable optimization)
- **ChatInputBar DS compliance:** Uses DS tokens correctly

---

## Wave 1 — Critical + High (all independent, parallelizable)

### Task C1: Fix feasibility inflight TOCTOU race
**Why:** `_feasibility_inflight` dict read/written without lock. Every other inflight dict in the codebase uses `async with lock`. Comment claiming "cooperative scheduling makes this atomic" is fragile — any added `await` breaks it silently.

**Files:**
1. `backend/app/planner/services/feasibility_service.py`
2. `backend/app/lifespan.py` (update caller — `cancel_feasibility_inflight` becomes async)
3. `backend/tests/test_feasibility_inflight.py` (new)

**Changes:**
- Add `_feasibility_inflight_lock = asyncio.Lock()` at module level (line ~103)
- Wrap lines 153-168 (check + register) in `async with _feasibility_inflight_lock:`
  - Lock covers: inflight check, pressure check, future creation + registration
  - Lock does NOT cover: the actual LLM call (avoid serializing all requests)
- Wrap `finally` block pop (line 198) in `async with _feasibility_inflight_lock:`
- Convert `cancel_feasibility_inflight()` to `async def`, wrap with lock
- Update `backend/app/lifespan.py:159` to `await cancel_feasibility_inflight()`
- Reference pattern: `backend/app/services/activity_browser.py:647-691`
- Delete the incorrect comment at lines 163-165

**Tests:**
- Two concurrent calls with same key → only 1 LLM invocation
- Future cleanup after exception
- Cancel clears all entries

**Verify:** `cd backend && ruff check . --fix && pytest`

---

### Task C2: Consolidate frontend plan_view_state SSoT
**Why:** Three inline view-state guards duplicate logic that `shouldBlockViewStateDowngrade()` already handles correctly. One variant (line 1667) is more aggressive and misses the `hasDayCards` check.

**Files:**
1. `frontend/state/documentStore.ts`
2. `frontend/components/layout/hooks/useItineraryGeneration.ts` (comment only)

**Changes in documentStore.ts:**

| Location | Current | Fix |
|----------|---------|-----|
| Lines 1108, 1174 | Hard-codes `S0_BOOTSTRAP` | Keep — this is document creation (no prior state). Add `// Bootstrap: no prior state to guard` comment |
| Lines 1262-1276 | Inline IIFE with S3/day_cards guard | Replace with `shouldBlockViewStateDowngrade(currentPVS, responsePVS, hasDayCards)` |
| Lines 1347-1362 | Duplicate of above in 409-retry | Replace with same `shouldBlockViewStateDowngrade` call |
| Lines 1667-1673 | Aggressive variant, no hasDayCards check | Replace with `shouldBlockViewStateDowngrade` + compute hasDayCards from current doc |

For lines 1262 and 1347, compute `hasDayCards` the same way the canonical pattern does (line 1863):
```typescript
const hasDayCards = Array.isArray(currentDoc?.day_cards) && (currentDoc?.day_cards?.length ?? 0) > 0;
const wouldDowngrade = shouldBlockViewStateDowngrade(currentPVS, responsePVS, hasDayCards);
plan_view_state: wouldDowngrade ? currentPVS : (responsePVS ?? currentPVS),
```

For line 1667, add the missing `hasDayCards` computation before the guard.

**useItineraryGeneration.ts:355** — Add comment: `// Backend CONSTRAINT_CONFLICT sets this intentionally; mergeEnvelope guards downgrade`

**Verify:** `cd frontend && npm run build && npm run lint:fix`

---

### Task H1: Spend guard hardening + tests
**Why:** In-memory counters reset on server restart. SPEND_GUARD_ENABLED disableable via env.

**Files:**
1. `backend/app/services/spend_guard.py`
2. `backend/tests/test_spend_guard.py`

**Changes:**
- Expand the Redis migration docstring at line 27-29 with concrete key schema (`spend:{session}:{date}`, INCRBY pattern, TTL = 86400)
- Add startup log at CRITICAL level if `spend_guard_enabled=False` and `env != "dev"` (check if this already exists in lifespan.py — it does at line 56-68, but only at INFO)
- Add tests: dayroll-over reset, concurrent access under `_spend_lock`, session-less requests enforce global cap only

**Verify:** `cd backend && pytest tests/test_spend_guard.py -v`

---

### Task H2: NDJSON generator enrichment cleanup parity
**Why:** SSE generator's finally block (line 1405) cleans up pending enrichments. NDJSON generator (line 2098) only logs.

**Files:**
1. `backend/app/streaming.py`

**Changes:**
- Extract shared enrichment cleanup from SSE finally (lines 1406-1430) into a helper:
  ```python
  async def _cleanup_pending_enrichment(session_id: str, source: str) -> None:
  ```
- Call from both SSE finally and NDJSON finally
- Wrap in try/except to prevent cleanup errors from masking real errors

**Verify:** `cd backend && ruff check . --fix`

---

### Task H3: request_dedup test coverage
**Why:** Zero test references for a module handling idempotency and expand-itinerary mutex.

**Files:**
1. `backend/tests/test_request_dedup.py` (new)

**Tests:**
- `test_check_idempotency_new_key` — returns False
- `test_check_idempotency_duplicate` — returns True
- `test_check_idempotency_none_key` — always False
- `test_acquire_expand_slot_first_time` — returns True
- `test_acquire_expand_slot_duplicate_rejected` — returns False
- `test_release_then_reacquire` — returns True
- `test_concurrent_acquire` — only one of N concurrent calls succeeds

**Verify:** `cd backend && pytest tests/test_request_dedup.py -v && rm -f backend/test_plan_document_pytest.db*`

---

### Task M4: Router cache stat key standardization
**Why:** Custom `stat_keys` in MemoryCache REPLACE defaults instead of extending them. Router cache misses `l2_hits`/`l2_misses`/`writes` keys that admin aggregation expects.

**Files:**
1. `backend/app/services/cache_core.py`

**Change at line 31-32:**
```python
# Before:
self._stats: dict[str, int] = {k: 0 for k in (stat_keys or default_keys)}

# After:
all_keys = list(dict.fromkeys(default_keys + (stat_keys or [])))
self._stats: dict[str, int] = {k: 0 for k in all_keys}
```

This makes custom keys additive — router_cache's `skipped_context_dependent` is added alongside the standard keys, not replacing them.

**Verify:** `cd backend && pytest tests/test_cache_core.py -v`

---

### Task M5: MapMarkerItem DS token alignment
**Why:** Hardcoded hex color map duplicates `SPECIALIST_COLORS` from `frontend/lib/specialists.ts`.

**Files:**
1. `frontend/components/map/MapMarkerItem.tsx`

**Changes:**
- Import `getSpecialistColor` from `frontend/lib/specialists.ts`
- Delete `SPECIALIST_MARKER_COLORS` dict (lines ~72-114)
- Replace usage at marker rendering with `getSpecialistColor(type)` call
- Keep `PIN_ICON` map (marker-specific, not a DS concern)

**Verify:** `cd frontend && npm run build` + visual check of map markers

---

### Task M6: Backend .env.example
**Why:** No onboarding reference for required env vars.

**Files:**
1. `backend/.env.example` (new)

**Content:** Extract all env var names from `backend/app/config.py` Settings class. Group by purpose (Database, API Keys, Models, Cache, Spend Guard, Debug). Use placeholder values only — never real keys.

**Verify:** All field names in Settings class have a corresponding entry.

---

## Wave 2 — Component Size Reduction (sequential, after Wave 1)

### Task M1: Split NomadicLanding (588 lines → target ≤200 each)
**Files:** `frontend/components/layout/NomadicLanding.tsx` + 2-3 new files
- Extract hook logic into `useNomadicLanding.ts`
- Extract discrete UI sections (header area, main content, sheets) into sub-components

### Task M2: Split ChatPanel (555 lines → target ≤200 each)
**Files:** `frontend/components/chat/ChatPanel.tsx` + 2-3 new files
**Depends on:** M1 complete

### Task M3: Split PlanFullDensityView (512 lines → target ≤200 each)
**Files:** `frontend/components/plan/PlanFullDensityView.tsx` + 2-3 new files
**Depends on:** M2 complete

> **Note:** M1-M3 are sequenced to avoid merge conflicts in the frontend. Each requires its own exploration phase to identify safe split boundaries. Remaining 25 components over 200 lines are lower priority and can be addressed incrementally.

---

## Wave 3 — Error Boundaries (after Wave 2 splits settle)

### Task M7: Add local error boundaries
**Files:** 2-3 parent component files
- Wrap `ChatModuleSheets` mount point (in ChatPanel) with `<ErrorBoundary>`
- Wrap `ItineraryDndWrapper` mount point (in PlanTimelineSection) with `<ErrorBoundary>`
- Use existing `frontend/components/ui/ErrorBoundary.tsx` — no new boundary component needed

**Depends on:** M1-M3 (to avoid touching files mid-split)

---

## Execution Summary

| Wave | Tasks | Total files | Parallelizable |
|------|-------|-------------|----------------|
| 1 | C1, C2, H1, H2, H3, M4, M5, M6 | ~14 | Yes (all independent) |
| 2 | M1, M2, M3 | ~9-12 | No (sequential) |
| 3 | M7 | 2-3 | After Wave 2 |

**Total estimated files:** ~25-29 across all waves
