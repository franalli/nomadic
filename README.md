# Nomadic Monorepo

A travel planning application with an AI-powered itinerary generator.

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
- LangGraph + LangChain (AI orchestration)
- SpaCy (NLP)
- Pydantic (validation)

**Infrastructure:**
- PostgreSQL 16
- Docker Compose

## Project Structure

```
nomadic/
├── frontend/           # Next.js app
│   ├── app/            # App Router pages
│   ├── components/     # React components (by feature)
│   ├── hooks/          # Custom React hooks
│   ├── lib/            # Utilities
│   ├── state/          # Zustand stores
│   └── types/          # TypeScript types
├── backend/            # Python API
│   ├── app/            # Main application
│   │   ├── planner/    # Planning logic
│   │   ├── services/   # Business services
│   │   ├── tools/      # External tool integrations
│   │   └── prompts/    # AI prompt templates
│   ├── migrations/     # Alembic DB migrations
│   └── tests/          # Test files
├── docs/               # Documentation
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

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/v1/graph_plan` | POST | Generate travel plan |
| `/v1/graph_plan/stream` | POST | Stream travel plan |
| `/v1/document` | GET | Get plan document |
| `/v1/document` | PATCH | Update plan document |
| `/v1/chat` | GET | Get chat history |
| `/v1/chat/last` | DELETE | Delete last message |

### Session Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/session` | DELETE | Archive session data |

### Tiles & Suggestions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/tiles/click` | POST | Record tile click |
| `/v1/tiles/refresh` | POST | Refresh tiles |
| `/v1/suggestions/click` | POST | Record suggestion click |
| `/v1/document/tiles/{branch_id}` | POST | Add tiles to document |

### Validation & Utilities

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/validate-trip-input` | POST | Validate trip input |
| `/v1/destination-image` | POST | Get destination image |
| `/v1/expand-itinerary` | POST | Expand itinerary details |

### Admin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/admin/clear-validation-cache` | POST | Clear validation caches |
| `/v1/admin/fresh-start` | POST | Reset planner state |
| `/v1/admin/graph-stats` | GET | Get graph statistics |
| `/v1/admin/planner` | GET | Get planner state |
| `/v1/admin/clear-all-checkpoints` | POST | Clear all checkpoints |
| `/v1/admin/clear-all-caches` | POST | Clear all caches |

## Environment Setup

### Backend (`backend/.env`)

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/nomadic
OPENAI_API_KEY=sk-...
# See backend/.env.example for full list
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
ruff format .       # Format (or: black app)
```

### Pre-commit Hooks

```bash
pre-commit install              # Install hooks
pre-commit run --all-files      # Run manually
```

Configured hooks: `black`, `ruff`, `detect-secrets`, `trailing-whitespace`, `end-of-file-fixer`

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
- Follow ruff/black formatting

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
