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
export PATH="$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -f "$SCRIPT_DIR/.ai_runtimes.env" ]; then
  set -a
  source "$SCRIPT_DIR/.ai_runtimes.env"
  set +a
fi
set -a
source "$ENV_FILE"
set +a

ENTRYPOINT="${BOT_ENTRYPOINT:-group_bot.py}"
python "$ENTRYPOINT"
