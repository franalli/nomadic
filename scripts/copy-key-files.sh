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

copy_if_exists() {
  local src="$1"
  local dest_name="$2"

  if [[ -f "$src" ]]; then
    cp "$src" "$DEST/$dest_name"
  else
    printf 'Skipping missing file: %s\n' "$src" >&2
  fi
}

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
  middleware/session.py \
  tile_service/service.py \
  tile_service/provider_base.py \
  tile_service/models.py; do
  copy_if_exists "$SRC/$f" "$(basename "$f")"
done

# --- Root CLAUDE.md ---
copy_if_exists "$ROOT/CLAUDE.md" "CLAUDE.md"

# --- Everything in planner/ (flat, skip __init__, cache, and trivial) ---
if [[ -d "$SRC/planner" ]]; then
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
else
  printf 'Skipping missing directory: %s\n' "$SRC/planner" >&2
fi

# --- Everything in tile_service/ (flat, skip __init__ and cache) ---
if [[ -d "$SRC/tile_service" ]]; then
  find "$SRC/tile_service" \
    -type f \
    ! -name '__init__.py' \
    ! -name '*.pyc' \
    ! -name '.DS_Store' \
    ! -path '*/__pycache__/*' \
    | while read -r src; do
      cp "$src" "$DEST/$(basename "$src")"
    done
else
  printf 'Skipping missing directory: %s\n' "$SRC/tile_service" >&2
fi

# --- Prompts (skip specialist .txt except synthesizer + local_expert) ---
if [[ -d "$SRC/prompts" ]]; then
  find "$SRC/prompts" \
    -type f \
    ! -name '*.pyc' \
    ! -name '.DS_Store' \
    ! -path '*/__pycache__/*' \
    ! -path '*/specialists/*' \
    | while read -r src; do
      cp "$src" "$DEST/$(basename "$src")"
    done
  # Keep only local_expert from specialists (synthesizer.txt lives at prompts/ root, already copied above)
  copy_if_exists "$SRC/prompts/specialists/local_expert.txt" "local_expert_specialist.txt"
else
  printf 'Skipping missing directory: %s\n' "$SRC/prompts" >&2
fi

# --- Everything in services/ (flat, skip __init__ and cache) ---
if [[ -d "$SRC/services" ]]; then
  find "$SRC/services" \
    -type f \
    ! -name '__init__.py' \
    ! -name '*.pyc' \
    ! -name '.DS_Store' \
    ! -path '*/__pycache__/*' \
    | while read -r src; do
      cp "$src" "$DEST/$(basename "$src")"
    done
else
  printf 'Skipping missing directory: %s\n' "$SRC/services" >&2
fi

# --- Everything in tools/ (flat, skip __init__ and cache) ---
if [[ -d "$SRC/tools" ]]; then
  find "$SRC/tools" \
    -type f \
    ! -name '__init__.py' \
    ! -name '*.pyc' \
    ! -name '.DS_Store' \
    ! -path '*/__pycache__/*' \
    | while read -r src; do
      cp "$src" "$DEST/$(basename "$src")"
    done
else
  printf 'Skipping missing directory: %s\n' "$SRC/tools" >&2
fi


# --- Frontend: components/chat only (TypeScript + TSX files) ---
if [[ -d "$ROOT/frontend/components/chat" ]]; then
  find "$ROOT/frontend/components/chat" \
    -type f \
    \( -name '*.ts' -o -name '*.tsx' \) \
    | while read -r src; do
      cp "$src" "$DEST/$(basename "$src")"
    done
else
  printf 'Skipping missing directory: %s\n' "$ROOT/frontend/components/chat" >&2
fi

echo "Copied key files to $DEST"
find "$DEST" -type f | wc -l | xargs printf "  %s files total\n"
