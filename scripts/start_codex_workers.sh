#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
QUEUE_ROOT="${QUEUE_ROOT:-$REPO_ROOT/.codex-queue}"
WORKTREE_ROOT="${WORKTREE_ROOT:-$(dirname "$REPO_ROOT")/.$(basename "$REPO_ROOT")-codex-worktrees}"
AGENTS_HIGH="${AGENTS_HIGH:-1}"
AGENTS_MEDIUM="${AGENTS_MEDIUM:-1}"
AGENTS_LOW="${AGENTS_LOW:-1}"

mkdir -p "$QUEUE_ROOT/inbox"
mkdir -p "$WORKTREE_ROOT"

start_level() {
  local level="$1"
  local count="$2"

  for _ in $(seq 1 "$count"); do
    python3 "$REPO_ROOT/scripts/codex_queue_worker.py" \
      --repo-root "$REPO_ROOT" \
      --queue-root "$QUEUE_ROOT" \
      --worktree-root "$WORKTREE_ROOT" \
      --level "$level" \
      --respawn \
      --cleanup-worktree-on-success &
  done
}

start_level high "$AGENTS_HIGH"
start_level medium "$AGENTS_MEDIUM"
start_level low "$AGENTS_LOW"

echo "Started Codex queue workers."
echo "Queue root:    $QUEUE_ROOT"
echo "Worktree root: $WORKTREE_ROOT"
echo "Workers: high=$AGENTS_HIGH medium=$AGENTS_MEDIUM low=$AGENTS_LOW"

wait
