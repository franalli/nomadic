#!/bin/bash
# Copy key files flat into docs/key_files/.
# This folder is git-ignored.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/backend/app"
DEST="$ROOT/docs/key_files"

# Clean and recreate
rm -rf "$DEST"
mkdir -p "$DEST"

# --- Explicit file list ---
for f in main.py plan_graph.py validation.py planner/state/graph_state.py crud_document.py crud_trip.py schemas.py config.py graph_plan_utils.py db_models.py middleware/session.py tile_service/service.py tile_service/provider_base.py tile_service/models.py; do
  cp "$SRC/$f" "$DEST/$(basename "$f")"
done

# --- Root CLAUDE.md ---
cp "$ROOT/CLAUDE.md" "$DEST/CLAUDE.md"

# --- Everything in planner/ (flat, skip __init__, cache, and trivial) ---
find "$SRC/planner" \
  -type f \
  ! -name '__init__.py' \
  ! -name 'test_mode.py' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  ! -path '*/cache/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Everything in prompts/ (flat, skip all .txt prompt templates) ---
find "$SRC/prompts" \
  -type f \
  ! -name '*.txt' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Everything in services/ (flat, skip __init__ and cache) ---
find "$SRC/services" \
  -type f \
  ! -name '__init__.py' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Everything in tools/ (flat, skip __init__ and cache) ---
find "$SRC/tools" \
  -type f \
  ! -name '__init__.py' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Frontend: explicit files (lib, types, hooks, components) ---
for f in \
  lib/api.ts \
  lib/streamParser.ts \
  lib/ghost-timeline-adapter.ts \
  lib/contentPolicyGuard.ts \
  lib/design-system.ts \
  types/plan-envelope.ts \
  types/document.ts \
  hooks/useViewNavigation.ts \
  hooks/usePreferenceAutoRegen.ts \
  components/plan/planStateHelpers.ts \
  components/map/InteractiveMap.tsx; do
  cp "$ROOT/frontend/$f" "$DEST/$(basename "$f")"
done

# --- Frontend: state/ (flat) ---
find "$ROOT/frontend/state" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Frontend: components/chat/ (flat) ---
find "$ROOT/frontend/components/chat" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

echo "Copied key files to $DEST"
find "$DEST" -type f | wc -l | xargs printf "  %s files total\n"
