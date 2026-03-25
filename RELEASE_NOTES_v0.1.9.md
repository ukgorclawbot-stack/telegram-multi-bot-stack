# v0.1.9 - Auth login and API key coexistence

This release fixes an important onboarding issue for beginners.

## Fixed

- the project no longer implies that `Codex`, `Claude Code`, or `Gemini CLI` must use API keys
- runtime setup now explicitly supports both:
  - API key mode
  - auth/login mode

## Improved

- `.ai_runtimes.env.example` now clearly marks API keys as optional
- `configure_ai_runtimes.sh` now tells users how to use:
  - `openclaw configure` or `openclaw onboard`
  - `gemini`
  - `codex login`
  - `claude auth login`
- `health_check.sh` now reports empty API env fields as optional instead of warning-level failure

## Goal

Make the project friendlier to real-world users, where some tools are authenticated by account login and others by API keys.
