#!/bin/bash
set -euo pipefail

MEMORY_ROOT="${SHARED_MEMORY_DIR:-$(cd "$(dirname "$0")/.." && pwd)/shared-memory}"
MEMORY_FILE="${LONG_TERM_MEMORY_FILE:-$MEMORY_ROOT/MEMORY.md}"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %z')"
TEXT="${*:-}"

if [ -z "$TEXT" ]; then
  echo "用法: $0 需要写入的记忆内容" >&2
  exit 1
fi

mkdir -p "$(dirname "$MEMORY_FILE")"
touch "$MEMORY_FILE"
printf -- "- [%s] %s\n" "$STAMP" "$TEXT" >> "$MEMORY_FILE"
echo "已写入: $MEMORY_FILE"
