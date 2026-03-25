#!/bin/bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$REPO_DIR/.ai_runtimes.env" ]; then
  set -a
  source "$REPO_DIR/.ai_runtimes.env"
  set +a
fi
"$REPO_DIR/.venv/bin/python" "$REPO_DIR/configure_stack.py"
