# CLAUDE.md — Agent Operating Manual

## 🎯 Current Sprint (UPDATE EVERY SESSION)

- **Focus:** UX polish, cost optimization, and shipping speed
- **Secondary:** post-demo delivery hardening across frontend/backend planner interactions
- **Active work:** UX and interaction polish, cost-aware recommendation optimizations, and SSoT doc alignment in `docs/*`
- **Active files:** `docs/{data-contracts.md,design-system.md,plan_graph_analysis.md,repo_structure.md,ux_unified_architecture.md}`, `.claude/{agents/code-reviewer.md,commands/update-docs.md}`, `CLAUDE.md`, `backend/app/{config.py,planner/{conversationalist.py,nodes/{router_extraction.py,vertical_specialist.py}},services/aviasales_provider.py,tile_service/google_places_provider.py}`, `backend/tests/{run_curl_flows.sh,test_aviasales_provider.py,test_conversationalist.py,test_google_places_hotel_provider.py,test_router_extraction.py,test_vertical_specialist_node.py}`, `frontend/components/{layout/{LandingHeaderContent.tsx,hooks/useBranchManager.ts},plan/{BookingPlanningView.tsx,BookingSummary.tsx,TripSummaryPills.tsx,TripSummaryPills.helpers.ts,TripSummaryPillsSegment.tsx,booking/BookingDrawer.tsx,tiles/{SuggestionCardContent.tsx,suggestionCardSections.tsx},timeline/{RichBlockRenderer.tsx,blocks/LogisticsBlock.tsx}},tiles/{MiniCardSummaryPricing.tsx,TileCard.tsx,TileCardActions.tsx,TileDetailsFooter.tsx,tileHelpers.ts}}`, `frontend/hooks/{useChatEffects.ts,useChatScrolling.ts,useChatSend.ts,useChatSse.ts}`, `frontend/state/panelToggleStore.ts`, `frontend/__tests__/{booking-links.test.tsx,booking-planning-view.test.tsx,booking-summary.test.tsx,logistics-block-sizing.test.tsx,rich-block-renderer.test.tsx,strategy-stage-orchestration.test.ts,suggestion-card-sizing.test.tsx,tileHelpers.test.ts,useBranchManager.test.tsx,useChatScrolling.test.tsx,useChatSend.optimistic-extension.test.tsx}`
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
12. `TripPlan` is the sole SSoT for all trip state — no parallel state objects

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
1. **TripPlan is SSoT** — single source of truth for all trip state
2. **Data over Agents** — flights/hotels are data fetchers via coordinator tile search, not agent personas
3. **Domain Experts remain modular** — Tier 1 (Diving/Hiking/Skiing/Cycling/Surfing/Climbing/Sailing/Wildlife Safari) run through specialist dispatch; Tier 2 (Cooking/Yoga/Nightlife/etc.) remain lightweight tile filters
4. **Coordinator Architecture** — `coordinator.execute_turn()` classifies, plans deterministic steps, executes modules, and builds the envelope
5. **Safe Routing** — LLM-based intent/change classification via `router_extraction.classify_change()` and `settings.router_model`, no regex
6. **Deterministic state transitions** — step execution + `_build_envelope()` own state/view-state/ack updates
7. **One Voice** — `conversationalist.py` streams the final assistant response
8. **Centralized LLM Factory** — `get_llm_by_model()` handles provider detection (OpenAI/Gemini), model-specific params, structured output retry. Models configured via `settings.*_model` env vars.

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

### Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind, Zustand, Framer Motion, Mapbox GL
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic, LangChain (OpenAI + Gemini)
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

# Backend
cd backend && python start.py           # Start server
cd backend && pytest                    # Tests
cd backend && ruff check . --fix        # Lint + fix

# ⚠️ Always run after pytest:
rm -f backend/test_plan_document_pytest.db*

# Environment
frontend/.env.local → NEXT_PUBLIC_API_URL, NEXT_PUBLIC_MAPBOX_TOKEN, NEXT_PUBLIC_DEBUG_LOGS
backend/.env → DATABASE_URL, OPENAI_API_KEY, GOOGLE_API_KEY, ROUTER_MODEL, SPECIALIST_MODEL, SPECIALIST_FALLBACK_MODEL, LOCAL_EXPERT_MODEL, GUARD_MODEL, SYNTHESIZER_PLANNING_MODEL, EXPERIENCE_MODEL, IATA_RESOLVER_MODEL, IATA_CACHE_TTL_HOURS, UNSPLASH_ACCESS_KEY, GOOGLE_MAPS_API_KEY, GOOGLE_MAPS_API_SECRET, VIATOR_API_KEY, VIATOR_ENABLED, VIATOR_CACHE_TTL_HOURS, VIATOR_API_URL, GET_YOUR_GUIDE_API_KEY, GET_YOUR_GUIDE_ENABLED, GET_YOUR_GUIDE_CACHE_TTL_HOURS, GET_YOUR_GUIDE_API_URL, AVIASALES_API_TOKEN, AVIASALES_MARKER, AVIASALES_ENABLED, AVIASALES_CACHE_TTL_HOURS, BOOKING_AFFILIATE_AID, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, ADMIN_API_KEY, MEDIA_PROXY_SIGNING_KEY, FRONTEND_ORIGIN, COOKIE_DOMAIN, GOOGLE_PLACES_PHOTOS_ENABLED, MAX_SESSIONS_PER_IP_HOUR, DEBUG, DEBUG_PLAN_MESSAGES, CLEAR_L2_ON_RESET
cd backend && alembic upgrade head      # DB migrations
docker compose up db --build            # Docker DB
```

---

## Coding Standards

### TypeScript/React

- Check `@docs/design-system.md` AND `@docs/ux_unified_architecture.md` FIRST
- 2-space indent, named exports, `cn()` for classNames
- Lucide React for icons (not react-icons, not heroicons)
- Components under 200 lines

### Python

- Check `@docs/plan_graph_analysis.md` FIRST
- 100 char line length, type hints on all functions
- Async for I/O, Pydantic v2 for schemas
- Follow ruff formatting

---

## Performance Notes

Coordinator routing and response generation rely on `settings.*_model` env vars (`router_model`, `specialist_model`, `synthesizer_planning_model`, etc.) via `llm_factory.py`. Do not bypass `get_llm_by_model()` or alter coordinator step sequencing/status mapping without measuring quality and UX impact.

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
