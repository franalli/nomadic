#!/bin/bash
# Cleanup Claude Code session data.
# Safe to run — preserves: ide/, session-env, settings.json, settings.local.json

# First: clear Codex local session/cache artifacts
rm -rf "$HOME/.codex/sessions" "$HOME/.codex/shell_snapshots" "$HOME/.codex/tmp"
rm -f "$HOME/.codex/models_cache.json"

# Also clear VS Code Copilot conversation/state artifacts
VSCODE_USER_DIR="$HOME/Library/Application Support/Code/User"
rm -rf "$VSCODE_USER_DIR/globalStorage/github.copilot-chat"
rm -rf "$VSCODE_USER_DIR/globalStorage/github.copilot"
if [ -d "$VSCODE_USER_DIR/workspaceStorage" ]; then
  find "$VSCODE_USER_DIR/workspaceStorage" -type d -name "GitHub.copilot-chat" -prune -exec rm -rf {} +
fi

CLAUDE_DIR="$HOME/.claude"

echo "Cleaning Claude Code data..."

# ✅ Delete (safe)
rm -rf "$CLAUDE_DIR/projects"
rm -rf "$CLAUDE_DIR/plans"
rm -rf "$CLAUDE_DIR/file-history"
rm -rf "$CLAUDE_DIR/debug"
rm -rf "$CLAUDE_DIR/shell-snapshots"
rm -rf "$CLAUDE_DIR/todos"
rm -f  "$CLAUDE_DIR/stats-cache.json"

# ❌ NOT touched: ide/, session-env, settings.json, settings.local.json, agents/

echo "Done. Cleaned: projects, plans, file-history, debug, shell-snapshots, todos, stats-cache.json"

# Restart VS Code
if pgrep -x "Electron" > /dev/null || pgrep -f "Visual Studio Code" > /dev/null; then
  echo "Restarting VS Code..."
  osascript -e 'quit app "Visual Studio Code"'
  sleep 2
  open -a "Visual Studio Code"
  echo "VS Code restarted."
else
  echo "VS Code not running, skipping restart."
fi
