#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECK_ONLY="${1:-}"

ensure_brew() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi

  echo "==> 未检测到 Homebrew，开始安装"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

ensure_node() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return
  fi

  ensure_brew
  echo "==> 安装 Node.js"
  brew install node
}

append_path_snippet() {
  local file="$1"
  local marker_begin="# telegram-multi-bot-stack npm prefix begin"

  touch "$file"
  if grep -Fq "$marker_begin" "$file"; then
    return
  fi

  cat >>"$file" <<'EOF'
# telegram-multi-bot-stack npm prefix begin
export PATH="$HOME/.npm-global/bin:$PATH"
# telegram-multi-bot-stack npm prefix end
EOF
}

ensure_writable_npm_prefix() {
  local prefix
  prefix="$(npm prefix -g 2>/dev/null || true)"

  if [ -n "$prefix" ] && [ -w "$prefix" ]; then
    return
  fi

  echo "==> 当前 npm 全局目录不可写，切换到用户目录前缀"
  mkdir -p "$HOME/.npm-global"
  npm config set prefix "$HOME/.npm-global"
  export PATH="$HOME/.npm-global/bin:$PATH"
  append_path_snippet "$HOME/.zprofile"
  append_path_snippet "$HOME/.zshrc"
}

print_version() {
  local command_name="$1"
  local label="$2"

  if command -v "$command_name" >/dev/null 2>&1; then
    local version
    version="$("$command_name" --version 2>/dev/null | head -n 1 || true)"
    if [ -n "$version" ]; then
      echo "[OK] $label 已安装 | $version"
    else
      echo "[OK] $label 已安装"
    fi
  else
    echo "[FAIL] $label 未安装"
  fi
}

install_package() {
  local package_name="$1"
  local bin_name="$2"
  local label="$3"

  if command -v "$bin_name" >/dev/null 2>&1; then
    echo "==> $label 已存在，跳过安装"
    return
  fi

  echo "==> 安装 $label"
  npm install -g "$package_name"
}

ensure_runtime_env_file() {
  if [ ! -f "$REPO_DIR/.ai_runtimes.env" ]; then
    cp "$REPO_DIR/.ai_runtimes.env.example" "$REPO_DIR/.ai_runtimes.env"
    echo "==> 已创建 .ai_runtimes.env"
  fi
}

if [ "$CHECK_ONLY" = "--check" ]; then
  echo "==> 检查 AI 运行时"
  print_version openclaw "OpenClaw"
  print_version gemini "Gemini CLI"
  print_version codex "Codex CLI"
  print_version claude "Claude Code"
  exit 0
fi

echo "==> 准备 AI 运行时安装环境"
ensure_node
ensure_writable_npm_prefix

install_package "openclaw" "openclaw" "OpenClaw"
install_package "@google/gemini-cli" "gemini" "Gemini CLI"
install_package "@openai/codex" "codex" "Codex CLI"
install_package "@anthropic-ai/claude-code" "claude" "Claude Code"

ensure_runtime_env_file

echo
echo "==> AI 运行时安装结果"
print_version openclaw "OpenClaw"
print_version gemini "Gemini CLI"
print_version codex "Codex CLI"
print_version claude "Claude Code"

echo
echo "下一步："
echo "1) bash ./configure_ai_runtimes.sh"
echo "2) bash ./configure.sh"
echo "3) bash ./apply_stack.sh"
