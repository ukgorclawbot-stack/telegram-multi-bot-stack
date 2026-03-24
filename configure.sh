#!/bin/bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
"$REPO_DIR/.venv/bin/python" "$REPO_DIR/configure_stack.py"
