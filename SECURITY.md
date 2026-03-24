# Security Policy

## Supported Scope

This project is a local multi-bot orchestration stack for Telegram on macOS.

Security-sensitive areas include:

- token handling
- local env generation
- launchd service generation
- local file permissions
- memory and runtime state storage

## Please Do Not Report Publicly First

If you discover a security issue, do not open a public issue with exploit details first.

Instead:

1. Prepare a short description
2. Include reproduction steps if possible
3. State whether secrets, tokens, or local file access are involved
4. Report it privately to the maintainer

## What Counts as a Security Issue

Examples:

- token leakage
- secrets written into generated files or logs
- unsafe default permissions
- arbitrary code execution through generated config
- unsafe path handling that could overwrite unintended files
- unintended cross-bot memory exposure

## What Usually Does Not Count

Examples:

- general install questions
- feature requests
- cosmetic documentation issues
- requests for new integrations

Those should go through normal issues or pull requests.

## Safe Contribution Rules

When contributing:

- never commit real tokens
- never paste `.env` secrets into issues or pull requests
- never include private machine paths that expose sensitive local structure beyond what is necessary
- prefer sanitized examples and placeholders

## Temporary Mitigation Guidance

If you think secrets may have been exposed:

1. rotate the affected Telegram bot tokens immediately
2. remove local generated env files if needed
3. check launchd-generated env files and logs
4. review `.bot_tokens.env`
5. re-run local setup with sanitized values

## Local Security Hygiene

Before publishing changes, double-check:

- `.bot_tokens.env` is not staged
- no runtime sqlite files are staged
- no generated logs are staged
- docs use placeholder paths where appropriate
