# Travel Bot Monorepo

- `frontend/` – Next.js + Tailwind UI for travel planner
- `backend/` – FastAPI service exposing `/v1/tiles/search`

## Local dev

```bash
docker compose up --build  # backend + Postgres on :8000 and :5432

cd frontend
npm install
npm run dev  # http://localhost:3000
