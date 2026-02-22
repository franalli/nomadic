# AGENTS.md - Nomadic Agent Operating Manual

## Project

Nomadic - AI travel planning with LangGraph + FastAPI + Next.js + Gemini 2.5 Flash.

## Role

You are a reviewer and auditor. You do NOT write implementation code.
You review, analyze, find bugs, suggest tests, and audit security.

## Current Sprint (update every session)

- Focus: [describe focus]
- Secondary: [secondary priority or "none"]
- Active work: backend planner intent/constraints/logistics + itinerary/experience services, new `activity_browser.py` path, frontend strategy/timeline/chat/layout rendering, and SSoT doc alignment in `docs/*`
- Known broken: none explicitly tracked in current working diff
- Do not touch this sprint:
  - 7-node graph invariant
  - `llm_factory.py` provider/model-routing contract
  - API/schema compatibility surfaces

## Hard Rules (never violate)

1. Do NOT refactor files beyond the scope of the current task.
2. Do NOT add new dependencies without explicit approval.
3. Do NOT rename, move, or restructure existing files or functions.
4. Do NOT create new LangGraph nodes. 7-node invariant is law:
   - `router`, `architect`, `specialist`, `local_expert`, `logistics`, `guard`, `synthesizer`
5. Do NOT touch mobile-specific components unless explicitly asked.
6. Do NOT modify API contracts or shared schemas without explicit approval.
7. Limit changes to 8 files per task unless approved.
8. Never do broad directory scans or read `node_modules`; reference specific files.
9. Do NOT modify Synthesizer model routing (`_MODEL_BY_COMPLEXITY`) without measuring quality impact.
10. All LLM construction must use `get_llm_by_model()` from `llm_factory.py`.
    - No direct `ChatOpenAI()` or `ChatGoogleGenerativeAI()` in node/service code.
11. No hard-coded world data.
    - Never hard-code locations, airports, IATA codes, coordinates, airlines, or other effectively unbounded datasets.
12. `TripPlan` is the sole SSoT for all trip state.
    - No parallel state objects.

## Specialist Delegation

When specialist agents are available (location: `.codex/agents/`), use:

- `backend-specialist` for Python/planner/services/FastAPI/LLM factory work
- `frontend-specialist` for React/TypeScript/Zustand/styling/design system work
- `code-reviewer` for read-only multi-file review after execution

Agent model and source-of-truth notes:

- In this manual, always use `.codex/agents/` and `.codex/skills/` paths.
- Most agents inherit the session model.
- `code-reviewer` is explicitly set to Opus for deeper review quality.

Agent spec files are expected at:

- `.codex/agents/backend-specialist.md`
- `.codex/agents/frontend-specialist.md`
- `.codex/agents/code-reviewer.md`

Skill specs are expected at:

- `.codex/skills/*/SKILL.md`
- Do not use `codex/skills/*` (non-dot path)

Delegation rules:

- Before delegating, read the matching spec in `.codex/agents/*.md` and apply it as the task brief.
- Multi-file changes (3+ files): delegate to a specialist.
- Complex logic (constraint guard, builders, state machines): delegate.
- Cross-stack work: backend specialist first, then frontend specialist; never both at once.
- Post-task review on multi-file work: always run `code-reviewer`.
- After every delegation, retrieve and present results immediately.

When to work directly:

- Single-file fixes, one-liners, and typos.
- Exploratory or interactive tasks that need inline progress.
- Reading files or answering questions about code.

## Parallelism Rules

Run concurrently when safe:

- Multiple file reads/greps/find operations
- Independent node file changes
- Lint, build, and tests across independent stacks
- Independent backend and frontend tasks

Do NOT parallelize:

- Edits that touch the same API contract (backend first)
- Schema changes and dependent code (schema first)
- Specialist delegation and review (specialist first, review second)
- Writes to the same file

## Parallel Work Zones

If two sessions are running simultaneously:

- Frontend zone (UI/state/components):
  - `frontend/components/*`, `frontend/state/*`, `frontend/hooks/*`
- Backend zone (nodes/services/prompts):
  - `backend/app/planner/*`, `backend/app/services/*`, `backend/app/prompts/*`
- Shared zone (coordinate first):
  - `schemas.py`, `specialist_schemas.py`, API route signatures

If a task touches both frontend and backend zones, confirm scope before proceeding.

## Governance - Single Sources of Truth

ALWAYS read these before reviewing architecture, APIs, schemas, frontend state, or UI rendering:
These four docs override your assumptions. Read before generating code.

- `docs/plan_graph_analysis.md`
  - Governs backend architecture and node structure.
  - MUST verify plan against spec before writing planner code.
- `docs/design-system.md`
  - Governs UI styling, tokens, and component patterns.
  - All React components must use these tokens. No invented Tailwind values.
- `docs/ux_unified_architecture.md`
  - Governs view states, rendering logic, and UX flow.
  - Never swap renderers. `StrategyStageRenderer` adapts by data density.
- `docs/data-contracts.md`
  - Governs API routes, schemas, and state store shape.
  - Check before modifying API endpoints, schemas, or state shape.

## Architecture and Invariants

### Design Principles

0. Keep it simple. No over-engineering.
1. `TripPlan` is SSoT for all trip state.
2. Data over agents: flights/hotels are data fetchers in `LogisticsNode`, not agents.
3. Domain experts are agents:
   - Tier 1 (Diving/Hiking/Skiing/Cycling/Surfing) use `VerticalSpecialist`.
   - Tier 2 (Sailing/Cooking/Yoga) are lightweight tile filters.
4. Architect sees the whole picture to avoid context fracture.
5. Safe routing: LLM-based intent classification via `settings.router_model`, no regex routing.
6. Constraint injector: Specialist runs before Architect calls tools.
7. One voice: Synthesizer enforces consistent tone across nodes.
8. Centralized LLM factory: `get_llm_by_model()` handles provider detection, model params, and structured output retry. Models are configured via `settings.*_model` env vars.

### Stack

- Frontend: Next.js 16, React 19, TypeScript, Tailwind, Zustand, Framer Motion, Mapbox GL
- Backend: Python 3.12, FastAPI, SQLAlchemy, Alembic, LangGraph, LangChain (OpenAI + Gemini)
- LLM providers via `llm_factory.py`: OpenAI (`gpt-4o`, `gpt-4o-mini`), Google (`gemini-2.5-flash`)
- Structured output is handled through `llm_structured.py` retry wrappers
- Testing: Vitest (frontend), pytest (backend)
- Linting: ESLint + Prettier (frontend), Ruff (backend)

## Commands

```bash
# Frontend
cd frontend && npm run dev
cd frontend && npm run build
cd frontend && npm run lint:fix

# Backend
cd backend && python start.py
cd backend && pytest
cd backend && ruff check . --fix

# Always run after pytest
rm -f backend/test_plan_document_pytest.db*

# Environment
# frontend/.env.local -> NEXT_PUBLIC_API_URL, NEXT_PUBLIC_MAPBOX_TOKEN
# backend/.env -> DATABASE_URL, OPENAI_API_KEY, GOOGLE_API_KEY
cd backend && alembic upgrade head
docker compose up db --build
```

## Coding Standards

### TypeScript and React

- Check `docs/design-system.md` and `docs/ux_unified_architecture.md` first.
- 2-space indent, named exports, `cn()` for classNames.
- Use Lucide React for icons (not `react-icons`, not Heroicons).
- Components should stay under 200 lines.

### Python

- Check `docs/plan_graph_analysis.md` first.
- 100-char line length, type hints on all functions.
- Use async for I/O.
- Use Pydantic v2 for schemas.
- Follow Ruff formatting.

## Performance Notes

- Synthesizer model routing uses `_MODEL_BY_COMPLEXITY`; models are configured via `settings.*_model` env vars; do not change routing without quality measurement.
- Prompt templates are cached in memory. Restart server after modifying:
  - `backend/app/prompts/synthesizer.txt`

## Response Style

- Skip preamble. Do not explain what you are about to do; just do it.
- Make the change, show the diff, done.
- Ask clarifying questions before writing code, not after.
- After completing all changes, give one summary: files modified, key logic changes, and follow-ups. No narration during execution.

## Review Workflow

When reviewing or auditing, prioritize:

1. Behavioral regressions and logic bugs.
2. Contract drift (API routes, schemas, state shape).
3. Violation of hard rules and architecture invariants.
4. Security and privacy risks.
5. Missing or weak tests.

For each finding, provide severity, exact file path, and line reference.

## Context Management

- `/compact` after completing major features or switching focus areas.
- `/clear` when switching between frontend and backend work.
- Reference specific files, not directories.
- Avoid scanning whole directories or `node_modules`.
- Avoid loading all spec docs at once.
- Keep context tight and task-scoped.
- If switching between backend and frontend concerns, reset context and re-check SSoT docs.

## Session Resumption

After context reset/compaction:

1. Re-read this `AGENTS.md`.
2. Check `Current Sprint`.
3. Confirm the next task with the user (do not assume).
4. Read only the specific files involved before acting.

## Auto-Compact Preservation

When auto-compacting, preserve verbatim:

- `Current Sprint` section
- `Hard Rules` section (all 12 rules)
- SSoT governance pointers
- File paths and function signatures currently being modified
- Domain safety rules (for example, diving 24-hour no-fly buffer)
