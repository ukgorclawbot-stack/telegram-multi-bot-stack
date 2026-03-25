#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/.ai_runtimes.env"

if [ ! -f "$ENV_FILE" ]; then
  cp "$REPO_DIR/.ai_runtimes.env.example" "$ENV_FILE"
  echo "==> 已创建 .ai_runtimes.env"
fi

echo "==> 当前 AI 运行时状态"
bash "$REPO_DIR/install_ai_runtimes.sh" --check || true

echo
echo "==> 准备配置 AI 认证环境"
echo "请在打开的文件里按需填写以下内容："
echo "- OPENAI_API_KEY"
echo "- ANTHROPIC_API_KEY"
echo "- GEMINI_API_KEY"
echo "- GOOGLE_API_KEY"
echo
echo "如果你更喜欢交互式登录，也可以稍后手动执行："
echo "- openclaw"
echo "- gemini"
echo "- codex"
echo "- claude"
echo

if command -v open >/dev/null 2>&1; then
  open -a TextEdit "$ENV_FILE"
else
  echo "请手动编辑：$ENV_FILE"
fi

echo
echo "配置完成后建议执行："
echo "bash ./health_check.sh"
