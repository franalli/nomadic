# Nomadic Monorepo

![Nomadic planning a 10-day Bali trip from a single prompt](docs/nomadic-demo.gif)

A travel planning application whose itinerary generator is an AI agent: a
LangChain `create_agent` tool-calling loop that decides which planning tools to
run each turn (field extraction, specialist advice, tile search, itinerary
build, validation). See [Architecture](#architecture).

## Tech Stack

**Frontend:**
- Next.js 16 (App Router)
- React 19
- TypeScript
- Tailwind CSS
- Zustand (state management)
- Framer Motion (animations)
- Mapbox GL (maps)

**Backend:**
- Python 3.12
- FastAPI
- SQLAlchemy + asyncpg (async PostgreSQL)
- Alembic (migrations)
- LangChain `create_agent` + LangGraph (agentic tool-calling loop)
- LLMs: OpenAI + Google Gemini (provider-routed via `llm_factory`; each step's model set by `*_MODEL` env vars)
- Pydantic v2 (validation)

**Infrastructure:**
- PostgreSQL 16
- Docker Compose

## Architecture

The planner is a single `create_agent` tool-calling loop — there is no
deterministic coordinator DAG. A turn flows:

```
POST /api/graph_plan/stream
  → streaming.generate_sse()                # SSE generator + connection slot
      → agent_runner.run_agent_turn_streaming   # drives the create_agent loop
          → agent.create_planner_agent()        # tool-calling graph + middleware
              ↳ the model selects tools:
                extract_trip_fields · get_specialist_advice · get_local_intel
                · search_tiles · build_itinerary · validate_plan
              ↳ terminal model turn streams the assistant reply
      → coordinator._build_envelope()       # final state → SSE complete envelope
```

Events on the wire: `node_status` · `partial` · `token` · `feasibility_warning`
· `complete` · `error`.

### Agent tools

Each tool wraps the node/service logic behind one planning capability; the model
decides which to call, and in what order, per turn.

| Tool | Wraps | Purpose |
|------|-------|---------|
| `extract_trip_fields` | `nodes/router_extraction` | Intent + field extraction + change typing |
| `get_specialist_advice` | `nodes/vertical_specialist` | Tier 1 specialist planning / replanning |
| `get_local_intel` | `nodes/local_expert` | Destination local-intelligence section |
| `search_tiles` | `nodes/logistics_node` | Flights / hotels / activities refresh |
| `build_itinerary` | `app/services/itinerary_builder` | Day-by-day schedule from sections + tiles |
| `validate_plan` | `nodes/constraint_guard` | Constraint + feasibility validation |

### Middleware

`agent.py` composes the loop from (outermost first) `ModelCallLimitMiddleware`
(8 model calls) and `ToolCallLimitMiddleware` (16 tool calls) as the runaway
bound, `ModelSelectionMiddleware` (upgrades the loop model on complex turns),
`ModelRetryMiddleware` (backoff on transient provider errors),
`DynamicPromptMiddleware` (per-turn system prompt from live plan state), and
`TurnLifecycleMiddleware` (resets `turn_meta` each turn, then merges every tool
result into agent state via a per-tool dispatch table).

### Itinerary expansion

```
POST /api/expand-itinerary
  → request_dedup                           # idempotency key + per-session mutex
  → streaming.generate_ndjson()
      → app/services/itinerary_builder      # day-by-day schedule, streamed as NDJSON
```

`PlanDocumentData` is the single source of truth for all trip state (persisted
as JSON in the `plan_documents` table). For depth, see:

- `CLAUDE.md` — working rules, file map, governance
- `docs/plan_graph_analysis.md` — backend planner spec
- `docs/ux_unified_architecture.md` — view states & rendering
- `docs/data-contracts.md` — API routes, schemas, state store
- `docs/design-system.md` — UI tokens

## Project Structure

```
nomadic/
├── frontend/           # Next.js app
│   ├── app/            # App Router pages
│   ├── components/     # React components (by feature)
│   ├── hooks/          # Custom React hooks (incl. useChatSse — SSE driver)
│   ├── lib/            # API clients, design system, parsers
│   ├── state/          # Zustand stores (documentStore is primary)
│   └── types/          # TypeScript types (document.ts, plan-envelope.ts)
├── backend/            # Python API (FastAPI)
│   ├── app/
│   │   ├── main.py        # App + all route handlers
│   │   ├── streaming.py   # SSE / NDJSON generators
│   │   ├── planner/       # The agentic loop
│   │   │   ├── agent.py       # create_planner_agent()
│   │   │   ├── middleware.py  # dynamic prompt + turn lifecycle
│   │   │   ├── tools/         # model-callable tools
│   │   │   ├── nodes/         # node logic the tools wrap
│   │   │   ├── services/      # agent_runner, feasibility, iata_resolver, suggestions
│   │   │   ├── coordinator.py # _build_envelope() + enrichment/tile helpers
│   │   │   ├── prompts/       # planner prompt builders
│   │   │   ├── state/         # GraphState / TripPlan
│   │   │   └── schemas/       # planner schemas
│   │   ├── services/      # itinerary_builder, caching, spend guard, enrichment
│   │   ├── tile_service/  # Google Places provider
│   │   ├── middleware/    # session + CSRF
│   │   └── prompts/       # specialist .txt prompts
│   ├── migrations/     # Alembic DB migrations
│   └── tests/          # pytest
├── docs/               # Single-source-of-truth specs
└── scripts/            # Utility scripts
```

## Local Development

### Prerequisites
- Node.js 20-22
- Python 3.12
- Docker (for PostgreSQL)

### Quick Start

```bash
# Start PostgreSQL
docker compose up db --build

# Backend (in separate terminal)
cd backend
pip install -r requirements.txt
python start.py  # or: uvicorn app.main:app --reload

# Frontend (in separate terminal)
cd frontend
npm install
npm run dev  # http://localhost:3000
```

### Docker Options

```bash
# PostgreSQL only
docker compose up db --build

# Backend + PostgreSQL
docker compose --profile backend up --build db backend
```

## API Reference

All routes are defined in `backend/app/main.py` (analytics routes in
`app/analytics_routes.py`). The live OpenAPI spec is at `http://localhost:8000/openapi.json`.

### Planning (the agent turn)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/graph_plan/stream` | POST | Run an agent turn; streams SSE (`token` / `partial` / `complete` / `error`) |

### Plan document & itinerary editing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/document` | GET | Fetch the current `PlanDocumentData` |
| `/api/document` | PATCH | Patch trip inputs / settings |
| `/api/expand-itinerary` | POST | Expand strategy into a day-by-day itinerary (NDJSON) |
| `/api/document/fill-day` | POST | Add an activity to one day (targeted, no full rebuild) |
| `/api/document/insert-activity-block` | POST | Insert an activity block |
| `/api/document/remove-block` | POST | Remove a block |
| `/api/document/apply-arrangement` | POST | Apply a day re-arrangement (drag/drop) |
| `/api/document/validate-arrangement` | POST | Validate a proposed arrangement |
| `/api/document/restore-snapshot` | POST | Undo — restore a prior snapshot |
| `/api/document/tiles/{branch_id}` | POST | Add tiles to a branch |

### Tiles, activities & enrichment

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tiles/refresh` | POST | Refresh tiles |
| `/api/tiles/click` | POST | Record a tile click (analytics) |
| `/api/activities/browse` | POST | Browse the activity pool |
| `/api/specialist/{section_id}/enrichment` | GET | Poll async specialist/local-expert enrichment |

### Chat & session

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | GET | Get chat history |
| `/api/chat/last` | DELETE | Delete the last message |
| `/api/session/new` | POST | Start a fresh session |
| `/api/session` | DELETE | Archive / reset session data |

### Auth (Google OAuth) · trips · sharing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/google/url` | GET | Get the Google OAuth URL |
| `/api/auth/google/callback` | POST | Complete OAuth |
| `/api/auth/me` | GET | Current user |
| `/api/auth/logout` | POST | Log out |
| `/api/trips` | GET | List the user's saved trips |
| `/api/trips/{trip_id}/resume` | POST | Resume a saved trip |
| `/api/share` | POST | Create a shareable link |
| `/api/shared/{slug}` | GET | Fetch a shared trip |
| `/api/share/fork/{slug}` | POST | Fork a shared trip |

### Utilities, media & analytics

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/validate-trip-input` | POST | Validate trip input |
| `/api/destination-image` | POST | Get a destination hero image |
| `/api/media/google-places-photo` | GET | Signed Google Places photo proxy |
| `/api/media/google-places-photo-url` | GET | Resolve a Places photo URL |
| `/api/analytics/event` | POST | Record a funnel event |

### Admin (require `ADMIN_API_KEY`)

- **Stats (GET):** `/api/admin/cache-stats`, `graph-stats`, `planner`,
  `places-telemetry`, `router-cache-stats`, `specialist-cache-stats`,
  `tile-cache-stats`, `spend-guard-stats`
- **Resets (POST):** `/api/admin/clear-all-caches`, `clear-l1-l2-caches`,
  `clear-router-cache`, `clear-specialist-cache`, `clear-tile-cache`,
  `clear-validation-cache`, `clear-spend-guard`, `clear-all-checkpoints`,
  `fresh-start`

## Environment Setup

### Backend (`backend/.env`)

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/nomadic
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...            # Gemini — LLMs are split across OpenAI + Gemini
# Per-step models are configurable: ROUTER_MODEL, SPECIALIST_MODEL,
# LOCAL_EXPERT_MODEL, GUARD_MODEL, SYNTHESIZER_PLANNING_MODEL, etc.
# Also: GOOGLE_PLACES / VIATOR / AVIASALES keys, OAuth creds, ADMIN_API_KEY, spend-guard caps.
# All env vars are read in app/config.py — that file is the authoritative list.
```

### Frontend (`frontend/.env.local`)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_MAPBOX_TOKEN=pk...
# See frontend/.env.example for full list
```

## Type Generation

Frontend TypeScript types can be auto-generated from backend Pydantic schemas:

```bash
# 1. Start backend first
cd backend && uvicorn app.main:app --reload

# 2. Generate types
cd frontend && npm run types:generate
```

Generated types: `frontend/types/generated.ts`

## Database Migrations (Alembic)

```bash
cd backend

# Apply all migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Rollback one migration
alembic downgrade -1

# View history
alembic history

# Run in Docker
docker compose run --rm backend alembic upgrade head
```

## Testing

### Frontend

```bash
cd frontend
npm run test        # Run once
npm run test:watch  # Watch mode
```

### Backend

```bash
cd backend
pytest                           # All tests
pytest -m "not slow"             # Skip slow tests
pytest -m "e2e"                  # E2E tests only
pytest --benchmark-only          # Benchmarks
```

Test markers: `nightly`, `slow`, `golden`, `e2e`, `llm_smoke`

## Linting & Formatting

### Frontend

```bash
cd frontend
npm run lint        # Check
npm run lint:fix    # Auto-fix
npm run format      # Prettier
```

### Backend

```bash
cd backend
ruff check .        # Lint
ruff check . --fix  # Auto-fix
ruff format .       # Format
```

### Pre-commit Hooks

```bash
pre-commit install              # Install hooks
pre-commit run --all-files      # Run manually
```

Configured hooks: `ruff`, `ruff-format`, `detect-secrets`, `detect-private-key`, `check-yaml`, `check-merge-conflict`, `trailing-whitespace`, `end-of-file-fixer`, and `ssot-check` (validates the `docs/` single-source-of-truth files)

## Coding Standards

### TypeScript/React
- 2-space indentation
- Named exports (avoid default exports)
- Define types at file top
- Use `cn()` for className merging
- Tailwind CSS for all styling

### Python
- Line length: 100 chars
- Use type hints
- Async functions for I/O operations
- Follow ruff formatting (`ruff format`)

## Claude Code Setup

For developers using Claude Code, this repo includes optimizations for 16GB RAM systems.

### Files

- **`CLAUDE.md`** - Lightweight project reference (use `@CLAUDE.md` to load context)
- **`.claudeignore`** - Excludes `node_modules`, `.venv`, build artifacts from indexing

### Recommended Settings

Add to `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 3
}
```

This reduces history retention from 30 days to 3 days, preventing memory bloat.

### Memory Management

If VS Code becomes sluggish or Extension Host usage climbs:

1. Run `/clear` to wipe conversation history
2. Type `Refer to @CLAUDE.md for my project rules.`

This reloads context from the lightweight markdown file instead of heavy JSONL history.

### Clearing Stale History (Manual)

```bash
# Delete old conversation logs (if needed)
rm -rf ~/.claude/projects/*/conversations/*.jsonl
```
