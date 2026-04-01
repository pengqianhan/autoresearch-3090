#!/bin/sh
set -eu

CLAUDE_BIN="${CLAUDE_BIN:-/home/phan635/.local/bin/claude}"
WORKSPACE_DIR="${MH_WORKSPACE_DIR:?MH_WORKSPACE_DIR is required}"
USER_PROMPT="${MH_USER_PROMPT:?MH_USER_PROMPT is required}"

if [ ! -x "$CLAUDE_BIN" ]; then
  echo "Claude binary not executable: $CLAUDE_BIN" >&2
  exit 2
fi

echo "[evaluator-wrapper] start $(date -Iseconds)" >&2
echo "[evaluator-wrapper] cwd=$(pwd)" >&2
echo "[evaluator-wrapper] workspace_dir=$WORKSPACE_DIR" >&2

"$CLAUDE_BIN" -p \
  --permission-mode bypassPermissions \
  --add-dir "$WORKSPACE_DIR" \
  --allowedTools "Read Edit Write Bash" \
  "$USER_PROMPT"

echo "[evaluator-wrapper] end $(date -Iseconds)" >&2
