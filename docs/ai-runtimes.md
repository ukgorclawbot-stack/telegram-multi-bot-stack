# AI Runtimes

This project can install and prepare the four AI CLIs used by the stack:

- OpenClaw
- Gemini CLI
- Codex CLI
- Claude Code

这份文档解释公开仓库如何把 4 个 AI CLI 一起装好，并把认证配置纳入一套小白也能照做的流程。

## 1. Why this layer exists / 为什么要补这一层

The bot stack itself is only the coordination layer.

If a beginner does not already have these AI CLIs installed, the bots may start but still fail when they try to call:

- `openclaw`
- `gemini`
- `codex`
- `claude`

这个项目本身只是 bot 协作框架。  
如果用户电脑里根本没有这 4 个 CLI，bot 服务即使拉起来，也会在真正执行时失败。

## 2. One-click flow / 一键流程

Recommended order:

```bash
bash ./install.sh
bash ./configure_ai_runtimes.sh
bash ./configure.sh
bash ./apply_stack.sh
bash ./health_check.sh
```

推荐顺序就是上面这 5 步。

## 3. What `install.sh` now does / install.sh 现在多做了什么

`install.sh` now also installs the AI runtime layer:

- ensure `node` and `npm` exist
- install `OpenClaw`
- install `Gemini CLI`
- install `Codex CLI`
- install `Claude Code`
- create `.ai_runtimes.env` if it does not exist

也就是说，现在 `install.sh` 不只是装 Python 依赖，还会把 4 个 AI CLI 一起装上。

## 4. What `configure_ai_runtimes.sh` does / configure_ai_runtimes.sh 做什么

This script helps users prepare authentication.

It does not print secrets.

It opens `.ai_runtimes.env` and lets users fill:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`

这个脚本的作用不是“替你登录账号”，而是：

- 统一生成认证配置文件
- 让新手知道该填哪些 key
- 给出交互式登录的备用入口

## 5. Two supported auth styles / 两种支持的认证方式

### 5.1 Environment variable style

Best for:

- servers
- unattended launchd jobs
- reproducible setup

适合：

- 新机器部署
- 后台服务
- 稳定复用

### 5.2 Interactive login style

Best for:

- local testing
- personal laptops
- quick first-time setup

适合：

- 本机先试
- 个人电脑
- 第一次快速上手

## 6. Important runtime note / 一个重要细节

This project makes the bot launch script load `.ai_runtimes.env` automatically.

这意味着：

- 你不用每次手动 `export`
- launchd 拉起来的 bot 也能继承这些认证环境

## 7. Health checks / 健康检查

After installation, run:

```bash
bash ./health_check.sh
```

It now reports whether these four AI CLIs are available.

现在健康检查会额外告诉你：

- OpenClaw 是否安装
- Gemini CLI 是否安装
- Codex CLI 是否安装
- Claude Code 是否安装

## 8. Recommended rule for beginners / 给小白的推荐规则

If you are a beginner:

1. let `install.sh` install the tools
2. fill `.ai_runtimes.env`
3. only then continue to bot token configuration

如果你是第一次装：

1. 先让 `install.sh` 装 4 个 AI CLI
2. 再填 `.ai_runtimes.env`
3. 最后再去填 bot token 和启动服务
