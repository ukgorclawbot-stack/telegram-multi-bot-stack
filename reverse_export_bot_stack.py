#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        from pip._vendor import tomli as tomllib  # type: ignore[no-redef]


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_REPO = SCRIPT_DIR
DEFAULT_OUTPUT = SCRIPT_DIR / "bot_stack.reverse_exported.toml"
DEFAULT_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

STACK_KEYS = [
    "repo_dir",
    "output_dir",
    "launch_agents_dir",
    "namespace",
    "runner_script",
    "bot_entrypoint",
    "allowed_user_ids",
]

DEFAULT_KEYS = [
    "group_task_db_path",
    "memory_db_path",
    "shared_memory_dir",
    "memory_timezone",
    "runner_timeout_secs",
    "persisted_history_limit",
    "max_context_messages",
    "enable_shared_memory_log",
    "poll_interval_secs",
    "task_command",
    "long_term_memory_script_path",
    "workspace_dir",
    "home_dir",
]

BOT_KEYS = [
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

ENV_TO_STACK = {
    "BOT_ENTRYPOINT": ("stack", "bot_entrypoint"),
    "ALLOWED_USER_IDS": ("stack", "allowed_user_ids"),
    "GROUP_TASK_DB_PATH": ("defaults", "group_task_db_path"),
    "MEMORY_DB_PATH": ("defaults", "memory_db_path"),
    "SHARED_MEMORY_DIR": ("defaults", "shared_memory_dir"),
    "MEMORY_TIMEZONE": ("defaults", "memory_timezone"),
    "RUNNER_TIMEOUT_SECS": ("defaults", "runner_timeout_secs"),
    "PERSISTED_HISTORY_LIMIT": ("defaults", "persisted_history_limit"),
    "MAX_CONTEXT_MESSAGES": ("defaults", "max_context_messages"),
    "ENABLE_SHARED_MEMORY_LOG": ("defaults", "enable_shared_memory_log"),
    "POLL_INTERVAL_SECS": ("defaults", "poll_interval_secs"),
    "TASK_COMMAND": ("defaults", "task_command"),
    "LONG_TERM_MEMORY_SCRIPT_PATH": ("defaults", "long_term_memory_script_path"),
}

ENV_TO_BOT = {
    "BOT_ROLE": "role",
    "BOT_MODE": "mode",
    "BOT_DISPLAY_NAME": "display_name",
    "ALLOW_GROUP_CHAT": "allow_group_chat",
    "ALLOW_DM_TASKS": "allow_dm_tasks",
    "ENABLE_DIRECT_PRIVATE_TASKS": "enable_direct_private_tasks",
    "PRIVATE_TASK_MODE": "private_task_mode",
    "ALLOW_LONG_TERM_MEMORY_WRITE": "allow_long_term_memory_write",
    "WORKDIR": "workdir",
    "PRIVATE_DIRECT_WORKDIR": "private_direct_workdir",
    "PERSISTED_HISTORY_LIMIT": "persisted_history_limit",
    "MAX_CONTEXT_MESSAGES": "max_context_messages",
    "POLL_INTERVAL_SECS": "poll_interval_secs",
}

IGNORED_ENV_KEYS = {"TELEGRAM_BOT_TOKEN", "GROUP_LOG_FILE"}
TOKEN_ENV_MAP = {
    "group-openclaw": "TG_OPENCLAW_GROUP_TOKEN",
    "group-gemini": "TG_GEMINI_GROUP_TOKEN",
    "group-codex": "TG_CODEX_GROUP_TOKEN",
    "private-openclaw": "TG_OPENCLAW_PRIVATE_TOKEN",
    "private-gemini": "TG_GEMINI_PRIVATE_TOKEN",
    "private-codex": "TG_CODEX_PRIVATE_TOKEN",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从当前仓库正式配置反向导出脱敏 bot stack TOML。")
    parser.add_argument("--source-repo", default=str(DEFAULT_SOURCE_REPO), help="运行中的 bot 仓库路径")
    parser.add_argument("--launch-agents-dir", default=str(DEFAULT_LAUNCH_AGENTS_DIR), help="LaunchAgents 目录")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="导出的 TOML 文件路径")
    return parser.parse_args()


def parse_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        env[key] = value
    return env


def parse_bool(text: str) -> bool:
    return text.lower() == "true"


def normalize_value(text: str) -> Any:
    if text.lower() in {"true", "false"}:
        return parse_bool(text)
    if text.isdigit():
        return int(text)
    return text


def parse_plist(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return plistlib.load(fh)


def shell_quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_table(name: str, data: dict[str, Any]) -> list[str]:
    lines = [f"[{name}]"]
    for key in STACK_KEYS if name == "stack" else DEFAULT_KEYS:
        if key in data and data[key] is not None:
            lines.append(f"{key} = {shell_quote(data[key])}")
    lines.append("")
    return lines


def render_bot_table(bot: dict[str, Any]) -> list[str]:
    lines = ["[[bots]]"]
    for key in BOT_KEYS:
        if key in bot and bot[key] is not None:
            lines.append(f"{key} = {shell_quote(bot[key])}")
    lines.append("")
    extra_env = bot.get("extra_env", {})
    if extra_env:
        lines.append("[bots.extra_env]")
        for key in sorted(extra_env.keys()):
            lines.append(f"{key} = {shell_quote(extra_env[key])}")
        lines.append("")
    return lines


def detect_env_files(source_repo: Path) -> list[Path]:
    primary = sorted(
        path
        for path in source_repo.glob("*.env")
        if path.is_file() and not path.name.endswith(".example") and not path.name.startswith(".")
    )
    if primary:
        return primary
    generated_env_dir = source_repo / "generated" / "bot-stack" / "env"
    return sorted(
        path
        for path in generated_env_dir.glob("*.env")
        if path.is_file() and not path.name.endswith(".example") and not path.name.startswith(".")
    )


def guess_scene(env_file: Path, env: dict[str, str]) -> str:
    if env_file.name.startswith("group."):
        return "group"
    if env_file.name.startswith("private."):
        return "private"
    if env.get("ALLOW_GROUP_CHAT", "").lower() == "true":
        return "group"
    return "private"


def derive_bot_id(env_file: Path) -> str:
    return env_file.name[:-4].replace(".", "-")


def derive_token_env(bot_id: str) -> str:
    return TOKEN_ENV_MAP.get(bot_id, f"{bot_id.upper().replace('-', '_')}_TOKEN")


def load_existing_stack_config(source_repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config_path = source_repo / "bot_stack.bootstrap.toml"
    if not config_path.exists():
        return {}, {}
    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    return dict(data.get("stack", {})), dict(data.get("defaults", {}))


def find_matching_plist(env_file: Path, launch_agents_dir: Path) -> Path | None:
    if not launch_agents_dir.exists():
        return None
    for plist_path in sorted(launch_agents_dir.glob("*.plist")):
        try:
            plist = parse_plist(plist_path)
        except Exception:
            continue
        joined_args = " ".join(str(item) for item in plist.get("ProgramArguments", []))
        if env_file.name in joined_args:
            return plist_path
    return None


def derive_namespace(service_labels: list[str]) -> str:
    for label in service_labels:
        if ".telegram-" in label:
            return label.split(".telegram-", 1)[0]
    return "com.example"


def export_config(source_repo: Path, launch_agents_dir: Path, output_path: Path) -> None:
    existing_stack, existing_defaults = load_existing_stack_config(source_repo)
    env_files = detect_env_files(source_repo)
    if not env_files:
        raise SystemExit(f"在 {source_repo} 下未找到正式 .env 文件")

    bots: list[dict[str, Any]] = []
    defaults: dict[str, Any] = dict(existing_defaults)
    stack: dict[str, Any] = {
        "repo_dir": str(source_repo),
        "output_dir": str(source_repo / "generated" / "bot-stack"),
        "launch_agents_dir": str(launch_agents_dir),
        "runner_script": str(source_repo / "run_role_bot.sh"),
    }
    stack.update(existing_stack)
    service_labels: list[str] = []

    for env_file in env_files:
        env = parse_env(env_file)
        if "BOT_ROLE" not in env:
            continue
        scene = guess_scene(env_file, env)
        bot_id = derive_bot_id(env_file)
        plist_path = find_matching_plist(env_file, launch_agents_dir)
        plist = parse_plist(plist_path) if plist_path else {}
        service_label = str(plist.get("Label", f"{stack.get('namespace', 'com.example')}.telegram-{bot_id}"))
        service_labels.append(service_label)
        bot: dict[str, Any] = {
            "id": bot_id,
            "scene": scene,
            "role": env.get("BOT_ROLE", ""),
            "token_env": derive_token_env(bot_id),
            "service_label": service_label,
        }
        extra_env: dict[str, Any] = {}
        for key, value in env.items():
            if key in IGNORED_ENV_KEYS:
                continue
            normalized = normalize_value(value)
            if key in ENV_TO_STACK:
                section, target_key = ENV_TO_STACK[key]
                if section == "stack":
                    stack[target_key] = normalized
                else:
                    defaults[target_key] = normalized
                continue
            if key in ENV_TO_BOT:
                bot[ENV_TO_BOT[key]] = normalized
                continue
            extra_env[key] = normalized
        if extra_env:
            bot["extra_env"] = extra_env
        bots.append(bot)

    if not bots:
        raise SystemExit(f"在 {source_repo} 下没有找到可导出的正式 bot env")

    stack["namespace"] = stack.get("namespace") or derive_namespace(service_labels)
    defaults.setdefault("workspace_dir", str(Path.home() / ".openclaw" / "workspace"))
    defaults.setdefault("home_dir", str(Path.home()))

    lines = [
        "# 这是从当前线上正式配置反向导出的脱敏 bot stack。",
        "# 不包含真实 token，请继续通过各 bot 的 token_env 环境变量注入。",
        "",
    ]
    lines.extend(render_table("stack", stack))
    lines.extend(render_table("defaults", defaults))
    for bot in bots:
        lines.extend(render_bot_table(bot))
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    source_repo = Path(args.source_repo).expanduser().resolve()
    launch_agents_dir = Path(args.launch_agents_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    export_config(source_repo, launch_agents_dir, output_path)
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
