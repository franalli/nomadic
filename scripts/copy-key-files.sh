#!/bin/bash
# Copy key backend/frontend files flat into docs/key_files/.
# This folder is git-ignored.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/backend/app"
DEST="$ROOT/docs/key_files"

# Clean and recreate
rm -rf "$DEST"
mkdir -p "$DEST"

# --- Explicit file list ---
for f in \
  main.py \
  validation.py \
  crud_document.py \
  crud_trip.py \
  schemas.py \
  config.py \
  graph_plan_utils.py \
  db_models.py \
  lifespan.py \
  streaming.py \
  request_dedup.py \
  rate_limit.py \
  sse_state.py \
  validation_cache.py \
  planner/plan_graph.py \
  middleware/session.py \
  tile_service/service.py \
  tile_service/provider_base.py \
  tile_service/models.py; do
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

# --- Everything in tile_service/ (flat, skip __init__ and cache) ---
find "$SRC/tile_service" \
  -type f \
  ! -name '__init__.py' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Everything in prompts/ (flat, include .txt prompt templates) ---
find "$SRC/prompts" \
  -type f \
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

# --- Everything in utils/ (flat, skip __init__ and cache) ---
find "$SRC/utils" \
  -type f \
  ! -name '__init__.py' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Frontend: lib/, types/, hooks/ (flat) ---
find "$ROOT/frontend/lib" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

find "$ROOT/frontend/types" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

find "$ROOT/frontend/hooks" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
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

# --- Frontend: map/, plan/, layout/ (flat) ---
find "$ROOT/frontend/components/map" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

find "$ROOT/frontend/components/plan" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

find "$ROOT/frontend/components/layout" \
  -type f \
  ! -name '.DS_Store' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

echo "Copied key files to $DEST"
find "$DEST" -type f | wc -l | xargs printf "  %s files total\n"
