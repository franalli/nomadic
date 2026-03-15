# Data Contracts — Frontend-Backend Boundary

> **Source files:** `backend/app/schemas.py`, `backend/app/main.py`, `frontend/state/documentStore.ts`, `frontend/lib/api.ts`, `frontend/types/plan-envelope.ts`

---

## 1. API Route Reference

### Planning (Core Graph Execution)

| Method | Path                     | Purpose                        | Request                   | Response            | Streaming  |
| ------ | ------------------------ | ------------------------------ | ------------------------- | ------------------- | ---------- |
| POST   | `/api/graph_plan/stream` | Streaming plan generation      | `GraphPlanRequest`        | SSE                 | **SSE**    |
| POST   | `/api/expand-itinerary`  | Strategy -> full itinerary     | `ExpandItineraryRequest`  | NDJSON              | **NDJSON** |

### Validation & Metadata

| Method | Path                       | Purpose                                 | Request                      | Response                      |
| ------ | -------------------------- | --------------------------------------- | ---------------------------- | ----------------------------- |
| POST   | `/api/validate-trip-input` | LLM-based origin/destination validation | `TripInputValidationRequest` | `TripInputValidationResponse` |
| POST   | `/api/destination-image`   | Unsplash banner image for destination   | `DestinationImageRequest`    | `DestinationImageResponse`    |
| GET    | `/api/media/google-places-photo-url` | Issue session-bound signed URL for Places photo proxy | Query params: `name`, `max_width?`, `max_height?`, `ttl_seconds?` (default 3600s, capped by `google_places_photo_signed_ttl_max`) | `{url, expires_in_seconds}` |
| GET    | `/api/media/google-places-photo` | Session-bound Google Places photo proxy (signed; 503 when photos are disabled) | Query params: `name`, `max_width?`, `max_height?`, `exp`, `sig` | Image bytes (`image/*`) |

### Tiles & Suggestions

| Method | Path                              | Purpose                                | Request                                                     | Response                                                                                                                      |
| ------ | --------------------------------- | -------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/api/tiles/click`                | Track tile click (analytics)           | `TileClickEvent`                                            | `{status: "ok"}`                                                                                                              |
| POST   | `/api/tiles/refresh`              | Refresh tiles for branch               | `TileRefreshRequest`                                        | `TileRefreshResponse`                                                                                                         |
| POST   | `/api/document/tiles/{branch_id}` | Fetch tiles for branch                 | --                                                          | `PlanDocumentResponse`                                                                                                        |
| POST   | `/api/document/fill-day`          | Generate activity tiles for a free day | `FillDayRequest{day_number, categories? (max 16), pinned_tile_ids?}` | `{day_number, tiles_added, day_card?, tiles?, version, excluded_categories?: string[], rejected?, rejection_reason?, rejection_code?, rejection_suggestion?}` |
| POST   | `/api/document/validate-arrangement` | Pure Python constraint check on proposed block moves (<50ms, no LLM) | `ArrangementValidateRequest{moves: BlockMove[]}` | `ArrangementResult{valid, violations: BlockViolation[]}` |
| POST   | `/api/document/apply-arrangement` | Validate + persist block moves with optimistic concurrency | `ArrangementApplyRequest{moves: BlockMove[], expected_version: int}` | `ArrangementResult{valid, violations, day_cards?, version?}` |
| POST   | `/api/document/remove-block` | Remove a single block from the itinerary (pure Python, <10ms, no LLM) | `RemoveBlockRequest{block_id, day_number, expected_version}` | `RemoveBlockResponse{day_number, day_card, version, removed_block_id}` |
| POST   | `/api/document/restore-snapshot` | Restore day_cards to a previous snapshot (undo stack; pure Python, <10ms, no LLM) | `RestoreSnapshotRequest{day_cards, expected_version}` | `RestoreSnapshotResponse{day_cards, version}` |
| POST   | `/api/activities/browse`               | Browse activities for a free/buffer day (partner-first: Viator, GYG supplement, Google Places fallback/supplement) | `BrowseActivitiesRequest{destination, day_number?, date?, hotel_location?, categories?}` | `{tiles: BrowseTile[], total: int, source: "stashed"\|"places"}` |
| POST   | `/api/document/insert-activity-block`  | Insert a browse tile as a block into a day (pure Python, no LLM) | `InsertActivityBlockRequest{day_number, tile, expected_version?}` | `InsertActivityBlockResponse{day_number, day_card, version, inserted_block_id}` |
| GET    | `/api/specialist/{section_id}/enrichment` | Fetch Phase B enrichment status for a specialist section (`local_expert` long-polls up to 6s before returning 202 pending) | -- | `SpecialistEnrichmentResponse{section_id, status: 'ready'\|'pending'\|'failed', data?, error_code?, retry_after_ms?}` |

### Documents (Plan State)

| Method | Path            | Purpose                   | Request             | Response               | Notes                                                                       |
| ------ | --------------- | ------------------------- | ------------------- | ---------------------- | --------------------------------------------------------------------------- |
| GET    | `/api/document` | Get current plan document | --                  | `PlanDocumentResponse` | 204 if no doc                                                               |
| PATCH  | `/api/document` | CRDT-style partial update | `PlanDocumentPatch` | `PlanDocumentResponse` | Last-writer-wins: reloads doc on version drift, includes universal no-op dedupe for pure `trip_inputs` patches (returns `changes_made=false`) |

### Sharing

| Method | Path                 | Purpose                              | Request | Response                   | Auth |
| ------ | -------------------- | ------------------------------------ | ------- | -------------------------- | ---- |
| POST   | `/api/share`         | Create frozen shareable trip snapshot | --      | `ShareTripResponse`        | Session + CSRF required |
| POST   | `/api/share/fork/{slug}` | Copy shared snapshot into caller-owned session document | -- | `ForkSharedTripResponse` | Session + CSRF required |
| GET    | `/api/shared/{slug}` | Public read-only shared trip payload | --      | `SharedTripPublicResponse` | Public |

`POST /api/share` persists a frozen snapshot of `trip_inputs`, `tiles`, `strategy_sections`, `day_cards`, `plan_view_state`, `executed_strategy_topics`, `constraint_violations`, and `preferred_tile_ids`. Signed `/api/media/*` proxy URLs are stripped before storage so public share pages never depend on session-bound media signatures. Anonymous shares expire after 90 days; authenticated shares are promoted to durable user-owned rows with `expires_at = null`.
`POST /api/share/fork/{slug}` copies that snapshot into a fresh caller-owned session and rotates the browser `session_id` + `csrf` cookie pair before the frontend reloads onto the forked document.

### Authentication

| Method | Path                        | Purpose                                   | Request                     | Response                | Auth |
| ------ | --------------------------- | ----------------------------------------- | --------------------------- | ----------------------- | ---- |
| GET    | `/api/auth/google/url`      | Build Google OAuth consent URL + set state cookie | --                    | `GoogleAuthUrlResponse` | Public |
| POST   | `/api/auth/google/callback` | Exchange OAuth code and attach session to user | `GoogleAuthCallbackRequest` | `AuthMeResponse` | Session + CSRF required |
| GET    | `/api/auth/me`              | Get current user for active session       | --                          | `AuthMeResponse`        | Session optional (returns `user: null`) |
| POST   | `/api/auth/logout`          | Invalidate current auth session token and clear cookies | --              | `{ok: true}`            | Session + CSRF required |

Auth flow contract:
- `GET /api/auth/google/url` sets a short-lived HttpOnly `oauth_state` cookie (10 minutes) and returns the Google consent URL targeting `FRONTEND_ORIGIN/auth/callback`.
- `POST /api/auth/google/callback` validates `state`, exchanges the code with Google, links the current browser session to a `users` row, rotates the browser `session_id` + `csrf` cookie pair together, and clears `oauth_state`.
- If a browser session is already linked to another user, callback flow creates a replacement session before linking to prevent cross-account reuse on shared browsers or tabs.

### Trips (User Scoped)

| Method | Path         | Purpose                                      | Request | Response            | Auth |
| ------ | ------------ | -------------------------------------------- | ------- | ------------------- | ---- |
| GET    | `/api/trips` | List plan documents across sessions for current authenticated user | -- | `UserTripsResponse` | Authenticated user required |
| POST   | `/api/trips/{trip_id}/resume` | Resume a specific owned trip by switching session cookie to that trip session | -- | `ResumeTripResponse` | Authenticated user + CSRF required |

`GET /api/trips` returns up to 50 most recently updated plan documents across all sessions linked to the authenticated user. `POST /api/trips/{trip_id}/resume` rotates the browser `session_id` + `csrf` cookie pair onto the owning trip session; frontend then reloads and rehydrates from that session's `/api/document`.

### Chat & Session

| Method | Path             | Purpose                     | Response                    |
| ------ | ---------------- | --------------------------- | --------------------------- |
| GET    | `/api/chat`      | Chat history (last 50)      | `ChatHistoryResponse`       |
| DELETE | `/api/chat/last` | Delete last user msg + undo | `DeleteLastMessageResponse` |
| POST   | `/api/session/new` | Start a fresh planning session while preserving auth linkage | 204 No Content |
| DELETE | `/api/session`   | Reset session & clear state | 204 No Content              |
| GET    | `/health`        | Health check                | JSON                        |

`POST /api/session/new` creates a new session row, carries forward the current `user_id`, rotates both `session_id` and `csrf` cookies, and keeps at most three recent trip-backed sessions per user by evicting older trip data. Unlike `DELETE /api/session`, it does not destroy the caller's prior trip by default.

### Admin (17 endpoints, gated by `X-Admin-Key` header)

All admin routes require `X-Admin-Key` header matching `ADMIN_API_KEY` env var. Most admin routes are limited to `10/min`; `POST /api/admin/clear-spend-guard` is limited to `5/min`.

Cache stats (GET): `specialist-cache-stats`, `tile-cache-stats`, `router-cache-stats`, `cache-stats` (unified), `spend-guard-stats`. Cache clear (POST): `clear-specialist-cache`, `clear-tile-cache` (L1+L2), `clear-router-cache`, `clear-l1-l2-caches` (force-wipes L1 memory caches + L2 response cache/unsplash cache rows, cancels in-flight browse/experience population, and drains Google Places geocode + country-code memory caches), `clear-all-caches` (clears planner/experience/router/browse/places-enrichment/iata caches + validation + the checkpoint-clear hook + unsplash; includes specialist and tile L1/L2 and response-cache types, cancels/busts in-flight browse + experience population, drains Google Places geocode + country-code caches, and clears the in-memory Places enrichment inflight dedupe map), `clear-all-checkpoints` (currently a no-op hook that reports zero checkpoints), `clear-validation-cache`, `clear-spend-guard`, `fresh-start`. Config (GET): `planner`, `graph-stats`. Telemetry (GET): `places-telemetry` (usage counters, circuit-breaker state, and geocode/country-code cache stats).

---

## 2. Streaming Protocols

### SSE (`/api/graph_plan/stream`)

Media type: `text/event-stream`. Events:

| Event         | Data                                                                                    | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `token`       | `{type: "token", data: "..."}`                                                          | Streaming text chunk                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `node_status` | `{type: "node_status", data: {node, status: "started"\|"completed", label, icon_key, estimated_duration_ms}}` | Coordinator step progress mapped to legacy node/tool names. Current payload contains only `node`, `status`, `label`, `icon_key`, `estimated_duration_ms`. Common values: `extract_trip_fields`, `get_specialist_advice`, `get_local_intel`, `search_tiles`, `build_itinerary`, `response`. `SHORT_CIRCUIT` emits no `node_status` event. |
| `complete`    | `{type: "complete", data: {document, session_state, version, ...}}`                     | Full response envelope. `document` includes `day_cards`, `itinerary_overview`, `itinerary_assumptions`, `hotel_filter_cascaded`, `suggested_responses`, `suggested_response_meta`, `suggestion_chips` (structured chips with action routing), `constraints_validated`, `constraint_violations`, `tiles_replaced`, and `ack_status`/`ack_updates`/`applied_updates`. When `day_cards` are present: `plan_view_state=S3_ITINERARY_READY` if conflict count is 0, `S3_EDITING` if conflicts exist, and `S3_PARTIAL_CONFLICT` on partial-failure path with returned day cards. When no concrete cards are produced: `S3_BLOCKED`. **`observability`** subfield currently emits `tokens`, `today_iso`, and `ready_to_generate_now`. Optional frontend fields such as `extraction_confidence`, `short_circuit_type`, `llm_calls_made`, `cache_hits`, and `confidence_routing` are reserved and not populated by backend today. |
| `partial`     | `{type: "partial", data: {kind: "strategy_sections"\|"tiles"\|"trip_inputs"\|"day_cards", payload: unknown}}` | Progressive render before `complete`. In the coordinator flow, emitted after classify/apply (`trip_inputs`), specialist/local-intel updates (`strategy_sections`), tile refresh (`tiles`, ID-keyed map matching `document.tiles`), and graph-built itinerary/card-conflict updates (`day_cards`). Tile partials may also carry `tiles_replaced=true` so the frontend can replace activity inventory immediately instead of waiting for the final envelope. Frontend merges via `store.mergeEnvelope(envelope, generation)` so stale events from prior send cycles are ignored. Errors must not crash stream -- wrapped defensively. `complete` event reconciles any differences. |
| `feasibility_warning` | `{type: "feasibility_warning", data: {topic, status, reason, alternative}}` | Coordinator-level feasibility signal for geographic-constrained specialists. Forwarded by `generate_sse()` as a public SSE event. Frontend handles via `onFeasibilityWarning` callback for toast display. |
| `error`       | `{type: "error", message: "..."}`                                                       | Error details                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

### NDJSON (`/api/expand-itinerary`)

Media type: `application/x-ndjson`. Events:

| Event      | Data                                                                                                     | Purpose             |
| ---------- | -------------------------------------------------------------------------------------------------------- | ------------------- |
| `progress` | `{type: "progress", stage: "itinerary", message: "...", pct: 30}`               | Progress update     |
| `envelope` | `{type: "envelope", plan_envelope: {...}}`                                                               | Partial plan update |
| `done`     | `{type: "done", message?: "duplicate_noop", plan_view_state?: "S3_ITINERARY_READY"|"S3_EDITING"|"S3_PARTIAL_CONFLICT", version?, dropped_preferred_count?, warnings?[]}` | Completion signal. Successful builds currently emit `S3_ITINERARY_READY` or `S3_EDITING`; idempotent duplicates can emit `message:"duplicate_noop"` without `plan_view_state`. |
| `error`    | `{type: "error", message: "..."}`                                                                        | Error details. `message` is usually plain text, but partial-conflict failures currently JSON-encode `{error:"CONSTRAINT_CONFLICT", conflicts[], resolutions[], day_cards[], plan_view_state, version}` into the same string field. |

**Frontend consumption:** `consumeNdjsonEnvelopeStream()` in `streamParser.ts` provides a shared NDJSON parser with typed callbacks (`onEnvelope`, `onProgress`, `onDone`, `onError`). Used by `startPreferenceAutoRegen()` and `useItineraryGenerationController.ts` expand-itinerary flows to avoid duplicated stream parsing. Parser JSON failures are logged and skipped (stream continues).

**`/api/expand-itinerary` date-flex early return:** when `trip_inputs.date_flex=true`, endpoint returns an immediate `error` event with:
`{"error":"FLEX_DATES_NOT_SUPPORTED","message":"Set fixed start and end dates to generate itinerary"}`.

**Activity category semantics (`/api/expand-itinerary`):**
- `booking_types.activities == "off"` is normalized to `activity_categories=[]` in builder input (explicit clear, skip activity placement),
- if activities are enabled and categories are omitted (`null`/`undefined`), builder receives `activity_categories=None` (no category filter),
- if categories are present, builder receives the explicit category list (including `[]` when intentionally provided).

### CSRF

- Reads `csrf` cookie (JS-readable, not HttpOnly)
- Adds `X-CSRF-Token` header on unsafe methods (POST, PUT, PATCH, DELETE)
- Any server-driven session rotation (`session/new`, shared-trip fork, Google OAuth callback, trip resume) rotates `session_id` and `csrf` together via the same helper so the readable token never lags the active session.
- Exempt paths: `/health`, `/api/session` (DELETE reset only), `/docs`, `/redoc`, `/openapi.json`

### Rate Limiting (`slowapi`)

Keying is route-aware: public/auth routes are IP-keyed; other routes use a trusted-session bucket only after the cookie/session token has been validated against the DB (`mark_trusted_session_id()`), with IP fallback for untrusted cookies. `request.state.validated_session_id` is also accepted when explicitly marked trusted. CORS preflight (`OPTIONS`) requests are exempt via `exempt_options_from_rate_limit` middleware (sets `_rate_limiting_complete` flag before the route handler runs, so slowapi skips the check entirely). Rate-limit exceeded responses return a numeric `Retry-After` header (seconds, parsed from slowapi's human-readable detail). Tiered:

| Tier                     | Endpoints                                                                                                                | Limit                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- |
| **Heavy (stream)**       | `graph_plan/stream`                                                                                                      | 6/min, 30/hr                                    |
| **Heavy (builder-only)** | `expand-itinerary`                                                                                                       | 10/min (can hit Google Places via `refresh_activity_categories` -- backend per-session mutex enforces one in-flight expand per session and returns 429 with `Retry-After: 5`; idempotency key released on failure to allow retries; frontend mutex also present) |
| **Media proxy**          | `media/google-places-photo`, `media/google-places-photo-url`                                                           | 120/min (proxy), 240/min (signed URL)           |
| **Medium**               | `destination-image`                                                                                                      | 15/min                                          |
| **Medium-Low**           | `validate-trip-input`, `tiles/refresh`                                                                                   | 6/min                                           |
| **Fill-day**             | `document/fill-day`                                                                                                      | 8/min                                           |
| **Browse**               | `activities/browse`                                                                                                      | 5/min                                           |
| **Share write**          | `share`                                                                                                                  | 5/min                                           |
| **Share fork**           | `share/fork/{slug}`                                                                                                      | 10/min                                          |
| **Shared public read**   | `shared/{slug}`                                                                                                          | 30/min (IP-only key)                            |
| **Auth init/callback**   | `auth/google/url`, `auth/google/callback`                                                                               | 10/min (IP-only key)                            |
| **Auth me/logout**       | `auth/me`, `auth/logout`                                                                                                 | 30/min / 10/min (IP-only key)                   |
| **Trips**                | `trips`, `trips/{trip_id}/resume`                                                                                        | 15/min                                          |
| **Session create**       | `session/new`                                                                                                            | 20/min                                          |
| **Light-read**           | `document` (GET+PATCH), `chat`, `chat/last`, `session`, `tiles/click`, `document/validate-arrangement`                   | 60/min                                          |
| **Light-fetch**          | `document/tiles/{branch_id}`                                                                                             | 12/min                                          |
| **Low-write**            | `document/apply-arrangement`, `document/remove-block`, `document/insert-activity-block`                                  | 30/min                                          |
| **Low-write (snapshot)** | `document/restore-snapshot`                                                                                              | 20/min                                          |
| **Enrichment**           | `specialist/{section_id}/enrichment`                                                                                     | 30/min                                          |
| **Admin**                | `/api/admin/*`                                                                                                           | 10/min by default; `clear-spend-guard` is 5/min (+ `X-Admin-Key` required) |

**Message-length fast 422:** `/api/graph_plan/stream` performs a message-length check before any DB work. Although `GraphPlanRequest.message` now validates up to 4000 chars at the schema layer, the endpoint still fast-rejects messages exceeding `GATE_THRESHOLDS["max_user_message_chars"]` (2000 chars) with an immediate HTTP 422. This short-circuits expensive downstream processing for oversized inputs.

### Security Middleware

- **Body size limit:** 512KB max. Middleware validates `Content-Length` first; non-numeric `Content-Length` returns `400 Invalid Content-Length`. If the header is missing on `POST`/`PUT`/`PATCH`, middleware streams/buffers the request body up to 512KB, returns `413 Payload too large` on overflow, and rehydrates the buffered body for downstream FastAPI/Pydantic consumers when the request is within limits. Early `400`/`413` middleware responses include CORS headers plus the lightweight security trio (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) so cross-origin frontend callers can read the error body without losing baseline protection.
- **Security headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security: max-age=63072000; includeSubDomains`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- **Backend CSP:** `Content-Security-Policy` header set on every response -- `default-src 'self'`, `script-src 'self' 'unsafe-inline'` (+ `'unsafe-eval'` in dev/local/test only for Next.js HMR), `style-src 'self' 'unsafe-inline'`, `img-src 'self' data: https://images.unsplash.com https://*.mapbox.com https://media.tacdn.com https://media-cdn.tripadvisor.com https://hare-media-cdn.tripadvisor.com https://cdn.getyourguide.com blob:`, `connect-src 'self' https://api.mapbox.com https://events.mapbox.com wss:`, `font-src 'self' data:`, `frame-ancestors 'none'`
- **Environment normalization:** `Settings.env` defaults to `"dev"`. Two computed properties: `is_dev` (True for `dev`, `local`, `development`, `test`) and `is_prod` (True for `prod`, `production`). All environment checks in `main.py` and `middleware/session.py` use these properties instead of hardcoded string comparisons.
- **Session middleware:** Skips `/health` and `/api/shared/*` (public shared reads stay cookie/session-free). Max 10 new sessions per IP per hour
- **Rate-limit keying:** Public/auth routes (`/api/shared/*`, `/api/auth/*`) are IP-keyed. Other routes use trusted session ids (validated cookie or `request.state.validated_session_id`) with IP fallback for untrusted values.
- **Rate-limit error contract:** 429 responses include numeric `Retry-After` and matching CORS headers for allowed origins; frontend `fetchWithRetry()` honours that header before retrying.
- **SSE connection limit:** Max 2 concurrent streams per session, 5 per IP (thread-safe slot reserve/release). Slots are acquired when the async generator actually starts and released from generator teardown, so abandoned/uniterated `StreamingResponse` objects do not leak capacity. SSE state extracted to `backend/app/sse_state.py` to break circular import between `main.py` and `lifespan.py`
- **Fill-day/session ordering:** `/api/document/fill-day` waits until no active graph SSE stream exists for that session
- **Places photo spend/circuit guard:** `/api/media/google-places-photo` requires a valid session, signed URL parameters, and circuit-state checks. It reserves Google Places spend via `spend_guard_scope`; if budget is exceeded it returns HTTP 429 with `Retry-After: 60`. If the photo circuit is open, endpoint returns HTTP 503 with `Service temporarily unavailable`.
- **Places photo feature flag:** when `GOOGLE_PLACES_PHOTOS_ENABLED=false`, both `/api/media/google-places-photo` and `/api/media/google-places-photo-url` return HTTP 503 and backend tile signing helpers skip signed photo URL generation.
- **Media proxy signing secret:** both signed URL generation and `/api/media/google-places-photo*` verification resolve their secret through `get_media_signing_secret()`, so the fallback chain is identical on both paths.
- **Frontend CSP:** Configured in `next.config.mjs` -- `unsafe-eval` allowed in dev only
- **Frontend remote images:** `next.config.mjs` allows Unsplash, Google/Mapbox, Viator/Tripadvisor CDN hosts (`media.tacdn.com`, `media-cdn.tripadvisor.com`, `hare-media-cdn.tripadvisor.com`), and GYG CDN (`cdn.getyourguide.com`) so affiliate activity images render through Next Image.

### Config Settings (`backend/app/config.py`)

Notable non-secret settings (beyond standard DB/API keys):

| Setting                          | Default              | Env Var                        | Purpose                                                     |
| -------------------------------- | -------------------- | ------------------------------ | ----------------------------------------------------------- |
| `google_places_cache_ttl_hours`  | 72                   | `GOOGLE_PLACES_CACHE_TTL_HOURS`| L2 Google Places tile cache TTL                             |
| `specialist_cache_ttl_hours`     | 168                  | `SPECIALIST_CACHE_TTL_HOURS`   | L2 specialist cache TTL                                     |
| `experience_cache_ttl_hours`     | 72                   | `EXPERIENCE_CACHE_TTL_HOURS`   | L2 experience cache TTL                                     |
| `google_places_enrichment_cache_ttl_hours` | 720        | `GOOGLE_PLACES_ENRICHMENT_CACHE_TTL_HOURS` | L2 cache TTL for Google Places activity enrichment payloads |
| `iata_cache_ttl_hours`           | 720                  | `IATA_CACHE_TTL_HOURS`         | L2 IATA resolver cache TTL                                  |
| `clear_l2_on_session_reset`      | false                | `CLEAR_L2_ON_RESET`            | Wipe L2 caches on session reset (dev only)                  |
| `google_maps_api_key`            | --                   | `GOOGLE_MAPS_API_KEY`          | Google Places API key                                       |
| `google_maps_api_secret`         | --                   | `GOOGLE_MAPS_API_SECRET`       | Google Places API secret                                    |
| `media_proxy_signing_key`        | `""`                 | `MEDIA_PROXY_SIGNING_KEY`      | Preferred override secret for signed Google Places media URLs |
| `router_model`                   | `gemini-2.5-flash`   | `ROUTER_MODEL`                 | LLM for router extraction + coordinator `classify_change()` |
| `local_expert_model`             | `gemini-2.5-flash`   | `LOCAL_EXPERT_MODEL`           | LLM for get_local_expert tool (function calling, phased response parsing and enrichment cleanup hooks) |
| `local_expert_use_llm`           | true                 | `LOCAL_EXPERT_USE_LLM`         | Feature flag -- set false to disable LLM in LocalExpert     |
| `specialist_model`               | `gpt-4o`             | `SPECIALIST_MODEL`             | LLM for get_specialist_advice tool domain reasoning (keep gpt-4o) |
| `specialist_fallback_model`      | --                   | `SPECIALIST_FALLBACK_MODEL`    | Optional fallback model when specialist_model fails         |
| `guard_model`                    | `gemini-2.5-flash`   | `GUARD_MODEL`                  | LLM for route/place validation fallback in constraint checks |
| `synthesizer_planning_model`     | `gemini-2.5-flash`   | `SYNTHESIZER_PLANNING_MODEL`   | LLM for coordinator conversational response generation       |
| `experience_model`               | `gemini-2.5-flash`   | `EXPERIENCE_MODEL`             | LLM for Tier 2 activity tile generation (experience_generator)|
| `iata_resolver_model`            | `gemini-2.5-flash`   | `IATA_RESOLVER_MODEL`          | LLM for airport IATA code resolution                        |
| `use_google_places_provider`     | false                | `USE_GOOGLE_PLACES_PROVIDER`   | Feature flag: enable Google Places for hotels and activities |
| `google_places_photos_enabled`   | true                 | `GOOGLE_PLACES_PHOTOS_ENABLED` | Feature flag: enable Google Places photo signing/proxy endpoints |
| `google_places_enrichment_enabled` | true               | `GOOGLE_PLACES_ENRICHMENT_ENABLED` | Kill switch: disable all Google Places enrichment calls |
| `viator_api_key`                | `""`                 | `VIATOR_API_KEY`               | Viator Affiliate API key for live activity pricing/images/deeplinks |
| `viator_enabled`                | false                | `VIATOR_ENABLED`               | Feature flag for Viator browse + enrichment flows |
| `viator_cache_ttl_hours`        | 1                    | `VIATOR_CACHE_TTL_HOURS`       | L1 TTL for Viator browse/match cache entries |
| `viator_api_url`                | `https://api.viator.com/partner` | `VIATOR_API_URL`    | Base URL for the Viator partner API client |
| `get_your_guide_api_key`        | `""`                 | `GET_YOUR_GUIDE_API_KEY`       | GYG affiliate API key for live activity pricing/images/deeplinks |
| `get_your_guide_enabled`        | false                | `GET_YOUR_GUIDE_ENABLED`       | Feature flag for GYG browse + enrichment flows |
| `get_your_guide_cache_ttl_hours`| 24                   | `GET_YOUR_GUIDE_CACHE_TTL_HOURS` | L1 TTL for GYG browse/match cache entries |
| `get_your_guide_api_url`        | `https://api.getyourguide.com/1` | `GET_YOUR_GUIDE_API_URL` | Base URL for the GYG partner API client |
| `aviasales_api_token`           | `""`                 | `AVIASALES_API_TOKEN`          | Travelpayouts API token for real-time flight search |
| `aviasales_marker`              | `""`                 | `AVIASALES_MARKER`             | Aviasales affiliate marker for deeplink attribution |
| `aviasales_enabled`             | false                | `AVIASALES_ENABLED`            | Feature flag for Aviasales real-time flight search |
| `aviasales_cache_ttl_hours`     | 1                    | `AVIASALES_CACHE_TTL_HOURS`    | TTL for Aviasales flight search cache entries |
| `booking_affiliate_aid`         | `""`                 | `BOOKING_AFFILIATE_AID`        | Optional Booking.com affiliate aid appended to hotel search deeplinks |
| `spend_guard_places_daily_cap_usd` | 2.00               | `SPEND_GUARD_PLACES_DAILY_CAP_USD` | Provider-level daily spend cap for Google Places API |
| `google_places_photo_signed_ttl_max` | 3600            | --                             | Max allowed signed Google Places photo URL TTL (seconds) |
| `langsmith_dev_sample_rate`      | 1.0                  | `LANGSMITH_DEV_SAMPLE_RATE`    | Fraction of dev sessions to trace (0.0=none, 1.0=all)       |
| `langsmith_prod_sample_rate`     | 0.15                 | `LANGSMITH_PROD_SAMPLE_RATE`   | Fraction of prod sessions to trace (recommended 0.15 steady-state) |
| `frontend_origin`                | `http://localhost:3000` | `FRONTEND_ORIGIN`           | Canonical frontend base URL for OAuth redirect and share URL generation |
| `cookie_domain`                  | --                   | `COOKIE_DOMAIN`                | Optional shared cookie domain for cross-subdomain auth/session cookies |
| `google_oauth_client_id`         | `""`                 | `GOOGLE_OAUTH_CLIENT_ID`       | Google OAuth client id for login flow                       |
| `google_oauth_client_secret`     | `""`                 | `GOOGLE_OAUTH_CLIENT_SECRET`   | Google OAuth client secret used in token exchange           |

`get_media_signing_secret()` is the canonical media-proxy signing fallback chain used by both
`backend/app/main.py` (URL verification) and
`backend/app/tile_service/google_places_provider.py` (signed URL generation):
`media_proxy_signing_key -> admin_api_key -> google_maps_api_secret -> google_maps_api_key`.
If the resolved value is empty, signed photo URL generation is skipped and the media endpoints return HTTP 503.

---

## 3. Core Schema Reference

Source: `backend/app/schemas.py`, `backend/app/planner/state/agent_state.py`

### NomadicAgentState (`backend/app/planner/state/agent_state.py`)

Extends LangChain's `AgentState` (which provides `messages` with `add_messages` reducer). Shared fields use `Annotated` reducers to support concurrent parallel tool updates.

```
NomadicAgentState (extends AgentState)
  |-- messages: list[AnyMessage]        (inherited, with add_messages reducer)
  |-- trip_plan: dict                   (serialized TripPlan core fields)
  |-- trip_settings: dict               (booking types, hotel stars, cabin class, ...)
  |-- tiles: dict                       ({"flights": [...], "hotels": [...], "activities": [...]})
  |-- strategy_sections: list           (strategy-section cards from specialist advice)
  |-- day_cards: list                   (itinerary day cards from build_itinerary)
  |-- constraints: list                 (active specialist constraints)
  |-- specialist_plans: dict            (coordinator specialist plan outputs keyed by topic, e.g. {"diving": {...}})
  |-- turn_meta: dict                   (per-turn metadata, reset each turn)
  '-- persistent_meta: dict             (cross-turn: plan_view_state, regen tier, ...)
```

### GraphState (`backend/app/planner/state/graph_state.py`)

Legacy 7-node graph state -- still exists as import target for shared types (`TripPlan`, `SpecialistConstraint`, `ConstraintSeverity`, etc.). The active planner uses `NomadicAgentState` above.

### Session / User / Shared Trip Persistence (`backend/app/db_models.py`)

- `Session.user_id` is now an optional FK to `users.id`, allowing multiple browser sessions to roll up under one account without changing `PlanDocument` ownership semantics.
- `User` stores Google identity fields: `google_id`, `email`, `name`, `avatar_url`, `last_login_at`.
- `SharedTrip` stores a public `slug`, optional `session_id`, optional `user_id`, immutable `snapshot`, denormalized metadata (`title`, `destination`, `hero_image_url`, `day_count`), `view_count`, and optional `expires_at`.
- `RuntimeState` stores shared short-lived runtime rows keyed by `state_key` with `state_type`, `scope`, optional `session_id` / `provider` / `day_key`, optional `expires_at`, and `value_micro_usd`. It backs both request-dedup leases (`state_type="lease"`) and spend-guard counters (`state_type="spend_counter"`).
- Session reset unlinks `SharedTrip.session_id` before deleting the session row so existing public share URLs survive anonymous session clears.
- Linking a session to a user promotes anonymous shared rows for that session by filling `user_id` and clearing `expires_at`.

### PlanDocumentData (Master Document)

```
PlanDocumentData
  |-- trip_inputs: DocumentTripInputs
  |     |-- destination?, destination_iata?, origin?, origin_iata?, country_code?
  |     |-- start_date?, end_date?
  |     |-- adults?, children?, budget?, currency
  |     |-- requires_assistance?, missing_fields[]
  |     |-- booking_types: BookingTypes (tri-state: off|suggested|on)
  |     |-- flight_settings, hotel_settings, transport_settings
  |     |    hotel_settings includes: min_stars, amenities[], style?, location?
  |     |-- activity_settings: {categories[], skill_level?, day_preferences: {activity: count}, activities_per_day (1-3, default 2)}
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
  |     |-- partner, partner_product_id, deeplink (deeplink_url is deprecated alias)
  |     |-- price_estimate?, live_price?, currency, price_basis?, is_estimate_only?
  |     |-- price_display? (NOT on Pydantic model -- injected at response time by complete envelope assembly)
  |     |-- rating?, review_count?, location_label?, geo: {lat, lng}?
  |     |-- category? (flight|hotel|activity|diving|hiking|etc.)
  |     |-- tags[], availability_status? (available|low|unknown|not_available), meta?, score?, source?, source_agent?
  |     |-- provider (expedia|booking|google_places|curated|mock|viator|gyg|unknown), cancel_policy_summary?
  |     '-- total_inclusive?, tax_and_service_fee?, property_fee?, is_refundable?
  |
  |-- strategy_sections: StrategySection[]
  |     |-- id, title, subtitle?, specialist_type?
  |     |-- feasibility_status?, feasibility_reason?, alternative_suggestion?
  |     |-- one_liner?, principles[] (<=4)
  |     |-- editorial_one_liner? (magazine-style hook for General/Local Expert cards)
  |     |-- vibe_trio?: [{label, image_url}] (mood images for General/Local Expert cards)
  |     |-- hero_image? (single action shot URL for niche specialist cards)
  |     |-- travel_intelligence?: Dict (12-category local knowledge from Local Expert)
  |     |-- local_expert_enrichment?: Dict (Phase A/B lifecycle: {state: 'pending'|'ready'|'failed', error_code?})
  |     |-- must_dos[], optional_upgrades[], logistics_notes[], tradeoffs_summary?
  |     |-- content_blocks[], booking_artifacts, impact_areas[]
  |     |-- constraints_applied[] (structured dict payload, accepts non-string values)
  |     |-- content_added[], bullets[]
  |     '-- destination_gallery[{label, image_url}], trip_summary?
  |
  |-- day_cards: DayCard[]
  |     |-- day_number, date?, label, subtitle?
  |     |   NOTE: subtitle exists in the frontend type but not the backend Pydantic model (frontend-only field)
  |     '-- blocks: DayBlock[]
  |           |-- id?, period (morning|afternoon|evening), activity_type, summary
  |           |-- intensity? (light|moderate|challenging)
  |           |-- is_buffer, buffer_type?, buffer_reason?
  |           |-- specialist_type?, constraints[]
  |           |-- active_constraints: ActiveConstraint[] (rendered badge list; each: {id, severity: 'info'|'warning'|'blocking', icon, title, description})
  |           |-- activity_domain?: 'tier1'|'tier2'
  |           |-- activity_provenance?: 'ai_suggested'|'user_browse_added'
  |           |-- map_type?: string (canonical map pin category e.g. "food", "cycling")
  |           |-- image_url?, duration?, coordinates: {lat, lng}?
  |           |-- scheduled_time?, logistics_details?, hotel_name?
  |           |-- booked_tile?, requires_booking, booking_category?
  |           |-- rating?: number (provider-supplied traveler rating; often Viator or GYG for live activity tiles)
  |           |-- review_count?: number (provider-supplied review volume when available)
  |           |-- price_level?: number (Google Places price level: 0=free, 1=$, 2=$$, 3=$$$, 4=$$$$)
  |           |-- price_estimate?: number (numeric price from tile data)
  |           |-- google_place_id?: string (Google Places ID)
  |           |-- deeplink?: string (Google Maps / Google Travel URL or partner booking URL such as Booking.com, Aviasales, Viator, or GYG)
  |           '-- preference_status?, preference_override_reason?, alternative_tile_id?
  |           NOTE: activity_type carries the display title for the card
  |           (e.g. "Potato Head Beach Club"). specialist_type carries the
  |           category for filtering/coloring (e.g. "nightlife", "diving").
  |           Fill-day endpoint uses tile.title for activity_type and
  |           meta.category for specialist_type (matching ItineraryBuilder),
  |           injects Tier-1 registry hard constraints into `constraints[]`, and
  |           normalizes `coordinates` from tile/meta payloads with itinerary-anchor
  |           fallback when generated tiles lack explicit coordinates. Coordinate
  |           extraction (`_extract_day_block_coordinates`, `_first_trip_anchor_coordinates`)
  |           now validates `isfinite()` and range (|lat|<=90, |lng|<=180).
  |
  |-- trip_context_id, assistant_message_id
  |-- plan_state: PlanState, ui_phase: UIPhase, plan_view_state: PlanViewState
  |-- resolver?: ResolverState (present only when plan_state = RESOLVING)
  |-- readiness: ReadinessItem[], destination_card?, booking_status?
  |-- conflicts[], constraints_validated[], constraint_violations[]
  |-- preferred_tile_ids[] (hearted tiles, 1.5x weight)
  |-- executed_strategy_topics[], pending_strategy_topics[]
  |-- open_decisions[]
  |-- itinerary_overview, itinerary_assumptions, hotel_filter_cascaded
  |-- applied_updates[], undo_snapshot, update_provenance
  |-- browseable_activities: Dict[] (provider-backed browse/fallback activity tile dicts for Browse Activities sheet; stashed by logistics_node)
  |-- ack_status, ack_updates[]  # AckStatus enum (see Section 4)
  |-- origin_just_set
  |-- tiles_replaced (bool: frontend should REPLACE tiles, not merge additively)
  |-- user_pinned_tiles: {tile_id -> {tile, source, category, preferred_day}} (Browse->Add persistence)
  |-- needs_refresh, can_expand_to_itinerary, ready_to_generate
     NOTE: `ready_to_generate` is true only when `destination`, `start_date`, and `end_date` are present and `date_flex=false`.
     It is false when `date_flex=true` (planning-only mode) because concrete itinerary generation requires fixed dates.
  |-- assistant_message?, suggested_responses[]
  |-- suggested_response_meta?: SuggestionChipMeta[] (parallel to suggested_responses)
  |     {chip_type: "cta"|"follow_up"|"setting", category: string, icon?: string}
  |-- suggestion_chips?: SuggestionChip[] (structured chips with action routing)
  |     {message, action_type: "send_message"|"open_pill"|"trigger_action", action_target?, chip_type, category, icon?}
  '-- _debug?: {router_extraction_failed: boolean}  (backend-only observability, not consumed by frontend)
```

### Key Request/Response Models

| Model                         | Purpose                                                                                                                                                                                                                                                                                                                                                                                                          |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GraphPlanRequest`            | Plan generation: message, trip_inputs, session_state, document_id, ui_phase, expected_version, thread_id, reset, suggestion_clicked. `trip_inputs` is capped at 100 keys, 32KB serialized size, and nesting depth 10; `session_state` is capped at 200 top-level keys, 64KB serialized size, and nesting depth 10; schema validation allows `message` up to 4000 chars, but `/api/graph_plan/stream` still applies the pre-DB 2000-char fast gate described above. Session state bootstrap/merge handled by shared `_prepare_graph_plan_session_state()` (used by `/graph_plan/stream`), and backend `serialize_agent_state()` trims verbose runtime fields before persistence to stay under the 64KB session envelope while preserving reload-safe affiliate activity fields (`partner`, `partner_product_id`, `source`, `source_agent`, `provider`, `live_price`, `price_basis`, `is_estimate_only`, and browse `rating`/`review_count`). User-owned settings (`activity_settings`, `hotel_settings`, `flight_settings`, `transport_settings`, `booking_types`) use deep merge via `_merge_user_owned_trip_settings()` to avoid clobbering omitted keys. |
| `ExpandItineraryRequest`      | Stage 2->3: `idempotency_key` (max length 200), strategy_sections, tiles, preferences, trip_inputs, force_full_rebuild, refresh_activity_categories?. `strategy_sections` is capped at 30 entries; each section payload is capped at ~50KB nested size; `tiles` is capped at 200 keys; `trip_inputs` is capped at 32KB serialized size and nesting depth 10. **`refresh_activity_categories`:** When set, re-searches activity tiles for these categories before building (used by activity pill changes at S3 to swap stale tiles without an agent turn). **Tile source selection:** `force_full_rebuild=true` (auto-expand after chat) uses DB tiles (authoritative -- written by `apply_planner_update`); `force_full_rebuild=false` (preference regen / manual) uses frontend tiles (includes hearted tiles, filters); empty frontend tiles falls back to DB tiles. **Idempotency:** `idempotency_key` is checked via `check_idempotency()` in `backend/app/request_dedup.py` using DB-backed lease rows in `runtime_state` (30s TTL) and is scoped by backend `session_id`, so duplicate suppression is per session across workers rather than global across all clients. Failed or aborted NDJSON runs now call `release_idempotency()` so the same key can be retried after an unsuccessful build; successful completions keep the duplicate guard until TTL expiry. |
| `PlanDocumentPatch`           | CRDT update: version, branches?, tiles?, selections?, trip_inputs?, remove_branch_ids?, remove_tile_ids?, preferred_tile_ids? The nested `DocumentTripInputsPatch` (used for `trip_inputs?`) supports partial updates for all user-owned settings: `booking_types`, `flight_settings`, `hotel_settings`, `activity_settings`, `transport_settings`, `date_flex`, `trip_duration`, `date_window_start`, `date_window_end`. Explicit `null` clears are supported; non-nullable fields reset to defaults (`currency -> "USD"`, `date_flex -> false`). |
| `PlanDocumentResponse`        | Document fetch: version, updated_by, document, updated_at, changes_made: bool                                                                                                                                                                                                                                                                                                                                    |
| `TileRefreshRequest/Response` | Refresh tiles for branch with new settings. `branch_id` is required and capped at 256 chars.                                                                                                                                                                                                                                                                                                                    |
| `SuggestionChip`              | Structured chip: message, action_type (`send_message`\|`open_pill`\|`trigger_action`), action_target?, chip_type (`cta`\|`follow_up`\|`setting`), category, icon?                                                                                                                                                                                                                                                |
| `SuggestionChipMeta`          | Chip styling: chip_type, category, icon? (parallel to `suggested_responses`)                                                                                                                                                                                                                                                                                                                                     |
| `BlockMove`                   | Single block relocation: `block_id` (max 256 chars), `from_day`, `to_day`, `to_position` (default 0)                                                                                                                                                                                                                                                                                                             |
| `ArrangementValidateRequest`  | Validate proposed moves without persisting: `moves: BlockMove[]`                                                                                                                                                                                                                                                                                                                                                 |
| `ArrangementApplyRequest`     | Validate + persist moves with optimistic concurrency: `moves: BlockMove[], expected_version: int`. Returns 409 on version mismatch.                                                                                                                                                                                                                                                                               |
| `BlockViolation`              | Constraint violation: `block_id`, `violation_code` (`LOCKED_BLOCK`\|`NO_FLY_BUFFER`\|`CROSS_DOMAIN_BUFFER_REQUIRED`\|`DAY_CAPACITY_EXCEEDED`), `severity` (`blocking`\|`warning`), `message`, `target_day`                                                                                                                                                                                                      |
| `ArrangementResult`           | Response from validate or apply: `valid: bool`, `violations: BlockViolation[]`, `day_cards?: list` (only on successful apply), `version?: int` (only on successful apply)                                                                                                                                                                                                                                        |
| `RemoveBlockRequest`          | Remove a single block: `block_id` (max 256 chars), `day_number`, `expected_version` (optimistic concurrency). 409 on version conflict. Buffer blocks and locked activity types (`arrival`, `departure`, `check-in`, `check-out`) cannot be removed (400). If removal leaves no activities, a `free_day` placeholder block is inserted. |
| `RemoveBlockResponse`         | Response from remove-block: `day_number`, `day_card` (updated day card dict), `version` (new version), `removed_block_id`                                                                                                                                                                                                                                                                                       |
| `RestoreSnapshotRequest`      | Restore day_cards to a previous snapshot (undo stack): `day_cards: List[Dict]` (max 60), `expected_version: int` (optimistic concurrency). 409 on version conflict. No constraint validation -- snapshot was captured immediately before the mutation. Rate limited to 20/min. |
| `RestoreSnapshotResponse`     | Response from restore-snapshot: `day_cards: List[Dict]`, `version: int`                                                                                                                                                                                               |
| `BrowseActivitiesRequest`       | Browse activities: destination, day_number?, date?, hotel_location?: {lat, lng}, categories?: string[] (backend schema default: `["cultural","food","nature","tours"]`; frontend client default: `["cultural"]`; service fallback when categories resolve empty: `["cultural","food","nature"]`). Service path is Viator-first when enabled, GYG supplements partner results (deduped by title), and Google Places backfills/supplements on empty or undersupplied partner inventory. If Maps is unavailable but partner tiles exist, the service can still return partner-only results. |
| `InsertActivityBlockRequest`    | Insert browse tile: day_number, tile (max 50 keys) (BrowseTile dict), expected_version? (deprecated -- no longer enforced) |
| `InsertActivityBlockResponse`   | Insert result: day_number, day_card, version, inserted_block_id |
| `SpecialistEnrichmentResponse`  | Phase B enrichment: section_id, status ('ready'\|'pending'\|'failed'), data?: Dict, error_code?: str, retry_after_ms?: int. `local_expert` polls the DB for up to 6s in 500ms intervals before falling back to `202 {status:"pending"}`. |
| `ShareTripResponse`             | Share creation result: `slug`, absolute `url`, derived `title`, optional `expires_at` (null for authenticated durable shares) |
| `SharedTripPublicResponse`      | Public shared-trip payload: metadata plus immutable `snapshot` used by `/trip/[slug]` server/client rendering |
| `ForkSharedTripResponse`        | Shared-trip fork result: `ok`, copied `destination`, `day_count`, and resulting `plan_view_state`; response also rotates the browser `session_id` + `csrf` cookie pair to the forked session |
| `GoogleAuthCallbackRequest` / `GoogleAuthUrlResponse` | OAuth bootstrap models for Google login (`code` + `state` callback, consent URL init). OAuth callback `code` and `state` are each capped at 256 chars. |
| `AuthUser` / `AuthMeResponse`   | Authenticated user summary returned by `/api/auth/me` and callback completion |
| `UserTripSummary` / `UserTripsResponse` | Lightweight owned-trip list for desktop/mobile account menus and trip resume flows |
| `ResumeTripResponse`            | `ok` + `trip_id` acknowledgement for session resume requests |

---

## 4. Enums & State Machines

### PlanViewState (density-driven rendering)

```
PlanViewState Literal (schemas.py) defines two families:
  - P-prefix (core density levels): P0_MINIMAL, P1_ENRICHED, P2_LOGISTICS, P3_FINALIZED, P3_EDITING, P3_BLOCKED
  - S-prefix (legacy aliases, marked for removal): S0_BOOTSTRAP, S1_FRAMING, S2_STRATEGY_READY, S2_BLOCKED,
    S3_ITINERARY_READY, S3_EDITING, S3_PARTIAL_CONFLICT, S3_BLOCKED

PlanDocumentData.plan_view_state default: "P0_MINIMAL"

Backend coordinator still emits S-prefix states:
  S0_BOOTSTRAP -> S2_STRATEGY_READY -> S3_ITINERARY_READY
                                       |-- S3_EDITING
                                       |-- S3_PARTIAL_CONFLICT
                                       '-- S3_BLOCKED

Note: S2_BLOCKED and S1_FRAMING are defined in the Literal type but never emitted
by the coordinator. Frontend VIEW_STATE_ORDER handles both P and S families.

Hydration guards:
  Downgrade protection (setFromPlanResponse, mergeEnvelope): S3->S2 blocked when day_cards exist
  Backend-authoritative hydration: fetch path persists backend `plan_view_state` as-is (no frontend promotion)
```

### Stage 3 Emission Contract

| Builder Result | Conflicts | Emitted `plan_view_state` |
| --- | --- | --- |
| `success=True` | `0` | `S3_ITINERARY_READY` |
| `success=True` | `>0` | `S3_EDITING` |
| `success=False` | `>0` (partial day cards returned) | `S3_PARTIAL_CONFLICT` |
| `success=False` | `0` | `S3_BLOCKED` |

### Selective Regen Field Mapping

`backend/app/services/regen_strategy.py` maps preference-only updates to builder-only regeneration:

- `preferences` -> `RegenStrategy.BUILDER`
- source snapshots:
  - previous: `document.preferred_tile_ids`
  - current: request `preferences.preferred_hotel_ids|preferred_activity_ids|preferred_flight_ids`

### Other Enums

| Enum               | Values                                                             | Purpose                                                                                                                                                                                                                         |
| ------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PlanState`        | INCOMPLETE, RESOLVING, STABLE, LOCKED                              | Backend-authoritative plan state                                                                                                                                                                                                |
| `UIPhase`          | bootstrap, expanded                                                | Chips-only vs full planner                                                                                                                                                                                                      |
| `ViewMode`         | planning, booking                                                  | Two-mode system (frontend-only, not a backend enum)                                                                                                                                                                             |
| `BookingTypeState` | off, suggested, on                                                 | Tri-state per booking category                                                                                                                                                                                                  |
| `ResolverStep`     | processing_constraints, matching_inventory, updating_itinerary     | Progress within RESOLVING                                                                                                                                                                                                       |
| `ReadinessKey`     | origin, destination, start_date, end_date, travelers, budget       | Constraint completeness                                                                                                                                                                                                         |
| `BookingState`     | idle, loading, ready, error                                        | Per-tab booking status                                                                                                                                                                                                          |
| `TileType`         | flight, hotel, activity                                            | Tile category                                                                                                                                                                                                                   |
| `TileProvider`     | expedia, booking, google_places, curated, mock, viator, gyg, unknown | Booking/data partner (expanded to track all tile data sources)                                                                                                                                                               |
| `PartnerPrice`     | `{partner, price, currency, url?, logo?, isBestPrice?}`            | Frontend-only (`frontend/types/tile.ts`): partner pricing entry for multi-partner price comparison on TileCard / TileDetailsModal. Not on Pydantic model. |
| `AckStatus`        | applied, partial, no_change, needs_clarification, failed, rejected | Update acknowledgement status. `rejected` used for route violations (e.g., same-city error). Backend Literal does NOT include `pending`; frontend types (`chat.ts`, `plan-envelope.ts`) add `pending` as a frontend-only value. |

---

## 5. Frontend State Store

Source: `frontend/state/documentStore.ts`, `frontend/state/uiStore.ts`, `frontend/state/userStore.ts`, `frontend/state/panelToggleStore.ts` (Zustand)

### Store Shape

| Category       | Key Fields                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------- |
| Document       | `version`, `updatedBy`, `updatedAt`, `document` (PlanDocumentData)                                |
| Loading        | `isLoading`, `isCommitting`, `error`                                                              |
| Selection      | `selectedBranchId`                                                                                |
| View           | `activeView` ('planning' \| 'booking'), `isPlanFinalized`                                         |
| Preferences    | `preferredTileIds` (Set), `pendingPreferencePatch`                                                |
| Regeneration   | `lastGeneratedPreferences`, `isRegenerating`, `isPending`, `expandInProgress`, `remainingSeconds` (`isRegenerating` = shared UI overlay state; `expandInProgress` = hard execution mutex) |
| Fill-day mutex | `_fillingDays` (Set\<number\>) -- per-day concurrency guard                                       |
| Mutation mutex | `_pendingMutations` (number) -- general mutation counter (fill-day, drag-drop)                    |
| Undo stack     | `undoEntry: UndoEntry \| null` -- depth-1 ephemeral undo (drag_move, remove_block, fill_day types) |
| PATCH shadow   | `_lastPatchedTripInputs` (`DocumentTripInputs \| null`) -- backend-confirmed snapshot of last successful trip_inputs PATCH; used by `commitTripInputs()` as the no-op dedup baseline (avoids false no-ops since `updateTripInputs()` mutates zustand before the PATCH fires) |
| Streaming      | `currentRunId`, `abortController`                                                                 |
| Generation     | `generation` (`GenerationState \| null`) -- envelope-driven generation status stored at root store level (not persisted in `document`) |
| Cart           | `cartTileIds` (Set)                                                                               |
| LLM Updates    | `llmUpdatedFields` (Set of field names LLM recently modified)                                     |
| Browse Activities | `browseableActivities` (Array<Record<string, unknown>>) -- provider-backed browse/fallback activity tiles stashed by `logistics_node`; hydrated from `document.browseable_activities` and SSE envelope |

### Key Actions

| Action                                                             | Purpose                                                                                                                                 |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `setFromPlanResponse()`                                            | Merge backend GraphPlanResponse into store (destination lock, S3-safe view state guard including lateral S3 transitions, tile/section merge, image URL sanitization). When incoming activity tiles have zero ID overlap with the current activity pool, the store treats that as a category-swap response and replaces only activity tiles while preserving existing non-activity inventory. |
| `mergeEnvelope()`                                                  | Streaming update: tiles, sections, day_cards, plan_view_state (with downgrade protection + image URL sanitization) plus root-level `generation` merge from envelope. Honors envelope-level `tiles_replaced` so category/destination refreshes replace tiles instead of merging stale activity cards. Uses RAF-batched buffering when available (`globalThis.requestAnimationFrame`) and not in test mode (`NODE_ENV=test` or `VITEST=true`). Consecutive SSE events in the same frame are deep-merged and flushed as one setState call. Buffering is generation-scoped (`_pendingEnvelopeGeneration`/`_bufferGeneration`) so stale SSE partials from previous send cycles are dropped. Module-level `_pendingEnvelope` + `_rafId` state, with `_bypassRAF=true` during flush to prevent recursion. |
| `updateTripInputs()`                                               | Sync local trip input update (no API call). Runs `applyActivityCategoryDefaults()` normalization: if categories are empty and activities are not explicitly off, seeds default category (`cultural`); if activities are off with empty categories, clears stale `day_preferences`. |
| `commitTripInputs()`                                               | Async PATCH with optimistic update + rollback (handles 409 retry, 404 graceful). Filters no-op `trip_inputs` fields before PATCH using `_lastPatchedTripInputs` as baseline (not live zustand state -- `updateTripInputs()` already mutated it); if empty after filtering, skips network write and returns success. Successful commits update `_lastPatchedTripInputs` and clear matching keys from `_userDirtySettings`. Both optimistic and response/409-retry document merges re-run `applyActivityCategoryDefaults()` before writing store state. |
| `ensureSettingsFlushed()`                                          | Flush only **dirty** settings before graph run (prevents overwriting backend-derived values). Per-send-cycle payload hash dedupe skips duplicate flush PATCHes for the same request cycle. |
| `fetchDocument()`                                                  | GET /api/document (hydrates backend document/state directly; no frontend upward `plan_view_state` promotion)    |
| `patchDocument()`                                                  | PATCH /api/document (preserves frontend-only fields)                                                                                    |
| `toggleTilePreference()`                                           | Heart/unheart a tile (single-select for hotels, multi-select for activities). Debounced 500ms PATCH to batch rapid toggles.             |
| `clearPreferences()`                                               | Clear all hearted tiles + sync to backend                                                                                               |
| `startGeneration()` / `abortGeneration()` / `completeGeneration()` | Streaming lifecycle (mutex via runId)                                                                                                   |
| `isCurrentRun()`                                                   | Check if a runId is the current run (ignore stale events)                                                                               |
| `selectTile()` / `deselectTile()`                                  | Tile selection within a branch (uses patchDocument)                                                                                     |
| `restoreTripInputs()`                                              | Restore trip inputs from undo snapshot                                                                                                  |
| `acknowledgeLLMUpdate()`                                           | Clear sparkle animation for a field                                                                                                     |
| `mergeSpeculativeContent()` / `clearSpeculativeContent()`          | Preload specialist sections during Setup phase                                                                                          |
| `replaceDayCard()`                                                 | Surgical single day card replacement (fill-day)                                                                                         |
| `setRegenerationState()`                                           | Shared regeneration UI state (isRegenerating, isPending, remainingSeconds). Display-only flag; not a hard concurrency guard by itself. |
| `setExpandInProgress()`                                            | Expand-itinerary mutex flag                                                                                                             |
| `claimFillDay(day)`                                                | Per-day fill mutex: returns `false` if day already in flight (prevents concurrent fill-day on same day from different call sites)       |
| `releaseFillDay(day)`                                              | Release per-day fill mutex after fill-day completes or fails                                                                            |
| `removeBlock(blockId, dayNumber)`                                  | POST `/api/document/remove-block` with optimistic concurrency. **409 retry:** On version conflict, performs one `GET /api/document` refresh attempt and retries once with the refreshed version. Uses `claimMutation()`/`releaseMutation()` mutex. On success, replaces the affected `day_card` in store, bumps `version`, and sets `undoEntry`. `previousVersion` in undo entry is set from `result.version - 1` (not `prevVersion`) to stay correct after retry. |
| `setUndoEntry(entry)`                                              | Set or clear the depth-1 undo entry (`UndoEntry \| null`)                                                                                                                                                                               |
| `executeUndo()`                                                    | POST `/api/document/restore-snapshot` with `undoEntry.previousDayCards` + current `version`. Clears `undoEntry` immediately to prevent double-undo. Silently no-ops on 409 (plan was modified concurrently). On success, replaces `day_cards` and `version` in store. |
| `claimMutation()` / `releaseMutation()`                            | Increment/decrement `_pendingMutations` counter for general mutation tracking                                                           |
| `hasPendingMutations()`                                            | Returns true when `_pendingMutations > 0` -- ChatPanel mutation gate polls this before sending graph requests to avoid version conflicts |
| `markPreferencesAsApplied()`                                       | Sync lastGeneratedPreferences after expand completes                                                                                    |
| `awaitPreferencePatch()`                                           | Wait for pending preference PATCH to complete before proceeding                                                                         |
| `setActiveView()`                                                  | Switch between 'planning' and 'booking' views                                                                                           |
| `setFinalized()`                                                   | Set plan finalization flag (gates Book view access)                                                                                     |
| `addToCart()` / `removeFromCart()` / `clearCart()`                  | Cart operations for booking mode                                                                                                        |
| `hasAllRequiredFields()`                                           | Computed selector: returns true when destination, start_date, and end_date are all set                                                  |
| `reset()`                                                          | Full store reset (aborts in-flight generation, cancels pending RAF flush, clears buffered envelope state)                              |

**Per-session expand mutex (backend):** `request_dedup.py` exports `acquire_expand_slot(session_id)` / `release_expand_slot(session_id)`. If `acquire_expand_slot` returns `False` (expand already in-flight for this session), the `/api/expand-itinerary` endpoint returns HTTP 429 with `Retry-After: 5`. The mutex is backed by DB lease rows in `runtime_state` under `state_key = lease:expand_mutex:{session_id}` with a 120s TTL, so crashed generators auto-expire and the lock now holds across backend workers. The same module keeps 30s idempotency leases in the shared table by scoping the key with backend `session_id` when available, hashing that scoped value with SHA-256, and storing the digest under `state_key = lease:request_idempotency:sha256:{digest}`. Released via `finally` in the streaming response wrapper. That same `finally` block now also calls `release_idempotency(req.idempotency_key, session_id=session_id)` unless the NDJSON stream emitted a real `done` event (duplicate no-op completions do not count as success), so failed rebuild attempts are retryable without waiting for the 30s idempotency TTL.

**`startPreferenceAutoRegen()` subscription** (`frontend/hooks/usePreferenceAutoRegen.ts`): Watches `preferredTileIds` changes and triggers `expand-itinerary` regen. Debounced 1.5s to batch rapid heart toggles into a single expand call. Also gates on `isStreamingResponse` (defers during active plan generation). `expandInProgress` is the sole hard mutex inside `triggerRegeneration()`; `isRegenerating` may already be true as early visual feedback from sheet saves or SSE rebuild nodes and must not block the expand request. When `expandInProgress` or the streaming mutex blocks, the module queues the pending regen via `pendingRegen` and flushes it when both mutexes clear (500ms debounce, dedup check against `lastGeneratedPreferences`). `useChatSse` / `useChatSend` also clear stale overlay state on complete, error, stale-stream, or abort paths so the display flag cannot get stuck high.

### User-Dirty Settings Tracker

Module-level `_userDirtySettings: Set<string>` (not Zustand state -- avoids re-renders). Each settings handler calls `markSettingDirty(key)` (e.g., `'activity_settings'`, `'hotel_settings'`). `ensureSettingsFlushed()` PATCHes only dirty keys, applies per-send-cycle payload-hash dedupe, and clears keys only after a successful (or no-op-filtered) commit. Failed commits retain dirty keys for retry, preventing silent loss of pending user-owned settings.

### State Guards

- **Destination lock:** Once set, destination can't change unless S0_EMPTY reset
- **View state downgrade protection:** Never downgrade plan_view_state when itinerary exists
- **Lateral Stage 3 transitions allowed:** `S3_ITINERARY_READY` <-> `S3_EDITING` <-> `S3_PARTIAL_CONFLICT` are valid and not blocked by downgrade guards
- **Destination/date change detection:** Triggers chat reset + tile/section clearing; destination changes, date window changes, or `date_flex=true` clear stale `day_cards` unless new cards are returned in the same payload
- **Fill-day version sync:** `fillDay()` in api.ts syncs `version` from response to store after success, preventing 409 cascade on subsequent calls
- **Graph-built itinerary skip:** `setFromPlanResponse` maps `itinerary_day_cards` -> `day_cards` if present. ChatPanel's expand gate checks `graphBuiltItinerary` flag -- skips expand-itinerary when graph already built day_cards
- **Mutation gate:** ChatPanel subscribes to `_pendingMutations` and waits up to 5s for `hasPendingMutations()` to clear before sending graph requests. If the timeout is hit, the draft message is restored to the input and send is blocked with a retry toast, preventing version conflicts from concurrent fill-day/drag-drop mutations
- **Trip-input PATCH dedupe:** frontend filters unchanged `trip_inputs` fields before PATCH; backend enforces a matching no-op guard for pure `trip_inputs` writes
- **Pre-graph settings flush dedupe:** `ensureSettingsFlushed()` computes a stable payload hash and skips duplicate flushes for the same send cycle (`sendCycleId`)
- **Activity settings merge precedence:** `setFromPlanResponse` gives local sheet state priority for `activity_settings.categories`, `activity_settings.day_preferences`, `activity_settings.activities_per_day`, and `booking_types.activities`, while backend response still drives other booking types (flights/hotels/transport)
- **Category-swap tile replacement:** `setFromPlanResponse` also replaces only activity tiles when the incoming activity tile set has no overlap with the current activity IDs, preventing stale category inventory from accumulating while preserving flights/hotels
- **Activity defaults normalization:** all trip-input merge paths (`updateTripInputs`, `commitTripInputs`, `setFromPlanResponse`, `mergeEnvelope`) run `applyActivityCategoryDefaults()` to keep categories/booking-types/day-preferences consistent
- **Fill-day real-block guard:** `TimelineThread` skips fill-day if the target day already has real activity blocks (race condition with graph SSE populating the day concurrently)
- **Fill-day generation gate:** `TimelineThread`/`StrategyStageRenderer` block fill-day while stream/regeneration is active (`currentRunId`/generation flags), then surface a non-blocking wait message
- **Fill-day burst guard:** `TimelineThread` and `StrategyStageRenderer` enforce a 1.5s local cooldown between fill-day requests
- **Send-cycle guard:** `messageSendNonce` increments on each user send to gate stale completion/scroll side-effects from overlapping Graph streams
- **RAF merge guard:** `mergeEnvelope()` disables RAF buffering when `requestAnimationFrame` is unavailable or test env flags are set; merges run inline for deterministic tests
- **Image URL hygiene:** document/envelope merge paths sanitize Picsum hosts (`picsum.photos`, `fastly.picsum.photos`) out of destination cards, tiles, day blocks, and strategy assets; required gallery/vibe images fall back to a deterministic Unsplash URL
- **Bookable activity filter:** `isBookableActivityTile()` in `tileSelectors.ts` filters fill-day generated tiles (`source_agent` in `experience_generator` or `vertical_specialist`) from the booking surface (`BookingSection`). Non-activity tiles always pass through.
- **Session reset hard reload:** `useBranchManager` now forces `window.location.reload()` after a successful session reset so fresh cookies/session identity are picked up before the planner rehydrates.

### UI Store (`frontend/state/uiStore.ts`)

Separate lightweight Zustand store for ephemeral and session-scoped UI state. It does not duplicate `TripPlan` document data. Some fields exist for persisted UI continuity before all consumers have migrated off older document/local state.

| Field / Action | Purpose |
| -------------- | ------- |
| `selectedBranchId` | Persisted branch-selection mirror provisioned in `uiStore`; current timeline/render consumers still read `documentStore.selectedBranchId` / `useBranchState` |
| `isComparisonMode` | Enables branch comparison UI state |
| `comparisonBranchIds` | Tuple of active comparison branch IDs |
| `hoveredActivityId` / `setHoveredActivityId()` | Ephemeral card↔map hover sync |
| `mobileHeaderCondensed` / `setMobileHeaderCondensed()` | Ephemeral mobile header collapse flag driven by `useStrategyStageOrchestration` scroll state |
| `setSelectedBranchId()` / `selectBranchIfNone()` | Helpers for the persisted branch-selection mirror in `uiStore` |

### Panel Toggle Store (`frontend/state/panelToggleStore.ts`)

Auxiliary Zustand store for booking-surface and travel-intel chrome. It does not own trip data; it only tracks which secondary panel is open plus the travel-advice badge state shared between `TripSummaryPills`, `LandingHeaderContent`, and `PlanFullDensityView`.

| Field / Action | Purpose |
| -------------- | ------- |
| `staysExpanded` / `toggleStays()` | Toggle the stays suggestions panel; opening it collapses flights, activities, and travel advice |
| `flightsExpanded` / `toggleFlights()` | Toggle the flights suggestions panel; opening it collapses stays, activities, and travel advice |
| `activitiesExpanded` / `toggleActivities()` | Toggle the activities suggestions panel; opening it collapses stays, flights, and travel advice |
| `intelExpanded` / `toggleIntel()` | Toggle destination travel advice; opening it collapses the booking suggestion panels |
| `travelAdviceCount`, `showTravelAdvice`, `isTravelAdvicePending` / `setTravelAdviceData()` | Badge count, visibility, and loading state pushed from local-expert polling |
| `reset()` | Clears all expanded panels plus travel-advice metadata on session reset |
| `setComparisonMode()` / `toggleBranchForComparison()` / `exitComparisonMode()` | Comparison-mode state transitions |
| `resetUI()` | Resets all UI-only state |

Persistence contract:
- Persisted: `selectedBranchId`, `isComparisonMode`, `comparisonBranchIds`
- Ephemeral only: `hoveredActivityId`, `mobileHeaderCondensed`
- Storage key: `nomadic-ui-state`

### Auth/User Store (`frontend/state/userStore.ts`)

Separate lightweight Zustand store for account state; it does not duplicate `TripPlan` or document data.

| Field / Action | Purpose |
| -------------- | ------- |
| `user`         | Current authenticated user (`AuthUser \| null`) from `/api/auth/me` |
| `trips`        | Cached `UserTripSummary[]` for desktop/mobile recent-trip menus |
| `loading`      | Auth bootstrap state; starts true until `fetchUser()` resolves |
| `resumingTripId` | UI guard for at-most-one active resume request at a time |
| `fetchUser()`  | GET `/api/auth/me`; 5s stale-window cache with in-flight request dedupe; clears to anonymous on failure |
| `fetchTrips({force?})` | GET `/api/trips`; 30s stale-window cache with in-flight request dedupe; `401` collapses to `[]` |
| `login()`      | GET `/api/auth/google/url`, then redirects the browser to the returned Google consent URL |
| `logout()`     | POST `/api/auth/logout`, then clears local auth/trip cache regardless of response |
| `resumeTrip(tripId)` | POST `/api/trips/{tripId}/resume`; rotates the browser back onto the selected trip session, then hard-reloads for clean document hydration |

Hydration contract:
- `useSessionHydration()` primes `useUserStore.fetchUser()` alongside document hydration so auth state is available immediately after reload.
- Desktop/mobile account menus call `fetchTrips()` lazily after `user` becomes non-null.
- Shared public pages do not depend on `userStore`; `/trip/[slug]` uses public fetches with `credentials: "omit"` and only creates a session when the user chooses to fork the trip.

---

## 6. Frontend API Client

Source: `frontend/lib/api.ts`, `frontend/lib/sharedTripApi.ts`

### Functions

| Function                     | Endpoint                        | Purpose                                                                                                                                                                                                                       |
| ---------------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apiFetch()`                 | (all)                           | Base fetch wrapper: credentials, CSRF header, abort guard                                                                                                                                                                     |
| `streamGraphPlan()`          | POST `/api/graph_plan/stream`   | SSE streaming (onToken, onComplete, onError, onNodeStatus, onPartial, onFeasibilityWarning callbacks). `onPartial` receives `SSEPartialEvent['data']` for progressive rendering before the `complete` event. Returns abort fn. Non-2xx responses preserve backend `detail` text in thrown errors when available. |
| `validateTripInput()`        | POST `/api/validate-trip-input` | LLM-based validation                                                                                                                                                                                                          |
| `fetchDestinationImage()`    | POST `/api/destination-image`   | Unsplash image                                                                                                                                                                                                                |
| `refreshTiles()`             | POST `/api/tiles/refresh`       | Refresh tiles for branch (uses `fetchWithRetry`, 2 retries, 500ms base delay)                                                                                                                                                 |
| `fillDay()`                  | POST `/api/document/fill-day`   | Generate activity tiles for a free day. Returns `tiles` map for store merge. Response may include `rejected: true` with `rejection_reason`, `rejection_code`, `rejection_suggestion` when Tier 1 constraint validation fails. Non-2xx errors preserve backend `detail` text in thrown error messages (used for 429/rejection toasts). |
| `validateArrangement()`      | POST `/api/document/validate-arrangement` | Check proposed block moves against constraints. Returns `{valid, violations[]}`. No LLM, target <50ms. |
| `applyArrangement()`         | POST `/api/document/apply-arrangement` | Validate + persist block moves. Throws `'VERSION_CONFLICT'` on 409. On success, returns `{valid, violations, day_cards, version}` -- caller must `mergeEnvelope({day_cards})` and `setState({version})` separately. |
| `removeBlock()`              | POST `/api/document/remove-block` | Remove a single block. Throws `'VERSION_CONFLICT'` on 409. Returns `{day_number, day_card, version, removed_block_id}`. |
| `browseActivities()`           | POST `/api/activities/browse`   | Browse destination activities for a destination. Params: `{destination, dayNumber?, date?, hotelLocation?, categories?}`. Backend fetch is Viator-first, then GYG supplement/dedupe, then Google Places fallback/supplement; if Maps is unavailable, partner-only live results may still be returned. Returns `{tiles: BrowseTile[], total: number}` (`api.ts` client typing; backend may also include `source: "stashed" \| "places"` and keeps `"places"` as the live-provider label). |
| `getSpecialistEnrichment()`    | GET `/api/specialist/{sectionId}/enrichment` | Fetch Phase B enrichment status for a specialist section. `local_expert` requests long-poll for up to 6s (500ms cadence) before the backend falls back to `202 {status:'pending', retry_after_ms:1500}`. Returns `{status: 'ready'\|'pending'\|'failed', section_id, data?, error_code?, retry_after_ms?}` or `null` (404). |
| `fetchSharedTrip()`            | GET `/api/shared/{slug}` | Public shared-trip client fetch used by `/trip/[slug]` fallback UI. Delegates to `sharedTripApi.ts`, which also exports the server-side `fetchSharedTripServer()` helper used by the RSC route. Uses `credentials: 'omit'`; throws user-facing `404`/`410` errors for missing or expired shares. |
| `trackDeeplinkClick()`         | POST `/api/tiles/click` | Fire-and-forget analytics ping for partner deeplink opens. Uses `apiFetch()` and intentionally swallows client-side failures. |
| `resetSession()`             | DELETE `/api/session`           | Clear session                                                                                                                                                                                                                 |
| `fetchWithRetry()`           | (wraps apiFetch)                | Exponential backoff retry on transient errors                                                                                                                                                                                 |
| `clearSessionLocalStorage()` | --                              | Clear session-related localStorage (preserves GDPR consent)                                                                                                                                                                   |
| `isTransientError()`         | --                              | (module-private) Check if an error is retryable (timeout, network, 502/503/504)                                                                                                                                               |
| `isTransientStatus()`        | --                              | (module-private) Check if HTTP status is retryable (502, 503, 504). 429 excluded -- retrying amplifies rate limits.                                                                                                            |
| `parseRetryAfter()`          | --                              | Parse `Retry-After` header from 429 response into numeric seconds (null if missing/unparseable)                                                                                                                               |

**`BrowseTile` interface** (exported from `api.ts`): `{id, type, title, subtitle?, description?, image_url?, photo_name?, duration?, rating?, review_count?, location_label?, geo?: {lat, lng}, price_estimate?, source, provider, category, tags?, place_id?, maps_uri?}`

- `price_estimate` and `live_price` are accepted as numeric strings in some upstream providers; frontend schema validation normalizes these to numbers in `documentStore` before rendering tile totals.
- Auth, share, fork, and trip-resume flows still mostly call `apiFetch()` directly from UI/store modules; shared-trip reads are the main exception and now live in `sharedTripApi.ts` for client/server reuse.

### Retry Logic

- Transient errors: timeout, network, 502, 503, 504
- **429 (rate limit):** Retried within `fetchWithRetry`. Honours `Retry-After` header via `parseRetryAfter()` -- if present, waits that many seconds; if absent, falls back to exponential backoff. `isTransientStatus()` still excludes 429 from its set, but `fetchWithRetry` handles 429 explicitly before the transient-status check.
- Exponential backoff: `delay = min(baseDelay * 2^attempt, maxDelay) + random(0-500ms)`
- Default: 3 max retries, 1s base, 10s max
- AbortError never retried
