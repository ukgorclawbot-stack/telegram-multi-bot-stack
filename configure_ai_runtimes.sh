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
echo "这一步同时支持两种方式："
echo "1) API key"
echo "2) auth / login"
echo
echo "如果你想用 API key，就在打开的文件里按需填写："
echo "- OPENAI_API_KEY"
echo "- ANTHROPIC_API_KEY"
echo "- GEMINI_API_KEY"
echo "- GOOGLE_API_KEY"
echo
echo "如果你想用 auth / login，也可以把这个文件留空，然后手动执行："
echo "- openclaw configure  或  openclaw onboard"
echo "- gemini"
echo "- codex login"
echo "- claude auth login"
echo

if command -v open >/dev/null 2>&1; then
  open -a TextEdit "$ENV_FILE"
else
  echo "请手动编辑：$ENV_FILE"
fi

echo
echo "配置完成后建议执行："
echo "bash ./health_check.sh"
