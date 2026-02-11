#!/bin/bash
# Copy key backend files flat into docs/key_backend_files/.
# This folder is git-ignored.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/backend/app"
DEST="$ROOT/docs/key_backend_files"

# Clean and recreate
rm -rf "$DEST"
mkdir -p "$DEST"

# --- Explicit file list ---
for f in plan_graph.py validation.py planner/state/graph_state.py crud_document.py crud_trip.py; do
  cp "$SRC/$f" "$DEST/$(basename "$f")"
done

# --- Root CLAUDE.md ---
cp "$ROOT/CLAUDE.md" "$DEST/CLAUDE.md"

# --- Everything in planner/ (flat, skip __init__ and cache) ---
find "$SRC/planner" \
  -type f \
  ! -name '__init__.py' \
  ! -name '*.pyc' \
  ! -name '.DS_Store' \
  ! -path '*/__pycache__/*' \
  ! -path '*/cache/*' \
  | while read -r src; do
    cp "$src" "$DEST/$(basename "$src")"
  done

# --- Everything in prompts/ (flat) ---
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

echo "Copied key files to $DEST"
find "$DEST" -type f | wc -l | xargs printf "  %s files total\n"
