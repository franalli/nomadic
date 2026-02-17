# CLAUDE.md — Agent Operating Manual

# CLAUDE.md — Agent Operating Manual

## 🎯 Current Sprint (UPDATE EVERY SESSION)

- **Focus:** Code health audit fixes (T3 tier)
- **Secondary:** DS token adoption
- **Active work:** Completed Batches A-H of code health audit + 3 trace-derived UX fixes: (1) synthesizer category-only additions → specialist_update response type, (2) L1 cold probe skips prefetch wait budget, (3) specialist content continuity reuse on same-dest date extensions
- **Known broken:** Pre-existing test failures: `test_facade_exports_meta_helpers` (missing init_turn_metadata export), `test_ground_flight_response_appends_date_adjustment_note`
- **DO NOT touch this sprint:** [frozen files/features]

---

Updated section:

```markdown
## 🤖 Agents

Three subagents in `.claude/agents/`.

- **backend-specialist** — Python/planner/services/FastAPI work
- **frontend-specialist** — React/TypeScript/Zustand/styling work
- **code-reviewer** — Review multi-file changes after executing a plan

### When to Delegate

- Multi-file changes (3+ files) → delegate to specialist
- Complex logic (constraint guard, builder, state machines) → delegate
- Cross-stack → backend specialist first, then frontend. Never both at once.
- Post-task review on multi-file work → always code-reviewer

### When to Work Directly without Agent Delegation

- Single-file fixes, one-liners, typos
- Exploratory/interactive tasks needing inline progress
- Reading files or answering questions about code

### Parallelism

Run independent operations concurrently:

- Multiple file reads → parallel
- Lint + build + test across different stacks → parallel
- Independent changes across different node files → parallel
- Multiple grep/find operations → parallel
- Independent backend + frontend work → parallel

DO NOT parallelize:

- Frontend + backend changes to the same API contract (backend first)
- Schema changes + dependent code (schema first)
- Specialist delegation + code review (specialist first, reviewer after)
- File writes to the same file (sequence always)

### Agent Result Handling

- After EVERY agent delegation, immediately retrieve and present the result ASAP.
- Do not wait for the user to ask. The delegation is not complete until the
  result is shown and any output files are confirmed.

---

## 🚫 Hard Rules (NEVER VIOLATE)

1. DO NOT refactor files beyond the scope of the current task
2. DO NOT add new dependencies without explicit approval
3. DO NOT rename, move, or restructure existing files or functions
4. DO NOT create new LangGraph nodes — 7-node invariant is law
5. DO NOT touch mobile-specific components unless explicitly asked
6. DO NOT modify API contracts or shared schemas without explicit approval
7. LIMIT changes to ≤8 files per task unless approved
8. NEVER do broad directory scans or read node_modules — reference specific files
9. DO NOT modify Synthesizer model routing (`_MODEL_BY_COMPLEXITY`) without measuring quality impact

---

## 🔀 Parallel Work Zones

When two Claude Code sessions run simultaneously, they MUST stay in their lanes:

| Zone                          | Owns                     | Files                                                                      |
| ----------------------------- | ------------------------ | -------------------------------------------------------------------------- |
| **Frontend**                  | UI, state, components    | `frontend/components/*`, `frontend/state/*`, `frontend/hooks/*`            |
| **Backend**                   | Nodes, services, prompts | `backend/app/planner/*`, `backend/app/services/*`, `backend/app/prompts/*` |
| **Shared (coordinate first)** | Types, API contracts     | `schemas.py`, `specialist_schemas.py`, API route signatures                |

If a task requires touching BOTH zones, stop and confirm scope before proceeding.

---

## 🛡️ Governance — Single Sources of Truth

These four docs override your assumptions. Read before generating code.

| SSoT Doc                           | Governs                                | Rule                                                                      |
| ---------------------------------- | -------------------------------------- | ------------------------------------------------------------------------- |
| `@docs/plan_graph_analysis.md`     | Backend architecture, node structure   | MUST verify plan against spec before writing planner code                 |
| `@docs/design-system.md`           | UI styling, tokens, component patterns | ALL React components use these tokens — no invented Tailwind values       |
| `@docs/ux_unified_architecture.md` | View states, rendering logic, UX flow  | Never swap renderers — use `StrategyStageRenderer`, adapt by data density |
| `@docs/data-contracts.md`          | API routes, schemas, state store       | Check before modifying API endpoints, schemas, or state shape             |

**Invariants:**

- `TripPlan` is SSoT for all trip state
- Right Panel NEVER empty after first user interaction
- 7-node LangGraph structure is fixed
- `plan_view_state` from backend determines rendering mode
- `[lng, lat]` coordinate format preserved through entire pipeline

---

## Architecture

### Design Principles

0. **Keep it simple** — no over-engineering
1. **TripPlan is SSoT** — single source of truth for all trip state
2. **Data over Agents** — flights/hotels are data fetchers (LogisticsNode), not agents
3. **Domain Experts ARE Agents** — Tier 1 (Diving/Hiking/Skiing/Cycling/Surfing) use VerticalSpecialist; Tier 2 (Sailing/Cooking/Yoga) are lightweight tile filters
4. **Architect sees the whole picture** — avoids context fracture
5. **Safe Routing** — LLM-based intent classification (GPT-4o-mini), no regex
6. **Constraint Injector** — Specialist runs BEFORE Architect calls tools
7. **One Voice** — Synthesizer ensures consistent tone across all nodes
8. **No hard-coded world data** — never hard-code locations, airports, geolocation, or any potentially infinite dataset

### Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind, Zustand, Framer Motion, Mapbox GL
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic, LangGraph, LangChain-OpenAI
- **Testing:** Vitest (frontend), pytest (backend)
- **Linting:** ESLint + Prettier (frontend), Ruff (backend)

---

## Commands
```

# Frontend

cd frontend && npm run dev # Dev server
cd frontend && npm run build # Production build (Render: npm ci --include=dev && npm run build)
cd frontend && npm run lint:fix # Lint + fix

# Backend

cd backend && python start.py # Start server
cd backend && pytest # Tests

# After running pytest, delete leftover SQLite artifacts:

rm -f backend/test_plan_document_pytest.db\*
cd backend && ruff check . --fix # Lint + fix

# Environment

frontend/.env.local → NEXT_PUBLIC_API_URL, NEXT_PUBLIC_MAPBOX_TOKEN
backend/.env → DATABASE_URL, OPENAI_KEY
cd backend && alembic upgrade head # DB migrations
docker compose up db --build # Docker DB

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

Synthesizer model routing (DO NOT modify without measuring quality impact):

| Response Type     | Model       | Latency | History Depth |
| ----------------- | ----------- | ------- | ------------- |
| greeting          | Template    | <50ms   | 0 turns       |
| exploration       | gpt-4o-mini | ~150ms  | 2 turns       |
| specialist_update | gpt-4o-mini | ~150ms  | 2 turns       |
| planning          | gpt-4o      | ~600ms  | 4 turns       |

Prompt templates cached in-memory — restart server after modifying `backend/app/prompts/synthesizer.txt`.

---

## Response Style

- **Skip preamble.** Don't explain what you're about to do — just do it.
- **Make the change, show the diff, done.**
- **Ask clarifying questions BEFORE writing code**, not after.
- **No narration.** Don't summarize what you changed after changing it unless asked.
- **Post-plan execution summary.** After executing a plan, provide a concise summary of all changes made: files modified, key logic added/removed, and any follow-up items.

---

## Machine: MacBook Pro M5 — 24GB RAM

- **Parallel sessions:** Two Claude Code instances comfortably, three if one is idle
- **File reads:** Up to 8–10 files in context per task
- **Builds:** `npm run build` and `pytest` can run concurrently with dev servers
- **Docker:** DB container + both dev servers simultaneously is fine
- **Still avoid:** Reading entire directories, node_modules, or loading all spec docs at once

### Context Management

- `/compact` after completing major features or switching focus areas
- `/clear` when switching between frontend and backend work
- Reference specific files (`@backend/app/planner/nodes/intent_router.py`), not directories

---

## Resumption Protocol (after /compact or /clear)

1. Re-read this `CLAUDE.md`
2. Check **Current Sprint** above
3. Ask what task to continue — do NOT assume
4. Read specific files involved BEFORE making changes

## Auto-Compact Preservation

When auto-compacting, MUST preserve verbatim:

- Current Sprint section
- Hard Rules section
- SSoT governance pointers
- 7-node LangGraph invariant
- File paths and function signatures currently being modified
- Domain safety rules (e.g., diving 24h no-fly buffer)
```
