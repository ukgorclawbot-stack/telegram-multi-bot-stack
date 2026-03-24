#!/bin/zsh
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 /absolute/path/to/env-file" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/run_role_bot.sh" "$1"
