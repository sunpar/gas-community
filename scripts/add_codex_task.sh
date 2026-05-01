#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 high|medium|low slug"
  echo "Then write the task body on stdin."
  exit 2
fi

LEVEL="$1"
SLUG="$2"

case "$LEVEL" in
  high|medium|low) ;;
  *)
    echo "Invalid level: $LEVEL"
    exit 2
    ;;
esac

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
QUEUE_ROOT="${QUEUE_ROOT:-$REPO_ROOT/.codex-queue}"
INBOX="$QUEUE_ROOT/inbox"

mkdir -p "$INBOX"

SAFE_SLUG="$(
  echo "$SLUG" |
    tr '[:upper:]' '[:lower:]' |
    sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//'
)"
FINAL="$INBOX/${LEVEL}__${SAFE_SLUG}.md"
TMP="$FINAL.tmp"

cat > "$TMP"
mv "$TMP" "$FINAL"

echo "Queued: $FINAL"
