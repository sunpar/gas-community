#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 TARGET_DIR" >&2
  echo "Install Codex queue runner files into TARGET_DIR." >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

TARGET_DIR="$1"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target directory does not exist: $TARGET_DIR" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_ROOT="$(cd -- "$TARGET_DIR" && pwd)"

install_file() {
  local src="$1"
  local dest="$2"

  mkdir -p "$(dirname "$dest")"
  cp -p "$src" "$dest"
  echo "Installed: ${dest#$TARGET_ROOT/}"
}

ensure_gitignore_entry() {
  local gitignore="$TARGET_ROOT/.gitignore"
  local entry=".codex-queue/"

  if [[ -f "$gitignore" ]] && grep -Fxq "$entry" "$gitignore"; then
    echo "Already ignored: $entry"
    return
  fi

  if [[ -f "$gitignore" ]] && [[ -s "$gitignore" ]] && [[ "$(tail -c 1 "$gitignore")" != "" ]]; then
    printf '\n' >> "$gitignore"
  fi
  printf '%s\n' "$entry" >> "$gitignore"
  echo "Updated: .gitignore"
}

install_file "$SOURCE_ROOT/scripts/codex_queue_worker.py" "$TARGET_ROOT/scripts/codex_queue_worker.py"
install_file "$SOURCE_ROOT/scripts/start_codex_workers.sh" "$TARGET_ROOT/scripts/start_codex_workers.sh"
install_file "$SOURCE_ROOT/scripts/add_codex_task.sh" "$TARGET_ROOT/scripts/add_codex_task.sh"
install_file "$SOURCE_ROOT/scripts/install_codex_queue.sh" "$TARGET_ROOT/scripts/install_codex_queue.sh"
install_file "$SOURCE_ROOT/config/codex-profiles.toml" "$TARGET_ROOT/config/codex-profiles.toml"
ensure_gitignore_entry

cat <<EOF

Installed Codex queue runner into:
$TARGET_ROOT

Next step:
Copy or include config/codex-profiles.toml in ~/.codex/config.toml before starting workers.
EOF
