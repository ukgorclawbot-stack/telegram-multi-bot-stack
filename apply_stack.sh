#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$REPO_DIR/.bot_tokens.env" ]; then
  set -a
  source "$REPO_DIR/.bot_tokens.env"
  set +a
fi

bash "$REPO_DIR/bootstrap_bot_stack.sh" apply "$REPO_DIR/bot_stack.bootstrap.toml"
