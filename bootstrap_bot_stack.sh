#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION="${1:-generate}"
CONFIG_PATH="${2:-$SCRIPT_DIR/bot_stack.bootstrap.toml}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

case "$ACTION" in
  generate)
    if [ ! -f "$CONFIG_PATH" ]; then
      echo "未找到配置文件: $CONFIG_PATH" >&2
      echo "你可以先执行：" >&2
      echo "  cp $SCRIPT_DIR/bot_stack.bootstrap.toml.example $SCRIPT_DIR/bot_stack.bootstrap.toml" >&2
      exit 1
    fi
    "$PYTHON_BIN" "$SCRIPT_DIR/bootstrap_bot_stack.py" --config "$CONFIG_PATH"
    ;;
  apply)
    if [ ! -f "$CONFIG_PATH" ]; then
      echo "未找到配置文件: $CONFIG_PATH" >&2
      echo "你可以先执行：" >&2
      echo "  cp $SCRIPT_DIR/bot_stack.bootstrap.toml.example $SCRIPT_DIR/bot_stack.bootstrap.toml" >&2
      exit 1
    fi
    "$PYTHON_BIN" "$SCRIPT_DIR/bootstrap_bot_stack.py" --config "$CONFIG_PATH" --apply-launchd --load-services
    ;;
  export-live)
    "$PYTHON_BIN" "$SCRIPT_DIR/reverse_export_bot_stack.py"
    ;;
  migration-template)
    if [ ! -f "$SCRIPT_DIR/bot_stack.reverse_exported.toml" ]; then
      "$PYTHON_BIN" "$SCRIPT_DIR/reverse_export_bot_stack.py"
    fi
    "$PYTHON_BIN" "$SCRIPT_DIR/make_migration_ready_stack.py"
    ;;
  *)
    echo "用法: $0 [generate|apply] [config-path]" >&2
    echo "      $0 export-live" >&2
    echo "      $0 migration-template" >&2
    exit 1
    ;;
esac
