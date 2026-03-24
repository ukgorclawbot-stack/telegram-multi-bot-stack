# Contributing

Thanks for contributing to Telegram Multi-Bot Stack.

## Before You Open a Pull Request

Please keep changes small and focused.

Recommended order:

1. Open an issue first if the change is large or changes architecture
2. Create a small branch for one topic only
3. Run the fastest local checks before submitting
4. Explain what changed and why

## Good First Contributions

These are especially welcome:

- documentation improvements
- install flow fixes
- CI fixes
- configuration generator improvements
- launchd template fixes
- health check improvements

## Local Checks

Run these before opening a PR:

```bash
python3 -m py_compile \
  bootstrap_bot_stack.py \
  configure_stack.py \
  reverse_export_bot_stack.py \
  make_migration_ready_stack.py \
  bot.py \
  group_bot.py \
  xhs_adapter.py \
  memory_store.py \
  routing.py \
  runners.py \
  task_registry.py

bash -n install.sh
bash -n configure.sh
bash -n apply_stack.sh
bash -n health_check.sh
bash -n scripts/shared-memory-write.sh
zsh -n bootstrap_bot_stack.sh
zsh -n run_role_bot.sh
zsh -n run_group_bot.sh
```

If your change affects generation logic, also run:

```bash
python3 configure_stack.py
python3 bootstrap_bot_stack.py --config bot_stack.bootstrap.toml
python3 reverse_export_bot_stack.py
python3 make_migration_ready_stack.py
```

## What Not to Commit

Do not commit:

- real Telegram bot tokens
- `.bot_tokens.env`
- local `.env` files with secrets
- generated runtime logs
- sqlite runtime files
- personal machine-specific secret values

The repository already ignores most runtime files. Please double-check anyway.

## Pull Request Checklist

- The change is focused and reviewable
- README or INSTALL docs were updated if behavior changed
- No secrets were added
- Fast local checks passed
- The PR description explains the user-facing impact

## Style Guidance

- Prefer small diffs over large refactors
- Keep behavior consistent with the current stack layout
- Do not introduce unnecessary dependencies
- Prefer explicit errors and simple scripts

## Security Reports

If you want to report a security issue, do not open a public issue first.

Please follow the process in [SECURITY.md](./SECURITY.md).
