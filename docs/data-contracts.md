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

### Admin (12 endpoints, dev/debug only)

Cache management: `GET/POST /api/admin/{specialist,tile,router}-cache-stats`, `clear-*-cache`, `clear-all-caches`, `clear-all-checkpoints`, `clear-validation-cache`, `fresh-start`. Config: `GET /api/admin/planner`, `GET /api/admin/graph-stats`.

---

## 2. Streaming Protocols

### SSE (`/api/graph_plan/stream`)

Media type: `text/event-stream`. Events:

| Event | Data | Purpose |
|-------|------|---------|
| `token` | `{type: "token", data: "..."}` | Streaming text chunk |
| `node_status` | `{node: "...", status: "..."}` | Node processing progress |
| `complete` | `{type: "complete", data: {document, session_state, version, ...}}` | Full response envelope |
| `error` | `{type: "error", message: "..."}` | Error details |

### NDJSON (`/api/expand-itinerary`, `/api/remove-specialist`)

Media type: `application/x-ndjson`. Events:

| Event | Data | Purpose |
|-------|------|---------|
| `progress` | `{type: "progress", stage: "itinerary", message: "...", pct: 30}` | Progress update |
| `envelope` | `{type: "envelope", plan_envelope: {...}}` | Partial plan update |
| `done` | `{type: "done", plan_view_state: "S3_ITINERARY_READY"}` | Completion signal |
| `error` | `{type: "error", message: "..."}` | Error details |

### CSRF

- Reads `csrf` cookie (JS-readable, not HttpOnly)
- Adds `X-CSRF-Token` header on unsafe methods (POST, PUT, PATCH, DELETE)

---

## 3. Core Schema Reference

Source: `backend/app/schemas.py`

### PlanDocumentData (Master Document)

```
PlanDocumentData
  |-- trip_inputs: DocumentTripInputs
  |     |-- destination?, origin?, start_date?, end_date?
  |     |-- adults?, children?, budget?, currency
  |     |-- booking_types: BookingTypes (tri-state: off|suggested|on)
  |     |-- flight_settings, hotel_settings, activity_settings, transport_settings
  |     '-- date_flex, trip_duration?, date_window_start/end?
  |
  |-- branches: DocumentBranch[]
  |     |-- id, label, description, is_primary
  |     |-- tiles: BranchTileIds (stays[], flights[], activities[])
  |     |-- selections: BranchSelections (stay, flight, activities[])
  |     '-- enrichment: vibe?, focus?, highlights[], flow[], notes[]
  |
  |-- tiles: {tile_id -> Tile}
  |     |-- id, type (flight|hotel|activity), title, subtitle?
  |     |-- price_estimate?, live_price?, currency, deeplink_url
  |     |-- geo: {lat, lon}?, tags[], source_agent? (specialist origin)
  |     '-- provider (expedia|booking|unknown), cancel_policy_summary?
  |
  |-- strategy_sections: StrategySection[]
  |     |-- id, title, specialist_type?, feasibility_status/reason?
  |     |-- one_liner?, principles[] (<=4)
  |     |-- must_dos[], optional_upgrades[], logistics_notes[]
  |     |-- content_blocks[], booking_artifacts
  |     '-- destination_gallery[], trip_summary?
  |
  |-- day_cards: DayCard[]
  |     |-- day_number, date?, label, subtitle?
  |     '-- blocks: DayBlock[]
  |           |-- period (morning|afternoon|evening), activity_type, summary
  |           |-- is_buffer, buffer_type?, coordinates: {lat, lng}?
  |           |-- booked_tile?, preference_status?, scheduled_time?
  |           '-- specialist_type?, requires_booking, booking_category?
  |           NOTE: activity_type carries the display title for the card
  |           (e.g. "Potato Head Beach Club"). specialist_type carries the
  |           category for filtering/coloring (e.g. "nightlife", "diving").
  |
  |-- plan_state: PlanState, ui_phase: UIPhase, plan_view_state: PlanViewState
  |-- readiness: ReadinessItem[], destination_card?, booking_status?
  |-- conflicts[], constraints_validated[], constraint_violations[]
  |-- preferred_tile_ids[] (hearted tiles, 1.5x weight)
  |-- needs_refresh, can_expand_to_itinerary, ready_to_generate
  '-- assistant_message?, suggested_responses[]
```

### Key Request/Response Models

| Model | Purpose |
|-------|---------|
| `GraphPlanRequest` | Plan generation: message, trip_inputs, session_state, document_id, ui_phase |
| `GraphPlanResponse` | Response: document (PlanDocumentData), session_state, version, observability |
| `ExpandItineraryRequest` | Stage 2->3: idempotency_key, strategy_sections, tiles, preferences |
| `RemoveSpecialistRequest` | Conflict resolution: keep_specialist, remove_hearted_tiles |
| `PlanDocumentPatch` | CRDT update: version, branches?, tiles?, selections?, trip_inputs? |
| `PlanDocumentResponse` | Document fetch: version, updated_by, document, updated_at |
| `TileRefreshRequest/Response` | Refresh tiles for branch with new settings |

---

## 4. Enums & State Machines

### PlanViewState (density-driven rendering)

```
P0_MINIMAL -> P1_ENRICHED -> P2_LOGISTICS -> P3_FINALIZED
                                              |-- P3_EDITING
                                              '-- P3_BLOCKED

Legacy aliases (still emitted): S0_BOOTSTRAP, S1_FRAMING, S2_STRATEGY_READY,
                                 S2_BLOCKED, S3_ITINERARY_READY, S3_EDITING, S3_BLOCKED
```

### Other Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `PlanState` | INCOMPLETE, RESOLVING, STABLE, LOCKED | Backend-authoritative plan state |
| `UIPhase` | bootstrap, expanded | Chips-only vs full planner |
| `ViewMode` | planning, booking | Two-mode system |
| `BookingTypeState` | off, suggested, on | Tri-state per booking category |
| `ResolverStep` | processing_constraints, matching_inventory, updating_itinerary | Progress within RESOLVING |
| `ReadinessKey` | origin, destination, start_date, end_date, travelers, budget | Constraint completeness |
| `BookingState` | idle, loading, ready, error | Per-tab booking status |
| `TileType` | flight, hotel, activity | Tile category |
| `TileProvider` | expedia, booking, unknown | Booking partner |

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
| Regeneration | `lastGeneratedPreferences`, `isRegenerating`, `isPending`, `expandInProgress` |
| Streaming | `currentRunId`, `abortController` |
| Cart | `cartTileIds` (Set) |
| LLM Updates | `llmUpdatedFields` (Set of field names LLM recently modified) |

### Key Actions

| Action | Purpose |
|--------|---------|
| `setFromPlanResponse()` | Merge backend GraphPlanResponse into store |
| `mergeEnvelope()` | Streaming update: tiles, sections, day_cards, plan_view_state |
| `commitTripInputs()` | Async PATCH with optimistic update + rollback |
| `fetchDocument()` | GET /api/document |
| `patchDocument()` | PATCH /api/document |
| `toggleTilePreference()` | Heart/unheart a tile |
| `startGeneration()` / `abortGeneration()` / `completeGeneration()` | Streaming lifecycle |

### State Guards

- **Destination lock:** Once set, destination can't change unless S0_EMPTY reset
- **View state downgrade protection:** Never downgrade plan_view_state when itinerary exists
- **Destination/date change detection:** Triggers chat reset + tile/section clearing

---

## 6. Frontend API Client

Source: `frontend/lib/api.ts`

### Functions

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `streamGraphPlan()` | POST `/api/graph_plan/stream` | SSE streaming (onToken, onComplete, onError, onNodeStatus callbacks). Returns abort fn. |
| `validateTripInput()` | POST `/api/validate-trip-input` | LLM-based validation |
| `fetchDestinationImage()` | POST `/api/destination-image` | Unsplash image |
| `refreshTiles()` | POST `/api/tiles/refresh` | Refresh tiles for branch |
| `trackSuggestionClick()` | POST `/api/suggestions/click` | Fire-and-forget analytics |
| `resetSession()` | DELETE `/api/session` | Clear session |

### Retry Logic

- Transient errors: timeout, network, 502, 503, 504, 429
- Exponential backoff: `delay = baseDelay * 2^attempt + random(0-500ms)`
- Default: 3 max retries, 1s base, 10s max
- AbortError never retried
