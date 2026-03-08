#!/usr/bin/env bash
# restart-dev.sh — Kill all dev processes and restart them.
# Called by VS Code task "Restart Dev Servers" (Ctrl+Shift+S).
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Stopping dev processes ==="

# Kill backend (uvicorn/python on :8000)
lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "Killed backend on :8000" || echo "No backend on :8000"

# Kill frontend (next dev on :3000)
lsof -ti:3000 | xargs kill -9 2>/dev/null && echo "Killed frontend on :3000" || echo "No frontend on :3000"

# Restart docker DB
echo "=== Restarting Docker DB ==="
cd "$DIR/backend"
docker compose stop db 2>/dev/null || true
docker compose up db --build -d
sleep 2

# Run migrations
echo "=== Running migrations ==="
source "$DIR/backend/.venv/bin/activate"
alembic upgrade head

# Start backend
echo "=== Starting backend ==="
cd "$DIR/backend"
python start.py &
BACKEND_PID=$!

# Wait for backend to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "Backend ready (PID $BACKEND_PID)"
        break
    fi
    sleep 1
done

# Start frontend
echo "=== Starting frontend ==="
cd "$DIR/frontend"
npm run dev &
FRONTEND_PID=$!
echo "Frontend started (PID $FRONTEND_PID)"

echo ""
echo "=== Dev servers restarted ==="
echo "  Backend:  http://localhost:8000 (PID $BACKEND_PID)"
echo "  Frontend: http://localhost:3000 (PID $FRONTEND_PID)"
echo ""

# Keep script alive so VS Code terminal stays open and shows logs
wait
