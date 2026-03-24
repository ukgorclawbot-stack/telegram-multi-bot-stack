#!/usr/bin/env python3
from __future__ import annotations

import getpass
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent
DEFAULT_HOME = Path.home()
DEFAULT_SHARED = REPO_DIR / "shared-memory"
CONFIG_PATH = REPO_DIR / "bot_stack.bootstrap.toml"
TOKENS_PATH = REPO_DIR / ".bot_tokens.env"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def yes_no(prompt: str, default: bool = True) -> bool:
    raw = ask(prompt, "Y" if default else "N").lower()
    return raw in {"y", "yes", "1", "true"}


def render_config(home_dir: str, allowed_user_ids: str, namespace: str, use_six_bot: bool) -> str:
    repo_dir = str(REPO_DIR)
    shared_dir = str(DEFAULT_SHARED)
    lines = [
        "[stack]",
        f'repo_dir = "{repo_dir}"',
        f'output_dir = "{repo_dir}/generated/bot-stack"',
        f'launch_agents_dir = "{home_dir}/Library/LaunchAgents"',
        f'namespace = "{namespace}"',
        f'runner_script = "{repo_dir}/run_role_bot.sh"',
        'bot_entrypoint = "group_bot.py"',
        f'allowed_user_ids = "{allowed_user_ids}"',
        "",
        "[defaults]",
        f'group_task_db_path = "{repo_dir}/group-tasks.sqlite3"',
        f'memory_db_path = "{repo_dir}/bot-memory.sqlite3"',
        f'shared_memory_dir = "{shared_dir}"',
        'memory_timezone = "Asia/Shanghai"',
        "runner_timeout_secs = 900",
        "persisted_history_limit = 24",
        "max_context_messages = 8",
        "enable_shared_memory_log = true",
        "poll_interval_secs = 5",
        'task_command = "task"',
        f'long_term_memory_script_path = "{repo_dir}/scripts/shared-memory-write.sh"',
        f'workspace_dir = "{home_dir}/.openclaw/workspace"',
        f'home_dir = "{home_dir}"',
        "",
    ]

    if use_six_bot:
        bot_blocks = [
            {
                "id": "group-openclaw",
                "scene": "group",
                "role": "openclaw",
                "mode": "dispatcher",
                "display_name": "OpenClaw Group",
                "token_env": "TG_OPENCLAW_GROUP_TOKEN",
                "workdir": f"{home_dir}/.openclaw/workspace",
                "allow_group_chat": "true",
                "allow_dm_tasks": "false",
                "enable_direct_private_tasks": "false",
                "private_task_mode": "manual",
                "allow_long_term_memory_write": "true",
                "extra": {
                    "RUNNER_BACKEND": "openclaw_router",
                    "PRIVATE_DIRECT_RUNNER_BACKEND": "openclaw_agent",
                    "PRIVATE_DIRECT_OPENCLAW_AGENT_ID": "main",
                    "OPENCLAW_BIN": "/opt/homebrew/bin/openclaw",
                    "OPENCLAW_ROUTER_CODING_AGENT": "codex",
                    "OPENCLAW_ROUTER_DOCS_AGENT": "gemini",
                    "OPENCLAW_ROUTER_DEFAULT_AGENT": "codex",
                },
            },
            {
                "id": "group-gemini",
                "scene": "group",
                "role": "gemini",
                "mode": "worker",
                "display_name": "Gemini Group",
                "token_env": "TG_GEMINI_GROUP_TOKEN",
                "workdir": f"{home_dir}/.openclaw/workspace",
                "allow_group_chat": "true",
                "allow_dm_tasks": "false",
                "enable_direct_private_tasks": "false",
                "private_task_mode": "direct",
                "allow_long_term_memory_write": "false",
                "extra": {
                    "RUNNER_BACKEND": "gemini_cli",
                    "GEMINI_BIN": "/opt/homebrew/bin/gemini",
                    "GEMINI_MODEL": "",
                    "GEMINI_APPROVAL_MODE": "auto_edit",
                },
            },
            {
                "id": "group-codex",
                "scene": "group",
                "role": "codex",
                "mode": "worker",
                "display_name": "Codex Group",
                "token_env": "TG_CODEX_GROUP_TOKEN",
                "workdir": home_dir,
                "allow_group_chat": "true",
                "allow_dm_tasks": "false",
                "enable_direct_private_tasks": "false",
                "private_task_mode": "direct",
                "allow_long_term_memory_write": "false",
                "extra": {
                    "RUNNER_BACKEND": "codex_cli",
                    "CODEX_BIN": "/opt/homebrew/bin/codex",
                    "CODEX_MODEL": "",
                    "CODEX_SANDBOX_MODE": "workspace-write",
                },
            },
            {
                "id": "private-openclaw",
                "scene": "private",
                "role": "openclaw",
                "mode": "dispatcher",
                "display_name": "OpenClaw Private",
                "token_env": "TG_OPENCLAW_PRIVATE_TOKEN",
                "workdir": home_dir,
                "private_direct_workdir": home_dir,
                "allow_group_chat": "false",
                "allow_dm_tasks": "true",
                "enable_direct_private_tasks": "true",
                "private_task_mode": "manual",
                "allow_long_term_memory_write": "true",
                "extra": {
                    "RUNNER_BACKEND": "openclaw_router",
                    "PRIVATE_DIRECT_RUNNER_BACKEND": "openclaw_agent",
                    "PRIVATE_DIRECT_OPENCLAW_AGENT_ID": "main",
                    "OPENCLAW_BIN": "/opt/homebrew/bin/openclaw",
                    "OPENCLAW_ROUTER_CODING_AGENT": "codex",
                    "OPENCLAW_ROUTER_DOCS_AGENT": "gemini",
                    "OPENCLAW_ROUTER_DEFAULT_AGENT": "codex",
                },
            },
            {
                "id": "private-gemini",
                "scene": "private",
                "role": "gemini",
                "mode": "worker",
                "display_name": "Gemini Private",
                "token_env": "TG_GEMINI_PRIVATE_TOKEN",
                "workdir": home_dir,
                "private_direct_workdir": home_dir,
                "allow_group_chat": "false",
                "allow_dm_tasks": "true",
                "enable_direct_private_tasks": "true",
                "private_task_mode": "direct",
                "allow_long_term_memory_write": "false",
                "extra": {
                    "RUNNER_BACKEND": "gemini_cli",
                    "GEMINI_BIN": "/opt/homebrew/bin/gemini",
                    "GEMINI_MODEL": "",
                    "GEMINI_APPROVAL_MODE": "auto_edit",
                },
            },
            {
                "id": "private-codex",
                "scene": "private",
                "role": "codex",
                "mode": "worker",
                "display_name": "Codex Private",
                "token_env": "TG_CODEX_PRIVATE_TOKEN",
                "workdir": home_dir,
                "private_direct_workdir": home_dir,
                "allow_group_chat": "false",
                "allow_dm_tasks": "true",
                "enable_direct_private_tasks": "true",
                "private_task_mode": "direct",
                "allow_long_term_memory_write": "false",
                "extra": {
                    "RUNNER_BACKEND": "codex_cli",
                    "CODEX_BIN": "/opt/homebrew/bin/codex",
                    "CODEX_MODEL": "",
                    "CODEX_SANDBOX_MODE": "workspace-write",
                },
            },
        ]
    else:
        count = int(ask("你要创建多少个 bot", "2"))
        bot_blocks = []
        for idx in range(count):
            print(f"\n配置第 {idx + 1} 个 bot")
            scene = ask("场景(group/private)", "group")
            role = ask("角色(openclaw/gemini/codex/claude)", "gemini")
            bot_id = ask("bot id", f"{scene}-{role}-{idx+1}")
            mode = ask("模式(dispatcher/worker)", "dispatcher" if role == "openclaw" else "worker")
            display_name = ask("显示名称", bot_id)
            token_env = ask("token 环境变量名", f"TG_{bot_id.upper().replace('-', '_')}_TOKEN")
            workdir = ask("工作目录", f"{home_dir}/.openclaw/workspace" if scene == "group" else home_dir)
            block = {
                "id": bot_id,
                "scene": scene,
                "role": role,
                "mode": mode,
                "display_name": display_name,
                "token_env": token_env,
                "workdir": workdir,
                "allow_group_chat": "true" if scene == "group" else "false",
                "allow_dm_tasks": "true" if scene == "private" else "false",
                "enable_direct_private_tasks": "true" if scene == "private" else "false",
                "private_task_mode": "manual" if role == "openclaw" else "direct",
                "allow_long_term_memory_write": "true" if role == "openclaw" else "false",
                "extra": {"RUNNER_BACKEND": {"openclaw": "openclaw_router", "gemini": "gemini_cli", "codex": "codex_cli", "claude": "claude_cli"}[role]},
            }
            if scene == "private":
                block["private_direct_workdir"] = ask("私聊直连工作目录", home_dir)
            bot_blocks.append(block)

    for block in bot_blocks:
        lines.extend(
            [
                "[[bots]]",
                f'id = "{block["id"]}"',
                f'scene = "{block["scene"]}"',
                f'role = "{block["role"]}"',
                f'mode = "{block["mode"]}"',
                f'display_name = "{block["display_name"]}"',
                f'token_env = "{block["token_env"]}"',
                f'workdir = "{block["workdir"]}"',
            ]
        )
        if "private_direct_workdir" in block:
            lines.append(f'private_direct_workdir = "{block["private_direct_workdir"]}"')
        lines.extend(
            [
                f'allow_group_chat = {block["allow_group_chat"]}',
                f'allow_dm_tasks = {block["allow_dm_tasks"]}',
                f'enable_direct_private_tasks = {block["enable_direct_private_tasks"]}',
                f'private_task_mode = "{block["private_task_mode"]}"',
                f'allow_long_term_memory_write = {block["allow_long_term_memory_write"]}',
                "",
                "[bots.extra_env]",
            ]
        )
        for key, value in block["extra"].items():
            lines.append(f'{key} = "{value}"')
        lines.append("")
    return "\n".join(lines)


def write_tokens_file(use_six_bot: bool) -> None:
    if not yes_no("是否现在把 bot token 写进本地 .bot_tokens.env", False):
        return
    token_keys = (
        [
            "TG_OPENCLAW_GROUP_TOKEN",
            "TG_GEMINI_GROUP_TOKEN",
            "TG_CODEX_GROUP_TOKEN",
            "TG_OPENCLAW_PRIVATE_TOKEN",
            "TG_GEMINI_PRIVATE_TOKEN",
            "TG_CODEX_PRIVATE_TOKEN",
        ]
        if use_six_bot
        else []
    )
    lines = []
    for key in token_keys:
        value = getpass.getpass(f"{key}: ").strip()
        lines.append(f'export {key}="{value}"')
    TOKENS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入: {TOKENS_PATH}")


def main() -> int:
    print("Telegram Bot Stack 配置向导\n")
    home_dir = ask("你的 home 目录", str(DEFAULT_HOME))
    allowed_user_ids = ask("允许使用这些 bot 的 Telegram user_id（逗号分隔）")
    namespace = ask("launchd 命名空间", "com.telegrambotstack")
    use_six_bot = yes_no("是否使用推荐的 6 bot 结构", True)
    content = render_config(home_dir, allowed_user_ids, namespace, use_six_bot)
    CONFIG_PATH.write_text(content + "\n", encoding="utf-8")
    print(f"\n已生成: {CONFIG_PATH}")
    write_tokens_file(use_six_bot)
    print("\n下一步：")
    print("1) 检查 bot_stack.bootstrap.toml")
    print("2) 如有需要，补全 .bot_tokens.env")
    print("3) 执行: bash ./apply_stack.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
