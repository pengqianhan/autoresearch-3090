#!/bin/sh
set -eu

CLAUDE_BIN="${CLAUDE_BIN:-/home/phan635/.local/bin/claude}"
REPO_ROOT="${MH_REPO_ROOT:?MH_REPO_ROOT is required}"
CANDIDATE_DIR="${MH_CANDIDATE_DIR:?MH_CANDIDATE_DIR is required}"
CANDIDATE_PROGRAM="${MH_CANDIDATE_PROGRAM:?MH_CANDIDATE_PROGRAM is required}"
PROMPT_FILE="${CANDIDATE_DIR}/proposer_prompt.txt"
MODE="${MH_CLAUDE_PROPOSER_MODE:-prompt}"
OUTPUT_FORMAT="${MH_CLAUDE_OUTPUT_FORMAT:-text}"
MODEL_ARG="${MH_CLAUDE_MODEL:-}"
EFFORT_ARG="${MH_CLAUDE_EFFORT:-}"
TOOLS_ARG="${MH_CLAUDE_PROPOSER_TOOLS:-Read Edit Write Bash(git:*) Bash(rg:*) Bash(ls:*) Bash(cat:*)}"
TASK_TEXT="Inspect the history and improve candidate_program.md in the current directory. Only edit candidate_program.md, then return a short summary of the changes."

if [ ! -x "$CLAUDE_BIN" ]; then
  echo "Claude binary not executable: $CLAUDE_BIN" >&2
  exit 2
fi

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Missing proposer prompt file: $PROMPT_FILE" >&2
  exit 2
fi

if [ ! -f "$CANDIDATE_PROGRAM" ]; then
  echo "Missing candidate program: $CANDIDATE_PROGRAM" >&2
  exit 2
fi

echo "[proposer-wrapper] start $(date -Iseconds)" >&2
echo "[proposer-wrapper] cwd=$(pwd)" >&2
echo "[proposer-wrapper] candidate_dir=$CANDIDATE_DIR" >&2
echo "[proposer-wrapper] candidate_program=$CANDIDATE_PROGRAM" >&2
echo "[proposer-wrapper] mode=$MODE output_format=$OUTPUT_FORMAT" >&2

set -- "$CLAUDE_BIN" -p \
  --permission-mode bypassPermissions \
  --add-dir "$REPO_ROOT" \
  --allowedTools "$TOOLS_ARG" \
  --append-system-prompt "$(cat "$PROMPT_FILE")"

if [ "$OUTPUT_FORMAT" != "text" ]; then
  set -- "$@" --output-format "$OUTPUT_FORMAT"
fi

if [ -n "$MODEL_ARG" ]; then
  set -- "$@" --model "$MODEL_ARG"
fi

if [ -n "$EFFORT_ARG" ]; then
  set -- "$@" --effort "$EFFORT_ARG"
fi

case "$MODE" in
  prompt)
    set -- "$@" "$TASK_TEXT"
    ;;
  stdin)
    echo "[proposer-wrapper] using stdin input mode" >&2
    printf '%s\n' "$TASK_TEXT" | "$@"
    echo "[proposer-wrapper] end $(date -Iseconds)" >&2
    exit 0
    ;;
  json)
    echo "[proposer-wrapper] using json output mode" >&2
    set -- "$@" --output-format json "$TASK_TEXT"
    ;;
  *)
    echo "Unknown MH_CLAUDE_PROPOSER_MODE: $MODE" >&2
    exit 2
    ;;
esac

"$@"

echo "[proposer-wrapper] end $(date -Iseconds)" >&2
