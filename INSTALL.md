# 安装说明 / Installation Guide

这份说明是给第一次接触这套框架的人准备的。  
This guide is written for first-time users.

---

## 中文

### 1. 你需要准备什么

在开始之前，请先准备：

1. 一台 macOS 电脑
2. 已安装 `Python 3`
3. 已安装 `Git`
4. 已安装 `Telegram`
5. 你准备创建的 Telegram bot token

如果你不确定电脑有没有装好 `Python 3` 和 `Git`，先在终端执行：

```bash
python3 --version
git --version
```

如果其中任意一条报错，先安装对应软件，再继续下面步骤。

### 2. 如何创建 Telegram bot

在 Telegram 里搜索 `@BotFather`，然后按下面步骤做：

1. 发送 `/newbot`
2. 给 bot 起名字
3. 给 bot 设置用户名（必须以 `bot` 结尾）
4. 保存返回的 token

如果你要用推荐的 6 bot 结构，就需要准备 6 个 token。

### 3. 下载项目

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
```

### 4. 一键安装依赖

```bash
bash ./install.sh
```

这个脚本会自动：

- 创建 `.venv`
- 安装 Python 依赖
- 安装 `OpenClaw / Gemini CLI / Codex / Claude Code`
- 初始化本地目录
- 准备配置模板

### 5. 配置 4 个 AI CLI

```bash
bash ./configure_ai_runtimes.sh
```

这一步会：

- 检查 4 个 AI CLI 是否已经安装
- 自动创建 `.ai_runtimes.env`
- 引导你填写 API key
- 告诉你如果更喜欢交互式登录，应该执行哪些 CLI

如果你完全是第一次装，建议在配置 bot stack 之前先完成这一步。

更详细的说明见：

- [docs/ai-runtimes.md](./docs/ai-runtimes.md)

### 6. 一键生成配置

```bash
bash ./configure.sh
```

配置向导会问你：

- 你的 home 目录
- 哪个 Telegram user_id 可以使用这些 bot
- 是否使用推荐的 6 bot 结构

如果你不知道自己的 `user_id`，可以先用任意临时 bot 或现有 bot 的 `/whoami` 来查。

### 7. 写入 token

如果你在配置向导里没有直接输入 token，就手动编辑：

```bash
open .bot_tokens.env
```

把每个 bot 的 token 填进去。首次安装后这个文件会自动生成。

如果你只想先搭最推荐的 6 bot 结构，通常只需要填这 6 行：

```bash
TG_OPENCLAW_GROUP_TOKEN=
TG_GEMINI_GROUP_TOKEN=
TG_CODEX_GROUP_TOKEN=
TG_OPENCLAW_PRIVATE_TOKEN=
TG_GEMINI_PRIVATE_TOKEN=
TG_CODEX_PRIVATE_TOKEN=
```

### 8. 启动

```bash
bash ./apply_stack.sh
```

这一步会：

- 读取 `.bot_tokens.env`
- 生成正式 env
- 生成正式 launchd plist
- 自动加载并启动服务

### 9. 只想先试运行

如果你还不想真正启动，只想先看会生成什么：

```bash
bash ./bootstrap_bot_stack.sh generate
```

生成后的文件在：

- `generated/bot-stack/env/`
- `generated/bot-stack/launchd/`
- `generated/bot-stack/STACK_SUMMARY.md`

### 10. 安装完成后怎么检查是否成功

直接执行：

```bash
bash ./health_check.sh
```

如果安装成功，你会看到：

- Telegram API 检查结果
- bot 服务状态
- 监控和晨报状态

### 11. 推荐给零基础用户的完整顺序

按这个顺序照做最稳：

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure_ai_runtimes.sh
bash ./configure.sh
open .bot_tokens.env
bash ./apply_stack.sh
bash ./health_check.sh
```

### 12. 常见问题

#### 12.1 提示没找到 Python

先安装 Python 3，再重试：

```bash
python3 --version
```

#### 12.2 提示 token 没提供

说明 `.bot_tokens.env` 还没写完整。

#### 12.3 机器人没响应

先检查 launchd 是否在线：

```bash
launchctl list | grep telegram
```

再看日志：

```bash
tail -n 100 generated/bot-stack/logs/*.log
```

---

## English

### 1. What You Need

Before you start, prepare:

1. A macOS computer
2. `Python 3` installed
3. `Git` installed
4. `Telegram` installed
5. Telegram bot tokens you plan to use

If you are not sure whether `Python 3` and `Git` are installed, run:

```bash
python3 --version
git --version
```

If either command fails, install the missing software first.

### 2. How to Create Telegram Bots

In Telegram, search for `@BotFather` and follow these steps:

1. Send `/newbot`
2. Pick a bot name
3. Pick a bot username ending with `bot`
4. Save the returned token

If you use the recommended 6-bot layout, prepare 6 tokens.

### 3. Clone the Project

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
```

### 4. Install Dependencies

```bash
bash ./install.sh
```

This script will automatically:

- create `.venv`
- install Python dependencies
- initialize local directories
- prepare configuration templates

### 5. Configure the Stack

```bash
bash ./configure.sh
```

The wizard will ask for:

- your home directory
- which Telegram user ID is allowed to use the bots
- whether to use the recommended 6-bot layout

If you do not know your Telegram `user_id`, use any temporary bot or an existing bot command such as `/whoami`.

### 6. Fill in Bot Tokens

If you did not enter tokens during the wizard, edit the token file manually:

```bash
open .bot_tokens.env
```

Fill in one token per bot. This file is created automatically on first install.

For the recommended 6-bot layout, these are the main fields:

```bash
TG_OPENCLAW_GROUP_TOKEN=
TG_GEMINI_GROUP_TOKEN=
TG_CODEX_GROUP_TOKEN=
TG_OPENCLAW_PRIVATE_TOKEN=
TG_GEMINI_PRIVATE_TOKEN=
TG_CODEX_PRIVATE_TOKEN=
```

### 7. Start the Stack

```bash
bash ./apply_stack.sh
```

This step will:

- load `.bot_tokens.env`
- generate final env files
- generate final launchd plist files
- load and start the services automatically

### 8. Preview Only

If you do not want to start services yet and only want to preview generated files:

```bash
bash ./bootstrap_bot_stack.sh generate
```

Generated files will appear in:

- `generated/bot-stack/env/`
- `generated/bot-stack/launchd/`
- `generated/bot-stack/STACK_SUMMARY.md`

### 9. Verify the Installation

Run:

```bash
bash ./health_check.sh
```

If setup is successful, you will see:

- Telegram API status
- bot service status
- monitor and report status

### 10. Best Order for Beginners

Follow these steps in this exact order:

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
open .bot_tokens.env
bash ./apply_stack.sh
bash ./health_check.sh
```

### 11. Common Problems

#### 11.1 Python Not Found

Install Python 3 first, then retry:

```bash
python3 --version
```

#### 11.2 Token Missing

That means `.bot_tokens.env` is incomplete.

#### 11.3 Bots Are Not Responding

Check whether launchd services are loaded:

```bash
launchctl list | grep telegram
```

Then inspect logs:

```bash
tail -n 100 generated/bot-stack/logs/*.log
```
