# CLAUDE.md — Agent Operating Manual

## 🎯 Current Sprint (UPDATE EVERY SESSION)

- **Focus:** backend planner intent/constraints/logistics + itinerary/experience services
- **Secondary:** none
- **Active work:** backend planner agent + tools architecture, frontend strategy/timeline/chat/layout rendering, and SSoT doc alignment in `docs/*`
- **Known broken:** none explicitly tracked in current working diff
- **DO NOT touch this sprint:** `llm_factory.py` provider/model-routing contract, API/schema compatibility surfaces

---

## 🚫 Hard Rules (NEVER VIOLATE)

1. DO NOT refactor files beyond the scope of the current task
2. DO NOT add new dependencies without explicit approval
3. DO NOT rename, move, or restructure existing files or functions
4. DO NOT bypass the create_agent + tools architecture — all planner logic flows through agent tools and middleware, not standalone LangGraph nodes
5. DO NOT touch mobile-specific components unless explicitly asked
6. DO NOT modify API contracts or shared schemas without explicit approval
7. LIMIT changes to ≤8 files per task unless approved
8. NEVER do broad directory scans or read node_modules — reference specific files
9. DO NOT modify agent model selection (`ModelSelectionMiddleware` in `middleware.py`) without measuring quality impact
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
| `@docs/plan_graph_analysis.md`     | Backend architecture, agent + tools    | MUST verify plan against spec before writing planner code             |
| `@docs/design-system.md`           | UI styling, tokens, component patterns | ALL React components use these tokens — no invented Tailwind values   |
| `@docs/ux_unified_architecture.md` | View states, rendering logic, UX flow  | Never swap renderers — `StrategyStageRenderer` adapts by data density |
| `@docs/data-contracts.md`          | API routes, schemas, state store       | Check before modifying API endpoints, schemas, or state shape         |

---

## Architecture

### Design Principles

0. **Keep it simple** — no over-engineering
1. **TripPlan is SSoT** — single source of truth for all trip state
2. **Data over Agents** — flights/hotels are data fetchers (search_tiles tool), not agents
3. **Domain Experts ARE Agents** — Tier 1 (Diving/Hiking/Skiing/Cycling/Surfing) use get_specialist_advice tool; Tier 2 (Sailing/Cooking/Yoga) are lightweight tile filters
4. **Single Agent Architecture** — one `create_agent` planner with 6 tools replaces the old 7-node DAG. The agent decides tool order dynamically.
5. **Safe Routing** — LLM-based intent classification via `extract_trip_fields` tool and `settings.router_model`, no regex
6. **Middleware over Nodes** — State mutation, model upgrades, prompt injection, and chip generation happen in `AgentMiddleware` hooks, not standalone nodes
7. **One Voice** — The planner agent generates responses directly; no separate synthesizer
8. **Centralized LLM Factory** — `get_llm_by_model()` handles provider detection (OpenAI/Gemini), model-specific params, structured output retry. Models configured via `settings.*_model` env vars.

### Agent Tools (6)

| Tool | Wraps | Purpose |
|------|-------|---------|
| `extract_trip_fields` | `router_extraction.py` | Parse intent + trip fields from user message |
| `get_local_intel` | `local_expert.py` | Trip Overview card + Phase B enrichment |
| `get_specialist_advice` | `vertical_specialist.py` | Domain-specific strategy (diving, hiking, etc.) |
| `search_tiles` | `logistics_node.py` | Flights, hotels, activities via TileService |
| `validate_plan` | `constraint_guard.py` | Budget/temporal/safety constraint checks |
| `build_itinerary` | `itinerary_builder.py` | Day-by-day schedule from tiles + constraints |

### Middleware Stack (4)

| Middleware | Hook | Purpose |
|-----------|------|---------|
| `ModelSelectionMiddleware` | `awrap_model_call` | Upgrades to planning model for complex turns |
| `DynamicPromptMiddleware` | `awrap_model_call` | Injects live trip state into system prompt |
| `TurnLifecycleMiddleware` | `abefore_agent`, `awrap_tool_call` | Resets turn meta, merges tool results into state |
| `SuggestionChipMiddleware` | `aafter_model` | Template-based chip generation (no LLM) |

### Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind, Zustand, Framer Motion, Mapbox GL
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic, LangGraph, LangChain (OpenAI + Gemini)
- **LLM Providers:** OpenAI (gpt-4o, gpt-4o-mini), Google (gemini-2.5-flash) — via `llm_factory.py`
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
backend/.env → DATABASE_URL, OPENAI_API_KEY, GOOGLE_API_KEY, ROUTER_MODEL, SPECIALIST_MODEL, LOCAL_EXPERT_MODEL, GUARD_MODEL, SYNTHESIZER_*_MODEL, UNSPLASH_ACCESS_KEY, DEBUG, DEBUG_PLAN_MESSAGES, CLEAR_L2_ON_RESET
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

Agent model selection in `ModelSelectionMiddleware` — upgrades from fast model to planning model for complex turns (first full plan, 3+ tool calls). Models configured via `settings.*_model` env vars. DO NOT modify selection logic without measuring quality impact. System prompt rebuilt from live state each turn via `DynamicPromptMiddleware`.

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
- Reference specific files (`@backend/app/planner/agent.py`), not directories
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
