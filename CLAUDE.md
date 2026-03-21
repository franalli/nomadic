# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🎯 Current Sprint (UPDATE EVERY SESSION)

- **Focus:** UX polish, cost optimization, and shipping speed
- **Secondary:** post-demo delivery hardening across frontend/backend planner interactions
- **Active work:** UX and interaction polish, cost-aware recommendation optimizations, and SSoT doc alignment in `docs/*`
- **Active files:** `docs/{data-contracts.md,plan_graph_analysis.md,ux_unified_architecture.md,repo_structure.md}`, `CLAUDE.md`, `backend/app/{planner/{coordinator.py,conversationalist.py,nodes/{logistics_node.py,router_extraction.py},schemas/coordinator_schemas.py},services/{aviasales_provider.py,sharing.py},analytics_routes.py,db_models.py,main.py}`, `frontend/components/{chat/{ChatSuggestionChips.tsx,DateFlexChip.tsx},plan/{BookingPlanningView.tsx,StrategyStageRenderer.tsx,tiles/TileRailCard.tsx,timeline/RichBlockRenderer.tsx},shared/SharedTripSections.tsx}`, `frontend/{hooks/useChatSse.ts,lib/{analytics.ts,ghost-timeline-adapter.ts},state/documentStore.ts,types/document.ts}`
- **Known broken:** none explicitly tracked in current diff
- **DO NOT touch this sprint:** `llm_factory.py` provider/model-routing contract; API/schema compatibility surfaces

---

## 🚫 Hard Rules (NEVER VIOLATE)

1. DO NOT refactor files beyond the scope of the current task
2. DO NOT add new dependencies without explicit approval
3. DO NOT rename, move, or restructure existing files or functions
4. DO NOT bypass coordinator architecture — planner turns flow through `coordinator.execute_turn()` and StepType execution contracts
5. DO NOT touch mobile-specific components unless explicitly asked
6. DO NOT modify API contracts or shared schemas without explicit approval
7. LIMIT changes to ≤8 files per task unless approved
8. NEVER do broad directory scans or read node_modules — reference specific files
9. DO NOT modify coordinator step mapping/status contract (`plan_turn`, `_step_node_name`, `_build_envelope`) without measuring UX impact
10. ALL LLM construction via `get_llm_by_model()` from `llm_factory.py` — no direct `ChatOpenAI()` or `ChatGoogleGenerativeAI()` constructors in node/service code
11. No hard-coded world data — never hard-code locations, airports, IATA codes, coordinates, airlines, or any potentially infinite dataset
12. `PlanDocumentData` is the sole SSoT for all trip state — no parallel state objects

---

## 🤖 Agents

Three subagents in `.claude/agents/`. Most agents inherit session model. Exception: code-reviewer is explicitly set to opus for deeper review quality.

- **backend-specialist** — Python/planner/services/FastAPI/LLM factory work
- **frontend-specialist** — React/TypeScript/Zustand/styling/design system work
- **code-reviewer** — Review multi-file changes after executing a plan (read-only)

### When to Delegate

- Multi-file changes (3+ files) → delegate to specialist
- Complex logic (constraint guard, builder, state machines) → delegate
- Cross-stack → backend specialist first, then frontend. Never both at once.
- Post-task review on multi-file work → always code-reviewer

### When to Work Directly

- Single-file fixes, one-liners, typos
- Exploratory/interactive tasks needing inline progress
- Reading files or answering questions about code

### Parallelism

Run concurrently: multiple file reads, lint+build+test across stacks, independent node file changes, multiple grep/find operations, independent backend+frontend work.

DO NOT parallelize: same API contract changes (backend first), schema+dependent code (schema first), specialist delegation+review (specialist first), writes to same file.

### Agent Result Handling

After EVERY agent delegation, immediately retrieve and present the result. Do not wait for the user to ask.

---

## 🔀 Parallel Work Zones

When two sessions run simultaneously:

| Zone                          | Owns                     | Files                                                                      |
| ----------------------------- | ------------------------ | -------------------------------------------------------------------------- |
| **Frontend**                  | UI, state, components    | `frontend/components/*`, `frontend/state/*`, `frontend/hooks/*`            |
| **Backend**                   | Nodes, services, prompts | `backend/app/planner/*`, `backend/app/services/*`, `backend/app/prompts/*` |
| **Shared (coordinate first)** | Types, API contracts     | `schemas.py`, `specialist_schemas.py`, API route signatures                |

If a task requires touching BOTH zones, stop and confirm scope before proceeding.

---

## 🛡️ Governance — Single Sources of Truth

These four docs override your assumptions. Read before generating code.

| SSoT Doc                           | Governs                                | Rule                                                                  |
| ---------------------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| `@docs/plan_graph_analysis.md`     | Backend architecture, coordinator + nodes/services | MUST verify plan against spec before writing planner code             |
| `@docs/design-system.md`           | UI styling, tokens, component patterns | ALL React components use these tokens — no invented Tailwind values   |
| `@docs/ux_unified_architecture.md` | View states, rendering logic, UX flow  | Never swap renderers — `StrategyStageRenderer` adapts by data density |
| `@docs/data-contracts.md`          | API routes, schemas, state store       | Check before modifying API endpoints, schemas, or state shape         |

---

## Architecture

### Design Principles

0. **Keep it simple** — no over-engineering
1. **PlanDocumentData is SSoT** — single source of truth for all trip state, persisted as JSON in the `plan_documents` DB table
2. **Data over Agents** — flights/hotels are data fetchers via coordinator tile search, not agent personas
3. **Domain Experts remain modular** — Tier 1 (Diving/Hiking/Skiing/Cycling/Surfing/Climbing/Sailing/Wildlife Safari) run through specialist dispatch; Tier 2 (Cooking/Yoga/Nightlife/etc.) remain lightweight tile filters
4. **Coordinator Architecture** — `coordinator.execute_turn()` is pure Python (no LangGraph). It classifies, plans deterministic steps, executes modules, and builds the envelope
5. **Safe Routing** — LLM-based intent/change classification via `router_extraction.classify_change()` and `settings.router_model`, no regex
6. **Deterministic state transitions** — step execution + `_build_envelope()` own state/view-state/ack updates
7. **One Voice** — `conversationalist.py` streams the final assistant response
8. **Centralized LLM Factory** — `get_llm_by_model()` handles provider detection (OpenAI/Gemini), model-specific params, structured output retry. Models configured via `settings.*_model` env vars.

### Backend Request Flow

```
POST /api/graph_plan/stream
  → main.py: graph_plan_stream_endpoint
  → streaming.py: generate_sse()
      → coordinator.execute_turn()   ← main planner logic (pure Python)
          → router_extraction.py     ← CLASSIFY step
          → vertical_specialist.py  ← DISPATCH_SPECIALISTS step
          → local_expert.py          ← LOCAL_INTEL step
          → logistics_node.py        ← SEARCH_TILES step
          → itinerary_builder.py     ← BUILD_ITINERARY step
          → conversationalist.py     ← GENERATE_RESPONSE step
      → streaming.py: release_sse_slot (finally)

POST /api/expand-itinerary
  → main.py: expand_itinerary_endpoint
      → request_dedup.py: check_idempotency → duplicate_noop if repeat
      → request_dedup.py: acquire_expand_slot → 429 if in-flight
  → streaming.py: generate_ndjson()
      → itinerary_builder.py         ← build day-by-day schedule
      → request_dedup.py: release_expand_slot (finally)
```

### Coordinator Steps

| StepType | Executes | Purpose |
|------|-------|---------|
| `CLASSIFY` | `router_extraction.classify_change()` | Intent + field extraction + change typing |
| `DISPATCH_SPECIALISTS` | `vertical_specialist.dispatch_specialist_with_brief()` | Tier 1 specialist planning/replanning |
| `LOCAL_INTEL` | `local_expert.py` helpers | Destination local-intelligence section |
| `SEARCH_TILES` | `logistics_node.py` | Flights/hotels/activities refresh |
| `BUILD_ITINERARY` | `services/itinerary_builder.py` | Day-by-day schedule from sections + tiles |
| `GENERATE_RESPONSE` | `conversationalist.py` | Final streaming assistant response |
| `SHORT_CIRCUIT` | coordinator helpers | Greeting/reset/question fast path |

### Key Backend Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, all routes, middleware registration |
| `app/streaming.py` | `generate_sse()` and `generate_ndjson()` generators |
| `app/lifespan.py` | Startup pre-warm + shutdown cleanup (DB engine, HTTP clients, inflight tasks) |
| `app/schemas.py` | All Pydantic request/response schemas incl. `PlanDocumentData` |
| `app/config.py` | All settings via pydantic-settings; `generate_session_token()`; sole place env vars are read |
| `app/middleware/session.py` | `SessionMiddleware` (issues session+CSRF cookies) + `CSRFMiddleware` (double-submit pattern) |
| `app/request_dedup.py` | DB-backed idempotency keys + per-session expand mutex (runtime_state table) |
| `app/sse_state.py` | SSE connection slot tracking (per-session and per-IP limits) |
| `app/analytics_routes.py` | Analytics routes: tile clicks (`/api/tiles/click`) + funnel events (`/api/analytics/event`), included in main.py |
| `app/planner/coordinator.py` | Core planner logic — `execute_turn()` entry point |
| `app/planner/llm_factory.py` | `get_llm_by_model()` — sole constructor for all LLM instances |
| `app/planner/specialist_registry.py` | SSoT for all Tier 1 specialist config (keywords, constraints, defaults) |
| `app/services/spend_guard.py` | Per-session + global daily USD caps; DB-backed via `runtime_state` table; `spend_guard_scope(session_id)` context manager |
| `app/services/cache_core.py` | `MemoryCache` (thread-safe TTLCache wrapper) + `l2_upsert()` for L2 DB writes |
| `app/tile_service/google_places_provider.py` | All Google Places API calls (Text Search, geocoding, photo proxy) |

### Cache Architecture

Two tiers: **L1** (in-process `MemoryCache`, `threading.RLock`) and **L2** (PostgreSQL `response_cache` table via `pg_insert` upsert).

| Module | Domain | L1 maxsize | L2 TTL source |
|--------|--------|-----------|---------------|
| `specialist_cache.py` | Specialist briefs | 128 | `settings.specialist_cache_ttl_hours` |
| `tile_cache.py` | Place tiles | 256 | `settings.google_places_cache_ttl_hours` |
| `router_cache.py` | Router results | 500 | L1 only |
| `experience_generator.py` | Fill-day content | 128 | `settings.experience_cache_ttl_hours` |

Cache keys always use `make_cache_key()` from `hashing.py`. Never bypass `MemoryCache` to access `TTLCache` directly (race condition).

### Frontend Architecture

**State** (Zustand stores in `frontend/state/`):
- `documentStore.ts` — primary store: `PlanDocumentData`, streaming state, tile mutations, regen tracking, undo stack
- `chatStore.ts` — chat history, SSE streaming state
- `uiStore.ts` — global UI flags (sheets open, loading states)
- `userStore.ts` — auth user, trip list, async fetch lifecycle
- `panelToggleStore.ts` — desktop panel visibility
- `mobileNavStore.ts` — mobile tab navigation

**Rendering pipeline** (`frontend/components/layout/`):
```
NomadicLanding → SplitLayoutView → left: ChatPanel, right: StrategyStageRenderer
                                           ↓ adapts by data density:
                                     PlanDensityViews → FullDensityTimeline (S3/S4)
                                                      → StrategyHero* (S2)
                                                      → ChipRow bootstrap (S0/S1)
```

**Key frontend lib files**:
- `lib/api.ts` — sole SSoT for all API calls; `apiFetch()` wrapper + `streamGraphPlan()` SSE client
- `lib/design-system.ts` — all DS tokens (colors, spacing, typography); use `DS.*` not raw Tailwind values
- `lib/specialists.ts` — frontend SSoT for specialist display config (mirrors `specialist_registry.py`)
- `lib/streamParser.ts` — parses SSE tokens/complete/error events from `generate_sse()`
- `types/document.ts` — TypeScript types for `PlanDocumentData` and all nested types
- `types/plan-envelope.ts` — `PlanViewState`, `PlanState`, `UIPhase` enums

### Middleware Ordering (Starlette LIFO)

`app.add_middleware()` is LIFO — last added = outermost = runs first on incoming requests. Effective order:

```
CSRFMiddleware → SessionMiddleware → CORSMiddleware → @middleware(http) stack → route
```

The `@app.middleware("http")` decorators (security headers, body size limit, OPTIONS rate-limit exemption) run between CORS and the route handler. CSRF skips OPTIONS and CSRF-exempt paths automatically.

### Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind, Zustand, Framer Motion, Mapbox GL
- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), Alembic, LangChain (OpenAI + Gemini)
- **LLM Providers:** OpenAI + Google Gemini via `llm_factory.py`; models configured via `settings.*_model` env vars
- **Testing:** Vitest (frontend), pytest (backend)
- **Linting:** ESLint + Prettier (frontend), Ruff (backend)

---

## Commands

```bash
# Frontend
cd frontend && npm run dev              # Dev server
cd frontend && npm run build            # Production build
cd frontend && npm run lint:fix         # Lint + fix
cd frontend && npm test                 # Run all Vitest tests
cd frontend && npm test -- path/to/test # Run a single test file

# Backend
cd backend && python start.py                              # Start server
cd backend && .venv/bin/pytest                             # All tests
cd backend && .venv/bin/pytest tests/test_foo.py -v        # Single test file
cd backend && .venv/bin/pytest tests/test_foo.py::test_fn  # Single test function
cd backend && .venv/bin/ruff check . --fix                 # Lint + fix

# ⚠️ Always run after pytest:
rm -f backend/test_plan_document_pytest.db*

# DB
cd backend && .venv/bin/alembic upgrade head   # Run migrations
docker compose up db --build                   # Start local Postgres

# Environment
frontend/.env.local → NEXT_PUBLIC_API_URL, NEXT_PUBLIC_MAPBOX_TOKEN, NEXT_PUBLIC_DEBUG_LOGS
backend/.env → DATABASE_URL, OPENAI_API_KEY, GOOGLE_API_KEY, ROUTER_MODEL, SPECIALIST_MODEL,
               SPECIALIST_FALLBACK_MODEL, LOCAL_EXPERT_MODEL, GUARD_MODEL,
               SYNTHESIZER_PLANNING_MODEL, EXPERIENCE_MODEL, IATA_RESOLVER_MODEL,
               IATA_CACHE_TTL_HOURS, UNSPLASH_ACCESS_KEY, GOOGLE_MAPS_API_KEY,
               GOOGLE_MAPS_API_SECRET, VIATOR_API_KEY, VIATOR_ENABLED,
               GET_YOUR_GUIDE_API_KEY, GET_YOUR_GUIDE_ENABLED, AVIASALES_API_TOKEN,
               AVIASALES_ENABLED, BOOKING_AFFILIATE_AID, GOOGLE_OAUTH_CLIENT_ID,
               GOOGLE_OAUTH_CLIENT_SECRET, ADMIN_API_KEY, MEDIA_PROXY_SIGNING_KEY,
               FRONTEND_ORIGIN, COOKIE_DOMAIN, GOOGLE_PLACES_PHOTOS_ENABLED,
               MAX_SESSIONS_PER_IP_HOUR, SPEND_GUARD_ENABLED,
               SPEND_GUARD_SESSION_DAILY_CAP_USD, SPEND_GUARD_GLOBAL_DAILY_CAP_USD,
               DEBUG, DEBUG_PLAN_MESSAGES, CLEAR_L2_ON_RESET
```

---

## Coding Standards

### TypeScript/React

- Check `@docs/design-system.md` AND `@docs/ux_unified_architecture.md` FIRST
- 2-space indent, named exports, `cn()` for classNames
- Lucide React for icons (not react-icons, not heroicons)
- Components under 200 lines
- All API calls through `apiFetch()` in `lib/api.ts` — no raw `fetch()` in components

### Python

- Check `@docs/plan_graph_analysis.md` FIRST
- 100 char line length, type hints on all functions
- Async for I/O, Pydantic v2 for schemas
- Follow ruff formatting
- All env vars read exclusively through `settings.*` (from `config.py`) — never `os.getenv()` outside `config.py`
- New specialist = 1 entry in `specialist_registry.py` + 1 `.txt` prompt file. No keyword lists elsewhere.

---

## Performance Notes

Coordinator routing and response generation rely on `settings.*_model` env vars (`router_model`, `specialist_model`, `synthesizer_planning_model`, etc.) via `llm_factory.py`. Do not bypass `get_llm_by_model()` or alter coordinator step sequencing/status mapping without measuring quality and UX impact.

Spend guard counters are **DB-backed** (stored in the `runtime_state` table) so they work across multiple workers and survive restarts within the same day.

---

## Response Style

- **Skip preamble.** Don't explain what you're about to do — just do it.
- **Make the change, show the diff, done.**
- **Ask clarifying questions BEFORE writing code**, not after.
- **After completing all changes**, give ONE summary: files modified, key logic changes, follow-ups. No narration during execution.

---

## Context Management

- `/compact` after completing major features or switching focus areas
- `/clear` when switching between frontend and backend work
- Reference specific files (`@backend/app/planner/coordinator.py`), not directories
- Avoid reading entire directories, node_modules, or loading all spec docs at once

---

## Resumption Protocol (after /compact or /clear)

1. Re-read this `CLAUDE.md`
2. Check **Current Sprint** above
3. Ask what task to continue — do NOT assume
4. Read specific files involved BEFORE making changes

## Auto-Compact Preservation

When auto-compacting, MUST preserve verbatim:

- Current Sprint section
- Hard Rules section (all 12 rules)
- SSoT governance pointers
- File paths and function signatures currently being modified
- Domain safety rules (e.g., diving 24h no-fly buffer)
