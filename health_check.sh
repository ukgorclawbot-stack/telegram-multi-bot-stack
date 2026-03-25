#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_PATH="${1:-$SCRIPT_DIR/bot_stack.bootstrap.toml}"
MONITOR_REPORT_PATH="${MONITOR_REPORT_PATH:-$HOME/.openclaw/workspace/reports/binance-monitor/latest.json}"
DAILY_REPORT_PATH="${DAILY_REPORT_PATH:-$HOME/.openclaw/workspace/reports/daily-crypto/latest.digest.json}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
export PATH="$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ -f "$SCRIPT_DIR/.ai_runtimes.env" ]; then
  set -a
  source "$SCRIPT_DIR/.ai_runtimes.env"
  set +a
fi

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

status_icon() {
  case "$1" in
    ok) echo "OK" ;;
    warn) echo "WARN" ;;
    fail) echo "FAIL" ;;
    *) echo "INFO" ;;
  esac
}

timestamp_of() {
  local path="$1"
  if [ -f "$path" ]; then
    stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "$path"
  else
    echo "-"
  fi
}

age_seconds_of() {
  local path="$1"
  if [ -f "$path" ]; then
    local now mtime
    now="$(date +%s)"
    mtime="$(stat -f '%m' "$path")"
    echo $((now - mtime))
  else
    echo "-1"
  fi
}

format_age() {
  local seconds="$1"
  if [ "$seconds" -lt 0 ]; then
    echo "缺失"
    return
  fi
  if [ "$seconds" -lt 60 ]; then
    echo "${seconds}s"
  elif [ "$seconds" -lt 3600 ]; then
    echo "$((seconds / 60))m"
  else
    echo "$((seconds / 3600))h"
  fi
}

launch_field() {
  local label="$1"
  local key="$2"
  (launchctl print "gui/$(id -u)/$label" 2>/dev/null || true) | awk -F'= ' -v key="$key" '
    $0 ~ ("^[[:space:]]*" key " = ") {gsub(/^[[:space:]]+/, "", $2); print $2; exit}
  '
}

load_bot_rows() {
  "$PYTHON_BIN" - "$CONFIG_PATH" <<'PY'
from pathlib import Path
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

config_path = Path(sys.argv[1])
if not config_path.exists():
    raise SystemExit(f"missing config: {config_path}")

data = tomllib.loads(config_path.read_text(encoding="utf-8"))
stack = dict(data.get("stack", {}))
bots = list(data.get("bots", []))
repo_dir = Path(stack.get("repo_dir", config_path.parent))
output_dir = Path(stack.get("output_dir", repo_dir / "generated" / "bot-stack"))
namespace = str(stack.get("namespace", "com.example"))

for bot in bots:
    bot_id = str(bot["id"])
    label = str(bot.get("service_label", f"{namespace}.telegram-{bot_id}"))
    display = str(bot.get("display_name", bot_id))
    scene = str(bot.get("scene", "unknown"))
    role = str(bot.get("role", "unknown"))
    logfile = output_dir / "logs" / f"{bot_id}.stdout.log"
    print(f"{bot_id}|{display}|{scene}|{role}|{label}|{logfile}")
PY
}

print_bot_status() {
  local bot_id="$1"
  local name="$2"
  local scene="$3"
  local role="$4"
  local label="$5"
  local logfile="$6"
  local state pid last_exit age state_icon

  state="$(launch_field "$label" "state")"
  pid="$(launch_field "$label" "pid")"
  last_exit="$(launch_field "$label" "last exit code")"
  [ -n "$state" ] || state="missing"
  [ -n "$pid" ] || pid="-"
  [ -n "$last_exit" ] || last_exit="-"
  age="$(format_age "$(age_seconds_of "$logfile")")"

  if [ "$state" = "running" ]; then
    state_icon="$(status_icon ok)"
  elif [ "$state" = "spawn scheduled" ] || [ "$state" = "waiting" ]; then
    state_icon="$(status_icon warn)"
  else
    state_icon="$(status_icon fail)"
  fi

  printf "[%s] %-18s scene=%-7s role=%-9s state=%-14s pid=%-6s last_exit=%-8s log_age=%s\n" \
    "$state_icon" "$name" "$scene" "$role" "$state" "$pid" "$last_exit" "$age"
}

check_file_freshness() {
  local name="$1"
  local path="$2"
  local freshness_seconds="$3"
  local age_seconds age state_icon detail

  if [ ! -e "$path" ]; then
    printf "[%s] %-18s 未配置或产物不存在 | path=%s\n" "$(status_icon info)" "$name" "$path"
    return
  fi

  age_seconds="$(age_seconds_of "$path")"
  age="$(format_age "$age_seconds")"
  if [ "$age_seconds" -ge 0 ] && [ "$age_seconds" -le "$freshness_seconds" ]; then
    state_icon="$(status_icon ok)"
    detail="最新产物正常"
  else
    state_icon="$(status_icon warn)"
    detail="最新产物偏旧"
  fi
  printf "[%s] %-18s output_age=%-8s updated_at=%s | %s\n" \
    "$state_icon" "$name" "$age" "$(timestamp_of "$path")" "$detail"
}

check_telegram_api() {
  local resolved proxy_host proxy_port
  resolved="$("$PYTHON_BIN" - <<'PY'
import socket
try:
    print(socket.gethostbyname("api.telegram.org"))
except Exception as e:
    print(f"ERROR:{type(e).__name__}:{e}")
PY
)"

  proxy_host="$(scutil --proxy | awk '/HTTPSProxy/ {print $3; exit}')"
  proxy_port="$(scutil --proxy | awk '/HTTPSPort/ {print $3; exit}')"

  if curl -I --max-time 10 https://api.telegram.org >/dev/null 2>&1; then
    printf "[%s] Telegram API 可达 | resolved=%s\n" "$(status_icon ok)" "$resolved"
  else
    printf "[%s] Telegram API 不可达 | resolved=%s\n" "$(status_icon fail)" "$resolved"
  fi

  if [ -n "${proxy_host:-}" ] && [ -n "${proxy_port:-}" ]; then
    if lsof -iTCP:"$proxy_port" -sTCP:LISTEN >/dev/null 2>&1; then
      printf "[%s] 系统代理正常监听 | %s:%s\n" "$(status_icon ok)" "$proxy_host" "$proxy_port"
    else
      printf "[%s] 系统代理已配置但端口未监听 | %s:%s\n" "$(status_icon warn)" "$proxy_host" "$proxy_port"
    fi
  else
    printf "[%s] 系统代理未启用\n" "$(status_icon ok)"
  fi
}

print_runtime_status() {
  local command_name="$1"
  local display_name="$2"
  local version

  if command -v "$command_name" >/dev/null 2>&1; then
    version="$("$command_name" --version 2>/dev/null | head -n 1 || true)"
    printf "[%s] %-18s installed | %s\n" "$(status_icon ok)" "$display_name" "${version:--}"
  else
    printf "[%s] %-18s missing\n" "$(status_icon fail)" "$display_name"
  fi
}

print_env_status() {
  local key="$1"
  if [ -n "${!key:-}" ]; then
    printf "[%s] %-18s configured\n" "$(status_icon ok)" "$key"
  else
    printf "[%s] %-18s empty\n" "$(status_icon warn)" "$key"
  fi
}

if [ ! -f "$CONFIG_PATH" ]; then
  echo "未找到配置文件：$CONFIG_PATH" >&2
  echo "请先执行 bash ./configure.sh 生成 bot_stack.bootstrap.toml" >&2
  exit 1
fi

echo "== Telegram / Proxy =="
check_telegram_api

echo
echo "== AI Runtimes =="
print_runtime_status "openclaw" "OpenClaw"
print_runtime_status "gemini" "Gemini CLI"
print_runtime_status "codex" "Codex CLI"
print_runtime_status "claude" "Claude Code"
print_env_status "OPENAI_API_KEY"
print_env_status "ANTHROPIC_API_KEY"
if [ -n "${GEMINI_API_KEY:-}" ] || [ -n "${GOOGLE_API_KEY:-}" ]; then
  printf "[%s] %-18s configured\n" "$(status_icon ok)" "Gemini auth"
else
  printf "[%s] %-18s empty\n" "$(status_icon warn)" "Gemini auth"
fi

echo
echo "== Bot Services =="
while IFS='|' read -r bot_id display scene role label logfile; do
  [ -n "$bot_id" ] || continue
  print_bot_status "$bot_id" "$display" "$scene" "$role" "$label" "$logfile"
done < <(load_bot_rows)

echo
echo "== Optional Runtime Outputs =="
check_file_freshness "Binance-Monitor" "$MONITOR_REPORT_PATH" 600
check_file_freshness "Daily-Crypto-Report" "$DAILY_REPORT_PATH" 93600
