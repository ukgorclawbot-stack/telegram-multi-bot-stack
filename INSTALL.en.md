# Installation Guide

This guide is for first-time users who want a clean, step-by-step setup path.

## 1. What You Need

Before you start, prepare:

1. A macOS computer
2. `Python 3` installed
3. `Git` installed
4. `Telegram` installed
5. Telegram bot tokens you plan to use

Check your environment first:

```bash
python3 --version
git --version
```

If either command fails, install the missing software first.

## 2. How to Create Telegram Bots

In Telegram, search for `@BotFather` and do the following:

1. Send `/newbot`
2. Choose a bot name
3. Choose a bot username ending with `bot`
4. Save the returned token

If you use the recommended 6-bot layout, prepare 6 tokens.

## 3. Clone the Project

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
```

## 4. Install Everything

```bash
bash ./install.sh
```

This script will automatically:

- create `.venv`
- install Python dependencies
- initialize local directories
- create configuration templates

## 5. Run the Configuration Wizard

```bash
bash ./configure.sh
```

The wizard will ask for:

- your home directory
- which Telegram user ID is allowed to use the bots
- whether to use the recommended 6-bot layout

If you do not know your Telegram `user_id`, use any temporary bot or an existing bot command such as `/whoami`.

## 6. Fill in Bot Tokens

If you did not enter tokens during the wizard, edit the token file manually:

```bash
open .bot_tokens.env
```

For the recommended 6-bot layout, these are the main keys:

```bash
TG_OPENCLAW_GROUP_TOKEN=
TG_GEMINI_GROUP_TOKEN=
TG_CODEX_GROUP_TOKEN=
TG_OPENCLAW_PRIVATE_TOKEN=
TG_GEMINI_PRIVATE_TOKEN=
TG_CODEX_PRIVATE_TOKEN=
```

## 7. Start the Stack

```bash
bash ./apply_stack.sh
```

This step will:

- load `.bot_tokens.env`
- generate final env files
- generate final launchd plist files
- load and start the services automatically

## 8. Preview Only

If you want to preview generated files without starting services:

```bash
bash ./bootstrap_bot_stack.sh generate
```

Generated files will appear in:

- `generated/bot-stack/env/`
- `generated/bot-stack/launchd/`
- `generated/bot-stack/STACK_SUMMARY.md`

## 9. Verify the Installation

Run:

```bash
bash ./health_check.sh
```

If setup is successful, you will see:

- Telegram API status
- bot service status
- monitor and report status

## 10. Best Order for Beginners

Use this exact sequence:

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
open .bot_tokens.env
bash ./apply_stack.sh
bash ./health_check.sh
```

## 11. Common Problems

### 11.1 Python Not Found

Install Python 3 first, then retry:

```bash
python3 --version
```

### 11.2 Token Missing

That means `.bot_tokens.env` is incomplete.

### 11.3 Bots Are Not Responding

Check whether launchd services are loaded:

```bash
launchctl list | grep telegram
```

Then inspect logs:

```bash
tail -n 100 generated/bot-stack/logs/*.log
```
