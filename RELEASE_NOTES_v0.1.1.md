# Telegram Multi-Bot Stack v0.1.1

This release improves public usability and onboarding.

## What's New

- Added GitHub Actions CI for syntax and generation checks
- Expanded `INSTALL.md` into a bilingual Chinese + English install guide
- Kept the beginner-friendly one-command flow unchanged

## Included Checks

- Python syntax validation
- Shell syntax validation
- Local config generation through the interactive wizard path
- Stack generation from generated config
- Reverse export validation
- Migration template validation

## Recommended Entry Points

- Chinese overview: `README.md`
- English overview: `README.en.md`
- Bilingual install guide: `INSTALL.md`

## Quick Start

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
bash ./apply_stack.sh
```
