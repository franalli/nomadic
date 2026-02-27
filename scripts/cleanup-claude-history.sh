#!/bin/bash
# =============================================================================
# Cleanup AI coding tool session data (Claude Code, Codex, VS Code Copilot)
# Safe to run — preserves auth, config, settings, keybindings, plugins, rules
# =============================================================================

set -euo pipefail

# --- Claude Code ---
CLAUDE_DIR="$HOME/.claude"
echo "🧹 Cleaning Claude Code data..."

# ✅ Session & history artifacts
rm -rf "$CLAUDE_DIR/projects"
rm -rf "$CLAUDE_DIR/plans"
rm -rf "$CLAUDE_DIR/todos"
rm -rf "$CLAUDE_DIR/tasks"
rm -rf "$CLAUDE_DIR/file-history"
rm -rf "$CLAUDE_DIR/shell-snapshots"
rm -rf "$CLAUDE_DIR/backups"
rm -rf "$CLAUDE_DIR/cache"
rm -rf "$CLAUDE_DIR/paste-cache"
rm -rf "$CLAUDE_DIR/debug"
rm -rf "$CLAUDE_DIR/telemetry"
rm -f  "$CLAUDE_DIR/stats-cache.json"
rm -f  "$CLAUDE_DIR/history.jsonl"
rm -f  "$CLAUDE_DIR/mcp-needs-auth-cache.json"
rm -rf "$CLAUDE_DIR/session-env"

# ❌ NOT touched: ide/, settings.json, keybindings.json, plugins/

echo "   ✅ Claude Code cleaned"

# --- Codex ---
CODEX_DIR="$HOME/.codex"
echo "🧹 Cleaning Codex data..."

# ✅ Session & history artifacts
rm -rf "$CODEX_DIR/sessions"
rm -rf "$CODEX_DIR/shell_snapshots"
rm -rf "$CODEX_DIR/tmp"
rm -rf "$CODEX_DIR/log"
rm -rf "$CODEX_DIR/vendor_imports"
rm -f  "$CODEX_DIR/models_cache.json"
rm -f  "$CODEX_DIR/history.jsonl"
rm -f  "$CODEX_DIR/state_5.sqlite"
rm -f  "$CODEX_DIR/state_5.sqlite-shm"
rm -f  "$CODEX_DIR/state_5.sqlite-wal"
rm -f  "$CODEX_DIR/.personality_migration"

# ❌ NOT touched: auth.json, config.toml, version.json, rules/, skills/

echo "   ✅ Codex cleaned"

# --- VS Code Copilot ---
VSCODE_USER_DIR="$HOME/Library/Application Support/Code/User"
echo "🧹 Cleaning VS Code Copilot data..."

rm -rf "$VSCODE_USER_DIR/globalStorage/github.copilot-chat"
rm -rf "$VSCODE_USER_DIR/globalStorage/github.copilot"
if [ -d "$VSCODE_USER_DIR/workspaceStorage" ]; then
  find "$VSCODE_USER_DIR/workspaceStorage" -type d -name "GitHub.copilot-chat" -prune -exec rm -rf {} +
fi

echo "   ✅ VS Code Copilot cleaned"

# --- Restart VS Code ---
if pgrep -x "Electron" > /dev/null || pgrep -f "Visual Studio Code" > /dev/null; then
  echo "🔄 Restarting VS Code..."
  osascript -e 'quit app "Visual Studio Code"'
  sleep 2
  open -a "Visual Studio Code"
  echo "   ✅ VS Code restarted"
else
  echo "   ℹ️  VS Code not running, skipping restart"
fi

echo ""
echo "🎉 Full cleanup complete."
