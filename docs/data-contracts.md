# Data Contracts — Frontend-Backend Boundary

> **Source files:** `backend/app/schemas.py`, `backend/app/main.py`, `frontend/state/documentStore.ts`, `frontend/lib/api.ts`, `frontend/types/plan-envelope.ts`

---

## 1. API Route Reference

### Planning (Core Graph Execution)

| Method | Path | Purpose | Request | Response | Streaming |
|--------|------|---------|---------|----------|-----------|
| POST | `/api/graph_plan` | Non-streaming plan generation | `GraphPlanRequest` | `GraphPlanResponse` | -- |
| POST | `/api/graph_plan/stream` | Streaming plan generation | `GraphPlanRequest` | SSE | **SSE** |
| POST | `/api/expand-itinerary` | Strategy -> full itinerary | `ExpandItineraryRequest` | NDJSON | **NDJSON** |
| POST | `/api/remove-specialist` | Remove specialist & regenerate | `RemoveSpecialistRequest` | NDJSON | **NDJSON** |

### Validation & Metadata

| Method | Path | Purpose | Request | Response |
|--------|------|---------|---------|----------|
| POST | `/api/validate-trip-input` | LLM-based origin/destination validation | `TripInputValidationRequest` | `TripInputValidationResponse` |
| POST | `/api/destination-image` | Unsplash banner image for destination | `DestinationImageRequest` | `DestinationImageResponse` |

### Tiles & Suggestions

| Method | Path | Purpose | Request | Response |
|--------|------|---------|---------|----------|
| POST | `/api/tiles/click` | Track tile click (analytics) | `TileClickEvent` | `{status: "ok"}` |
| POST | `/api/tiles/refresh` | Refresh tiles for branch | `TileRefreshRequest` | `TileRefreshResponse` |
| POST | `/api/document/tiles/{branch_id}` | Fetch tiles for branch | -- | `PlanDocumentResponse` |
| POST | `/api/suggestions/click` | Track suggestion click | `SuggestionClickEvent` | `{status: "ok"}` |
| POST | `/api/document/fill-day` | Generate activity tiles for a free day | `FillDayRequest{day_number, categories?, pinned_tile_ids?}` | `{day_number, tiles_added, day_card, tiles?, version}` |

### Documents (Plan State)

| Method | Path | Purpose | Request | Response | Notes |
|--------|------|---------|---------|----------|-------|
| GET | `/api/document` | Get current plan document | -- | `PlanDocumentResponse` | 204 if no doc |
| PATCH | `/api/document` | CRDT-style partial update | `PlanDocumentPatch` | `PlanDocumentResponse` | Optimistic locking via version |

### Chat & Session

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/chat` | Chat history (last 50) | `ChatHistoryResponse` |
| DELETE | `/api/chat/last` | Delete last user msg + undo | `DeleteLastMessageResponse` |
| DELETE | `/api/session` | Reset session & clear state | 204 No Content |
| GET | `/health` | Health check | JSON |

### Admin (13 endpoints, gated by `X-Admin-Key` header)

All admin routes require `X-Admin-Key` header matching `ADMIN_API_KEY` env var. Rate limited: 10/min.

Cache stats (GET): `specialist-cache-stats`, `tile-cache-stats`, `router-cache-stats`, `cache-stats` (unified). Cache clear (POST): `clear-specialist-cache`, `clear-tile-cache`, `clear-router-cache`, `clear-all-caches`, `clear-all-checkpoints`, `clear-validation-cache`, `fresh-start`. Config (GET): `planner`, `graph-stats`.

---

## 2. Streaming Protocols

### SSE (`/api/graph_plan/stream`)

Media type: `text/event-stream`. Events:

| Event | Data | Purpose |
|-------|------|---------|
| `token` | `{type: "token", data: "..."}` | Streaming text chunk |
| `node_status` | `{node: "...", status: "started"\|"completed", label, icon_key, estimated_duration_ms}` | Node processing progress. `label`, `icon_key`, `estimated_duration_ms` only present on `started` events. Special node `logic_reveal` emits routing decisions (e.g., `label: "ROUTING: DIVING"`, status: `"completed"`). Frontend type also defines `stage?, tier?, topic?, max_tokens?` but these are not currently emitted by the backend. |
| `complete` | `{type: "complete", data: {document, session_state, version, ...}}` | Full response envelope. `document` includes `day_cards` (when builder ran), `suggested_responses`, `suggested_response_meta`, `constraints_validated`, `constraint_violations`, `tiles_replaced` — all passed through from graph output. When `day_cards` present, `plan_view_state` is promoted to `S3_ITINERARY_READY`. `suggested_responses` falls back to `metadata.synthesizer_output.suggested_replies` when `state.suggested_replies` is empty (GraphState parse failure recovery). |
| `error` | `{type: "error", message: "..."}` | Error details |

### NDJSON (`/api/expand-itinerary`, `/api/remove-specialist`)

Media type: `application/x-ndjson`. Events:

| Event | Data | Purpose |
|-------|------|---------|
| `progress` | `{type: "progress", stage: "structure"\|"strategy"\|"itinerary", message: "...", pct: 30}` | Progress update |
| `envelope` | `{type: "envelope", plan_envelope: {...}}` | Partial plan update |
| `done` | `{type: "done", plan_view_state: "S3_ITINERARY_READY", version?, dropped_preferred_count?, warnings?[]}` | Completion signal |
| `error` | `{type: "error", message: "..."}` | Error details |

### CSRF

- Reads `csrf` cookie (JS-readable, not HttpOnly)
- Adds `X-CSRF-Token` header on unsafe methods (POST, PUT, PATCH, DELETE)
- Exempt paths: `/health`, `/docs`, `/redoc`, `/openapi.json` only

### Rate Limiting (`slowapi`)

Keyed by session cookie → IP fallback. CORS preflight (`OPTIONS`) requests share a single `__preflight__` bucket so they never exhaust a real user's rate limit. Tiered:

| Tier | Endpoints | Limit |
|------|-----------|-------|
| **Heavy** | `graph_plan/*` (non-stream), `remove-specialist` | 3/min, 15/hr |
| **Heavy (stream)** | `graph_plan/stream` | 10/min, 40/hr |
| **Heavy (builder-only)** | `expand-itinerary` | 20/min (no LLM — frontend mutex prevents abuse) |
| **Medium** | `validate-trip-input`, `destination-image`, `tiles/refresh` | 15/min |
| **Medium-Low** | `document/fill-day` | 10/min |
| **Light** | `document` (GET+PATCH), `document/tiles/{branch_id}`, `chat`, `chat/last`, `session`, `tiles/click`, `suggestions/click` | 60/min |
| **Admin** | `/api/admin/*` | 10/min (+ `X-Admin-Key` required) |

### Security Middleware

- **Body size limit:** 512KB max (`Content-Length` check before Pydantic parsing)
- **Security headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- **Session middleware:** Skips `/health` (no session cookie overhead on health checks). Max 10 new sessions per IP per hour
- **SSE connection limit:** Max 2 concurrent streams per session, 5 per IP
- **Frontend CSP:** Configured in `next.config.mjs` — `unsafe-eval` allowed in dev only

---

## 3. Core Schema Reference

Source: `backend/app/schemas.py`

### PlanDocumentData (Master Document)

```
PlanDocumentData
  |-- trip_inputs: DocumentTripInputs
  |     |-- destination?, origin?, start_date?, end_date?
  |     |-- adults?, children?, budget?, currency
  |     |-- requires_assistance?, missing_fields[]
  |     |-- booking_types: BookingTypes (tri-state: off|suggested|on)
  |     |-- flight_settings, hotel_settings, transport_settings
  |     |-- activity_settings: {categories[], skill_level?, day_preferences: {activity: count}}
  |     '-- date_flex, trip_duration?, date_window_start/end?
  |
  |-- branches: DocumentBranch[]
  |     |-- id, label, description, is_primary
  |     |-- destination, origin, start_date, end_date
  |     |-- adults, children, requires_assistance, budget, currency
  |     |-- image_url, hero_images
  |     |-- tiles: BranchTileIds (stays[], flights[], activities[])
  |     |-- selections: BranchSelections (stay, flight, activities[])
  |     '-- vibe?, focus?, highlights[], flow[], notes[]
  |
  |-- tiles: {tile_id -> Tile}
  |     |-- id, type (flight|hotel|activity), title, subtitle?, image_url?
  |     |-- partner, partner_product_id, deeplink_url
  |     |-- price_estimate?, live_price?, currency, price_basis?, is_estimate_only?
  |     |-- price_display? (NOT on Pydantic model — injected at response time by response_envelope)
  |     |-- rating?, review_count?, location_label?, geo: {lat, lon}?
  |     |-- tags[], availability_status? (available|low|unknown|not_available), meta?, score?, source?, source_agent?
  |     |-- provider (expedia|booking|unknown), cancel_policy_summary?
  |     '-- total_inclusive?, tax_and_service_fee?, property_fee?, is_refundable?
  |
  |-- strategy_sections: StrategySection[]
  |     |-- id, title, subtitle?, specialist_type?
  |     |-- feasibility_status?, feasibility_reason?, alternative_suggestion?
  |     |-- one_liner?, principles[] (<=4)
  |     |-- must_dos[], optional_upgrades[], logistics_notes[], tradeoffs_summary?
  |     |-- content_blocks[], booking_artifacts, impact_areas[]
  |     |-- constraints_applied[], content_added[], bullets[]
  |     '-- destination_gallery[], trip_summary?
  |
  |-- day_cards: DayCard[]
  |     |-- day_number, date?, label, subtitle?
  |     |   NOTE: subtitle exists in the frontend type but not the backend Pydantic model (frontend-only field)
  |     '-- blocks: DayBlock[]
  |           |-- id?, period (morning|afternoon|evening), activity_type, summary
  |           |-- intensity? (light|moderate|challenging)
  |           |-- is_buffer, buffer_type?, buffer_reason?
  |           |-- specialist_type?, constraints[]
  |           |-- image_url?, duration?, coordinates: {lat, lng}?
  |           |-- scheduled_time?, logistics_details?, hotel_name?
  |           |-- booked_tile?, requires_booking, booking_category?
  |           '-- preference_status?, preference_override_reason?, alternative_tile_id?
  |           NOTE: activity_type carries the display title for the card
  |           (e.g. "Potato Head Beach Club"). specialist_type carries the
  |           category for filtering/coloring (e.g. "nightlife", "diving").
  |           Fill-day endpoint uses tile.title for activity_type and
  |           meta.category for specialist_type (matching ItineraryBuilder).
  |
  |-- trip_context_id, assistant_message_id
  |-- plan_state: PlanState, ui_phase: UIPhase, plan_view_state: PlanViewState
  |-- resolver?: ResolverState (present only when plan_state = RESOLVING)
  |-- readiness: ReadinessItem[], destination_card?, booking_status?
  |-- conflicts[], constraints_validated[], constraint_violations[]
  |-- preferred_tile_ids[] (hearted tiles, 1.5x weight)
  |-- executed_strategy_topics[], pending_strategy_topics[]
  |-- open_decisions[]
  |-- itinerary_overview, itinerary_assumptions
  |-- applied_updates[], undo_snapshot, update_provenance
  |-- ack_status, ack_updates[]
  |-- origin_just_set
  |-- tiles_replaced (bool: frontend should REPLACE tiles, not merge additively)
  |-- user_pinned_tiles: {tile_id -> {tile, source, category, preferred_day}} (Browse→Add persistence)
  |-- needs_refresh, can_expand_to_itinerary, ready_to_generate
  |-- assistant_message?, suggested_responses[]
  |-- suggested_response_meta?: SuggestionChipMeta[] (parallel to suggested_responses)
  |     {chip_type: "cta"|"follow_up"|"setting", category: string, icon?: string}
  '-- _debug?: {router_extraction_failed: boolean}  (observability, always present in SSE)
```

### Key Request/Response Models

| Model | Purpose |
|-------|---------|
| `GraphPlanRequest` | Plan generation: message, trip_inputs, session_state, document_id, ui_phase, expected_version, thread_id, reset, suggestion_clicked |
| `GraphPlanResponse` | Response: document (PlanDocumentData), session_state, version, observability, updated_by, updated_at, changes_made, request_id |
| `ExpandItineraryRequest` | Stage 2->3: idempotency_key, strategy_sections, tiles, preferences, trip_inputs, force_full_rebuild. **Tile source selection:** `force_full_rebuild=true` (auto-expand after chat) uses DB tiles (authoritative — written by `apply_planner_update`); `force_full_rebuild=false` (preference regen / manual) uses frontend tiles (includes hearted tiles, filters); empty frontend tiles falls back to DB tiles. |
| `RemoveSpecialistRequest` | Conflict resolution: keep_specialist, remove_hearted_tiles, idempotency_key, trip_inputs, strategy_sections, tiles, preferences |
| `PlanDocumentPatch` | CRDT update: version, branches?, tiles?, selections?, trip_inputs?, remove_branch_ids?, remove_tile_ids?, preferred_tile_ids? |
| `PlanDocumentResponse` | Document fetch: version, updated_by, document, updated_at, changes_made: bool |
| `TileRefreshRequest/Response` | Refresh tiles for branch with new settings |

---

## 4. Enums & State Machines

### PlanViewState (density-driven rendering)

```
Backend-emitted states (from _compute_plan_view_state):
  S0_BOOTSTRAP → S1_FRAMING → S2_STRATEGY_READY → S3_ITINERARY_READY
                                |-- S2_BLOCKED        |-- S3_EDITING
                                                      '-- S3_BLOCKED

Defined in PlanViewState Literal but not yet emitted by backend:
  P0_MINIMAL, P1_ENRICHED, P2_LOGISTICS, P3_FINALIZED, P3_EDITING, P3_BLOCKED
  These are planned density-level replacements for the S-prefixed states.

Frontend-only states (not emitted by backend):
  S0_EMPTY — initial state before any interaction
  S1_DESTINATION_SET — destination chosen but no strategy yet
  S3_PARTIAL_CONFLICT — partial conflict during itinerary editing

Hydration guards:
  Downgrade protection (setFromPlanResponse, mergeEnvelope): S3→S2 blocked when day_cards exist
  Upward reconciliation (fetchDocument): stale state promoted when data contradicts it
    - day_cards exist + state < S3 (not BLOCKED/S3 variant) → S3_ITINERARY_READY
    - strategy_sections exist + state < S2 (not BLOCKED) → S2_STRATEGY_READY
```

### Other Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `PlanState` | INCOMPLETE, RESOLVING, STABLE, LOCKED | Backend-authoritative plan state |
| `UIPhase` | bootstrap, expanded | Chips-only vs full planner |
| `ViewMode` | planning, booking | Two-mode system (frontend-only, not a backend enum) |
| `BookingTypeState` | off, suggested, on | Tri-state per booking category |
| `ResolverStep` | processing_constraints, matching_inventory, updating_itinerary | Progress within RESOLVING |
| `ReadinessKey` | origin, destination, start_date, end_date, travelers, budget | Constraint completeness |
| `BookingState` | idle, loading, ready, error | Per-tab booking status |
| `TileType` | flight, hotel, activity | Tile category |
| `TileProvider` | expedia, booking, unknown | Booking partner |
| `AckStatus` | applied, partial, no_change, needs_clarification, failed, rejected | Update acknowledgement status. `rejected` used for route violations (e.g., same-city error). Backend Literal does NOT include `pending`; frontend types (`chat.ts`, `plan-envelope.ts`) add `pending` as a frontend-only value. |

---

## 5. Frontend State Store

Source: `frontend/state/documentStore.ts` (Zustand)

### Store Shape

| Category | Key Fields |
|----------|------------|
| Document | `version`, `updatedBy`, `updatedAt`, `document` (PlanDocumentData) |
| Loading | `isLoading`, `isCommitting`, `error` |
| Selection | `selectedBranchId` |
| View | `activeView` ('planning' \| 'booking'), `isPlanFinalized` |
| Preferences | `preferredTileIds` (Set), `pendingPreferencePatch` |
| Regeneration | `lastGeneratedPreferences`, `isRegenerating`, `isPending`, `expandInProgress`, `remainingSeconds` |
| Fill-day mutex | `_fillingDays` (Set\<number\>) — per-day concurrency guard |
| Mutation mutex | `_pendingMutations` (number) — general mutation counter (fill-day, drag-drop) |
| Streaming | `currentRunId`, `abortController` |
| Cart | `cartTileIds` (Set) |
| LLM Updates | `llmUpdatedFields` (Set of field names LLM recently modified) |

### Key Actions

| Action | Purpose |
|--------|---------|
| `setFromPlanResponse()` | Merge backend GraphPlanResponse into store (destination lock, view state guard, tile/section merge) |
| `mergeEnvelope()` | Streaming update: tiles, sections, day_cards, plan_view_state (with downgrade protection) |
| `updateTripInputs()` | Sync local trip input update (no API call) |
| `commitTripInputs()` | Async PATCH with optimistic update + rollback (handles 409 retry, 404 graceful) |
| `ensureSettingsFlushed()` | Flush only **dirty** settings before graph run (prevents overwriting backend-derived values) |
| `fetchDocument()` | GET /api/document (with upward view state reconciliation) |
| `patchDocument()` | PATCH /api/document (preserves frontend-only fields) |
| `toggleTilePreference()` | Heart/unheart a tile (single-select for hotels, multi-select for activities) |
| `clearPreferences()` | Clear all hearted tiles + sync to backend |
| `startGeneration()` / `abortGeneration()` / `completeGeneration()` | Streaming lifecycle (mutex via runId) |
| `isCurrentRun()` | Check if a runId is the current run (ignore stale events) |
| `selectTile()` / `deselectTile()` | Tile selection within a branch (uses patchDocument) |
| `restoreTripInputs()` | Restore trip inputs from undo snapshot |
| `acknowledgeLLMUpdate()` | Clear sparkle animation for a field |
| `mergeSpeculativeContent()` / `clearSpeculativeContent()` | Preload specialist sections during Setup phase |
| `replaceDayCard()` | Surgical single day card replacement (fill-day) |
| `setRegenerationState()` | Shared regeneration UI state (isRegenerating, isPending, remainingSeconds) |
| `setExpandInProgress()` | Expand-itinerary mutex flag |
| `claimFillDay(day)` | Per-day fill mutex: returns `false` if day already in flight (prevents concurrent fill-day on same day from different call sites) |
| `releaseFillDay(day)` | Release per-day fill mutex after fill-day completes or fails |
| `claimMutation()` / `releaseMutation()` | Increment/decrement `_pendingMutations` counter for general mutation tracking |
| `hasPendingMutations()` | Returns true when `_pendingMutations > 0` — ChatPanel mutation gate polls this before sending graph requests to avoid version conflicts |
| `markPreferencesAsApplied()` | Sync lastGeneratedPreferences after expand completes |
| `awaitPreferencePatch()` | Wait for pending preference PATCH to complete before proceeding |

| `setActiveView()` | Switch between 'planning' and 'booking' views |
| `setFinalized()` | Set plan finalization flag (gates Book view access) |
| `addToCart()` / `removeFromCart()` / `clearCart()` | Cart operations for booking mode |
| `hasAllRequiredFields()` | Computed selector: returns true when destination is set (only requirement) |
| `reset()` | Full store reset (aborts in-flight generation) |

**`usePreferenceAutoRegen` hook** (`frontend/hooks/usePreferenceAutoRegen.ts`): Watches `preferredTileIds` changes and triggers `expand-itinerary` regen. When `expandInProgress` mutex blocks, the hook queues the pending regen via `pendingRegenRef` and flushes it when the mutex clears (500ms debounce, dedup check against `lastGeneratedPreferences`). Avoids silently dropping preference changes made during an active expand.

### User-Dirty Settings Tracker

Module-level `_userDirtySettings: Set<string>` (not Zustand state — avoids re-renders). Each settings handler calls `markSettingDirty(key)` (e.g., `'activity_settings'`, `'hotel_settings'`). `ensureSettingsFlushed()` only PATCHes keys in the dirty set, then clears it. This prevents empty frontend defaults from overwriting backend-derived values (e.g., specialist-extracted categories like `["diving", "hiking"]`).

### State Guards

- **Destination lock:** Once set, destination can't change unless S0_EMPTY reset
- **View state downgrade protection:** Never downgrade plan_view_state when itinerary exists
- **Destination/date change detection:** Triggers chat reset + tile/section clearing
- **Fill-day version sync:** `fillDay()` in api.ts syncs `version` from response to store after success, preventing 409 cascade on subsequent calls
- **Graph-built itinerary skip:** `setFromPlanResponse` maps `itinerary_day_cards` → `day_cards` if present. ChatPanel's expand gate checks `graphBuiltItinerary` flag — skips expand-itinerary when graph already built day_cards
- **Mutation gate:** ChatPanel waits for `hasPendingMutations()` to clear (max 10s poll) before sending graph requests, preventing version conflicts from concurrent fill-day/drag-drop mutations

---

## 6. Frontend API Client

Source: `frontend/lib/api.ts`

### Functions

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `apiFetch()` | (all) | Base fetch wrapper: credentials, CSRF header, abort guard |
| `streamGraphPlan()` | POST `/api/graph_plan/stream` | SSE streaming (onToken, onComplete, onError, onNodeStatus callbacks). Returns abort fn. |
| `validateTripInput()` | POST `/api/validate-trip-input` | LLM-based validation |
| `fetchDestinationImage()` | POST `/api/destination-image` | Unsplash image |
| `refreshTiles()` | POST `/api/tiles/refresh` | Refresh tiles for branch (uses `fetchWithRetry`, 2 retries, 500ms base delay) |
| `fillDay()` | POST `/api/document/fill-day` | Generate activity tiles for a free day. Returns `tiles` map for store merge. |
| `trackSuggestionClick()` | POST `/api/suggestions/click` | Fire-and-forget analytics |
| `resetSession()` | DELETE `/api/session` | Clear session |
| `fetchWithRetry()` | (wraps apiFetch) | Exponential backoff retry on transient errors |
| `clearSessionLocalStorage()` | -- | Clear session-related localStorage (preserves GDPR consent) |
| `isTransientError()` | -- | Check if an error is retryable (timeout, network, 502/503/504) |
| `isTransientStatus()` | -- | Check if HTTP status is retryable (502, 503, 504, 429) |

### Retry Logic

- Transient errors: timeout, network, 502, 503, 504, 429
- Exponential backoff: `delay = min(baseDelay * 2^attempt, maxDelay) + random(0-500ms)`
- Default: 3 max retries, 1s base, 10s max
- AbortError never retried
