# Nomadic Monorepo

- `frontend/` – Next.js + Tailwind UI for travel planner
- `backend/` – FastAPI service exposing `/v1/tiles/search`

# DB Setup

- `backend/.env` # for local uvicorn dev
- `backend/.env.docker` # for docker-compose

## Local dev

```bash
docker compose up --build  # backend + Postgres on :8000 and :5432
uvicorn app.main:app --reload # run fastAPI locally (without Docker)

cd frontend
npm install
npm run dev  # http://localhost:3000

```

## Tooling

- **Black** – configured in `backend/pyproject.toml` (`[tool.black]`, line length 88, py312) and enforced by the pre-commit `black` hook; run `python -m black app` inside `backend/` for manual formatting.
- **Ruff** – `[tool.ruff]` in the same file (E/F/I/B, py312) powers linting; VS Code’s `source.fixAll.ruff` and the `ruff --fix` pre-commit hook keep files clean, matching the manual `python -m ruff check app --fix` command.
- **Pre-commit hooks** – install once with `pre-commit install`; the configured `black` and `ruff --fix` hooks (see `.pre-commit-config.yaml`) automatically format/lint staged backend files or can be run explicitly via `pre-commit run --all-files`.
- **Frontend linting** – run `npm run lint` inside `frontend/` (runs `next lint` and full `eslint .`) or `npm run lint:fix` to auto-fix what ESLint safely can.
