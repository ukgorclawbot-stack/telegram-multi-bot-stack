# v0.1.8 - AI runtime installation and setup

This release improves first-time installation for beginners.

## Added

- one-command installation for:
  - OpenClaw
  - Gemini CLI
  - Codex CLI
  - Claude Code
- `install_ai_runtimes.sh`
- `configure_ai_runtimes.sh`
- `.ai_runtimes.env.example`
- `docs/ai-runtimes.md`

## Improved

- `install.sh` now installs AI runtimes as part of the default setup flow
- `run_role_bot.sh` now loads `.ai_runtimes.env`
- `health_check.sh` now checks AI runtime availability and auth env presence
- `README.md`, `README.en.md`, `INSTALL.md`, and `INSTALL.en.md` now include the AI runtime setup flow

## Goal

Make the repository closer to a real beginner-friendly one-click installer, even for users who do not already have OpenClaw, Gemini CLI, Codex CLI, or Claude Code installed.
