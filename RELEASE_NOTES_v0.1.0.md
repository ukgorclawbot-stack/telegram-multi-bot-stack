# Telegram Multi-Bot Stack v0.1.0

First public release of the stack.

## Highlights

- One-command install, configure, and apply flow
- Supports separated group bots and private bots
- Supports flexible bot counts through a TOML stack file
- Includes reverse export from a live stack
- Includes migration-ready template generation for new machines
- Includes health check tooling for Telegram, bot services, monitor output, and report output

## Quick Start

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
bash ./apply_stack.sh
```

## Recommended Docs

- Chinese quick guide: `README.md`
- English quick guide: `README.en.md`
- Beginner install guide: `INSTALL.md`

## Included Commands

```bash
bash ./install.sh
bash ./configure.sh
bash ./apply_stack.sh
bash ./health_check.sh
bash ./bootstrap_bot_stack.sh generate
bash ./bootstrap_bot_stack.sh export-live
bash ./bootstrap_bot_stack.sh migration-template
```

## Notes

- Secrets are not committed. Fill bot tokens through `.bot_tokens.env`.
- Generated runtime files are ignored by Git.
- This release is designed for macOS and launchd-based local deployment.
