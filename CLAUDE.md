# CLAUDE.md — Agent Operating Manual

## 🎯 Current Sprint (UPDATE EVERY SESSION)

- **Focus:** [describe focus]
- **Secondary:** [secondary priority or "none"]
- **Active work:** Stage 12 shipped — synthesizer voice polish (no system jargon), per-response-type token limits, budget context enrichment + structured constraint violations in synthesis context, budget suggestion chips, static FALLBACK_MESSAGE replacing template fallbacks, `suggested_action` on budget constraint violations, fill-day endpoint (`POST /api/document/fill-day`), `generate_experience_tiles_for_day()`, Stepper UI component, day preference steppers in ActivitiesSheet, FreeDayCard fill button + category picker.
- **Known broken:** none
- **DO NOT touch this sprint:** [frozen files/features]

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

| SSoT Doc                           | Governs                                | Rule                                                                     |
| ---------------------------------- | -------------------------------------- | ------------------------------------------------------------------------ |
| `@docs/plan_graph_analysis.md`     | Backend architecture, node structure   | MUST verify plan against spec before writing planner code                |
| `@docs/design-system.md`           | UI styling, tokens, component patterns | ALL React components use these tokens — no invented Tailwind values      |
| `@docs/ux_unified_architecture.md` | View states, rendering logic, UX flow  | Never swap renderers — use `UnifiedStageRenderer`, adapt by data density |
| `@docs/data-contracts.md`          | API routes, schemas, state store       | Check before modifying API endpoints, schemas, or state shape            |

**Invariants from these docs:**

- `TripPlan` is the SSoT for all trip state
- Right Panel NEVER empty after first user interaction
- 7-node LangGraph structure is fixed
- `plan_view_state` from backend determines rendering mode
- `[lng, lat]` coordinate format preserved through entire pipeline

---

## Architecture (Reference Only — Read the SSoT Docs for Details)

### Design Principles

0. **Keep it simple** — no over-engineering
1. **TripPlan is SSoT** — single source of truth for all trip state
2. **Data over Agents** — flights/hotels are data fetchers (LogisticsNode), not agents
3. **Domain Experts ARE Agents** — Tier 1 (Diving/Hiking/Skiing/Cycling/Surfing) use VerticalSpecialist with reasoning; Tier 2 (Sailing/Cooking/Yoga) are lightweight tile filters
4. **Architect sees the whole picture** — avoids context fracture
5. **Safe Routing** — LLM-based intent classification (GPT-4o-mini), no regex
6. **Constraint Injector** — Specialist runs BEFORE Architect calls tools
7. **One Voice** — Synthesizer ensures consistent tone across all nodes
8. **No hard-coded world data** — never hard-code locations, airports, geolocation, or any potentially infinite dataset — always write generic LLM logic to handle these cases

### Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind, Zustand, Framer Motion, Mapbox GL
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic, LangGraph, LangChain-OpenAI
- **Testing:** Vitest (frontend), pytest (backend)
- **Linting:** ESLint + Prettier (frontend), Ruff + Black (backend)

---

## Commands

### Frontend (`/frontend`)

```
npm run dev          # Dev server
npm run build        # Production build
npm run lint:fix     # Lint + fix
npm run test         # Tests
```

### Backend (`/backend`)

```
python start.py      # Start server
pytest               # Tests
ruff check . --fix   # Lint + fix
```

### Environment

- Frontend env: `frontend/.env.local` → `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAPBOX_TOKEN`
- Backend env: `backend/.env` → `DATABASE_URL`, `OPENAI_KEY`
- DB migrations: `cd backend && alembic upgrade head`
- Docker DB: `docker compose up db --build`

---

## Performance Notes

### Synthesizer Latency Optimization (Stage 8)

The Synthesizer uses intelligent model routing for faster response times:

- **greeting**: Template only (no LLM, <50ms)
- **exploration**: gpt-4o-mini (~150ms, $0.15/1M tokens)
- **specialist_update**: gpt-4o-mini (~150ms, $0.15/1M tokens)
- **planning**: gpt-4o (~600ms, $2.50/1M tokens)

Prompt templates are cached in-memory:

- Cache cleared on process restart
- If you modify `backend/app/prompts/synthesizer.txt`, restart the server
- Cache safety: template.render() must only use `response_type` variable

Context window dynamically trims history:

- greeting: 0 turns (bypassed entirely)
- exploration/specialist_update: 2 turns (4 messages)
- planning: 4 turns (8 messages)

**DO NOT modify `_MODEL_BY_COMPLEXITY` or `_HISTORY_DEPTH_BY_TYPE` without measuring quality impact**

---

## Coding Standards

### TypeScript/React

- Check `@docs/design-system.md` AND `@docs/ux_unified_architecture.md` FIRST
- 2-space indent, named exports, `cn()` for classNames
- Lucide React for icons (not react-icons, not heroicons)
- `React.forwardRef` for reusable components
- Components under 200 lines

### Python

- Check `@docs/plan_graph_analysis.md` FIRST
- 100 char line length, type hints on all functions
- Async for I/O, Pydantic v2 for schemas
- Follow ruff/black formatting

---

## Response Style

- **Skip preamble.** Don't explain what you're about to do — just do it.
- **Make the change, show the diff, done.**
- **Ask clarifying questions BEFORE writing code**, not after.
- **No narration.** Don't summarize what you changed after changing it unless asked.

---

## Machine: MacBook Pro M5 — 24GB RAM

This machine can handle heavier workloads. Adjust behavior accordingly:

- **Parallel sessions:** Two Claude Code instances comfortably, three if one is idle/monitoring
- **File reads:** Can load up to 8–10 files in context per task without concern
- **Builds:** `npm run build` and `pytest` can run concurrently with dev servers
- **Docker:** DB container + both dev servers simultaneously is fine
- **Compaction:** Less urgent than on constrained machines — compact after major milestones, not every sub-task
- **Still avoid:** Reading entire directories, node_modules, or loading all spec docs at once unnecessarily

### Context Management

- Run `/compact` after completing major features or switching focus areas
- Run `/clear` when switching between frontend and backend work
- Reference specific files (`@backend/app/planner/nodes/intent_router.py`), not directories
- If stuck or confused: re-read `@CLAUDE.md`, then ask

---

## After /compact or /clear — Resumption Protocol

1. Re-read this `CLAUDE.md`
2. Check the **Current Sprint** section above
3. Ask what task to continue — do NOT assume or pick up where you think you left off
4. Read the specific files involved BEFORE making any changes

## Auto-Compact Preservation

When auto-compacting, MUST preserve:

- The **Current Sprint** section verbatim
- The **Hard Rules** section verbatim
- SSoT governance pointers
- The 7-node LangGraph invariant
- Context management rules
- Verbatim file paths and function signatures currently being modified
- Domain safety rules (e.g., diving 24h no-fly buffer)
