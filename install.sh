#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> 检查 Python 3"
command -v python3 >/dev/null 2>&1 || { echo "未找到 python3，请先安装 Python 3"; exit 1; }

echo "==> 创建虚拟环境"
if [ ! -d "$REPO_DIR/.venv" ]; then
  python3 -m venv "$REPO_DIR/.venv"
fi

echo "==> 安装依赖"
"$REPO_DIR/.venv/bin/pip" install -U pip >/dev/null
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

echo "==> 准备脚本权限"
chmod +x "$REPO_DIR/run_role_bot.sh" \
         "$REPO_DIR/run_group_bot.sh" \
         "$REPO_DIR/install.sh" \
         "$REPO_DIR/configure.sh" \
         "$REPO_DIR/apply_stack.sh" \
         "$REPO_DIR/bootstrap_bot_stack.sh" \
         "$REPO_DIR/health_check.sh" \
         "$REPO_DIR/scripts/shared-memory-write.sh"

echo "==> 初始化本地目录"
mkdir -p "$REPO_DIR/shared-memory" "$REPO_DIR/generated"
touch "$REPO_DIR/shared-memory/MEMORY.md"

if [ ! -f "$REPO_DIR/bot_stack.bootstrap.toml" ]; then
  cp "$REPO_DIR/bot_stack.bootstrap.toml.example" "$REPO_DIR/bot_stack.bootstrap.toml"
  echo "==> 已创建 bot_stack.bootstrap.toml"
fi

if [ ! -f "$REPO_DIR/.bot_tokens.env.example" ]; then
  cat > "$REPO_DIR/.bot_tokens.env.example" <<'EOF'
export TG_OPENCLAW_GROUP_TOKEN=""
export TG_GEMINI_GROUP_TOKEN=""
export TG_CODEX_GROUP_TOKEN=""
export TG_OPENCLAW_PRIVATE_TOKEN=""
export TG_GEMINI_PRIVATE_TOKEN=""
export TG_CODEX_PRIVATE_TOKEN=""
EOF
fi

if [ ! -f "$REPO_DIR/.bot_tokens.env" ]; then
  cp "$REPO_DIR/.bot_tokens.env.example" "$REPO_DIR/.bot_tokens.env"
  echo "==> 已创建 .bot_tokens.env"
fi

echo
echo "安装完成。下一步："
echo "1) bash ./configure.sh"
echo "2) 把 bot token 写入 .bot_tokens.env"
echo "3) bash ./apply_stack.sh"
