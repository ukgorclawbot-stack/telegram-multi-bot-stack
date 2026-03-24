# FAQ

## 1. Do I need exactly 6 bots?

No.

The repository ships with a recommended 6-bot layout, but the stack generator supports custom bot counts and custom combinations of roles.

## 2. Which file should I edit first?

For most users, start with:

- `bash ./install.sh`
- `bash ./configure.sh`

You usually do not need to hand-edit `bot_stack.bootstrap.toml` on day one.

## 3. Where do I put Telegram bot tokens?

Put them in:

- `.bot_tokens.env`

Do not commit this file.

## 4. Why are there both group bots and private bots?

Because group-chat responsibilities and private-chat responsibilities are usually different.

Typical split:

- group bots: routing, reporting, teamwork
- private bots: deeper execution and higher-permission personal workflows

## 5. What does the health check script do?

`bash ./health_check.sh` checks:

- Telegram API reachability
- local proxy state
- bot service status
- monitor output freshness
- report output freshness

## 6. What does reverse export do?

It converts a live local stack into a sanitized TOML file so you can:

- document your current running setup
- rebuild it later
- create migration-ready templates

## 7. What does the migration-ready template do?

It rewrites a reverse-exported stack into a new-machine template with placeholder paths such as `/Users/your_user/...`.

This is useful when you want to:

- move to a new Mac
- share a sanitized deployment template
- bootstrap a second machine faster

## 8. Does CI start my real bots?

No.

CI only runs lightweight validation:

- Python syntax checks
- shell syntax checks
- local config generation
- stack generation
- reverse export
- migration template generation

It does not start your real local Telegram services.

## 9. What files should never be committed?

Never commit:

- `.bot_tokens.env`
- real secrets
- runtime sqlite files
- generated logs
- private local runtime data

## 10. Where should I report a vulnerability?

Follow:

- [SECURITY.md](../SECURITY.md)

Do not post sensitive exploit details in a public issue first.
