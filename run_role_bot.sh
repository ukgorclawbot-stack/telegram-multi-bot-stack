#!/bin/zsh
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 /absolute/path/to/env-file" >&2
  exit 1
fi

ENV_FILE="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"
source .venv/bin/activate
set -a
source "$ENV_FILE"
set +a

ENTRYPOINT="${BOT_ENTRYPOINT:-group_bot.py}"
python "$ENTRYPOINT"
