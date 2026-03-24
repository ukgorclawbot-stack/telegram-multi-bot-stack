#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        from pip._vendor import tomli as tomllib  # type: ignore[no-redef]


VALID_ROLES = {"openclaw", "gemini", "codex", "claude"}
VALID_SCENES = {"group", "private"}
VALID_MODES = {"dispatcher", "worker"}
VALID_PRIVATE_TASK_MODES = {"direct", "queue", "hybrid", "manual"}
SCRIPT_DIR = Path(__file__).resolve().parent
HOME_DIR = Path.home()
DEFAULT_WORKSPACE_DIR = HOME_DIR / ".openclaw" / "workspace"
DEFAULT_SHARED_MEMORY_DIR = SCRIPT_DIR / "shared-memory"
DEFAULT_LONG_TERM_MEMORY_SCRIPT = SCRIPT_DIR / "scripts" / "shared-memory-write.sh"
DEFAULT_GROUP_TASK_DB_PATH = SCRIPT_DIR / "group-tasks.sqlite3"
DEFAULT_MEMORY_DB_PATH = SCRIPT_DIR / "bot-memory.sqlite3"
DEFAULT_LAUNCH_AGENTS_DIR = HOME_DIR / "Library" / "LaunchAgents"

ROLE_ENV_DEFAULTS: dict[str, dict[str, Any]] = {
    "openclaw": {
        "RUNNER_BACKEND": "openclaw_router",
        "OPENCLAW_BIN": "/opt/homebrew/bin/openclaw",
        "OPENCLAW_ROUTER_CODING_AGENT": "codex",
        "OPENCLAW_ROUTER_DOCS_AGENT": "gemini",
        "OPENCLAW_ROUTER_DEFAULT_AGENT": "codex",
    },
    "gemini": {
        "RUNNER_BACKEND": "gemini_cli",
        "GEMINI_BIN": "/opt/homebrew/bin/gemini",
        "GEMINI_MODEL": "",
        "GEMINI_APPROVAL_MODE": "auto_edit",
    },
    "codex": {
        "RUNNER_BACKEND": "codex_cli",
        "CODEX_BIN": "/opt/homebrew/bin/codex",
        "CODEX_MODEL": "",
        "CODEX_SANDBOX_MODE": "workspace-write",
    },
    "claude": {
        "RUNNER_BACKEND": "claude_cli",
        "CLAUDE_BIN": "/opt/homebrew/bin/claude",
        "CLAUDE_MODEL": "",
        "CLAUDE_PERMISSION_MODE": "acceptEdits",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="基于清单一键生成 Telegram 多 bot 的 env 和 launchd 配置。"
    )
    parser.add_argument("--config", required=True, help="bot stack TOML 配置文件路径")
    parser.add_argument("--output-dir", help="生成输出目录；默认取配置里的 stack.output_dir")
    parser.add_argument(
        "--apply-launchd",
        action="store_true",
        help="把生成的 plist 复制到 launch_agents_dir",
    )
    parser.add_argument(
        "--load-services",
        action="store_true",
        help="在 apply-launchd 基础上直接 load/start 服务",
    )
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required string: {key}")
    return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    if not slug:
        raise ValueError(f"Invalid slug value: {value!r}")
    return slug


def to_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return ""
    if re.search(r"\s", text) or '"' in text or "'" in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def validate_bot(bot: dict[str, Any]) -> None:
    role = require_str(bot, "role")
    scene = require_str(bot, "scene")
    mode = require_str(bot, "mode")
    private_task_mode = require_str(bot, "private_task_mode")
    if role not in VALID_ROLES:
        raise ValueError(f"Unsupported role: {role}")
    if scene not in VALID_SCENES:
        raise ValueError(f"Unsupported scene: {scene}")
    if mode not in VALID_MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    if private_task_mode not in VALID_PRIVATE_TASK_MODES:
        raise ValueError(f"Unsupported private_task_mode: {private_task_mode}")
    if mode == "worker" and not bot.get("runner_backend") and not bot.get("extra_env", {}).get("RUNNER_BACKEND"):
        raise ValueError(f"Worker bot requires runner_backend: {bot['id']}")


def build_bot_config(raw_bot: dict[str, Any], stack: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    bot = dict(raw_bot)
    bot["id"] = slugify(require_str(bot, "id"))
    bot["scene"] = require_str(bot, "scene")
    bot["role"] = require_str(bot, "role")
    bot["mode"] = require_str(bot, "mode")
    bot["private_task_mode"] = str(
        coalesce(bot.get("private_task_mode"), "manual" if bot["role"] == "openclaw" else "direct")
    )
    bot["display_name"] = coalesce(bot.get("display_name"), bot["id"])
    bot["runner_backend"] = coalesce(bot.get("runner_backend"), ROLE_ENV_DEFAULTS[bot["role"]].get("RUNNER_BACKEND"))
    bot["allow_group_chat"] = bool(coalesce(bot.get("allow_group_chat"), bot["scene"] == "group"))
    bot["allow_dm_tasks"] = bool(coalesce(bot.get("allow_dm_tasks"), bot["scene"] == "private"))
    bot["enable_direct_private_tasks"] = bool(
        coalesce(bot.get("enable_direct_private_tasks"), bot["scene"] == "private")
    )
    bot["allow_long_term_memory_write"] = bool(
        coalesce(bot.get("allow_long_term_memory_write"), bot["role"] == "openclaw")
    )
    workspace_dir = defaults.get("workspace_dir", str(DEFAULT_WORKSPACE_DIR))
    home_dir = defaults.get("home_dir", str(HOME_DIR))
    default_workdir = workspace_dir if bot["scene"] == "group" else home_dir
    bot["workdir"] = str(coalesce(bot.get("workdir"), default_workdir))
    bot["private_direct_workdir"] = coalesce(
        bot.get("private_direct_workdir"), home_dir if bot["scene"] == "private" else None
    )
    bot["persisted_history_limit"] = int(
        coalesce(bot.get("persisted_history_limit"), defaults.get("persisted_history_limit", 24))
    )
    bot["max_context_messages"] = int(
        coalesce(bot.get("max_context_messages"), defaults.get("max_context_messages", 8))
    )
    bot["poll_interval_secs"] = int(
        coalesce(bot.get("poll_interval_secs"), defaults.get("poll_interval_secs", 5))
    )
    bot["runner_timeout_secs"] = int(
        coalesce(bot.get("runner_timeout_secs"), defaults.get("runner_timeout_secs", 900))
    )
    bot["service_label"] = str(
        coalesce(bot.get("service_label"), f"{stack['namespace']}.telegram-{bot['id']}")
    )
    extra_env = dict(ROLE_ENV_DEFAULTS[bot["role"]])
    extra_env.update(bot.get("extra_env", {}))
    if bot.get("runner_backend"):
        extra_env["RUNNER_BACKEND"] = bot["runner_backend"]
    bot["extra_env"] = extra_env
    validate_bot(bot)
    return bot


def resolve_token(bot: dict[str, Any]) -> tuple[str, bool]:
    if bot.get("token"):
        return str(bot["token"]), True
    token_env = bot.get("token_env")
    if isinstance(token_env, str) and token_env:
        value = os.environ.get(token_env, "")
        if value:
            return value, True
        return f"replace_with_{bot['id']}_bot_token", False
    return f"replace_with_{bot['id']}_bot_token", False


def build_env_lines(bot: dict[str, Any], stack: dict[str, Any], defaults: dict[str, Any]) -> list[str]:
    token, _ = resolve_token(bot)
    allowed_user_ids = coalesce(
        bot.get("allowed_user_ids"), stack.get("allowed_user_ids"), defaults.get("allowed_user_ids"), ""
    )
    shared_memory_dir = str(defaults.get("shared_memory_dir", str(DEFAULT_SHARED_MEMORY_DIR)))
    long_term_script = str(
        defaults.get(
            "long_term_memory_script_path",
            str(DEFAULT_LONG_TERM_MEMORY_SCRIPT),
        )
    )

    entries: list[tuple[str, Any]] = [
        ("TELEGRAM_BOT_TOKEN", token),
        ("BOT_ENTRYPOINT", stack.get("bot_entrypoint", "group_bot.py")),
        ("BOT_ROLE", bot["role"]),
        ("BOT_MODE", bot["mode"]),
        ("BOT_DISPLAY_NAME", bot["display_name"]),
        ("ALLOW_DM_TASKS", bot["allow_dm_tasks"]),
        ("ENABLE_DIRECT_PRIVATE_TASKS", bot["enable_direct_private_tasks"]),
        ("PRIVATE_TASK_MODE", bot["private_task_mode"]),
        ("ALLOW_GROUP_CHAT", bot["allow_group_chat"]),
        ("ALLOWED_USER_IDS", allowed_user_ids),
        ("GROUP_TASK_DB_PATH", defaults.get("group_task_db_path", str(DEFAULT_GROUP_TASK_DB_PATH))),
        ("MEMORY_DB_PATH", defaults.get("memory_db_path", str(DEFAULT_MEMORY_DB_PATH))),
        ("PERSISTED_HISTORY_LIMIT", bot["persisted_history_limit"]),
        ("MAX_CONTEXT_MESSAGES", bot["max_context_messages"]),
        ("ENABLE_SHARED_MEMORY_LOG", bool(defaults.get("enable_shared_memory_log", True))),
        ("SHARED_MEMORY_DIR", shared_memory_dir),
        ("MEMORY_TIMEZONE", defaults.get("memory_timezone", "Asia/Shanghai")),
        ("ALLOW_LONG_TERM_MEMORY_WRITE", bot["allow_long_term_memory_write"]),
        ("WORKDIR", bot["workdir"]),
        ("RUNNER_TIMEOUT_SECS", bot["runner_timeout_secs"]),
    ]
    if bot["role"] == "openclaw":
        entries.insert(4, ("TASK_COMMAND", defaults.get("task_command", "task")))
    if bot["scene"] == "private" and bot.get("private_direct_workdir"):
        entries.append(("PRIVATE_DIRECT_WORKDIR", bot["private_direct_workdir"]))
    if bot["mode"] == "worker":
        entries.append(("POLL_INTERVAL_SECS", bot["poll_interval_secs"]))
    if bot["allow_long_term_memory_write"]:
        entries.append(("LONG_TERM_MEMORY_SCRIPT_PATH", long_term_script))

    existing_keys = {key for key, _ in entries}
    for key, value in bot["extra_env"].items():
        if key in existing_keys:
            for idx, (existing_key, _) in enumerate(entries):
                if existing_key == key:
                    entries[idx] = (key, value)
                    break
        else:
            entries.append((key, value))
    return [f"{key}={to_env_value(value)}" for key, value in entries]


def render_launchd(bot: dict[str, Any], stack: dict[str, Any], env_path: Path, stdout_path: Path, stderr_path: Path) -> bytes:
    repo_dir = Path(stack["repo_dir"])
    run_script = Path(stack["runner_script"])
    plist = {
        "Label": bot["service_label"],
        "ProgramArguments": [
            "/bin/zsh",
            "-lc",
            f"cd {repo_dir} && {run_script} {env_path}",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(repo_dir),
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
    }
    return plistlib.dumps(plist)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def apply_launchd(plist_path: Path, launch_agents_dir: Path, label: str, load_services: bool) -> None:
    target = launch_agents_dir / plist_path.name
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plist_path, target)
    if not load_services:
        return
    subprocess.run(["launchctl", "unload", str(target)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "load", str(target)], check=True)
    subprocess.run(["launchctl", "start", label], check=False)


def render_summary(stack: dict[str, Any], bots: list[dict[str, Any]], output_dir: Path, warnings: list[str]) -> str:
    lines = [
        "# Bot Stack Bootstrap Summary",
        "",
        f"- 仓库目录：`{stack['repo_dir']}`",
        f"- 输出目录：`{output_dir}`",
        f"- 机器人数量：`{len(bots)}`",
        "",
        "| Bot | 场景 | 角色 | 模式 | service label | env 文件 | plist 文件 |",
        "|---|---|---|---|---|---|---|",
    ]
    for bot in bots:
        lines.append(
            f"| `{bot['id']}` | `{bot['scene']}` | `{bot['role']}` | `{bot['mode']}` | "
            f"`{bot['service_label']}` | `env/{bot['id']}.env` | `launchd/{bot['id']}.plist` |"
        )
    lines.extend(
        [
            "",
            "## 一键生成",
            "",
            "```bash",
            f"cd {stack['repo_dir']}",
            f"bash ./bootstrap_bot_stack.sh generate {stack['config_path']}",
            "```",
            "",
            "## 一键生成并应用 launchd",
            "",
            "```bash",
            f"cd {stack['repo_dir']}",
            f"bash ./bootstrap_bot_stack.sh apply {stack['config_path']}",
            "```",
        ]
    )
    if warnings:
        lines.extend(["", "## 提醒", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    stack = dict(config.get("stack", {}))
    defaults = dict(config.get("defaults", {}))
    raw_bots = list(config.get("bots", []))
    if not raw_bots:
        raise SystemExit("配置里至少要有一个 [[bots]]")

    stack["repo_dir"] = require_str(stack, "repo_dir")
    stack["namespace"] = require_str(stack, "namespace")
    stack["runner_script"] = require_str(stack, "runner_script")
    stack["bot_entrypoint"] = str(stack.get("bot_entrypoint", "group_bot.py"))
    stack["config_path"] = str(config_path)

    output_dir = Path(
        args.output_dir
        or stack.get("output_dir")
        or (Path(stack["repo_dir"]) / "generated" / "bot-stack")
    ).expanduser().resolve()
    env_dir = output_dir / "env"
    launchd_dir = output_dir / "launchd"
    logs_dir = output_dir / "logs"

    bots = [build_bot_config(bot, stack, defaults) for bot in raw_bots]
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for bot in bots:
        if bot["id"] in seen_ids:
            raise SystemExit(f"重复 bot id: {bot['id']}")
        if bot["service_label"] in seen_labels:
            raise SystemExit(f"重复 service_label: {bot['service_label']}")
        seen_ids.add(bot["id"])
        seen_labels.add(bot["service_label"])

    warnings: list[str] = []
    for bot in bots:
        env_lines = build_env_lines(bot, stack, defaults)
        _, has_real_token = resolve_token(bot)
        if not has_real_token:
            warnings.append(f"{bot['id']} 未读取到真实 token，env 中写入了占位值。")
        env_path = env_dir / f"{bot['id']}.env"
        write_text(env_path, "\n".join(env_lines) + "\n")

        stdout_path = logs_dir / f"{bot['id']}.stdout.log"
        stderr_path = logs_dir / f"{bot['id']}.stderr.log"
        plist_path = launchd_dir / f"{bot['id']}.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_bytes(render_launchd(bot, stack, env_path, stdout_path, stderr_path))

        if args.apply_launchd:
            if not has_real_token:
                raise SystemExit(f"{bot['id']} 缺少真实 token，不能 apply launchd。")
            launch_agents_dir = Path(
                stack.get("launch_agents_dir", str(DEFAULT_LAUNCH_AGENTS_DIR))
            ).expanduser()
            apply_launchd(plist_path, launch_agents_dir, bot["service_label"], args.load_services)

    write_text(output_dir / "STACK_SUMMARY.md", render_summary(stack, bots, output_dir, warnings))
    print(f"generated {len(bots)} bots into {output_dir}")
    if warnings:
        for warning in warnings:
            print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
