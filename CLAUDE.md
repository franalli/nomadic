# CLAUDE.md - Project Reference

## 🛡️ Governance & Specs (CRITICAL)

- **Backend SSoT:** `@docs/plan_graph_analysis.md` is the SINGLE SOURCE OF TRUTH for architecture.
  - **Rule:** Before generating code for `backend/app/planner/`, you **MUST** verify your plan against this spec.
  - **Invariant:** Strictly adhere to the 7-node structure; DO NOT create new nodes without updating the spec first.
- **Frontend SSoT:** `@docs/design-system.md` is the SINGLE SOURCE OF TRUTH for UI styling.
  - **Rule:** All React components **MUST** use the tokens, colors, and patterns defined in this file.
  - **Invariant:** Do not invent arbitrary Tailwind values; use the design tokens.
- **UX Logic SSoT:** `@docs/ux_unified_architecture.md` is the SINGLE SOURCE OF TRUTH for View States & Rendering.
  - **Rule:** Never swap entire renderers (Setup vs Plan). Use `UnifiedStageRenderer` and adapt based on data density (Bridge Mode vs Full Mode).
  - **Invariant:** The Right Panel must NEVER be empty after the first user interaction.

## Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS, Zustand, Framer Motion, Mapbox GL, Unsplash Images
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic (migrations), LangGraph, LangChain-OpenAI
- **Testing:** Vitest (frontend), pytest (backend)
- **Linting:** ESLint + Prettier (frontend), Ruff + Black (backend)

## Environment & Setup

- **Frontend Env:** `frontend/.env.local` (requires `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAPBOX_TOKEN`)
- **Backend Env:** `backend/.env` (requires `DATABASE_URL`, `OPENAI_KEY`)
- **DB Setup:** `cd backend && alembic upgrade head` to apply migrations locally
- **Docker:** `docker compose up db --build` for PostgreSQL

## Commands

### Frontend (run from `/frontend`)

- `npm run dev` - Start dev server
- `npm run build` - Production build
- `npm run lint` / `npm run lint:fix` - Linting
- `npm run test` - Run tests
- `npm run format` - Format code

### Backend (run from `/backend`)

- `python start.py` - Start server
- `pytest` - Run tests
- `ruff check .` - Lint
- `ruff format .` - Format

## Core Architecture

_For deep details, see Governance section above._

### Design Principles

0. **Keep Solutions Simple** - DO NOT over-engineer anything, keep solutions light and simple
1. **TripPlan is the SSoT** - Single Source of Truth for all trip state
2. **Data over Agents** - Flights/Hotels are data fetchers (LogisticsNode), not complex agents
3. **Domain Experts ARE Agents** - Tier 1 activities (Diving/Hiking/Skiing/Cycling/Surfing) require reasoning (VerticalSpecialist); Tier 2 (Sailing/Cooking/Yoga etc.) are lightweight tile filters
4. **Architect sees the whole picture** - Avoids context fracture
5. **Safe Routing** - LLM-based intent classification (GPT-4o-mini), no regex patterns
6. **Constraint Injector** - Specialist runs BEFORE Architect calls tools
7. **One Voice** - Synthesizer ensures consistent response tone regardless of which node contributed

## Project Structure

nomadic/ ├── frontend/ # Next.js app │ ├── app/ # App Router pages │ ├── components/ # React components (by feature) │ ├── hooks/ # Custom React hooks │ ├── lib/ # Utilities │ ├── state/ # Zustand stores ├── backend/ # Python API │ ├── app/ # Main application │ │ ├── planner/ # LangGraph nodes and state │ │ ├── prompts/ # Jinja2 prompt templates │ │ ├── services/ # Business services │ ├── migrations/ # Alembic DB migrations │ └── tests/ # Test files └── docs/ # Architecture documentation

## Coding Standards

### TypeScript/React

- **Check `@docs/design-system.md` AND `@docs/ux_unified_architecture.md` first.**
- 2-space indentation
- Named exports (avoid default exports)
- Use `cn()` for className merging
- Use `React.forwardRef` for reusable components
- Use Lucide React for icons (not react-icons or heroicons)
- Keep components under 200 lines

### Python

- **Check `@docs/plan_graph_analysis.md` first.**
- Line length: 100 chars
- Use type hints on all functions
- Async functions for I/O operations
- Follow ruff/black formatting
- Always use Pydantic v2 for request/response schemas

## Memory Management (16GB RAM)

- **Avoid:** Large-scale refactors of more than 5 files at once
- **Avoid:** Reading entire directories or node_modules
- **Reference Mode:** Read specific files (e.g., `@backend/app/planner/nodes/intent_router.py`) rather than broad directory scans
- **Context Reset:** Run `/clear` after completing tasks to purge history from RAM
- **If stuck:** Reference `@CLAUDE.md` to reload context cleanly

## Auto-Compact Instructions

When auto-compacting this conversation, MUST preserve:

- **Governance:** The SSoT status of `plan_graph_analysis.md`, `design-system.md`, and `ux_unified_architecture.md`
- **Architecture SSoT:** The 7-node LangGraph structure and `TripPlan` as single source of truth
- **Memory Safety:** The "Memory Management (16GB RAM)" rules
- **Current Progress:** Verbatim file paths and function signatures currently being modified
- **Specialist Logic:** Preserve domain-specific safety rules (e.g., diving 24h no-fly buffer)

**Compaction Strategy:**

- Use `/compact` manually after completing a significant sub-task
- Use `/clear` when switching between frontend and backend work
