#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        from pip._vendor import tomli as tomllib  # type: ignore[no-redef]


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = SCRIPT_DIR / "bot_stack.reverse_exported.toml"
DEFAULT_OUTPUT = SCRIPT_DIR / "bot_stack.migration_ready.toml"
PLACEHOLDER_HOME = "/Users/your_user"
PLACEHOLDER_REPO = f"{PLACEHOLDER_HOME}/telegram-bot-stack-open"
PLACEHOLDER_SHARED = f"{PLACEHOLDER_REPO}/shared-memory"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把反向导出的当前 bot stack 配置加工成新机器迁移模板。")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="反向导出的 TOML 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="迁移版 TOML 输出路径")
    parser.add_argument("--target-home", default=PLACEHOLDER_HOME, help="新机器 home 目录前缀")
    parser.add_argument("--target-repo", help="新机器上的 bot 仓库目录；默认基于 target-home 生成")
    parser.add_argument("--target-shared", help="新机器上的共享记忆目录；默认用 repo 下的 shared-memory")
    return parser.parse_args()


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def shell_quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def replace_prefix(text: str, source_home: str, target_home: str) -> str:
    if text.startswith(source_home):
        return target_home + text[len(source_home):]
    return text


def transform_value(value: Any, source_home: str, target_home: str, target_repo: str, target_shared: str) -> Any:
    if not isinstance(value, str):
        return value
    updated = replace_prefix(value, source_home, target_home)
    for legacy_name in (
        "telegram" + "-openai-bot" + "-tooling",
        "telegram-openai-bot",
        "telegram-bot-stack-open",
    ):
        legacy_root = f"{target_home}/{legacy_name}"
        if updated == legacy_root or updated.startswith(legacy_root + "/"):
            updated = target_repo + updated[len(legacy_root):]
    updated = re.sub(
        rf"^{re.escape(target_home)}/[^/]+/memory(?=/|$)",
        target_shared,
        updated,
    )
    return updated


def render_table(name: str, data: dict[str, Any]) -> list[str]:
    lines = [f"[{name}]"]
    for key in sorted(data.keys()):
        lines.append(f"{key} = {shell_quote(data[key])}")
    lines.append("")
    return lines


def render_bot(bot: dict[str, Any]) -> list[str]:
    lines = ["[[bots]]"]
    ordered_keys = [
        "id",
        "scene",
        "role",
        "mode",
        "display_name",
        "token_env",
        "workdir",
        "private_direct_workdir",
        "allow_group_chat",
        "allow_dm_tasks",
        "enable_direct_private_tasks",
        "private_task_mode",
        "allow_long_term_memory_write",
        "persisted_history_limit",
        "max_context_messages",
        "poll_interval_secs",
        "service_label",
    ]
    for key in ordered_keys:
        if key in bot:
            lines.append(f"{key} = {shell_quote(bot[key])}")
    lines.append("")
    extra_env = bot.get("extra_env", {})
    if extra_env:
        lines.append("[bots.extra_env]")
        for key in sorted(extra_env.keys()):
            lines.append(f"{key} = {shell_quote(extra_env[key])}")
        lines.append("")
    return lines


def build_migration_ready(data: dict[str, Any], target_home: str, target_repo: str, target_shared: str) -> str:
    stack = dict(data.get("stack", {}))
    defaults = dict(data.get("defaults", {}))
    bots = [dict(bot) for bot in data.get("bots", [])]
    source_home = str(
        Path(
            str(
                defaults.get("home_dir")
                or Path(str(stack.get("repo_dir", PLACEHOLDER_REPO))).expanduser().parent
            )
        ).expanduser()
    )

    for key, value in list(stack.items()):
        stack[key] = transform_value(value, source_home, target_home, target_repo, target_shared)
    for key, value in list(defaults.items()):
        defaults[key] = transform_value(value, source_home, target_home, target_repo, target_shared)
    for bot in bots:
        for key, value in list(bot.items()):
            if key == "extra_env":
                continue
            bot[key] = transform_value(value, source_home, target_home, target_repo, target_shared)
        extra_env = dict(bot.get("extra_env", {}))
        for key, value in list(extra_env.items()):
            extra_env[key] = transform_value(value, source_home, target_home, target_repo, target_shared)
        bot["extra_env"] = extra_env

    stack["repo_dir"] = target_repo
    stack["output_dir"] = f"{target_repo}/generated/bot-stack"
    stack["launch_agents_dir"] = f"{target_home}/Library/LaunchAgents"
    stack["runner_script"] = f"{target_repo}/run_role_bot.sh"
    defaults["group_task_db_path"] = f"{target_repo}/group-tasks.sqlite3"
    defaults["memory_db_path"] = f"{target_repo}/bot-memory.sqlite3"
    defaults["shared_memory_dir"] = target_shared
    defaults["long_term_memory_script_path"] = f"{target_repo}/scripts/shared-memory-write.sh"
    defaults["workspace_dir"] = f"{target_home}/.openclaw/workspace"
    defaults["home_dir"] = target_home

    lines = [
        "# 这是适合新机器直接落地的迁移版 bot stack 模板。",
        "# 默认使用仓库自带 shared-memory，不依赖额外配置仓库。",
        "# 真实 token 仍然不写入文件，请继续通过 token_env 对应的环境变量注入。",
        "",
    ]
    lines.extend(render_table("stack", stack))
    lines.extend(render_table("defaults", defaults))
    for bot in bots:
        lines.extend(render_bot(bot))
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    target_home = args.target_home.rstrip("/")
    target_repo = (args.target_repo or f"{target_home}/telegram-bot-stack-open").rstrip("/")
    target_shared = (args.target_shared or f"{target_repo}/shared-memory").rstrip("/")
    data = load_toml(source)
    output.write_text(build_migration_ready(data, target_home, target_repo, target_shared), encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
