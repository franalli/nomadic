# CLAUDE.md - Project Reference

## Tech Stack
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS, Zustand, Framer Motion, Mapbox GL
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic (migrations), LangGraph, LangChain-OpenAI
- **Testing:** Vitest (frontend), pytest (backend)
- **Linting:** ESLint + Prettier (frontend), Ruff + Black (backend)

## Environment & Setup
- **Frontend Env:** `frontend/.env.local` (requires `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAPBOX_TOKEN`)
- **Backend Env:** `backend/.env` (requires `DATABASE_URL`, `OPENAI_API_KEY`)
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

This project uses a **7-node LangGraph system** for AI-powered trip planning.

**IMPORTANT:** See `@docs/plan_graph_analysis.md` for the full technical spec before modifying anything in `backend/app/planner/`.

### Design Principles
1. **TripPlan is the SSoT** - Single Source of Truth for all trip state
2. **Data over Agents** - Flights/Hotels are data fetchers (LogisticsNode + TileService), not complex agents
3. **Domain Experts ARE Agents** - Diving/Hiking/Skiing require reasoning (VerticalSpecialist)
4. **Architect sees the whole picture** - Avoids context fracture
5. **Safe Routing** - LLM-based intent classification (GPT-4o-mini), no regex patterns
6. **Panic Button** - Hard-coded reset commands (`/reset`, `/clear`) bypass LLM entirely
7. **Constraint Injector** - Specialist runs BEFORE Architect calls tools
8. **One Voice** - Synthesizer ensures consistent response tone regardless of which node contributed

### Node Overview
| Node | Type | Purpose |
|------|------|---------|
| IntentRouter | LLM (fast) | Classifies intent: GREETING, RESET, PLANNING |
| TripArchitect | LLM | Core planning logic ("The Boss") |
| VerticalSpecialist | LLM | Domain expert (diving, hiking, skiing) |
| LocalExpert | LLM | City logistics and tips |
| LogisticsNode | Data | Flight fetching + safety logic |
| ConstraintGuard | Python | Pure validation, can trigger auto-fix loop |
| Synthesizer | LLM | Unified response generation |

## Project Structure
```
nomadic/
├── frontend/           # Next.js app
│   ├── app/            # App Router pages
│   ├── components/     # React components (by feature)
│   ├── contexts/       # React contexts
│   ├── hooks/          # Custom React hooks
│   ├── lib/            # Utilities
│   ├── state/          # Zustand stores
│   └── types/          # TypeScript types
├── backend/            # Python API
│   ├── app/            # Main application
│   │   ├── planner/    # LangGraph nodes and state
│   │   ├── prompts/    # Jinja2 prompt templates
│   │   ├── services/   # Business services
│   │   ├── tile_service/ # Tile generation
│   │   └── tools/      # External tool integrations
│   ├── migrations/     # Alembic DB migrations
│   └── tests/          # Test files
└── docs/               # Architecture documentation
```

## Coding Standards

### TypeScript/React
- 2-space indentation
- Named exports (avoid default exports)
- Define types at file top
- Use `cn()` for className merging
- Tailwind CSS for all styling
- Use `React.forwardRef` for reusable components
- Use Lucide React for icons (not react-icons or heroicons)
- Keep components under 200 lines; split into sub-components if larger

### Python
- Line length: 100 chars
- Use type hints on all functions
- Async functions for I/O operations
- Follow ruff/black formatting
- Always use Pydantic v2 for request/response schemas
- Return specific HTTP status codes (201 for Created, 204 for No Content, etc.)

## Testing Workflow
- **Unit Tests:** Always run from the respective subdirectory (`/frontend` or `/backend`)
- **Pre-Commit:** Ensure `ruff check .` and `npm run lint` pass before asking for a commit
- **Backend Markers:** `pytest -m "not slow"` to skip slow tests during development

## Memory Management (16GB RAM)
- **Avoid:** Large-scale refactors of more than 5 files at once
- **Avoid:** Reading entire directories or node_modules
- **Reference Mode:** Read specific files (e.g., `@backend/app/planner/nodes_v2/intent_router.py`) rather than broad directory scans
- **Incremental:** Implement changes step-by-step and verify after each logical step
- **Context Reset:** Run `/clear` after completing tasks to purge history from RAM
- **If stuck:** Reference `@CLAUDE.md` to reload context cleanly

## Auto-Compact Instructions
When auto-compacting this conversation, MUST preserve:
- **Architecture SSoT:** The 7-node LangGraph structure and `TripPlan` as single source of truth
- **Memory Safety:** The "Memory Management (16GB RAM)" rules - especially avoid reading large directories
- **Current Progress:** Verbatim file paths and function signatures currently being modified
- **Debugging State:** Any active error messages or test failures from `pytest` or `vitest`
- **Critical Context:** Do NOT generalize architectural decisions; keep specific logic for `ConstraintGuard` auto-fix loop
- **Specialist Logic:** Preserve domain-specific safety rules (e.g., diving 24h no-fly buffer)

**Self-Update Rule:** If we establish a new project-wide pattern during a session, suggest adding it to this file before `/clear`.

**Compaction Strategy:**
- Use `/compact` manually after completing a significant sub-task
- Use `/clear` when switching between frontend and backend work (full RAM wipe + fresh `@CLAUDE.md` reload)
