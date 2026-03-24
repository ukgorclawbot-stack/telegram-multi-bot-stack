#!/usr/bin/env python3
import asyncio
import contextlib
from dataclasses import replace
import json
import logging
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_store import (
    ConversationMemoryStore,
    LongTermMemoryWriter,
    SharedMemoryJournal,
    build_instant_memory_snapshot,
    render_memory_search_digest,
    render_recent_memory_digest,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters

from routing import classify_group_message_semantics, classify_task, format_allowed_agents
from runners import RunnerConfig, run_task
from task_registry import TaskRegistry


BASE_DIR = Path(__file__).resolve().parent
OPENCLAW_WORKSPACE_DIR = Path(
    os.getenv("OPENCLAW_WORKSPACE_DIR", str(Path.home() / ".openclaw" / "workspace"))
).expanduser()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BOT_ROLE = os.getenv("BOT_ROLE", "").strip().lower()
BOT_MODE = os.getenv("BOT_MODE", "worker").strip().lower()
BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", BOT_ROLE or "agent").strip()
GROUP_TASK_DB_PATH = os.getenv("GROUP_TASK_DB_PATH", str(BASE_DIR / "group-tasks.sqlite3")).strip()
LOG_FILE = Path(os.getenv("GROUP_LOG_FILE", str(BASE_DIR / f"group-{BOT_ROLE or 'agent'}.log")).strip())
POLL_INTERVAL_SECS = int(os.getenv("POLL_INTERVAL_SECS", "5"))
PROGRESS_DELAY_SECS = int(os.getenv("PROGRESS_DELAY_SECS", "45"))
DIRECT_GROUP_PROGRESS_DELAY_SECS = int(os.getenv("DIRECT_GROUP_PROGRESS_DELAY_SECS", "30"))
DIRECT_GROUP_FALLBACK_TIMEOUT_SECS = int(os.getenv("DIRECT_GROUP_FALLBACK_TIMEOUT_SECS", "120"))
DIRECT_PRIVATE_PROGRESS_DELAY_SECS = int(os.getenv("DIRECT_PRIVATE_PROGRESS_DELAY_SECS", "20"))
DIRECT_PRIVATE_FALLBACK_TIMEOUT_SECS = int(os.getenv("DIRECT_PRIVATE_FALLBACK_TIMEOUT_SECS", "120"))
TASK_STALE_CLAIM_SECS = int(os.getenv("TASK_STALE_CLAIM_SECS", "120"))
WORKDIR = os.getenv("WORKDIR", str(Path.home() / ".openclaw" / "workspace")).strip()
TASK_COMMAND = os.getenv("TASK_COMMAND", "task").strip()
ALLOW_GROUP_CHAT = os.getenv("ALLOW_GROUP_CHAT", "true").strip().lower() in {"1", "true", "yes", "on"}
ALLOW_DM_TASKS = os.getenv("ALLOW_DM_TASKS", "true").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_DIRECT_PRIVATE_TASKS = os.getenv("ENABLE_DIRECT_PRIVATE_TASKS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PRIVATE_TASK_MODE = os.getenv("PRIVATE_TASK_MODE", "direct").strip().lower()
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "16" if BOT_ROLE == "openclaw" else "8"))
PERSISTED_HISTORY_LIMIT = int(os.getenv("PERSISTED_HISTORY_LIMIT", "80" if BOT_ROLE == "openclaw" else "24"))
INSTANT_MEMORY_OWN_LIMIT = int(os.getenv("INSTANT_MEMORY_OWN_LIMIT", "6"))
INSTANT_MEMORY_SHARED_LIMIT = int(os.getenv("INSTANT_MEMORY_SHARED_LIMIT", "6"))
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", str(BASE_DIR / "bot-memory.sqlite3")).strip()
ENABLE_SHARED_MEMORY_LOG = os.getenv("ENABLE_SHARED_MEMORY_LOG", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SHARED_MEMORY_DIR = os.getenv(
    "SHARED_MEMORY_DIR",
    str(BASE_DIR / "shared-memory"),
).strip()
MEMORY_TIMEZONE = os.getenv("MEMORY_TIMEZONE", "Asia/Shanghai").strip()
ALLOW_LONG_TERM_MEMORY_WRITE = os.getenv("ALLOW_LONG_TERM_MEMORY_WRITE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LONG_TERM_MEMORY_SCRIPT_PATH = os.getenv(
    "LONG_TERM_MEMORY_SCRIPT_PATH",
    str(BASE_DIR / "scripts" / "shared-memory-write.sh"),
).strip()
RUNNER_BACKEND = os.getenv("RUNNER_BACKEND", "").strip()
PRIVATE_DIRECT_RUNNER_BACKEND = os.getenv("PRIVATE_DIRECT_RUNNER_BACKEND", "").strip()
PRIVATE_DIRECT_OPENCLAW_AGENT_ID = os.getenv("PRIVATE_DIRECT_OPENCLAW_AGENT_ID", "main").strip()
PRIVATE_DIRECT_WORKDIR = os.getenv("PRIVATE_DIRECT_WORKDIR", "").strip()
RUNNER_TIMEOUT_SECS = int(os.getenv("RUNNER_TIMEOUT_SECS", "900"))
ALLOWED_USER_IDS = {
    int(user_id.strip())
    for user_id in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if user_id.strip().isdigit()
}

CODEx_BIN = os.getenv("CODEX_BIN", "codex").strip()
CODEX_MODEL = os.getenv("CODEX_MODEL", "gpt-5.4-mini").strip()
CODEX_REASONING_EFFORT = os.getenv("CODEX_REASONING_EFFORT", "medium").strip()
CODEX_SANDBOX_MODE = os.getenv("CODEX_SANDBOX_MODE", "workspace-write").strip()
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "").strip()
CLAUDE_PERMISSION_MODE = os.getenv("CLAUDE_PERMISSION_MODE", "acceptEdits").strip()
GEMINI_BIN = os.getenv("GEMINI_BIN", "gemini").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
GEMINI_APPROVAL_MODE = os.getenv("GEMINI_APPROVAL_MODE", "auto_edit").strip()
OPENCLAW_BIN = os.getenv("OPENCLAW_BIN", "openclaw").strip()
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", BOT_ROLE).strip()
OPENCLAW_ROUTER_CODING_AGENT = os.getenv("OPENCLAW_ROUTER_CODING_AGENT", "codex").strip()
OPENCLAW_ROUTER_DOCS_AGENT = os.getenv("OPENCLAW_ROUTER_DOCS_AGENT", "gemini").strip()
OPENCLAW_ROUTER_DEFAULT_AGENT = os.getenv("OPENCLAW_ROUTER_DEFAULT_AGENT", "codex").strip()
DAILY_CRYPTO_LATEST_DIGEST_JSON_PATH = os.getenv(
    "DAILY_CRYPTO_LATEST_DIGEST_JSON_PATH",
    str(Path.home() / ".openclaw" / "workspace" / "reports" / "daily-crypto" / "latest.digest.json"),
).strip()
DAILY_CRYPTO_LATEST_DIGEST_TEXT_PATH = os.getenv(
    "DAILY_CRYPTO_LATEST_DIGEST_TEXT_PATH",
    str(Path.home() / ".openclaw" / "workspace" / "reports" / "daily-crypto" / "latest.digest.txt"),
).strip()
DAILY_REPORT_CALLBACK_PREFIX = "daily-report:"
NO_REPLY_SENTINEL = "[[NO_REPLY]]"
RUNTIME_MONITOR_INTERVAL_SECS = 60
RUNTIME_MONITOR_LOOKBACK_MINUTES = 1
RUNTIME_MONITOR_MIN_LOOKBACK_MOVE = 3.0
RUNTIME_MONITOR_SECONDARY_LOOKBACK_MINUTES = 5
RUNTIME_MONITOR_SECONDARY_MIN_LOOKBACK_MOVE = 10.0
RUNTIME_MONITOR_ALERT_MODE = "dual-rise"
TENBAGGER_SCRIPT_PATH = Path.home() / ".openclaw" / "workspace" / "scripts" / "fetch_high_low_ratio.py"
TENBAGGER_OUTPUT_DIR = Path.home() / ".openclaw" / "workspace" / "reports" / "binance-tenbagger"
ROLE_ASSIGNMENT_KEYWORDS = [
    "职责",
    "角色定位",
    "定位",
    "你负责",
    "你的主要职责",
    "你的职责",
    "以后你负责",
    "只负责",
    "专门负责",
]
HANDOFF_KEYWORDS = [
    "帮",
    "协助",
    "审核",
    "检查",
    "排查",
    "处理",
    "接手",
    "优化",
    "修复",
    "review",
    "看一下",
    "发给",
    "交给",
    "让",
    "请",
]
PRIMARY_GROUP_ROUTING_KEYWORDS = [
    "发给",
    "交给",
    "转给",
    "转交给",
    "转发给",
    "让他",
    "让她",
    "让其",
    "协助",
    "配合",
    "接手",
    "复核",
    "复查",
    "审核",
    "检查",
    "审一下",
    "帮他",
    "帮你",
    "帮忙",
]
DELEGATION_RETURN_CATEGORY = "delegation-return"

EXPLICIT_DISPATCH_MARKERS = [
    "#codex",
    "#claude",
    "#claudecode",
    "#gemini",
    "#dispatch",
    "#派单",
    "交给codex",
    "交给claude",
    "交给gemini",
    "让codex",
    "让claude",
    "让gemini",
    "派给codex",
    "派给claude",
    "派给gemini",
    "分配给codex",
    "分配给claude",
    "分配给gemini",
    "分派给codex",
    "分派给claude",
    "分派给gemini",
    "请分派",
    "帮我分派",
    "请派单",
    "帮我派单",
    "请分配给合适",
    "交给合适的bot",
    "交给对应bot",
]

AGENT_SERVICE_LABELS = {
    "openclaw": ["com.ukgorclawbot.telegram-group-openclaw"],
    "gemini": ["com.ukgorclawbot.telegram-group-gemini"],
    "claude": ["com.ukgorclawbot.telegram-group-claude"],
    "codex": ["com.ukgorclawbot.telegram-openai-bot", "com.ukgorclawbot.telegram-group-codex"],
}


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    logging.getLogger("httpx").handlers = []
    logging.getLogger("httpx").propagate = False
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").handlers = []
    logging.getLogger("httpcore").propagate = False
    logging.getLogger("httpcore").disabled = True


def validate_env() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
    if BOT_ROLE not in {"openclaw", "codex", "claude", "gemini"}:
        raise RuntimeError("BOT_ROLE must be one of: openclaw, codex, claude, gemini")
    if BOT_MODE not in {"dispatcher", "worker"}:
        raise RuntimeError("BOT_MODE must be dispatcher or worker")
    if PRIVATE_TASK_MODE not in {"direct", "queue", "hybrid", "manual"}:
        raise RuntimeError("PRIVATE_TASK_MODE must be direct, queue, hybrid, or manual")
    if BOT_MODE == "worker" and not RUNNER_BACKEND:
        raise RuntimeError("Worker bot requires RUNNER_BACKEND")


def get_registry(app: Application) -> TaskRegistry:
    return app.bot_data["registry"]


def get_memory_store(app: Application) -> ConversationMemoryStore:
    return app.bot_data["memory_store"]


def get_instant_memory_snapshot(app: Application, chat_id: str) -> str:
    return build_instant_memory_snapshot(
        get_memory_store(app),
        bot_role=BOT_ROLE,
        chat_id=chat_id,
        own_limit=INSTANT_MEMORY_OWN_LIMIT,
        shared_limit=INSTANT_MEMORY_SHARED_LIMIT,
    )


def get_shared_journal(app: Application) -> SharedMemoryJournal:
    return app.bot_data["shared_memory_journal"]


def get_long_term_writer(app: Application) -> LongTermMemoryWriter:
    return app.bot_data["long_term_memory_writer"]


def mirror_group_result_to_openclaw_memory(
    memory_store: ConversationMemoryStore,
    *,
    chat_id: str,
    user_id: str,
    content: str,
) -> None:
    clean = content.strip()
    if BOT_ROLE == "openclaw" or not clean:
        return
    memory_store.append_message(
        "openclaw",
        chat_id,
        user_id,
        "assistant",
        f"[群聊结果 · {BOT_DISPLAY_NAME}]\n{clean}",
    )


def get_runner_config() -> RunnerConfig:
    return RunnerConfig(
        backend=RUNNER_BACKEND,
        workdir=WORKDIR,
        timeout_secs=RUNNER_TIMEOUT_SECS,
        codex_bin=CODEx_BIN,
        codex_model=CODEX_MODEL,
        codex_reasoning_effort=CODEX_REASONING_EFFORT,
        codex_sandbox=CODEX_SANDBOX_MODE,
        claude_bin=CLAUDE_BIN,
        claude_model=CLAUDE_MODEL,
        claude_permission_mode=CLAUDE_PERMISSION_MODE,
        gemini_bin=GEMINI_BIN,
        gemini_model=GEMINI_MODEL,
        gemini_approval_mode=GEMINI_APPROVAL_MODE,
        openclaw_bin=OPENCLAW_BIN,
        openclaw_agent_id=OPENCLAW_AGENT_ID,
        openclaw_router_coding_agent=OPENCLAW_ROUTER_CODING_AGENT,
        openclaw_router_docs_agent=OPENCLAW_ROUTER_DOCS_AGENT,
        openclaw_router_default_agent=OPENCLAW_ROUTER_DEFAULT_AGENT,
    )


async def notify_long_running_task(
    app: Application,
    *,
    task_id: int,
    chat_id: str,
    route_reason: str,
) -> None:
    await asyncio.sleep(PROGRESS_DELAY_SECS)
    task = get_registry(app).get_task(task_id)
    if not task or str(task.get("status", "")) != "claimed":
        return

    delegation_source_role, delegation_target_role = parse_route_pair(route_reason, "user-delegation:")
    if delegation_source_role and delegation_target_role == BOT_ROLE:
        if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
            text = (
                f"[{BOT_DISPLAY_NAME}] 任务 #{task_id} 仍在处理中，"
                "我会继续直接同步进展，并把关键结果写回 OpenClaw 记忆。"
            )
        else:
            text = (
                f"[{BOT_DISPLAY_NAME}] 任务 #{task_id} 仍在检查相关路径和代码链路，"
                f"完成后我会先把结果交回 {resolve_role_display_name(delegation_source_role)} 统一汇总。"
            )
    else:
        text = f"[{BOT_DISPLAY_NAME}] 任务 #{task_id} 仍在处理中，我会在完成后继续同步结果。"
    await app.bot.send_message(chat_id=chat_id, text=text)


async def send_group_chat_text(
    app: Application,
    *,
    chat_id: int,
    text: str,
    thread_id: Optional[int] = None,
) -> None:
    text = text[:4000]
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, message_thread_id=thread_id)
        return
    except BadRequest as exc:
        if not is_group_reply_fallback_error(exc):
            raise
        logging.warning(
            "Falling back to root group send role=%s chat_id=%s thread_id=%s error=%s",
            BOT_ROLE,
            chat_id,
            thread_id,
            exc,
        )
    await app.bot.send_message(chat_id=chat_id, text=text)


async def notify_long_running_direct_group_task(
    app: Application,
    *,
    chat_id: int,
    thread_id: Optional[int],
    message_semantics: str = "task",
) -> None:
    await asyncio.sleep(DIRECT_GROUP_PROGRESS_DELAY_SECS)
    if message_semantics == "casual":
        text = f"[{BOT_DISPLAY_NAME}] 我在想一下，马上回你。"
    else:
        text = (
            f"[{BOT_DISPLAY_NAME}] 这条需求还在处理中，"
            "我正在整理关键信息和执行步骤，稍后继续直接回复你。"
        )
    await send_group_chat_text(
        app,
        chat_id=chat_id,
        thread_id=thread_id,
        text=text,
    )


async def notify_long_running_direct_private_task(
    app: Application,
    *,
    chat_id: int,
) -> None:
    await asyncio.sleep(DIRECT_PRIVATE_PROGRESS_DELAY_SECS)
    text = f"[{BOT_DISPLAY_NAME}] 这条我还在处理；如果直连继续卡住，我会自动切到任务链继续跑。"
    await app.bot.send_message(chat_id=chat_id, text=text)


def get_private_runner_config() -> RunnerConfig:
    cfg = get_runner_config()
    if PRIVATE_DIRECT_RUNNER_BACKEND:
        cfg.backend = PRIVATE_DIRECT_RUNNER_BACKEND
    elif BOT_ROLE == "openclaw" and BOT_MODE == "dispatcher":
        cfg.backend = "openclaw_agent"
    if PRIVATE_DIRECT_WORKDIR:
        cfg.workdir = PRIVATE_DIRECT_WORKDIR
    if cfg.backend == "openclaw_agent" and BOT_ROLE == "openclaw" and BOT_MODE == "dispatcher":
        cfg.openclaw_agent_id = PRIVATE_DIRECT_OPENCLAW_AGENT_ID or "main"
    return cfg


def summarize_text(text: str, limit: int = 120) -> str:
    clean = text.replace("\n", " ").strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit]}..."


def is_group_like_chat(chat_type: Optional[str]) -> bool:
    return chat_type in {"group", "supergroup", "channel"}


def extract_message_mentions(message: Any) -> set[str]:
    mentions: set[str] = set()
    if not message:
        return mentions

    entities = list(getattr(message, "entities", None) or [])
    entities.extend(getattr(message, "caption_entities", None) or [])
    for entity in entities:
        entity_type = str(getattr(entity, "type", "")).lower()
        if entity_type != "mention":
            continue
        try:
            raw = message.parse_entity(entity)
        except Exception:
            continue
        normalized = raw.strip().lower().lstrip("@")
        if normalized:
            mentions.add(normalized)

    raw_text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    for match in re.findall(r"@([A-Za-z0-9_]{5,})", raw_text):
        mentions.add(match.lower())
    return mentions


def extract_ordered_message_mentions(message: Any) -> List[str]:
    ordered: List[str] = []
    raw_text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    for match in re.findall(r"@([A-Za-z0-9_]{5,})", raw_text):
        normalized = match.lower()
        if normalized not in ordered:
            ordered.append(normalized)
    return ordered


def resolve_primary_group_bot_mention(message: Any) -> str:
    raw_text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip().lower()
    ordered_bot_mentions = [
        mention
        for mention in extract_ordered_message_mentions(message)
        if mention.endswith("bot")
    ]
    if len(ordered_bot_mentions) < 2:
        return ""
    has_routing_hint = any(keyword in raw_text for keyword in PRIMARY_GROUP_ROUTING_KEYWORDS)
    if not has_routing_hint:
        has_routing_hint = bool(
            re.search(
                r"@[a-z0-9_]{5,}bot.*(?:让|交给|发给|转给|协助|配合|检查|审核|解决)\s+@[a-z0-9_]{5,}bot",
                raw_text,
            )
        )
    if not has_routing_hint:
        return ""
    return ordered_bot_mentions[0]


def resolve_user_delegation_targets(message: Any, self_username: str) -> List[str]:
    primary_mention = resolve_primary_group_bot_mention(message)
    if not primary_mention or primary_mention != self_username:
        return []

    targets: List[str] = []
    for mention in extract_ordered_message_mentions(message):
        normalized = mention.lower()
        if not normalized.endswith("bot") or normalized == self_username:
            continue
        if normalized not in targets:
            targets.append(normalized)
    return targets


def build_group_delegation_ack_text(target_mentions: List[str]) -> str:
    rendered = "、".join(f"@{mention}" for mention in target_mentions)
    if len(target_mentions) == 1:
        return (
            f"收到，这条我先接住。"
            f"我会先把相关脚本和数据链路整理后交给 {rendered} 协助处理，"
            "等他回我结果后我再统一向你汇报。"
        )
    return f"收到，这条我先接住。我会先协调 {rendered} 协助处理，等结果回来后我再统一向你汇报。"


def build_role_delegation_ack_text(target_roles: List[str]) -> str:
    rendered = "、".join(resolve_role_display_name(role) for role in target_roles)
    if len(target_roles) == 1:
        return (
            "收到，这条我先接住。"
            f"按当前群职责，这部分我会交给 {rendered} 继续处理，"
            "等他回我结果后我再统一向你汇报。"
        )
    return f"收到，这条我先接住。按当前群职责，这部分我会协调 {rendered} 继续处理，等结果回来后我再统一向你汇报。"


def build_openclaw_task_breakdown(text: str, target_roles: Optional[List[str]] = None) -> List[Dict[str, str]]:
    route = classify_task(text)
    lowered = text.lower()
    preferred_roles = [role for role in (target_roles or []) if role in {"codex", "claude", "gemini"}]
    if not preferred_roles:
        preferred_roles = [
            role
            for role in route.get("allowed_agents", [])
            if str(role) in {"codex", "claude", "gemini"}
        ]
    preferred_roles = [str(role) for role in preferred_roles]

    needs_summary = any(
        keyword in lowered
        for keyword in (
            "汇报",
            "总结",
            "报告",
            "整理",
            "分析",
            "结论",
            "晨报",
            "日报",
            "市场情况",
            "跟踪",
        )
    )
    needs_research = any(
        keyword in lowered
        for keyword in (
            "资料",
            "情报",
            "搜索",
            "搜集",
            "翻译",
            "润色",
            "数据",
        )
    )

    steps: List[Dict[str, str]] = []
    seen_roles: set[str] = set()
    can_use_gemini = "gemini" in preferred_roles or is_agent_service_online("gemini")

    def add_step(role: str, title: str, goal: str) -> None:
        normalized_role = str(role)
        if normalized_role in seen_roles:
            return
        seen_roles.add(normalized_role)
        steps.append(
            {
                "owner": normalized_role,
                "title": title,
                "goal": goal,
            }
        )

    docs_only = str(route.get("category", "")) == "docs"
    tech_role = next((role for role in preferred_roles if role in {"codex", "claude"}), "")
    if docs_only:
        if can_use_gemini or not preferred_roles:
            add_step(
                "gemini",
                "资料整理与分析",
                "围绕用户目标搜集资料、读取现成脚本或现有结果，并输出中文结论。",
            )
        return steps

    if tech_role:
        add_step(
            tech_role,
            "技术执行",
            "围绕用户需求完成开发、脚本、排障或配置落地，并给出路径状态与验证结果。",
        )

    if can_use_gemini and (needs_summary or needs_research or tech_role):
        add_step(
            "gemini",
            "结果整理与中文汇报",
            "基于执行结果整理资料、分析数据，并输出适合群聊查看的中文结论。",
        )

    if not steps:
        fallback_role = preferred_roles[0] if preferred_roles else "gemini"
        fallback_title = "资料整理与分析" if fallback_role == "gemini" else "技术执行"
        fallback_goal = (
            "围绕用户目标搜集资料、读取现成脚本或现有结果，并输出中文结论。"
            if fallback_role == "gemini"
            else "围绕用户需求完成开发、脚本、排障或配置落地，并给出路径状态与验证结果。"
        )
        add_step(fallback_role, fallback_title, fallback_goal)

    return steps


def render_openclaw_task_breakdown(breakdown: List[Dict[str, str]]) -> str:
    if not breakdown:
        return ""
    lines = ["拆分计划："]
    for idx, step in enumerate(breakdown, start=1):
        owner = resolve_role_display_name(str(step.get("owner", "")))
        title = str(step.get("title", "")).strip() or "任务执行"
        goal = str(step.get("goal", "")).strip() or "按职责继续处理。"
        lines.append(f"{idx}. {owner}：{title} - {goal}")
    return "\n".join(lines)


def build_openclaw_dispatch_ack_text(text: str, target_roles: List[str]) -> str:
    breakdown = build_openclaw_task_breakdown(text, target_roles)
    breakdown_text = render_openclaw_task_breakdown(breakdown)
    if not breakdown_text:
        return "收到，我先拆一下这条任务，然后按职责继续分派。"
    return (
        "收到，我先拆一下这条任务。\n"
        f"{breakdown_text}\n"
        "接下来：我会按这个拆分继续分派，并把关键进展写回 OpenClaw 记忆。"
    )


def inject_openclaw_breakdown_into_payload(payload: str, text: str, target_roles: List[str]) -> str:
    breakdown = build_openclaw_task_breakdown(text, target_roles)
    breakdown_text = render_openclaw_task_breakdown(breakdown)
    if not breakdown_text:
        return payload
    return (
        f"{payload}\n\n"
        "OpenClaw 拆分结果：\n"
        f"{breakdown_text}\n"
        "请优先按这个拆分理解当前任务；如果你只负责其中一段，就聚焦自己负责的那一步。"
    )


def parse_openclaw_breakdown_steps(payload: str) -> List[Dict[str, str]]:
    marker = "OpenClaw 拆分结果："
    if marker not in payload:
        return []
    block = payload.split(marker, 1)[1]
    steps: List[Dict[str, str]] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        match = re.match(r"^\d+\.\s+([^：:]+)[：:]\s*([^-]+?)\s*-\s*(.+)$", line)
        if not match:
            continue
        owner_name = match.group(1).strip().lower()
        title = match.group(2).strip()
        goal = match.group(3).strip()
        owner_role = {
            "openclaw": "openclaw",
            "codex": "codex",
            "gemini": "gemini",
            "claude code": "claude",
            "claude": "claude",
        }.get(owner_name)
        if not owner_role:
            continue
        steps.append({"owner": owner_role, "title": title, "goal": goal})
    return steps


def resolve_openclaw_followup_roles_from_payload(payload: str, current_role: str) -> List[str]:
    steps = parse_openclaw_breakdown_steps(payload)
    if not steps:
        return []
    try:
        current_index = next(idx for idx, step in enumerate(steps) if step.get("owner") == current_role)
    except StopIteration:
        return []
    roles: List[str] = []
    for step in steps[current_index + 1 :]:
        role = str(step.get("owner", ""))
        if role and role not in roles and is_agent_service_online(role):
            roles.append(role)
    return roles


def build_openclaw_step_status_text(payload: str, current_role: str, current_state: str) -> str:
    steps = parse_openclaw_breakdown_steps(payload)
    if not steps:
        return ""
    try:
        current_index = next(idx for idx, step in enumerate(steps) if step.get("owner") == current_role)
    except StopIteration:
        current_index = -1
    lines = ["步骤状态："]
    for idx, step in enumerate(steps):
        role = str(step.get("owner", ""))
        title = str(step.get("title", "")).strip() or "任务执行"
        display = resolve_role_display_name(role)
        if idx < current_index:
            status = "已完成"
        elif idx == current_index and current_index >= 0:
            status = current_state
        else:
            status = "待开始"
        lines.append(f"- {display} | {title} | {status}")
    return "\n".join(lines)


def build_openclaw_followup_payload(
    payload: str,
    *,
    current_role: str,
    next_role: str,
    original_user_text: str,
    worker_result: str,
) -> str:
    steps = parse_openclaw_breakdown_steps(payload)
    step_lookup = {str(step.get("owner", "")): step for step in steps}
    next_roles_after_current = resolve_openclaw_followup_roles_from_payload(payload, next_role)
    is_final_step = not next_roles_after_current
    current_display = resolve_role_display_name(current_role)
    next_display = resolve_role_display_name(next_role)
    next_step = step_lookup.get(next_role, {})
    next_title = str(next_step.get("title", "")).strip() or "结果整理与汇报"
    next_goal = str(next_step.get("goal", "")).strip() or "基于前序结果继续完成当前步骤。"
    breakdown_text = render_openclaw_task_breakdown(steps) if steps else ""
    payload_text = (
        "来自 Telegram 群聊中 openclaw 的拆分后续步骤。\n"
        f"OpenClaw 步骤模式：{'FINAL_SUMMARY' if is_final_step else 'FOLLOWUP'}\n"
        f"原始用户消息：{original_user_text}\n"
        f"上一位执行者：{current_display}\n"
        f"当前需要你接手的角色：{next_display}\n"
        f"当前步骤：{next_title}\n"
        f"目标：{next_goal}\n"
        f"上一阶段结果：{summarize_text(worker_result, limit=1600)}\n"
    )
    if breakdown_text:
        payload_text += f"\nOpenClaw 拆分结果：\n{breakdown_text}\n"
    if is_final_step:
        payload_text += (
            "\n这是 OpenClaw 拆分中的最后一步。"
            "请直接基于上一阶段结果完成中文汇总并面向群聊回复，"
            "不要继续委派给其他 bot，除非用户在后续新消息里明确要求。"
            "不要解释内部任务系统，不要暴露思考过程。"
        )
    else:
        payload_text += (
            "\n请只完成你当前负责的这一步，并直接给出适合群聊发送的最终中文结果。"
            "不要解释内部任务系统，不要暴露思考过程。"
        )
    return payload_text


def create_openclaw_followup_tasks_from_payload(
    registry: TaskRegistry,
    *,
    payload: str,
    current_role: str,
    chat_id: str,
    source_user_id: str,
    original_user_text: str,
    worker_result: str,
) -> List[tuple[str, int]]:
    next_roles = resolve_openclaw_followup_roles_from_payload(payload, current_role)
    created: List[tuple[str, int]] = []
    for next_role in next_roles[:1]:
        task_id = registry.create_task(
            source_chat_id=chat_id,
            source_message_id="",
            source_user_id=source_user_id,
            source_text=build_openclaw_followup_payload(
                payload,
                current_role=current_role,
                next_role=next_role,
                original_user_text=original_user_text,
                worker_result=worker_result,
            ),
            category="bot-handoff",
            route_reason=f"user-delegation:openclaw->{next_role}",
            allowed_agents=[next_role],
        )
        created.append((next_role, task_id))
    return created


def should_bypass_openclaw_return_task(source_role: str, target_role: str) -> bool:
    return source_role == "openclaw" and target_role == BOT_ROLE


def is_openclaw_final_summary_payload(payload: str) -> bool:
    return "OpenClaw 步骤模式：FINAL_SUMMARY" in payload


def resolve_openclaw_followup_roles(
    memory_store: ConversationMemoryStore,
    *,
    chat_id: str,
    user_text: str,
    reply_text: str,
) -> List[str]:
    explicit_targets = [
        role
        for role in extract_handoff_targets(reply_text, BOT_ROLE)
        if role in {"codex", "claude"} and is_agent_service_online(role)
    ]
    if explicit_targets:
        return explicit_targets

    auto_roles = resolve_technical_auto_delegation_roles(
        memory_store,
        chat_id=chat_id,
        text=user_text,
    )
    deduped: List[str] = []
    for role in auto_roles:
        if role not in {"codex", "claude"}:
            continue
        if role not in deduped:
            deduped.append(role)
    return deduped


def build_history_transcript(history: List[Dict[str, str]], limit: int = 8) -> str:
    transcript: List[str] = []
    for item in history[-limit:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        transcript.append(f"[{role}]\n{summarize_text(item['content'], limit=240)}")
    return "\n\n".join(transcript)


def parse_route_pair(route_reason: str, prefix: str) -> tuple[str, str]:
    if not route_reason.startswith(prefix):
        return "", ""
    payload = route_reason[len(prefix):]
    if "->" not in payload:
        return "", ""
    left, right = payload.split("->", 1)
    return left.strip().lower(), right.strip().lower()


def extract_original_user_text(payload: str) -> str:
    for line in payload.splitlines():
        if line.startswith("原始用户消息："):
            return line.split("：", 1)[1].strip()
    return summarize_text(payload, limit=180)


def build_delegation_return_payload(
    requester_role: str,
    worker_role: str,
    original_user_text: str,
    worker_result: str,
) -> str:
    return (
        f"你现在作为 Telegram 群里的 {requester_role}，需要向用户做最终汇报。\n"
        f"用户最初的要求：{original_user_text}\n"
        f"{worker_role} 的处理结果：{summarize_text(worker_result, limit=1200)}\n\n"
        "请直接用中文面向用户回复，说明对方已经协助完成了什么、当前最新情况是什么、还有没有剩余问题。"
        "默认使用简体中文，不要夹带英文结论句；专有名词、路径、仓库名、代币代码可保留原文。"
        "请保留“路径状态”小节，逐条列出每个已检查路径及其状态。"
        "如果当前没有拿到明确路径，也要明确写“暂未返回明确路径”。"
        "不要解释内部任务系统。"
        "不要写思考过程，不要写 I will、我将、接下来、先去、正在、准备。"
        "如果协作结果是超时或失败，就直接如实说明当前还没修好，并给出下一步最小行动。"
        "建议格式：结论：...\\n路径状态：\\n- <路径> | <状态> | <说明>\\n下一步：..."
        "只输出最终要发到群里的成品回复。"
    )


def resolve_role_display_name(role: str) -> str:
    mapping = {
        "openclaw": "OpenClaw",
        "codex": "Codex",
        "claude": "Claude Code",
        "gemini": "Gemini",
    }
    return mapping.get(role.lower(), role or "协作 bot")


def extract_worker_result(payload: str, worker_role: str) -> str:
    prefix = f"{worker_role} 的处理结果："
    for line in payload.splitlines():
        if line.startswith(prefix):
            return line.split("：", 1)[1].strip()
    return ""


def extract_path_status_lines(text: str) -> List[str]:
    candidates: List[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = line.lstrip("-*• ").strip()
        if not normalized:
            continue
        if not (
            "/" in normalized
            or re.search(r"\b[\w./-]+\.(py|sh|ts|js|jsx|tsx|json|md|yaml|yml|toml)\b", normalized)
        ):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(f"- {summarize_text(normalized, limit=220)}")
    return candidates[:8]


def looks_like_planning_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    first_line = stripped.splitlines()[0].strip()
    first_lower = first_line.lower()
    english_prefixes = (
        "i will",
        "i'll",
        "let me",
        "i am going to",
        "i need to",
        "i should",
        "i can",
    )
    chinese_prefixes = (
        "我将",
        "接下来",
        "我会先",
        "我先",
        "先去",
        "正在",
        "准备",
        "先看",
        "先检查",
        "先确认",
    )
    return first_lower.startswith(english_prefixes) or first_line.startswith(chinese_prefixes)


def line_looks_like_meta_reply(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    english_prefixes = (
        "i will",
        "i'll",
        "let me",
        "here's my plan",
        "plan:",
        "thinking:",
        "analysis:",
        "first,",
    )
    chinese_prefixes = (
        "我将",
        "接下来",
        "我会先",
        "我先",
        "先去",
        "正在",
        "准备",
        "思路",
        "思路：",
        "分析：",
        "计划：",
        "让我先",
        "我来先",
    )
    return lowered.startswith(english_prefixes) or stripped.startswith(chinese_prefixes)


def compact_casual_reply(text: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return cleaned
    parts = re.split(r"(?<=[。！？!?])\s*", cleaned)
    kept: List[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        kept.append(part)
        preview = "".join(kept)
        if len(kept) >= 2 or len(preview) >= limit:
            break
    result = "".join(kept) if kept else cleaned
    return summarize_text(result, limit=limit)


def normalize_direct_group_reply_output(
    result_text: str,
    *,
    message_semantics: str,
) -> str:
    cleaned = (result_text or "").strip()
    if not cleaned:
        return cleaned

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    while lines and line_looks_like_meta_reply(lines[0]):
        lines.pop(0)
    cleaned = "\n".join(lines).strip() or cleaned

    if message_semantics == "casual":
        cjk_lines = [line for line in cleaned.splitlines() if contains_cjk(line)]
        if cjk_lines:
            cleaned = "\n".join(cjk_lines).strip()
        if looks_like_planning_text(cleaned):
            cleaned = "在呢，我刚刚在想怎么接你的话。你继续说，我接着聊。"
        cleaned = compact_casual_reply(cleaned, limit=120)

    return cleaned[:4000]


def build_delegation_return_fallback(worker_role: str, worker_result: str) -> str:
    worker_display = resolve_role_display_name(worker_role)
    normalized = summarize_text(worker_result, limit=1200)
    path_lines = extract_path_status_lines(worker_result)
    path_block = "\n".join(path_lines) if path_lines else "- 暂未返回明确路径"
    failure_markers = ("超时", "失败", "报错", "异常", "未完成", "还没", "没有", "未能")
    if any(marker in worker_result for marker in failure_markers):
        return (
            f"我先同步一下最新情况：{worker_display} 这次已经介入协助，但当前还没有完全收口。"
            f"目前结果是：{normalized}\n\n"
            f"路径状态：\n{path_block}\n\n"
            "下一步：这项检查现在还没完全修好；我会继续让他先核对数据源和脚本入口，再尽快给你准确结论。"
        )[:4000]
    return (
        f"我先同步一下最新情况：{worker_display} 已经协助完成这轮检查。"
        f"当前结论是：{normalized}\n\n"
        f"路径状态：\n{path_block}"
    )[:4000]


def normalize_delegation_return_output(result_text: str, payload: str, route_reason: str) -> str:
    cleaned = result_text.strip()
    worker_role, _requester_role = parse_route_pair(route_reason, "delegation-return:")
    if not looks_like_planning_text(cleaned):
        return cleaned[:4000]
    worker_result = extract_worker_result(payload, worker_role) or cleaned
    logging.info(
        "Normalizing delegation-return output role=%s route=%s because runner returned planning text",
        BOT_ROLE,
        route_reason,
    )
    return build_delegation_return_fallback(worker_role, worker_result)


def create_delegation_return_task(
    registry: TaskRegistry,
    *,
    requester_role: str,
    worker_role: str,
    chat_id: str,
    source_user_id: str,
    original_user_text: str,
    worker_result: str,
) -> int:
    return registry.create_task(
        source_chat_id=chat_id,
        source_message_id="",
        source_user_id=source_user_id,
        source_text=build_delegation_return_payload(
            requester_role,
            worker_role,
            original_user_text,
            worker_result,
        ),
        category=DELEGATION_RETURN_CATEGORY,
        route_reason=f"delegation-return:{worker_role}->{requester_role}",
        allowed_agents=[requester_role],
    )


def create_user_delegation_tasks(
    registry: TaskRegistry,
    *,
    source_role: str,
    chat_id: str,
    source_message_id: str,
    source_user_id: str,
    user_text: str,
    history: List[Dict[str, str]],
    target_mentions: List[str],
) -> List[tuple[str, int]]:
    route = classify_task(user_text)
    explicit_target_roles = [
        role
        for role in (resolve_agent_role_from_mention(target) for target in target_mentions)
        if role
    ]
    recent_user_notes: List[str] = []
    seen_notes: set[str] = set()
    for item in history[-6:]:
        if item.get("role") == "assistant":
            continue
        note = summarize_text(item["content"], limit=140)
        if note in seen_notes:
            continue
        seen_notes.add(note)
        recent_user_notes.append(note)
    context_note = "\n".join(f"- {note}" for note in recent_user_notes[-2:])
    lowered_text = user_text.lower()
    fast_path_hints: List[str] = []
    if any(keyword in user_text for keyword in ("最新市场数据", "市场数据", "实时价格")):
        fast_path_hints.extend(
            [
                str(OPENCLAW_WORKSPACE_DIR / "trading-dashboard" / "server.js"),
                str(OPENCLAW_WORKSPACE_DIR / "trading-dashboard" / "trades.json"),
                str(OPENCLAW_WORKSPACE_DIR / "btc-scalp-sim" / "market.py"),
            ]
        )
    if any(keyword in lowered_text for keyword in ("daily-crypto", "github report", "异动")):
        fast_path_hints.append(str(OPENCLAW_WORKSPACE_DIR / "scripts" / "daily-crypto-github-report.sh"))
    if any(keyword in lowered_text for keyword in ("github", "推特", "twitter", "x", "币安", "binance", "9点", "准时", "定时", "汇报")):
        fast_path_hints.extend(
            [
                str(OPENCLAW_WORKSPACE_DIR / "scripts" / "daily_crypto_report.py"),
                str(OPENCLAW_WORKSPACE_DIR / "scripts" / "binance_monitor.py"),
                str(OPENCLAW_WORKSPACE_DIR / "cron" / "jobs.json"),
            ]
        )
    deduped_hints: List[str] = []
    for hint in fast_path_hints:
        if hint not in deduped_hints:
            deduped_hints.append(hint)
    created: List[tuple[str, int]] = []
    for target_mention in target_mentions:
        target_role = resolve_agent_role_from_mention(target_mention)
        if not target_role or target_role == source_role:
            continue
        is_review_request = any(
            keyword in lowered_text
            for keyword in (
                "审核",
                "review",
                "检查",
                "排查",
                "确认",
                "看一下",
                "核对",
                "审计",
            )
        )
        is_implementation_request = (
            str(route.get("category", "")) == "coding"
            and not is_review_request
        ) or any(
            keyword in lowered_text
            for keyword in (
                "实现",
                "开发",
                "搭建",
                "新增",
                "增加",
                "创建",
                "重写",
                "改造",
                "接入",
                "部署",
                "定时",
                "监测",
                "监控",
                "实时",
                "异动",
                "抓取",
                "采集",
                "汇报",
                "自动化",
            )
        )
        implementation_subtasks: List[Dict[str, Any]] = []
        if is_implementation_request and target_role in {"codex", "claude"}:
            implementation_subtasks = build_implementation_subtasks(
                lowered_text=lowered_text,
                user_text=user_text,
            )
        if implementation_subtasks:
            for spec in implementation_subtasks:
                payload = (
                    f"来自 Telegram 群聊中 {source_role} 的用户指定协作请求。\n"
                    f"原始用户消息：{user_text}\n"
                    f"主责 bot：{source_role}\n"
                    f"协作目标：{target_role}\n"
                    f"子任务：{spec['title']}\n"
                    f"目标：{spec['goal']}\n"
                    "请直接在工作区落地这个子任务，不要只做审计或给建议。\n"
                    "请优先用 rg / rg --files 快速定位相关文件，不要做长时间全盘发散搜索。\n"
                    "请按固定格式返回：结论、路径状态、已完成变更、验证、下一步。\n"
                    "路径状态里至少逐条列出本轮检查过或修改过的每个路径，例如：- /path/file.py | 已修改/已检查/未找到/待复核 | 说明。\n"
                    "已完成变更里请明确写出新增或修改了哪些文件。\n"
                )
                if spec["paths"]:
                    payload += "优先处理这些目标路径：\n"
                    payload += "\n".join(f"- {path}" for path in spec["paths"]) + "\n"
                if spec.get("validation"):
                    payload += f"建议验证：{spec['validation']}\n"
                if context_note:
                    payload += f"\n最近用户补充：\n{context_note}\n"
                if source_role == "openclaw":
                    payload = inject_openclaw_breakdown_into_payload(payload, user_text, explicit_target_roles)
                payload += (
                    "\n最终过程反馈和结果汇报一律使用简体中文；专有名词、路径、仓库名、代币代码可保留原文。"
                    "\n请从对应职责出发直接接手。"
                    "如果关键文件不存在，就基于现有目录补齐最小可运行实现；如果当前轮还不能完全收口，也要先提交最小可运行骨架，并明确剩余阻塞。"
                    "不要长篇复述群聊。"
                )
                task_id = registry.create_task(
                    source_chat_id=chat_id,
                    source_message_id=source_message_id,
                    source_user_id=source_user_id,
                    source_text=payload,
                    category="bot-handoff",
                    route_reason=f"user-delegation:{source_role}->{target_role}",
                    allowed_agents=[target_role],
                )
                created.append((target_role, task_id))
            continue
        payload = (
            f"来自 Telegram 群聊中 {source_role} 的用户指定协作请求。\n"
            f"原始用户消息：{user_text}\n"
            f"主责 bot：{source_role}\n"
            f"协作目标：{target_role}\n"
        )
        if is_implementation_request and target_role in {"codex", "claude"}:
            payload += (
                "目标：根据用户这条最新需求直接落地开发/改造，不要只做审计或给建议。\n"
                "如果需要新增或修改脚本、配置、调度任务，请直接在工作区实现最小可运行版本。\n"
                "请优先自己在工作目录内定位现有脚本/仓库；如果关键文件不存在，就基于现有目录补齐实现。\n"
                "请优先用 rg / rg --files 快速定位文件，不要做长时间全盘发散搜索。\n"
                "请按固定格式返回：结论、路径状态、已完成变更、验证、下一步。\n"
                "路径状态里至少逐条列出本轮检查过或修改过的每个路径，例如：- /path/file.py | 已修改/已检查/未找到/待复核 | 说明。\n"
                "已完成变更里请明确写出新增或修改了哪些文件。\n"
            )
        else:
            payload += (
                "目标：检查相关代码或脚本，确认当前实现是否满足用户要求，并给出最小修复建议。\n"
                "请优先自己在工作目录内定位相关脚本/仓库，不要等待别人继续补充路径。\n"
                "请优先用 rg / rg --files 快速定位文件，不要做长时间全盘发散搜索。\n"
                "请按固定格式返回：结论、路径状态、下一步。\n"
                "路径状态里至少逐条列出本轮检查过的每个路径，例如：- /path/file.py | 已检查/未找到/待复核 | 说明。\n"
            )
        if deduped_hints:
            payload += "优先检查这些高相关路径；如果前 2-3 个路径已经足以确认问题，就不要继续扩展搜索：\n"
            payload += "\n".join(f"- {path}" for path in deduped_hints[:4]) + "\n"
        if context_note:
            payload += f"\n最近用户补充：\n{context_note}\n"
        if source_role == "openclaw":
            payload = inject_openclaw_breakdown_into_payload(payload, user_text, explicit_target_roles)
        if is_implementation_request and target_role in {"codex", "claude"}:
            payload += (
                "\n最终过程反馈和结果汇报一律使用简体中文；专有名词、路径、仓库名、代币代码可保留原文。"
                "\n请从对应职责出发直接接手。"
                "这轮目标是先把能落地的核心链路做出来；如果暂时不能完全收口，也要先提交最小可运行骨架，并明确剩余阻塞。"
                "不要只停在方案或审计结论，也不要长篇复述群聊。"
            )
        else:
            payload += (
                "\n最终过程反馈和结果汇报一律使用简体中文；专有名词、路径、仓库名、代币代码可保留原文。"
                "\n请从对应职责出发直接接手。"
                "如果在当前轮还不能完全收口，请优先返回：已检查的路径、确认到的问题点、以及下一步最小修复。"
                "不要做无边界探索，也不要长篇复述群聊。"
        )
        task_id = registry.create_task(
            source_chat_id=chat_id,
            source_message_id=source_message_id,
            source_user_id=source_user_id,
            source_text=payload,
            category="bot-handoff",
            route_reason=f"user-delegation:{source_role}->{target_role}",
            allowed_agents=[target_role],
        )
        created.append((target_role, task_id))
    return created


def build_implementation_subtasks(
    *,
    lowered_text: str,
    user_text: str,
) -> List[Dict[str, Any]]:
    subtasks: List[Dict[str, Any]] = []
    has_x_topic = any(keyword in lowered_text for keyword in ("推特", "twitter", "x 情报", "x情报", "x 热门", "x热门", "x 动态", "x动态"))
    has_report_topic = any(keyword in lowered_text for keyword in ("github", "日报", "汇报")) or has_x_topic
    has_monitor_topic = any(keyword in lowered_text for keyword in ("币安", "binance", "监测", "监控", "实时", "异动", "合约", "网络", "连不上", "超时", "接口"))

    if has_report_topic:
        subtasks.append(
            {
                "title": "日报脚本",
                "goal": (
                    "重写或完善每日加密日报脚本，覆盖推特/加密圈信息、GitHub 当日热门开源项目 Top 10、以及市场摘要输出，"
                    "并确保输出结构适合每日早上 9 点汇报。"
                ),
                "paths": [
                    str(OPENCLAW_WORKSPACE_DIR / "scripts" / "daily_crypto_report.py"),
                ],
                "validation": (
                    f"python3 {OPENCLAW_WORKSPACE_DIR / 'scripts' / 'daily_crypto_report.py'} "
                    "--date 2026-03-23 --output-dir /tmp/daily-crypto-smoke"
                ),
            }
        )
    if has_monitor_topic:
        monitor_title = "币安异动监控脚本"
        monitor_goal = (
            "新增或完善币安异动监控脚本，至少支持全 USDT 交易对扫描，能够输出当天突然异动的币种，"
            "并移除 mock 数据回退。"
        )
        if any(keyword in lowered_text for keyword in ("网络", "连不上", "超时", "接口")):
            monitor_title = "实时合约监控脚本网络问题"
            monitor_goal = (
                "排查并修复实时合约监控脚本的网络问题，优先检查行情接口连通性、超时、重试、代理/证书、"
                "以及请求失败后的降级逻辑，确保脚本能稳定拉到实时行情。"
            )
        subtasks.append(
            {
                "title": monitor_title,
                "goal": monitor_goal,
                "paths": [
                    str(OPENCLAW_WORKSPACE_DIR / "scripts" / "binance_monitor.py"),
                ],
                "validation": (
                    f"python3 {OPENCLAW_WORKSPACE_DIR / 'scripts' / 'binance_monitor.py'} --once"
                ),
            }
        )
    if any(keyword in lowered_text for keyword in ("9点", "准时", "定时", "cron", "每天", "每日")):
        subtasks.append(
            {
                "title": "调度配置",
                "goal": (
                    "更新调度配置，确保每日 9:00 汇报任务正确指向日报脚本；如果实时监控需要单独轮询或守护进程，"
                    "请补齐最小可运行配置或明确待手动部署项。"
                ),
                "paths": [
                    str(OPENCLAW_WORKSPACE_DIR / "cron" / "jobs.json"),
                ],
                "validation": (
                    "python3 - <<'PY'\n"
                    "import json\n"
                    f"print(json.load(open('{OPENCLAW_WORKSPACE_DIR / 'cron' / 'jobs.json'}')))\n"
                    "PY"
                ),
            }
        )
    if not subtasks:
        return []
    deduped: List[Dict[str, Any]] = []
    seen_titles: set[str] = set()
    for spec in subtasks:
        title = str(spec["title"])
        if title in seen_titles:
            continue
        seen_titles.add(title)
        deduped.append(spec)
    return deduped


def create_user_delegation_tasks_for_roles(
    registry: TaskRegistry,
    *,
    source_role: str,
    chat_id: str,
    source_message_id: str,
    source_user_id: str,
    user_text: str,
    history: List[Dict[str, str]],
    target_roles: List[str],
) -> List[tuple[str, int]]:
    target_mentions = [f"{role}bot" for role in target_roles]
    return create_user_delegation_tasks(
        registry,
        source_role=source_role,
        chat_id=chat_id,
        source_message_id=source_message_id,
        source_user_id=source_user_id,
        user_text=user_text,
        history=history,
        target_mentions=target_mentions,
    )


def resolve_technical_auto_delegation_roles(
    memory_store: ConversationMemoryStore,
    *,
    chat_id: str,
    text: str,
) -> List[str]:
    route = classify_task(text)
    route_reason = str(route.get("route_reason", ""))
    if route_reason == "defaulted to coding pair for ambiguous task":
        return []

    allowed_agents = [str(agent) for agent in route.get("allowed_agents", [])]
    if BOT_ROLE in allowed_agents:
        return []

    if BOT_ROLE == "openclaw":
        dispatchable_agents = [agent for agent in allowed_agents if agent in {"codex", "claude", "gemini"}]
        if not dispatchable_agents:
            return []
        profiled_agents = [agent for agent in dispatchable_agents if memory_store.get_chat_profile(agent, chat_id)]
        candidates = profiled_agents or dispatchable_agents
        available_candidates = [agent for agent in candidates if is_agent_service_online(agent)]
        if available_candidates:
            return available_candidates[:1]
        available_dispatchable_agents = [agent for agent in dispatchable_agents if is_agent_service_online(agent)]
        if available_dispatchable_agents:
            return available_dispatchable_agents[:1]
        return []

    technical_agents = [agent for agent in allowed_agents if agent in {"codex", "claude"}]
    if not technical_agents:
        return []

    profiled_agents = [agent for agent in technical_agents if memory_store.get_chat_profile(agent, chat_id)]
    candidates = profiled_agents or technical_agents
    available_candidates = [agent for agent in candidates if is_agent_service_online(agent)]
    if available_candidates:
        return available_candidates[:1]
    available_technical_agents = [agent for agent in technical_agents if is_agent_service_online(agent)]
    if available_technical_agents:
        return available_technical_agents[:1]
    return []


def is_agent_service_online(agent_name: str) -> bool:
    labels = AGENT_SERVICE_LABELS.get(agent_name, [])
    if not labels:
        return True
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return True
    output = result.stdout or ""
    return any(label in output for label in labels)


def should_handle_group_message_for_bot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[bool, bool]:
    message = update.effective_message
    mentions = extract_message_mentions(message)
    bot_mentions = {mention for mention in mentions if mention.endswith("bot")}
    if not bot_mentions:
        return True, False

    self_username = (
        (getattr(context.bot, "username", None) or "")
        .strip()
        .lower()
        .lstrip("@")
    )
    self_mentioned = bool(self_username and self_username in bot_mentions)
    if not self_mentioned:
        logging.info(
            "Ignoring group message for other bots role=%s chat_id=%s self=%s mentioned=%s",
            BOT_ROLE,
            getattr(update.effective_chat, "id", None),
            self_username or "-",
            ",".join(sorted(bot_mentions)),
        )
        return False, False
    primary_mention = resolve_primary_group_bot_mention(message)
    if primary_mention and self_username != primary_mention:
        logging.info(
            "Ignoring delegated secondary mention role=%s chat_id=%s self=%s primary=%s mentioned=%s",
            BOT_ROLE,
            getattr(update.effective_chat, "id", None),
            self_username or "-",
            primary_mention,
            ",".join(sorted(bot_mentions)),
        )
        return False, False
    return True, True


def is_group_role_assignment(text: str, mentioned_self: bool = False) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return bool(mentioned_self and any(keyword in lowered for keyword in ROLE_ASSIGNMENT_KEYWORDS))


def build_group_role_note(text: str) -> str:
    cleaned = re.sub(r"@([A-Za-z0-9_]{5,})", "", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:1000]


def resolve_agent_role_from_mention(mention: str) -> str:
    lowered = mention.lower()
    if "codex" in lowered:
        return "codex"
    if "gemini" in lowered:
        return "gemini"
    if "claude" in lowered:
        return "claude"
    return ""


def extract_handoff_targets(text: str, source_role: str) -> List[str]:
    lowered = text.strip().lower()
    if not lowered or not any(keyword in lowered for keyword in HANDOFF_KEYWORDS):
        return []
    targets: List[str] = []
    for mention in sorted(set(re.findall(r"@([A-Za-z0-9_]{5,})", text))):
        role = resolve_agent_role_from_mention(mention)
        if role and role != source_role and role not in targets:
            targets.append(role)
    return targets


def build_handoff_payload(source_role: str, user_text: str, reply_text: str) -> str:
    return (
        f"来自 Telegram 群聊中 {source_role} 的协作请求。\n"
        f"原始用户消息：{user_text}\n"
        f"{source_role} 的说明：{reply_text}\n"
        "请直接接手并在群里反馈结果。"
    )


def enqueue_handoff_tasks(
    registry: TaskRegistry,
    *,
    chat_id: str,
    source_message_id: str,
    source_user_id: str,
    source_role: str,
    user_text: str,
    reply_text: str,
) -> List[tuple[str, int]]:
    created: List[tuple[str, int]] = []
    for target_role in extract_handoff_targets(reply_text, source_role):
        task_id = registry.create_task(
            source_chat_id=chat_id,
            source_message_id=source_message_id,
            source_user_id=source_user_id,
            source_text=build_handoff_payload(source_role, user_text, reply_text),
            category="bot-handoff",
            route_reason=f"bot-handoff:{source_role}->{target_role}",
            allowed_agents=[target_role],
        )
        created.append((target_role, task_id))
    return created


def is_group_reply_fallback_error(exc: BadRequest) -> bool:
    message = str(exc).lower()
    return (
        "topic_closed" in message
        or "message to be replied not found" in message
        or "message thread not found" in message
    )


async def send_text_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    text = text[:4000]
    if not is_group_like_chat(getattr(chat, "type", None)):
        await message.reply_text(text, reply_markup=reply_markup)
        return

    thread_id = getattr(message, "message_thread_id", None)
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=thread_id,
        )
        return
    except BadRequest as exc:
        if not is_group_reply_fallback_error(exc):
            raise
        logging.warning(
            "Falling back to root group send role=%s chat_id=%s thread_id=%s error=%s",
            BOT_ROLE,
            chat.id,
            thread_id,
            exc,
        )
    await context.bot.send_message(chat_id=chat.id, text=text, reply_markup=reply_markup)


def parse_json_output(raw: str) -> Dict[str, Any]:
    start = raw.find("{")
    if start == -1:
        raise ValueError("JSON payload not found")
    return json.loads(raw[start:])


def run_openclaw_json_status() -> Dict[str, Any]:
    result = subprocess.run(
        [OPENCLAW_BIN, "status", "--json"],
        cwd=WORKDIR,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    payload = f"{result.stdout}\n{result.stderr}".strip()
    return parse_json_output(payload)


def format_age_ms(age_ms: Optional[int]) -> str:
    if age_ms is None:
        return "unknown"
    seconds = max(0, int(age_ms / 1000))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def format_context_tokens(value: Optional[int]) -> str:
    if not value:
        return "unknown"
    if value >= 1_000_000:
        return f"{value // 1_000_000}M"
    if value >= 1000:
        return f"{value // 1000}k"
    return str(value)


def build_openclaw_status_text() -> str:
    status = run_openclaw_json_status()
    gateway = status.get("gateway", {})
    gateway_service = status.get("gatewayService", {})
    agents = status.get("agents", {})
    sessions = status.get("sessions", {})
    memory_plugin = status.get("memoryPlugin", {})
    security = status.get("securityAudit", {}).get("summary", {})

    default_agent_id = agents.get("defaultId", "main")
    default_agent = next(
        (agent for agent in agents.get("agents", []) if agent.get("id") == default_agent_id),
        None,
    )
    default_agent_age = format_age_ms(
        default_agent.get("lastActiveAgeMs") if default_agent else None
    )
    gateway_state = "reachable" if gateway.get("reachable") else f"unreachable ({gateway.get('error', 'unknown')})"
    memory_state = "enabled" if memory_plugin.get("enabled") else "disabled"
    memory_plugin_name = memory_plugin.get("slot") or "none"
    channel_summary = list(status.get("channelSummary") or [])
    channel_summary.append(f"Telegram: dispatcher ({PRIVATE_TASK_MODE}; group dispatch + memory only)")
    sessions_defaults = sessions.get("defaults", {})

    lines = [
        "OpenClaw status",
        "",
        "Overview",
        f"Dashboard: http://127.0.0.1:18789/",
        f"Gateway: {gateway.get('mode', 'unknown')} · {gateway.get('url', '-')} · {gateway_state}",
        "Gateway service: {} · {} · {}".format(
            gateway_service.get("label", "unknown"),
            gateway_service.get("loadedText", "unknown"),
            gateway_service.get("runtimeShort", "unknown"),
        ),
        "Agents: {} · sessions {} · default {} active {} ago".format(
            len(agents.get("agents", [])),
            agents.get("totalSessions", sessions.get("count", 0)),
            default_agent_id,
            default_agent_age,
        ),
        "Memory: {} (plugin {}) · shared daily {} · long-term {}".format(
            memory_state,
            memory_plugin_name,
            "on" if ENABLE_SHARED_MEMORY_LOG else "off",
            "on" if ALLOW_LONG_TERM_MEMORY_WRITE else "off",
        ),
        "Sessions: {} active · default {} ({} ctx)".format(
            sessions.get("count", 0),
            sessions_defaults.get("model", "unknown"),
            format_context_tokens(sessions_defaults.get("contextTokens")),
        ),
        f"Channels: {'; '.join(channel_summary) if channel_summary else 'none'}",
        "Security audit: {} critical · {} warn · {} info".format(
            security.get("critical", 0),
            security.get("warn", 0),
            security.get("info", 0),
        ),
        "",
        "Telegram",
        f"Private mode: {PRIVATE_TASK_MODE}",
        f"Group chat: {'on' if ALLOW_GROUP_CHAT else 'off'}",
        "Group role: dispatch + decomposition + status + memory only",
        "Group reporter: gemini",
        "Group direct execution: off",
        f"Private direct backend: {PRIVATE_DIRECT_RUNNER_BACKEND or 'openclaw_agent'}({PRIVATE_DIRECT_OPENCLAW_AGENT_ID or 'main'})",
        f"Dispatch backend: {RUNNER_BACKEND or '-'}",
        f"Group dispatch: /{TASK_COMMAND}",
    ]
    return "\n".join(lines)


def should_handle_private_direct(text: str) -> bool:
    clean = text.strip().lower()
    if not clean:
        return False
    direct_phrases = [
        "在吗",
        "你好",
        "hi",
        "hello",
        "刚刚我让你做什么了",
        "刚才我让你做什么了",
        "我刚才让你做什么了",
        "我刚刚让你做什么了",
        "继续刚才",
        "继续上一个",
        "上一条",
        "上一个任务",
        "你记得吗",
    ]
    if any(phrase in clean for phrase in direct_phrases):
        return True
    return len(clean) <= 8


def bot_supports_daily_digest_shortcut() -> bool:
    return BOT_ROLE in {"openclaw", "gemini"}


def classify_daily_digest_query(text: str) -> str:
    if not bot_supports_daily_digest_shortcut():
        return ""

    lowered = text.strip().lower()
    if not lowered:
        return ""

    implementation_keywords = [
        "脚本",
        "代码",
        "开发",
        "实现",
        "重写",
        "修改",
        "修复",
        "优化",
        "部署",
        "配置",
        "接入",
        "创建",
        "新建",
        "更新",
        "完善",
        "调度",
        "cron",
        "定时",
        "监控",
        "任务",
    ]
    if any(keyword in lowered for keyword in implementation_keywords):
        return ""

    binance_keywords = ["币安异动", "binance", "异动", "涨幅", "跌幅", "mover", "movers"]
    github_keywords = ["github", "热门仓库", "热门项目", "代码热门", "开源热门", "trending"]
    x_keywords = ["x情报", "x 情报", "x 热门", "x消息", "x 资讯", "推特", "twitter", "x动态", "x 动态", "社媒"]
    sentiment_keywords = ["市场情绪", "情绪", "fear", "greed", "恐慌", "贪婪"]
    full_report_keywords = [
        "长版报告",
        "长板报告",
        "完整报告",
        "完整日报",
        "完整晨报",
        "全文",
        "全部报告",
        "完整内容",
    ]
    report_keywords = [
        "晨报",
        "早报",
        "日报",
        "daily report",
        "crypto report",
        "morning report",
        "morning brief",
    ]
    query_keywords = [
        "今天",
        "今日",
        "最新",
        "发我",
        "给我",
        "看看",
        "看下",
        "来一份",
        "汇总",
        "总结",
    ]

    has_query_hint = any(keyword in lowered for keyword in query_keywords) or len(lowered) <= 16

    if any(keyword in lowered for keyword in full_report_keywords):
        return "markdown"
    if any(keyword in lowered for keyword in binance_keywords) and has_query_hint:
        return "binance"
    if any(keyword in lowered for keyword in github_keywords) and has_query_hint:
        return "github"
    if any(keyword in lowered for keyword in x_keywords) and has_query_hint:
        return "x"
    if any(keyword in lowered for keyword in sentiment_keywords) and has_query_hint:
        return "sentiment"

    if not any(keyword in lowered for keyword in report_keywords):
        return ""
    return "full" if has_query_hint else ""


def should_serve_daily_digest(
    text: str,
    *,
    chat_type: Optional[str] = None,
    mentioned_self: bool = False,
) -> bool:
    if not classify_daily_digest_query(text):
        return False
    if not is_group_like_chat(chat_type):
        return True
    if BOT_ROLE == "gemini":
        return True
    return False


def is_recent_memory_query(text: str) -> bool:
    lowered = " ".join(text.strip().lower().split())
    if not lowered:
        return False
    keywords = [
        "最近记忆",
        "记忆摘要",
        "最近摘要",
        "最近上下文",
        "最近发生了什么",
        "recent memory",
        "memory summary",
    ]
    return any(keyword in lowered for keyword in keywords)


def is_system_health_query(text: str) -> bool:
    lowered = " ".join(text.strip().lower().split())
    if not lowered:
        return False
    keywords = [
        "检查系统健康",
        "系统健康",
        "健康检查",
        "检查健康",
        "bot 在线吗",
        "bot在线吗",
        "telegram 断了吗",
        "telegram断了吗",
        "监控还在跑吗",
        "晨报调度正常吗",
        "system health",
        "health check",
    ]
    return any(keyword in lowered for keyword in keywords)


def is_system_health_query(text: str) -> bool:
    lowered = " ".join(text.strip().lower().split())
    if not lowered:
        return False
    keywords = [
        "检查系统健康",
        "系统健康",
        "健康检查",
        "检查健康",
        "bot 在线吗",
        "bot在线吗",
        "telegram 断了吗",
        "telegram断了吗",
        "监控还在跑吗",
        "晨报调度正常吗",
        "system health",
        "health check",
    ]
    return any(keyword in lowered for keyword in keywords)


def extract_memory_search_query(text: str) -> str:
    clean = " ".join(text.strip().split())
    if not clean:
        return ""
    patterns = [
        r"^/memory_search(?:@\w+)?\s+(.+)$",
        r"^搜索记忆[:：]?\s*(.+)$",
        r"^检索记忆[:：]?\s*(.+)$",
        r"^查记忆[:：]?\s*(.+)$",
        r"^memory search[:：]?\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def build_recent_memory_response(app: Application, chat_id: str) -> str:
    return render_recent_memory_digest(
        get_memory_store(app),
        bot_role=BOT_ROLE,
        chat_id=chat_id,
        own_limit=INSTANT_MEMORY_OWN_LIMIT,
        shared_limit=INSTANT_MEMORY_SHARED_LIMIT,
    )


def build_memory_search_response(app: Application, chat_id: str, query: str) -> str:
    return render_memory_search_digest(
        get_memory_store(app),
        bot_role=BOT_ROLE,
        chat_id=chat_id,
        query=query,
    )


def build_daily_digest_inline_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("查看长版", callback_data=f"{DAILY_REPORT_CALLBACK_PREFIX}markdown"),
                InlineKeyboardButton("晨报摘要", callback_data=f"{DAILY_REPORT_CALLBACK_PREFIX}full"),
            ],
            [
                InlineKeyboardButton("币安异动", callback_data=f"{DAILY_REPORT_CALLBACK_PREFIX}binance"),
                InlineKeyboardButton("GitHub 热门", callback_data=f"{DAILY_REPORT_CALLBACK_PREFIX}github"),
            ],
            [
                InlineKeyboardButton("X 情报", callback_data=f"{DAILY_REPORT_CALLBACK_PREFIX}x"),
                InlineKeyboardButton("市场情绪", callback_data=f"{DAILY_REPORT_CALLBACK_PREFIX}sentiment"),
            ],
        ]
    )


def split_telegram_text(text: str, limit: int = 3600) -> List[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= limit:
        return [cleaned]

    parts: List[str] = []
    chunk = ""
    for paragraph in cleaned.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = paragraph if not chunk else f"{chunk}\n\n{paragraph}"
        if len(candidate) <= limit:
            chunk = candidate
            continue
        if chunk:
            parts.append(chunk)
            chunk = ""
        if len(paragraph) <= limit:
            chunk = paragraph
            continue
        lines = paragraph.splitlines()
        line_chunk = ""
        for line in lines:
            candidate_line = line if not line_chunk else f"{line_chunk}\n{line}"
            if len(candidate_line) <= limit:
                line_chunk = candidate_line
                continue
            if line_chunk:
                parts.append(line_chunk)
            if len(line) <= limit:
                line_chunk = line
                continue
            for index in range(0, len(line), limit):
                parts.append(line[index : index + limit])
            line_chunk = ""
        if line_chunk:
            chunk = line_chunk
    if chunk:
        parts.append(chunk)
    return parts


def format_daily_digest_binance(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "今天的币安异动摘要还没生成。"
    lines = ["今日币安异动"]
    for item in items[:5]:
        symbol = str(item.get("symbol", "-"))
        move = item.get("price_change_percent")
        quote_volume = item.get("quote_volume")
        move_text = f"{float(move):+.2f}%" if isinstance(move, (int, float)) else str(move or "-")
        volume_text = f"{float(quote_volume) / 1_000_000:.2f}M" if isinstance(quote_volume, (int, float)) else "-"
        lines.append(f"- {symbol} | {move_text} | 成交额 {volume_text} USDT")
    return "\n".join(lines)


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text or "")


def choose_localized_text(*values: Any, fallback: str = "") -> str:
    normalized: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    for text in normalized:
        if contains_cjk(text):
            return text
    return normalized[0] if normalized else fallback


def translate_sentiment_label(label: str) -> str:
    lowered = (label or "").strip().lower()
    mapping = {
        "extreme fear": "极度恐慌",
        "fear": "恐慌",
        "neutral": "中性",
        "greed": "贪婪",
        "extreme greed": "极度贪婪",
    }
    return mapping.get(lowered, label or "-")


def format_daily_digest_github(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "今天的 GitHub 热门摘要还没生成。"
    lines = ["今日 GitHub 热门"]
    for item in items[:5]:
        repo = str(item.get("repo", "-"))
        language = str(item.get("language", "") or "未知")
        stars_today = item.get("stars_today")
        desc = choose_localized_text(
            item.get("description_zh"),
            item.get("description"),
            fallback="查看仓库说明",
        )
        if not contains_cjk(desc):
            desc = "查看仓库说明"
        desc = summarize_text(desc, limit=72)
        star_text = f"+{int(stars_today)}" if isinstance(stars_today, (int, float)) else "-"
        lines.append(f"- {repo} | {language} | 今日星标 {star_text} | {desc}")
    return "\n".join(lines)


def format_daily_digest_x(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "今天的 X 情报摘要还没生成。"
    lines = ["今日 X 情报"]
    for item in items[:5]:
        account = str(item.get("account", "-"))
        title = choose_localized_text(
            item.get("summary_zh"),
            item.get("title_zh"),
            item.get("summary"),
            item.get("title"),
            fallback="该条情报已收录，详见长版报告。",
        )
        if not contains_cjk(title):
            title = "该条情报已收录，详见长版报告。"
        title = summarize_text(title, limit=96)
        lines.append(f"- @{account} {title}")
    return "\n".join(lines)


def format_daily_digest_sentiment(sentiment: Dict[str, Any]) -> str:
    if not sentiment:
        return "今天的市场情绪摘要还没生成。"
    value = str(sentiment.get("value", "-"))
    classification = choose_localized_text(
        sentiment.get("classification_zh"),
        sentiment.get("value_classification_zh"),
        sentiment.get("classification"),
        sentiment.get("value_classification"),
        fallback="-",
    )
    classification = translate_sentiment_label(classification)
    return f"今日市场情绪\n- 恐慌与贪婪指数：{value}\n- 分类：{classification}"


def build_localized_daily_digest_from_payload(payload: Dict[str, Any]) -> str:
    report_date = str(payload.get("report_date", "")).strip() or "今日"
    sentiment = payload.get("market_sentiment") or payload.get("fng_index") or {}
    sentiment_value = str(sentiment.get("value", "-"))
    sentiment_label = choose_localized_text(
        sentiment.get("classification_zh"),
        sentiment.get("value_classification_zh"),
        sentiment.get("classification"),
        sentiment.get("value_classification"),
        fallback="-",
    )
    sentiment_label = translate_sentiment_label(sentiment_label)

    binance_items = payload.get("top_binance_movers") or (payload.get("binance_movers") or {}).get("items") or []
    contract_items = payload.get("top_contract_movers") or (payload.get("contract_movers") or {}).get("items") or []
    github_items = payload.get("top_github_repos") or (payload.get("github_trending") or {}).get("items") or []
    x_items = payload.get("top_x_posts") or (payload.get("x_watchlist") or {}).get("items") or []
    potential_raw = payload.get("top_potential_picks") or payload.get("potential_picks") or []
    if isinstance(potential_raw, dict):
        potential_items = potential_raw.get("items") or []
    elif isinstance(potential_raw, list):
        potential_items = potential_raw
    else:
        potential_items = []

    def format_movers(items: List[Dict[str, Any]]) -> str:
        if not items:
            return "暂无"
        parts: List[str] = []
        for item in items[:3]:
            symbol = str(item.get("symbol", "-"))
            move = item.get("price_change_percent")
            move_text = f"{float(move):+.2f}%" if isinstance(move, (int, float)) else str(move or "-")
            parts.append(f"{symbol} {move_text}")
        return "，".join(parts) if parts else "暂无"

    def format_github(items: List[Dict[str, Any]]) -> str:
        if not items:
            return "暂无"
        repos = [str(item.get("repo", "-")).strip() for item in items[:3] if str(item.get("repo", "")).strip()]
        return "，".join(repos) if repos else "暂无"

    def format_x_focus(items: List[Dict[str, Any]]) -> str:
        if not items:
            return "暂无"
        accounts = [f"@{str(item.get('account', '-')).strip()}" for item in items[:3] if str(item.get("account", "")).strip()]
        return "、".join(accounts) + "（详见长版）" if accounts else "暂无"

    def format_picks(items: List[Dict[str, Any]]) -> str:
        if not items:
            return "暂无"
        picks: List[str] = []
        for item in items[:3]:
            symbol = str(item.get("symbol", "-"))
            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)):
                picks.append(f"{symbol}({int(confidence)})")
            else:
                picks.append(symbol)
        return "，".join(picks) if picks else "暂无"

    lines = [
        f"每日加密晨报 | {report_date}",
        f"情绪：{sentiment_value} | {sentiment_label}",
        f"异动：{format_movers(binance_items)}",
        f"合约：{format_movers(contract_items)}",
        f"GitHub：{format_github(github_items)}",
        f"焦点：{format_x_focus(x_items)}",
        f"潜力币：{format_picks(potential_items)}",
    ]
    return "\n".join(lines)


def build_daily_digest_reply(query_text: str) -> str:
    digest_json_path = Path(DAILY_CRYPTO_LATEST_DIGEST_JSON_PATH)
    digest_text_path = Path(DAILY_CRYPTO_LATEST_DIGEST_TEXT_PATH)
    query_type = classify_daily_digest_query(query_text)

    if digest_json_path.exists():
        payload = json.loads(digest_json_path.read_text())
        markdown_path = str((payload.get("paths") or {}).get("markdown", "")).strip()

        if query_type == "binance":
            reply = format_daily_digest_binance(payload.get("top_binance_movers") or [])
        elif query_type == "github":
            reply = format_daily_digest_github(payload.get("top_github_repos") or [])
        elif query_type == "x":
            reply = format_daily_digest_x(payload.get("top_x_posts") or [])
        elif query_type == "sentiment":
            reply = format_daily_digest_sentiment(payload.get("market_sentiment") or {})
        else:
            reply = build_localized_daily_digest_from_payload(payload)
            if not reply.strip():
                reply = str(payload.get("digest_text", "")).strip()

        if reply:
            if markdown_path:
                return f"{reply}\n\n长版报告：{markdown_path}"
            return reply

    if digest_text_path.exists():
        digest_text = digest_text_path.read_text().strip()
        if digest_text:
            return digest_text

    raise FileNotFoundError("daily crypto digest not found")


def build_daily_report_messages(query_text: str) -> tuple[List[str], str]:
    digest_json_path = Path(DAILY_CRYPTO_LATEST_DIGEST_JSON_PATH)
    digest_text_path = Path(DAILY_CRYPTO_LATEST_DIGEST_TEXT_PATH)
    query_type = classify_daily_digest_query(query_text)

    if digest_json_path.exists():
        payload = json.loads(digest_json_path.read_text())
        markdown_path = str((payload.get("paths") or {}).get("markdown", "")).strip()

        if query_type == "markdown":
            markdown_text = ""
            if markdown_path and Path(markdown_path).exists():
                markdown_text = Path(markdown_path).read_text().strip()
            else:
                latest_md = digest_json_path.with_name("latest.md")
                if latest_md.exists():
                    markdown_text = latest_md.read_text().strip()
                    markdown_path = str(latest_md)
            if markdown_text:
                messages = split_telegram_text(markdown_text)
                footer = f"长版报告路径：{markdown_path}" if markdown_path else ""
                if footer:
                    if messages and len(messages[-1]) + len(footer) + 2 <= 3600:
                        messages[-1] = f"{messages[-1]}\n\n{footer}"
                    else:
                        messages.append(footer)
                summary = f"已发送长版报告（共 {len(messages)} 段）"
                return messages, summary

        reply = build_daily_digest_reply(query_text)
        return [reply], reply

    if digest_text_path.exists():
        digest_text = digest_text_path.read_text().strip()
        if digest_text:
            return [digest_text], digest_text

    raise FileNotFoundError("daily crypto digest not found")


def build_daily_report_messages_for_callback(query_type: str) -> tuple[List[str], str]:
    label_map = {
        "markdown": "长版报告",
        "full": "今天晨报",
        "binance": "今天币安异动",
        "github": "今天 GitHub 热门",
        "x": "今天 X 情报",
        "sentiment": "今天市场情绪",
    }
    return build_daily_report_messages(label_map.get(query_type, "今天晨报"))


async def send_daily_report_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query_text: str,
    memory_store: Optional[ConversationMemoryStore] = None,
    chat_id: str = "",
    user_id: str = "",
) -> None:
    try:
        reply_messages, reply_summary = build_daily_report_messages(query_text)
    except FileNotFoundError:
        reply_messages = ["今天的晨报摘要还没生成，先稍后再问我一次。"]
        reply_summary = reply_messages[0]

    if memory_store and chat_id:
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_summary)
        if is_group_like_chat(getattr(update.effective_chat, "type", None)):
            mirror_group_result_to_openclaw_memory(
                memory_store,
                chat_id=chat_id,
                user_id=user_id,
                content=reply_summary,
            )

    reply_markup = build_daily_digest_inline_markup()
    for index, reply_text in enumerate(reply_messages):
        await send_text_response(
            update,
            context,
            reply_text,
            reply_markup=reply_markup if index == 0 else None,
        )


def should_force_group_reply(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if has_explicit_dispatch_request(text):
        return True
    if re.search(r"[?？]$", text.strip()):
        return True
    force_keywords = [
        "在吗",
        "你好",
        "hello",
        "hi",
        "大家好",
        "谁有空",
        "谁来",
        "请",
        "帮我",
        "能不能",
        "可以吗",
        "怎么看",
        "为什么",
        "怎么",
        "是否",
        "修复",
        "翻译",
        "润色",
        "总结",
        "分析",
        "整理",
    ]
    return any(keyword in lowered for keyword in force_keywords)


def has_explicit_dispatch_request(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in EXPLICIT_DISPATCH_MARKERS)


def should_dispatch_private_task(text: str) -> bool:
    clean = text.strip()
    lowered = clean.lower()
    if not clean:
        return False

    if has_explicit_dispatch_request(clean):
        return True

    has_url = "http://" in lowered or "https://" in lowered

    if re.search(r"[?？]$", clean) and not any(word in lowered for word in ["修复", "翻译", "润色", "部署", "安装", "配置"]):
        return False

    route = classify_task(clean)
    if route["category"] == "explicit":
        return True

    action_keywords = [
        "修复",
        "开发",
        "实现",
        "安装",
        "配置",
        "部署",
        "编写",
        "写一个",
        "创建",
        "新建",
        "修改",
        "检查",
        "审核",
        "测试",
        "翻译",
        "润色",
        "整理",
        "总结成文",
        "生成",
        "完成",
        "处理",
        "安排",
        "分派",
        "派单",
        "派给",
        "阅读",
        "分析",
        "提炼",
        "归纳",
        "总结",
        "摘要",
    ]
    if has_url:
        return any(keyword in lowered for keyword in action_keywords)

    if any(keyword in lowered for keyword in action_keywords):
        return True

    return False


def should_route_unmentioned_group_task_to_openclaw(
    text: str,
    *,
    chat_type: Optional[str] = None,
    mentioned_self: bool = False,
) -> bool:
    if mentioned_self or not is_group_like_chat(chat_type):
        return False
    return classify_group_message_semantics(text) == "task"


def should_queue_explicit_group_followup(
    text: str,
    *,
    mentioned_self: bool = False,
    message_semantics: str = "task",
) -> bool:
    if not mentioned_self or message_semantics == "casual":
        return False

    lowered = text.strip().lower()
    if not lowered:
        return False

    followup_keywords = [
        "下一步",
        "接下来",
        "继续",
        "继续做",
        "继续处理",
        "接着",
        "跟进",
        "推进",
        "按你说的",
        "照你说的",
        "有结果了吗",
        "有进展吗",
        "结果呢",
        "进展如何",
        "处理一下",
        "解决",
    ]
    return any(keyword in lowered for keyword in followup_keywords)


def build_private_prompt(history: List[Dict[str, str]], instant_memory: str = "") -> str:
    transcript = []
    for item in history[-MAX_CONTEXT_MESSAGES:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        transcript.append(f"[{role}]\n{item['content']}")
    transcript_text = "\n\n".join(transcript)
    role_rules = ""
    private_workdir = PRIVATE_DIRECT_WORKDIR or WORKDIR
    if BOT_ROLE == "gemini":
        role_rules = (
            "私聊职责：你在私聊中是独立的端到端执行伙伴，而不是群聊里的资料汇报角色。\n"
            "1. 端到端自主执行：面对任务时，先研究现有代码库和上下文，再制定策略，然后进入执行阶段；默认遵循“计划-行动-验证”的循环，完成后主动做最小可行验证。\n"
            "2. 专家级代码开发与维护：你可以针对工作空间中的现有项目进行功能开发、Bug 修复、代码重构、脚本编写、性能优化和工程维护，目标是交付可运行、可验证、可维护的结果。\n"
            "3. 系统与安全完整性保护：严禁泄露、打印、提交任何密钥、密码、Token 或其他敏感信息；尊重 Git 规范，除非用户明确要求，否则不要主动 commit 或 push；执行时要尽量保持工作空间状态一致。\n"
            "4. 战略技术协作：你可以处理模糊需求，主动做调研，给出可落地的技术方案，并在必要时先拆解步骤再执行。\n"
            "5. 多维度技能调用：你可以调用已接入的专项技能、现成脚本、现成工具和现成命令来完成跨平台自动化任务；如果有更稳的现成能力，优先复用而不是重复造轮子。\n"
            f"权限边界：私聊执行默认以 {private_workdir} 作为工作根目录，可在本机该范围内自主查目录、读写文件、运行命令和调用已有 skill/脚本；群聊职责与权限边界不受这条规则影响。\n"
            "输出要求：默认用简体中文；先给结论，再给关键步骤、验证结果和下一步；不要暴露冗长思考过程。\n"
        )
    return (
        f"你现在作为 {BOT_DISPLAY_NAME}，通过 Telegram 与同一个用户持续协作。\n"
        f"角色={BOT_ROLE}\n"
        f"工作目录={private_workdir}\n"
        f"{role_rules}"
        f"{instant_memory + chr(10) if instant_memory else ''}"
        "默认用简体中文直接回复用户；只有用户明确要求其他语言时才切换语言。\n"
        "请结合最近对话上下文，继续处理最后一条用户消息。"
        "如果历史与最后一条消息冲突，以最后一条为准。"
        "回复直接面向用户，不要解释系统内部实现。\n\n"
        f"{transcript_text}"
    )


def build_private_fallback_prompt(history: List[Dict[str, str]], instant_memory: str = "") -> str:
    trimmed_history = history[-4:] if len(history) > 4 else history
    compact_history = []
    for item in trimmed_history:
        compact_history.append(
            {
                "role": item["role"],
                "content": summarize_text(item["content"], limit=600)
                if item["role"] == "assistant"
                else item["content"],
            }
        )
    return build_private_prompt(compact_history, instant_memory=instant_memory)


def build_group_prompt(
    history: List[Dict[str, str]],
    force_reply: bool = False,
    group_role_note: str = "",
    message_semantics: str = "task",
    instant_memory: str = "",
) -> str:
    transcript = []
    for item in history[-MAX_CONTEXT_MESSAGES:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        transcript.append(f"[{role}]\n{item['content']}")
    transcript_text = "\n\n".join(transcript)
    reply_rule = (
        "请直接回应最后一条群消息，并像正常群成员一样自然发言。"
        if force_reply
        else f"如果这条最新消息不需要你从当前角色出面回应，或者你没有明显增量价值，请只输出 {NO_REPLY_SENTINEL}。"
    )
    role_prefix = ""
    if group_role_note:
        role_prefix = (
            f"当前群内为你指定的职责：{group_role_note}\n"
            "这条职责只在当前群生效，不适用于私聊或其他群。\n"
        )
    role_rules = ""
    if BOT_ROLE == "gemini":
        role_rules = (
            "职责边界：你负责办公文档、资料搜索、翻译润色、以及基于现成脚本/现成可执行代码的资料采集与结果分析。\n"
            "严禁事项：不要新增、修改、删除任何代码、脚本、配置、调度任务或工程文件。\n"
            "允许事项：如果仓库里已经有现成脚本、现成命令或现成可执行代码，你可以直接运行它们来采集数据、读取结果、做分析和汇总，但不要改动这些文件。\n"
            "如果最后一条群消息实质上要求写代码、改代码、开发脚本、修复脚本、改配置、接入或部署，你不应自己落地代码；应优先协调或交给 Codex，自己只负责资料整理、结果分析和最终汇总。\n"
        )
    style_rule = ""
    if message_semantics == "casual":
        style_rule = (
            "这条最新消息是闲聊，不是任务。\n"
            "请像自然群友一样直接接话，用简体中文短回复，控制在 1 到 3 句。\n"
            "不要写思考过程、计划、步骤、分析框架、心理活动，不要中英混杂，不要项目汇报腔。\n"
        )
    return (
        f"你现在作为 {BOT_DISPLAY_NAME}，在 Telegram 群聊中与同一个用户以及其他 bot 协作。\n"
        f"角色={BOT_ROLE}\n"
        f"工作目录={WORKDIR}\n"
        f"{role_prefix}"
        f"{role_rules}"
        f"{style_rule}"
        f"{instant_memory + chr(10) if instant_memory else ''}"
        f"{reply_rule}\n"
        "默认用简体中文在群里回复；只有用户明确要求其他语言时才切换语言。\n"
        "如果需要回应，可以自然参与群聊；如果是执行型请求，可以直接完成并汇报结果。"
        "不要解释系统内部实现，不要冒充其他 bot。\n\n"
        f"{transcript_text}"
    )


def build_dispatch_prompt(history: List[Dict[str, str]], instant_memory: str = "") -> str:
    transcript = []
    for item in history[-MAX_CONTEXT_MESSAGES:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        transcript.append(f"[{role}]\n{item['content']}")
    transcript_text = "\n\n".join(transcript)
    return (
        "下面是用户在 Telegram 对话里的最近上下文。\n"
        f"{instant_memory + chr(10) if instant_memory else ''}"
        "请代表接手该任务的 agent，根据上下文完成最后一条用户请求。"
        "最终过程反馈和结果汇报默认都使用简体中文；只有用户明确要求其他语言时才切换。\n"
        "若历史与最后一条用户消息冲突，以最后一条为准。\n\n"
        f"{transcript_text}"
    )


def is_allowed_user(update: Update) -> bool:
    user = update.effective_user
    if user and not getattr(user, "is_bot", False):
        if not ALLOWED_USER_IDS:
            return True
        return bool(user.id in ALLOWED_USER_IDS)

    chat = update.effective_chat
    message = update.effective_message
    sender_chat = getattr(message, "sender_chat", None)
    if chat and is_group_like_chat(chat.type) and sender_chat and sender_chat.id == chat.id:
        logging.info(
            "Allowing anonymous group sender role=%s chat_id=%s sender_chat_id=%s",
            BOT_ROLE,
            getattr(chat, "id", None),
            getattr(sender_chat, "id", None),
        )
        return True

    if chat and is_group_like_chat(chat.type):
        logging.info(
            "Rejected group sender role=%s chat_id=%s user_id=%s sender_chat_id=%s",
            BOT_ROLE,
            getattr(chat, "id", None),
            getattr(user, "id", None) if user else None,
            getattr(sender_chat, "id", None) if sender_chat else None,
        )
    return False


async def log_raw_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not is_group_like_chat(chat.type):
        return
    user = update.effective_user
    sender_chat = getattr(message, "sender_chat", None)
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    logging.info(
        "Raw update role=%s chat_type=%s chat_id=%s user_id=%s sender_chat_id=%s text=%s",
        BOT_ROLE,
        chat.type,
        getattr(chat, "id", None),
        getattr(user, "id", None) if user else None,
        getattr(sender_chat, "id", None) if sender_chat else None,
        summarize_text(text, limit=100),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    await send_text_response(
        update,
        context,
        f"{BOT_DISPLAY_NAME} 已启动。\nrole={BOT_ROLE}\nmode={BOT_MODE}"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    if BOT_MODE == "dispatcher":
        extra = " /remember" if BOT_ROLE == "openclaw" and ALLOW_LONG_TERM_MEMORY_WRITE else ""
        private_hint = "私聊里会自动区分：普通对话直接回复，明确任务会派给对应 bot。"
        if PRIVATE_TASK_MODE == "manual":
            private_hint = "私聊默认直接回复；只有你显式写明要分派或带 #codex/#gemini 时才会派单。"
        group_hint = f"群里发送 /{TASK_COMMAND} 任务内容进行派单。"
        group_mode_hint = f"群聊自由对话={'on' if ALLOW_GROUP_CHAT else 'off'}"
        if BOT_ROLE == "openclaw":
            group_hint = "群里我默认先拆分任务，再做分派、状态回执和记忆写入；晨报与资料汇报默认交给 Gemini，开发交给 Codex。"
            group_mode_hint = "群聊自动分派=on / 群聊直接执行=off"
        await send_text_response(
            update,
            context,
            f"私聊我会按模式 {PRIVATE_TASK_MODE} 处理任务；{group_hint}\n"
            f"例如：/{TASK_COMMAND} 修复 telegram worker 的 sqlite 锁问题\n"
            f"{private_hint}\n"
            f"{group_mode_hint}\n"
            f"可用命令：/start /help /status /memory_recent /memory_search /reset{extra}"
        )
        return
    await send_text_response(
        update,
        context,
        f"{BOT_DISPLAY_NAME} 私聊按模式 {PRIVATE_TASK_MODE} 处理任务；群聊自由对话={'on' if ALLOW_GROUP_CHAT else 'off'}。\n"
        "可用命令：/start /help /status /memory_recent /memory_search /reset"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    if BOT_MODE == "dispatcher":
        if BOT_ROLE == "openclaw":
            try:
                status_text = await asyncio.to_thread(build_openclaw_status_text)
            except Exception as exc:
                logging.exception("Failed to build OpenClaw status")
                status_text = (
                    "OpenClaw status\n\n"
                    "Overview\n"
                    "Gateway: status unavailable\n"
                    f"Reason: {summarize_text(str(exc), limit=200)}\n\n"
                    "Telegram\n"
                    f"Private mode: {PRIVATE_TASK_MODE}\n"
                    f"Group chat: {'on' if ALLOW_GROUP_CHAT else 'off'}\n"
                    "Group role: dispatch + decomposition + status + memory only\n"
                    "Group reporter: gemini\n"
                    "Group direct execution: off\n"
                    f"Private direct backend: {PRIVATE_DIRECT_RUNNER_BACKEND or 'openclaw_agent'}({PRIVATE_DIRECT_OPENCLAW_AGENT_ID or 'main'})\n"
                    f"Dispatch backend: {RUNNER_BACKEND or '-'}"
                )
            await send_text_response(update, context, status_text[:4000])
            return
        await send_text_response(
            update,
            context,
            "dispatcher 在线\n"
            f"private_task_mode={PRIVATE_TASK_MODE}\n"
            f"group_chat={'on' if ALLOW_GROUP_CHAT else 'off'}\n"
            f"direct_private={'yes' if ENABLE_DIRECT_PRIVATE_TASKS else 'no'}\n"
            f"private_direct_backend={PRIVATE_DIRECT_RUNNER_BACKEND or ('openclaw_agent(main)' if BOT_ROLE == 'openclaw' else RUNNER_BACKEND or '-')}\n"
            f"memory_db={MEMORY_DB_PATH}\n"
            f"shared_memory={'on' if ENABLE_SHARED_MEMORY_LOG else 'off'}\n"
            f"long_term_memory={'on' if ALLOW_LONG_TERM_MEMORY_WRITE else 'off'}"
        )
        return
    busy = bool(context.application.bot_data.get("busy"))
    await send_text_response(
        update,
        context,
        "worker={}\nbackend={}\nworkdir={}\ndirect_private={}\ngroup_chat={}\nbusy={}\nmemory_db={}\nshared_memory={}\nlong_term_memory={}".format(
            BOT_ROLE,
            RUNNER_BACKEND,
            WORKDIR,
            f"{'yes' if ENABLE_DIRECT_PRIVATE_TASKS else 'no'} ({PRIVATE_TASK_MODE})",
            "on" if ALLOW_GROUP_CHAT else "off",
            "yes" if busy else "no",
            MEMORY_DB_PATH,
            "on" if ENABLE_SHARED_MEMORY_LOG else "off",
            "on" if ALLOW_LONG_TERM_MEMORY_WRITE else "off",
        )
    )


async def memory_recent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    await send_text_response(update, context, build_recent_memory_response(context.application, chat_id))


async def memory_search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    query = " ".join(context.args).strip()
    if not query:
        await send_text_response(update, context, "用法：/memory_search 关键词")
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    await send_text_response(update, context, build_memory_search_response(context.application, chat_id, query))


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    get_memory_store(context.application).clear_history(BOT_ROLE, chat_id)
    get_memory_store(context.application).clear_chat_profile(BOT_ROLE, chat_id)
    await send_text_response(update, context, "当前聊天上下文已清空。")


async def remember_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    if BOT_ROLE != "openclaw" or not ALLOW_LONG_TERM_MEMORY_WRITE:
        await send_text_response(update, context, "当前 bot 没有长期记忆写入权限。")
        return
    text = " ".join(context.args).strip()
    if not text:
        await send_text_response(update, context, "用法：/remember 要写入长期记忆的内容")
        return
    try:
        await asyncio.to_thread(get_long_term_writer(context.application).append_note, text)
    except Exception as exc:
        logging.exception("Long-term memory write failed")
        await send_text_response(update, context, f"长期记忆写入失败：{summarize_text(str(exc), limit=300)}")
        return

    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    ack_text = f"[OpenClaw] 已写入长期记忆\nsummary={summarize_text(text)}"
    get_memory_store(context.application).append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
    if ENABLE_SHARED_MEMORY_LOG:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="long-memory",
            task_summary=text,
            result_summary="已追加到 MEMORY.md",
            status="completed",
        )
    await send_text_response(update, context, ack_text)


async def daily_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if not is_allowed_user(update):
        await query.answer("未授权用户", show_alert=True)
        return

    data = str(query.data or "")
    if not data.startswith(DAILY_REPORT_CALLBACK_PREFIX):
        await query.answer()
        return

    query_type = data.removeprefix(DAILY_REPORT_CALLBACK_PREFIX).strip()
    if query_type not in {"markdown", "full", "binance", "github", "x", "sentiment"}:
        await query.answer("暂不支持该查看项", show_alert=True)
        return

    await query.answer()
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    await send_daily_report_response(
        update,
        context,
        query_text={
            "markdown": "长版报告",
            "full": "今天晨报",
            "binance": "今天币安异动",
            "github": "今天 GitHub 热门",
            "x": "今天 X 情报",
            "sentiment": "今天市场情绪",
        }[query_type],
        memory_store=get_memory_store(context.application),
        chat_id=chat_id,
        user_id=user_id,
    )


async def task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    if BOT_MODE != "dispatcher":
        return
    text = " ".join(context.args).strip()
    if not text:
        await send_text_response(update, context, f"用法：/{TASK_COMMAND} 任务内容")
        return
    get_memory_store(context.application).append_message(
        BOT_ROLE,
        str(getattr(update.effective_chat, "id", "")),
        str(getattr(update.effective_user, "id", "")),
        "user",
        text,
    )
    await create_task_from_text(update, context, text)


async def capture_dm_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        return
    if BOT_MODE != "dispatcher" or not ALLOW_DM_TASKS:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    text = (update.message.text or "").strip()
    if text.startswith("/"):
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    memory_store = get_memory_store(context.application)
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "user", text)
    history = memory_store.get_history(BOT_ROLE, chat_id, MAX_CONTEXT_MESSAGES)
    instant_memory = get_instant_memory_snapshot(context.application, chat_id)
    memory_search_query = extract_memory_search_query(text)
    if memory_search_query:
        await send_text_response(
            update,
            context,
            build_memory_search_response(context.application, chat_id, memory_search_query),
        )
        return
    if is_recent_memory_query(text):
        await send_text_response(
            update,
            context,
            build_recent_memory_response(context.application, chat_id),
        )
        return
    if is_system_health_query(text):
        await send_text_response(
            update,
            context,
            build_system_health_summary(),
        )
        return
    if should_serve_daily_digest(text, chat_type=getattr(update.effective_chat, "type", None)):
        await send_daily_report_response(
            update,
            context,
            query_text=text,
            memory_store=memory_store,
            chat_id=chat_id,
            user_id=user_id,
        )
        return
    if ENABLE_DIRECT_PRIVATE_TASKS and should_handle_private_direct(text):
        await execute_direct_private_task(update, context, text, history)
        return

    if PRIVATE_TASK_MODE == "direct" and ENABLE_DIRECT_PRIVATE_TASKS:
        await execute_direct_private_task(update, context, text, history)
        return
    if PRIVATE_TASK_MODE == "manual":
        if has_explicit_dispatch_request(text):
            task_payload = build_dispatch_prompt(history, instant_memory=instant_memory)
            await create_task_from_text(update, context, text, task_payload=task_payload)
            return
        if ENABLE_DIRECT_PRIVATE_TASKS:
            await execute_direct_private_task(update, context, text, history)
            return
    if PRIVATE_TASK_MODE == "hybrid":
        if should_dispatch_private_task(text):
            task_payload = build_dispatch_prompt(history, instant_memory=instant_memory)
            await create_task_from_text(update, context, text, task_payload=task_payload)
            return
        if ENABLE_DIRECT_PRIVATE_TASKS:
            await execute_direct_private_task(update, context, text, history)
            return

    task_payload = build_dispatch_prompt(history, instant_memory=instant_memory)
    await create_task_from_text(update, context, text, task_payload=task_payload)


async def capture_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        return
    if not ALLOW_GROUP_CHAT:
        return
    if update.effective_chat and not is_group_like_chat(update.effective_chat.type):
        return
    text = (update.message.text or "").strip()
    if not text or text.startswith("/"):
        return

    should_handle, mentioned_self = should_handle_group_message_for_bot(update, context)
    if not should_handle:
        return
    group_role_assignment = is_group_role_assignment(text, mentioned_self)
    self_username = (
        (getattr(context.bot, "username", None) or "")
        .strip()
        .lower()
        .lstrip("@")
    )
    delegation_targets = resolve_user_delegation_targets(update.effective_message, self_username)
    if not delegation_targets and BOT_ROLE != "openclaw" and mentioned_self:
        primary_mention = resolve_primary_group_bot_mention(update.effective_message)
        ordered_bot_mentions = [
            mention
            for mention in extract_ordered_message_mentions(update.effective_message)
            if mention.endswith("bot")
        ]
        if primary_mention and primary_mention == self_username and len(ordered_bot_mentions) >= 2:
            delegation_targets = [
                mention
                for mention in ordered_bot_mentions
                if mention != self_username
            ]
            if delegation_targets:
                logging.info(
                    "Recovered delegation targets role=%s chat_id=%s self=%s targets=%s",
                    BOT_ROLE,
                    chat_id,
                    self_username,
                    ",".join(delegation_targets),
                )
    message_semantics = classify_group_message_semantics(text)
    if delegation_targets:
        message_semantics = "task"
    elif BOT_ROLE != "openclaw" and should_queue_explicit_group_followup(
        text,
        mentioned_self=mentioned_self,
        message_semantics=message_semantics,
    ):
        message_semantics = "task"
    digest_query_type = classify_daily_digest_query(text)
    if digest_query_type and not should_serve_daily_digest(
        text,
        chat_type=getattr(update.effective_chat, "type", None),
        mentioned_self=mentioned_self,
    ):
        logging.info(
            "Ignoring shared daily digest query role=%s chat_id=%s text=%s",
            BOT_ROLE,
            getattr(update.effective_chat, "id", None),
            summarize_text(text),
        )
        return

    if BOT_ROLE != "openclaw" and message_semantics == "status" and not mentioned_self:
        logging.info(
            "Ignoring unmentioned status query for role=%s chat_id=%s text=%s",
            BOT_ROLE,
            getattr(update.effective_chat, "id", None),
            summarize_text(text),
        )
        return

    if BOT_ROLE != "openclaw" and should_route_unmentioned_group_task_to_openclaw(
        text,
        chat_type=getattr(update.effective_chat, "type", None),
        mentioned_self=mentioned_self,
    ):
        logging.info(
            "Ignoring unmentioned group task for role=%s chat_id=%s text=%s",
            BOT_ROLE,
            getattr(update.effective_chat, "id", None),
            summarize_text(text),
        )
        return

    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    force_reply = mentioned_self or should_force_group_reply(text) or message_semantics == "casual"
    logging.info(
        "Received group message role=%s chat_id=%s user_id=%s force_reply=%s text=%s",
        BOT_ROLE,
        chat_id,
        user_id,
        "yes" if force_reply else "no",
        summarize_text(text),
    )
    memory_store = get_memory_store(context.application)
    if group_role_assignment:
        note = build_group_role_note(text)
        memory_store.set_chat_profile(BOT_ROLE, chat_id, note)
        logging.info(
            "Updated group profile role=%s chat_id=%s profile=%s",
            BOT_ROLE,
            chat_id,
            summarize_text(note, limit=120),
        )
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "user", text)
    history = memory_store.get_history(BOT_ROLE, chat_id, MAX_CONTEXT_MESSAGES)
    instant_memory = get_instant_memory_snapshot(context.application, chat_id)
    memory_search_query = extract_memory_search_query(text)
    if memory_search_query:
        await send_text_response(
            update,
            context,
            build_memory_search_response(context.application, chat_id, memory_search_query),
        )
        return
    if is_recent_memory_query(text):
        await send_text_response(
            update,
            context,
            build_recent_memory_response(context.application, chat_id),
        )
        return
    if is_system_health_query(text):
        reply_text = build_system_health_summary()
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_text)
        if ENABLE_SHARED_MEMORY_LOG:
            get_shared_journal(context.application).append_event(
                bot_role=BOT_ROLE,
                scope="group-status",
                task_summary=text,
                result_summary=reply_text,
                status="completed",
            )
        await send_text_response(update, context, reply_text)
        return
    if should_serve_daily_digest(
        text,
        chat_type=getattr(update.effective_chat, "type", None),
        mentioned_self=mentioned_self,
    ):
        await send_daily_report_response(
            update,
            context,
            query_text=text,
            memory_store=memory_store,
            chat_id=chat_id,
            user_id=user_id,
        )
        return
    if BOT_ROLE == "openclaw" and message_semantics == "status":
        reply_text = build_running_scripts_query_summary()
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_text)
        if ENABLE_SHARED_MEMORY_LOG:
            get_shared_journal(context.application).append_event(
                bot_role=BOT_ROLE,
                scope="group-status",
                task_summary=text,
                result_summary=reply_text,
                status="completed",
            )
        await send_text_response(update, context, reply_text)
        return
    if message_semantics != "casual" and delegation_targets and not group_role_assignment:
        delegation_roles = [
            role
            for role in (resolve_agent_role_from_mention(target) for target in delegation_targets)
            if role
        ]
        ack_text = (
            build_openclaw_dispatch_ack_text(text, delegation_roles)
            if BOT_ROLE == "openclaw"
            else build_group_delegation_ack_text(delegation_targets)
        )
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
        await send_text_response(update, context, ack_text)
        created = create_user_delegation_tasks(
            get_registry(context.application),
            source_role=BOT_ROLE,
            chat_id=chat_id,
            source_message_id=str(getattr(update.effective_message, "message_id", "")),
            source_user_id=user_id,
            user_text=text,
            history=history,
            target_mentions=delegation_targets,
        )
        for target_role, task_id in created:
            logging.info(
                "Created user delegation role=%s target=%s task_id=%s",
                BOT_ROLE,
                target_role,
                task_id,
            )
        return

    auto_delegate_roles = resolve_technical_auto_delegation_roles(
        memory_store,
        chat_id=chat_id,
        text=text,
    )
    if message_semantics != "casual" and auto_delegate_roles and not group_role_assignment:
        ack_text = (
            build_openclaw_dispatch_ack_text(text, auto_delegate_roles)
            if BOT_ROLE == "openclaw"
            else build_role_delegation_ack_text(auto_delegate_roles)
        )
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
        await send_text_response(update, context, ack_text)
        created = create_user_delegation_tasks_for_roles(
            get_registry(context.application),
            source_role=BOT_ROLE,
            chat_id=chat_id,
            source_message_id=str(getattr(update.effective_message, "message_id", "")),
            source_user_id=user_id,
            user_text=text,
            history=history,
            target_roles=auto_delegate_roles,
        )
        for target_role, task_id in created:
            logging.info(
                "Created auto delegation role=%s target=%s task_id=%s",
                BOT_ROLE,
                target_role,
                task_id,
            )
        return

    if (
        BOT_ROLE != "openclaw"
        and should_queue_explicit_group_followup(
            text,
            mentioned_self=mentioned_self,
            message_semantics=message_semantics,
        )
        and not group_role_assignment
    ):
        logging.info(
            "Queueing explicit group follow-up role=%s chat_id=%s text=%s",
            BOT_ROLE,
            chat_id,
            summarize_text(text),
        )
        await queue_group_message_for_self(
            update,
            context,
            text,
            history,
            reason="explicit-group-followup",
        )
        return

    if BOT_MODE == "dispatcher" and has_explicit_dispatch_request(text):
        task_payload = build_dispatch_prompt(history, instant_memory=instant_memory)
        await create_task_from_text(update, context, text, task_payload=task_payload)
        return

    if message_semantics == "casual" and ENABLE_DIRECT_PRIVATE_TASKS:
        await execute_direct_group_task(
            update,
            context,
            text,
            history,
            force_reply=True,
            group_role_assignment=group_role_assignment,
            message_semantics=message_semantics,
        )
        return

    if ENABLE_DIRECT_PRIVATE_TASKS and BOT_ROLE != "openclaw":
        route = classify_task(text)
        if (
            BOT_ROLE == "gemini"
            and str(route.get("route_reason", "")) == "matched runtime-monitoring execution keywords"
            and not group_role_assignment
        ):
            await queue_group_message_for_self(
                update,
                context,
                text,
                history,
                reason="runtime-monitoring-self-queue",
            )
            return
        await execute_direct_group_task(
            update,
            context,
            text,
            history,
            force_reply=force_reply,
            group_role_assignment=group_role_assignment,
            message_semantics=message_semantics,
        )


async def direct_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        return
    if not ENABLE_DIRECT_PRIVATE_TASKS or PRIVATE_TASK_MODE != "direct":
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    text = (update.message.text or "").strip()
    if not text or text.startswith("/"):
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    memory_store = get_memory_store(context.application)
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "user", text)
    history = memory_store.get_history(BOT_ROLE, chat_id, MAX_CONTEXT_MESSAGES)
    memory_search_query = extract_memory_search_query(text)
    if memory_search_query:
        await send_text_response(
            update,
            context,
            build_memory_search_response(context.application, chat_id, memory_search_query),
        )
        return
    if is_recent_memory_query(text):
        await send_text_response(
            update,
            context,
            build_recent_memory_response(context.application, chat_id),
        )
        return
    if is_system_health_query(text):
        reply_text = build_system_health_summary()
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_text)
        if ENABLE_SHARED_MEMORY_LOG:
            get_shared_journal(context.application).append_event(
                bot_role=BOT_ROLE,
                scope="private-status",
                task_summary=text,
                result_summary=reply_text,
                status="completed",
            )
        await send_text_response(update, context, reply_text)
        return
    if should_serve_daily_digest(text, chat_type=getattr(update.effective_chat, "type", None)):
        await send_daily_report_response(
            update,
            context,
            query_text=text,
            memory_store=memory_store,
            chat_id=chat_id,
            user_id=user_id,
        )
        return
    if BOT_ROLE == "gemini" and should_use_tenbagger_tool(text):
        ack_text = "收到，我直接调用现成的 10 倍币筛选脚本，跑完后把结果发给你。"
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
        await send_text_response(update, context, ack_text)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply_text = await asyncio.to_thread(run_tenbagger_tool)
        memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_text)
        if ENABLE_SHARED_MEMORY_LOG:
            get_shared_journal(context.application).append_event(
                bot_role=BOT_ROLE,
                scope="private-direct",
                task_summary=text,
                result_summary=reply_text,
                status="completed",
        )
        await send_text_response(update, context, reply_text)
        return
    try:
        await execute_direct_private_task(update, context, text, history)
    except Exception as exc:
        logging.exception("Direct private task failed role=%s user_id=%s", BOT_ROLE, user_id)
        await fallback_direct_private_task_to_queue(
            update,
            context,
            text,
            history,
            error_text=str(exc),
        )


async def execute_direct_group_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    history: Optional[List[Dict[str, str]]] = None,
    force_reply: bool = False,
    group_role_assignment: bool = False,
    message_semantics: str = "task",
) -> None:
    logging.info(
        "Direct group task role=%s user_id=%s text=%s",
        BOT_ROLE,
        getattr(update.effective_user, "id", None),
        summarize_text(text),
    )
    runner_cfg = get_private_runner_config()
    chat_id = str(getattr(update.effective_chat, "id", ""))
    chat_id_int = int(getattr(update.effective_chat, "id", 0) or 0)
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    group_role_note = get_memory_store(context.application).get_chat_profile(BOT_ROLE, chat_id)
    instant_memory = get_instant_memory_snapshot(context.application, chat_id)
    prompt = build_group_prompt(
        history or [],
        force_reply=force_reply,
        group_role_note=group_role_note,
        message_semantics=message_semantics,
        instant_memory=instant_memory,
    )
    direct_runner_cfg = runner_cfg
    if message_semantics != "casual":
        direct_runner_cfg = replace(
            runner_cfg,
            timeout_secs=min(runner_cfg.timeout_secs, DIRECT_GROUP_FALLBACK_TIMEOUT_SECS),
        )
    progress_task: Optional[asyncio.Task[Any]] = None
    if force_reply and not group_role_assignment:
        if message_semantics != "casual":
            await send_text_response(
                update,
                context,
                f"[{BOT_DISPLAY_NAME}] 收到，这条需求我先接住，正在处理，稍后直接给你结果。",
            )
            progress_task = asyncio.create_task(
                notify_long_running_direct_group_task(
                    context.application,
                    chat_id=chat_id_int,
                    thread_id=thread_id,
                    message_semantics=message_semantics,
                )
            )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_task, prompt, direct_runner_cfg),
            timeout=direct_runner_cfg.timeout_secs + 15,
        )
    except Exception as exc:
        logging.exception(
            "Direct group task failed role=%s user_id=%s; falling back to queue=%s",
            BOT_ROLE,
            getattr(update.effective_user, "id", None),
            "yes" if message_semantics != "casual" and not group_role_assignment else "no",
        )
        if message_semantics != "casual" and not group_role_assignment:
            await fallback_direct_group_task_to_queue(
                update,
                context,
                text,
                history or [],
                error_text=str(exc),
            )
            return
        raise
    finally:
        if progress_task:
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task
    if result.startswith("Runner failed:") and message_semantics != "casual" and not group_role_assignment:
        logging.warning(
            "Direct group task produced runner failure role=%s user_id=%s; falling back to queue",
            BOT_ROLE,
            getattr(update.effective_user, "id", None),
        )
        await fallback_direct_group_task_to_queue(
            update,
            context,
            text,
            history or [],
            error_text=result,
        )
        return
    reply_text = normalize_direct_group_reply_output(
        result,
        message_semantics=message_semantics,
    )
    if not reply_text or reply_text == NO_REPLY_SENTINEL:
        logging.info(
            "Suppressed group reply role=%s user_id=%s",
            BOT_ROLE,
            getattr(update.effective_user, "id", None),
        )
        return

    reply_text = reply_text[:4000]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    user_id = str(getattr(update.effective_user, "id", ""))
    memory_store = get_memory_store(context.application)
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_text)
    if not group_role_assignment:
        mirror_group_result_to_openclaw_memory(
            memory_store,
            chat_id=chat_id,
            user_id=user_id,
            content=reply_text,
        )
    if ENABLE_SHARED_MEMORY_LOG and not group_role_assignment:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="group-direct",
            task_summary=text,
            result_summary=reply_text,
            status="completed",
        )
    await send_text_response(update, context, reply_text)
    if message_semantics != "casual":
        created = enqueue_handoff_tasks(
            get_registry(context.application),
            chat_id=chat_id,
            source_message_id=str(getattr(update.effective_message, "message_id", "")),
            source_user_id=user_id,
            source_role=BOT_ROLE,
            user_text=text,
            reply_text=reply_text,
        )
        for target_role, task_id in created:
            logging.info(
                "Created bot handoff role=%s target=%s task_id=%s",
                BOT_ROLE,
                target_role,
                task_id,
            )


async def fallback_direct_group_task_to_queue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    history: List[Dict[str, str]],
    *,
    error_text: str,
) -> None:
    route = classify_task(text)
    if BOT_ROLE == "gemini" and str(route.get("route_reason", "")) == "matched runtime-monitoring execution keywords":
        route_payload = text
    else:
        route_payload = (
            build_dispatch_prompt(
                history,
                instant_memory=get_instant_memory_snapshot(
                    context.application,
                    str(getattr(update.effective_chat, "id", "")),
                ),
            )
            if history
            else text
        )
    allowed_roles = [
        str(agent)
        for agent in list(route["allowed_agents"])
        if str(agent) in {"codex", "claude", "gemini"} and is_agent_service_online(str(agent))
    ]
    if not allowed_roles:
        allowed_roles = [
            str(agent)
            for agent in list(route["allowed_agents"])
            if str(agent) in {"codex", "claude", "gemini"}
        ]

    registry = get_registry(context.application)
    task_id = registry.create_task(
        source_chat_id=str(update.effective_chat.id),
        source_message_id=str(getattr(update.effective_message, "message_id", "")),
        source_user_id=str(getattr(update.effective_user, "id", "")),
        source_text=route_payload,
        category=str(route["category"]),
        route_reason=f"direct-fallback:{BOT_ROLE}:{route['route_reason']}",
        allowed_agents=allowed_roles or list(route["allowed_agents"]),
    )
    ack_text = (
        f"[{BOT_DISPLAY_NAME}] 这条消息直连执行卡住了，我已切到任务链继续处理。"
        f"\n任务编号：#{task_id}"
        f"\ncategory={route['category']}"
        f"\neligible={format_allowed_agents(allowed_roles or list(route['allowed_agents']))}"
        f"\nreason={route['route_reason']}"
        f"\nsummary={summarize_text(text)}"
    )
    memory_store = get_memory_store(context.application)
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
    mirror_group_result_to_openclaw_memory(
        memory_store,
        chat_id=chat_id,
        user_id=user_id,
        content=f"{ack_text}\n降级原因：{summarize_text(error_text, limit=240)}",
    )
    if ENABLE_SHARED_MEMORY_LOG:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="group-direct-fallback",
            task_summary=text,
            result_summary=summarize_text(error_text, limit=300),
            status="queued",
            task_id=task_id,
            category=str(route["category"]),
            allowed_agents=list(allowed_roles or list(route["allowed_agents"])),
        )
    await send_text_response(update, context, ack_text)


async def execute_direct_private_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> None:
    logging.info(
        "Direct private task role=%s user_id=%s text=%s",
        BOT_ROLE,
        getattr(update.effective_user, "id", None),
        summarize_text(text),
    )
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    runner_cfg = get_private_runner_config()
    instant_memory = get_instant_memory_snapshot(
        context.application,
        str(getattr(update.effective_chat, "id", "")),
    )
    prompt = (
        build_private_fallback_prompt(history or [], instant_memory=instant_memory)
        if BOT_ROLE == "gemini"
        else build_private_prompt(history or [], instant_memory=instant_memory)
    )
    direct_runner_cfg = runner_cfg
    if BOT_ROLE == "gemini":
        direct_runner_cfg = replace(
            runner_cfg,
            timeout_secs=min(runner_cfg.timeout_secs, DIRECT_PRIVATE_FALLBACK_TIMEOUT_SECS),
        )
        await send_text_response(
            update,
            context,
            f"[{BOT_DISPLAY_NAME}] 收到，我先处理；如果直连卡住，我会自动切到任务链继续跑。",
        )
    progress_task: Optional[asyncio.Task[Any]] = None
    if BOT_ROLE == "gemini":
        progress_task = asyncio.create_task(
            notify_long_running_direct_private_task(
                context.application,
                chat_id=update.effective_chat.id,
            )
        )
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_task, prompt, direct_runner_cfg),
            timeout=direct_runner_cfg.timeout_secs + 15,
        )
    finally:
        if progress_task:
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task
    reply_text = result[:4000]
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    get_memory_store(context.application).append_message(BOT_ROLE, chat_id, user_id, "assistant", reply_text)
    if ENABLE_SHARED_MEMORY_LOG:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="private-direct",
            task_summary=text,
            result_summary=reply_text,
            status="completed",
        )
    await send_text_response(update, context, reply_text)


async def fallback_direct_private_task_to_queue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    history: List[Dict[str, str]],
    *,
    error_text: str,
) -> None:
    route = classify_task(text)
    if BOT_ROLE == "gemini" and str(route.get("route_reason", "")) == "matched runtime-monitoring execution keywords":
        route_payload = text
    else:
        route_payload = (
            build_private_fallback_prompt(
                history,
                instant_memory=get_instant_memory_snapshot(
                    context.application,
                    str(getattr(update.effective_chat, "id", "")),
                ),
            )
            if history
            else text
        )
    registry = get_registry(context.application)
    task_id = registry.create_task(
        source_chat_id=str(update.effective_chat.id),
        source_message_id=str(getattr(update.effective_message, "message_id", "")),
        source_user_id=str(getattr(update.effective_user, "id", "")),
        source_text=route_payload,
        category=str(route["category"]),
        route_reason=f"private-self-queue:{BOT_ROLE}:direct-timeout",
        allowed_agents=[BOT_ROLE],
    )
    ack_text = (
        f"[{BOT_DISPLAY_NAME}] 这条私聊直连卡住了，我已切到任务链继续处理。"
        f"\n任务编号：#{task_id}"
        f"\nsummary={summarize_text(text)}"
    )
    memory_store = get_memory_store(context.application)
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
    if ENABLE_SHARED_MEMORY_LOG:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="private-direct-fallback",
            task_summary=text,
            result_summary=summarize_text(error_text, limit=300),
            status="queued",
            task_id=task_id,
            category=str(route["category"]),
            allowed_agents=[BOT_ROLE],
        )
    await send_text_response(update, context, ack_text)


async def create_task_from_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    task_payload: Optional[str] = None,
) -> None:
    route = classify_task(text)
    preferred_roles = [
        agent
        for agent in list(route["allowed_agents"])
        if str(agent) in {"codex", "claude", "gemini"} and is_agent_service_online(str(agent))
    ]
    decomposition_roles = preferred_roles or [
        str(agent)
        for agent in list(route["allowed_agents"])
        if str(agent) in {"codex", "claude", "gemini"}
    ]
    source_payload = task_payload or text
    if BOT_ROLE == "openclaw":
        source_payload = inject_openclaw_breakdown_into_payload(source_payload, text, decomposition_roles)
    registry = get_registry(context.application)
    task_id = registry.create_task(
        source_chat_id=str(update.effective_chat.id),
        source_message_id=str(getattr(update.message, "message_id", "")),
        source_user_id=str(getattr(update.effective_user, "id", "")),
        source_text=source_payload,
        category=str(route["category"]),
        route_reason=str(route["route_reason"]),
        allowed_agents=list(route["allowed_agents"]),
    )
    logging.info(
        "Created task id=%s category=%s allowed=%s text=%s",
        task_id,
        route["category"],
        format_allowed_agents(route["allowed_agents"]),
        summarize_text(text),
    )
    ack_text = (
        build_openclaw_dispatch_ack_text(text, decomposition_roles)
        if BOT_ROLE == "openclaw"
        else (
            f"[OpenClaw] 任务 #{task_id} 已创建\n"
            f"category={route['category']}\n"
            f"eligible={format_allowed_agents(route['allowed_agents'])}\n"
            f"reason={route['route_reason']}\n"
            f"summary={summarize_text(text)}"
        )
    )
    if BOT_ROLE == "openclaw":
        ack_text += (
            f"\n任务编号：#{task_id}"
            f"\ncategory={route['category']}"
            f"\neligible={format_allowed_agents(route['allowed_agents'])}"
            f"\nreason={route['route_reason']}"
            f"\nsummary={summarize_text(text)}"
        )
    get_memory_store(context.application).append_message(
        BOT_ROLE,
        str(getattr(update.effective_chat, "id", "")),
        str(getattr(update.effective_user, "id", "")),
        "assistant",
        ack_text,
    )
    await send_text_response(update, context, ack_text)


async def queue_group_message_for_self(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    history: List[Dict[str, str]],
    *,
    reason: str,
) -> None:
    route = classify_task(text)
    if reason == "runtime-monitoring-self-queue":
        route_payload = text
    else:
        route_payload = (
            build_dispatch_prompt(
                history,
                instant_memory=get_instant_memory_snapshot(
                    context.application,
                    str(getattr(update.effective_chat, "id", "")),
                ),
            )
            if history
            else text
        )
    registry = get_registry(context.application)
    task_id = registry.create_task(
        source_chat_id=str(update.effective_chat.id),
        source_message_id=str(getattr(update.effective_message, "message_id", "")),
        source_user_id=str(getattr(update.effective_user, "id", "")),
        source_text=route_payload,
        category=str(route["category"]),
        route_reason=f"group-self-queue:{BOT_ROLE}:{reason}",
        allowed_agents=[BOT_ROLE],
    )
    ack_text = (
        f"[{BOT_DISPLAY_NAME}] 收到，这条我切到任务链继续处理。"
        f"\n任务编号：#{task_id}"
        f"\nsummary={summarize_text(text)}"
    )
    memory_store = get_memory_store(context.application)
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    memory_store.append_message(BOT_ROLE, chat_id, user_id, "assistant", ack_text)
    mirror_group_result_to_openclaw_memory(
        memory_store,
        chat_id=chat_id,
        user_id=user_id,
        content=f"{ack_text}\nreason={reason}",
    )
    if ENABLE_SHARED_MEMORY_LOG:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="group-self-queue",
            task_summary=text,
            result_summary=reason,
            status="queued",
            task_id=task_id,
            category=str(route["category"]),
            allowed_agents=[BOT_ROLE],
        )
    await send_text_response(update, context, ack_text)
    if ENABLE_SHARED_MEMORY_LOG:
        get_shared_journal(context.application).append_event(
            bot_role=BOT_ROLE,
            scope="dispatch",
            task_summary=text,
            status="queued",
            task_id=task_id,
            category=str(route["category"]),
            allowed_agents=list(route["allowed_agents"]),
        )


def build_runtime_monitor_status_summary() -> str:
    status = ensure_runtime_monitor_process(target_chat_id=get_default_runtime_monitor_target())
    return render_runtime_monitor_status_summary(status)


def should_use_tenbagger_tool(text: str) -> bool:
    normalized = (text or "").lower()
    if "币安" not in normalized or "合约" not in normalized:
        return False
    if not any(keyword in normalized for keyword in ("10倍", "十倍", "1000%")):
        return False
    return any(keyword in normalized for keyword in ("筛选", "最低点", "最高点", "涨幅"))


def run_tenbagger_tool() -> str:
    if not TENBAGGER_SCRIPT_PATH.exists():
        return f"未找到现成脚本：{TENBAGGER_SCRIPT_PATH}"
    command = [
        "python3",
        str(TENBAGGER_SCRIPT_PATH),
        "--output-dir",
        str(TENBAGGER_OUTPUT_DIR),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
        cwd=str(TENBAGGER_SCRIPT_PATH.parent.parent),
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return f"调用 10 倍币筛选脚本失败：{detail[:1200] or '未知错误'}"

    json_path = TENBAGGER_OUTPUT_DIR / "binance_futures_tenbaggers.json"
    if not json_path.exists():
        return f"脚本已运行，但没有找到输出文件：{json_path}"

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"脚本已运行，但读取结果失败：{exc}"

    items = payload.get("items") or []
    count = int(payload.get("count") or len(items))
    if not items:
        return (
            "结论：脚本已跑完，但当前结果里没有筛出自 2026-01-01 以来从最低点到最高点涨幅达到 10 倍的 Binance U 本位合约。\n"
            f"结果文件：{json_path}\n"
            f"CSV 文件：{TENBAGGER_OUTPUT_DIR / 'binance_futures_tenbaggers.csv'}"
        )

    lines = [
        "结论：我已经直接调用现成脚本完成筛选。",
        f"命中数量：{count}",
        f"结果文件：{json_path}",
        f"CSV 文件：{TENBAGGER_OUTPUT_DIR / 'binance_futures_tenbaggers.csv'}",
        "前 10 个涨幅倍数最高的合约：",
    ]
    for item in items[:10]:
        symbol = item.get("symbol", "")
        ratio = float(item.get("ratio", 0) or 0)
        low_price = item.get("low_price", "")
        high_price = item.get("high_price", "")
        low_time = item.get("low_time_utc", "")
        high_time = item.get("high_time_utc", "")
        lines.append(
            f"- {symbol} | {ratio:.2f}x | low={low_price} @ {low_time} | high={high_price} @ {high_time}"
        )
    return "\n".join(lines)


def build_running_scripts_query_summary() -> str:
    lines: List[str] = []
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        ps_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        ps_lines = []

    def find_first(pattern: str) -> Optional[str]:
        for line in ps_lines:
            if pattern in line:
                return line
        return None

    openclaw_dispatch = find_first("group-openclaw.env") or find_first("group.openclaw.env")
    gemini_worker = find_first("group-gemini.env") or find_first("group.gemini.env")
    codex_bot = find_first("group-codex.env") or find_first("bot.py")
    monitor_loop = find_first("binance_monitor.py --market futures --loop")

    if openclaw_dispatch:
        lines.append(f"- {BASE_DIR / 'group_bot.py'} | 正在跑 | OpenClaw 群分派器")
    if gemini_worker:
        lines.append(f"- {BASE_DIR / 'group_bot.py'} | 正在跑 | Gemini 群 worker")
    if codex_bot:
        lines.append(f"- {BASE_DIR / 'bot.py'} | 正在跑 | Codex bot")
    if monitor_loop:
        lines.append(f"- {OPENCLAW_WORKSPACE_DIR / 'scripts' / 'binance_monitor.py'} | 正在跑 | 1 分钟波动达到 3% 或 5 分钟波动达到 10% 时实时通知")

    if not lines:
        lines.append("- 暂未检测到和当前群协作框架直接相关的活跃脚本。")

    return "结论：当前正在跑的核心脚本如下。\n运行中脚本：\n" + "\n".join(lines)


def build_system_health_summary() -> str:
    script_path = BASE_DIR / "health_check.sh"
    try:
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            cwd=str(BASE_DIR),
        )
    except Exception as exc:
        return f"结论：系统健康检查执行失败。\n原因：{exc}"

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return f"结论：系统健康检查没有返回内容。exit={result.returncode}"
    return output


def build_system_health_summary() -> str:
    script_path = BASE_DIR / "health_check.sh"
    try:
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            cwd=str(BASE_DIR),
        )
    except Exception as exc:
        return f"结论：系统健康检查执行失败。\n原因：{exc}"

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return f"结论：系统健康检查没有返回内容。exit={result.returncode}"
    return output


def get_runtime_monitor_paths() -> dict[str, Path]:
    workspace = Path.home() / ".openclaw" / "workspace"
    return {
        "workspace": workspace,
        "script": workspace / "scripts" / "binance_monitor.py",
        "log": workspace / "scripts" / "binance_monitor.log",
        "latest_report": workspace / "reports" / "binance-monitor" / "latest.md",
        "jobs": workspace / "cron" / "jobs.json",
    }


def list_runtime_monitor_processes() -> List[Dict[str, Any]]:
    processes: List[Dict[str, Any]] = []
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in result.stdout.splitlines():
            normalized = line.strip()
            if "binance_monitor.py" not in normalized or "--market futures" not in normalized:
                continue
            parts = normalized.split(None, 1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            command = parts[1] if len(parts) > 1 else ""
            processes.append({"pid": pid, "command": command})
    except Exception:
        return []
    return processes


def build_runtime_monitor_command(target_chat_id: str) -> List[str]:
    paths = get_runtime_monitor_paths()
    command = [
        "python3",
        str(paths["script"]),
        "--market",
        "futures",
        "--loop",
        "--send",
        "--interval-seconds",
        str(RUNTIME_MONITOR_INTERVAL_SECS),
        "--lookback-minutes",
        str(RUNTIME_MONITOR_LOOKBACK_MINUTES),
        "--min-lookback-price-move",
        f"{RUNTIME_MONITOR_MIN_LOOKBACK_MOVE:.1f}",
        "--secondary-lookback-minutes",
        str(RUNTIME_MONITOR_SECONDARY_LOOKBACK_MINUTES),
        "--secondary-min-lookback-price-move",
        f"{RUNTIME_MONITOR_SECONDARY_MIN_LOOKBACK_MOVE:.1f}",
        "--alert-mode",
        RUNTIME_MONITOR_ALERT_MODE,
    ]
    if target_chat_id:
        command.extend(["--target", target_chat_id])
    return command


def get_default_runtime_monitor_target() -> str:
    explicit_target = os.getenv("OPENCLAW_TELEGRAM_TARGET", "").strip()
    if explicit_target:
        return explicit_target
    if ALLOWED_USER_IDS:
        return str(sorted(ALLOWED_USER_IDS)[0])
    return ""


def is_desired_runtime_monitor_process(command: str, *, target_chat_id: str) -> bool:
    required_markers = [
        "binance_monitor.py",
        "--market futures",
        "--loop",
        "--send",
        f"--interval-seconds {RUNTIME_MONITOR_INTERVAL_SECS}",
        f"--lookback-minutes {RUNTIME_MONITOR_LOOKBACK_MINUTES}",
        f"--min-lookback-price-move {RUNTIME_MONITOR_MIN_LOOKBACK_MOVE:.1f}",
        f"--secondary-lookback-minutes {RUNTIME_MONITOR_SECONDARY_LOOKBACK_MINUTES}",
        f"--secondary-min-lookback-price-move {RUNTIME_MONITOR_SECONDARY_MIN_LOOKBACK_MOVE:.1f}",
        f"--alert-mode {RUNTIME_MONITOR_ALERT_MODE}",
    ]
    if target_chat_id:
        required_markers.append(f"--target {target_chat_id}")
    return all(marker in command for marker in required_markers)


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate_runtime_monitor_process(pid: int) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            return
        deadline = time.time() + 2
        while time.time() < deadline:
            if not is_process_alive(pid):
                return
            time.sleep(0.1)


def run_runtime_monitor_smoke(paths: dict[str, Path]) -> tuple[bool, str]:
    command = [
        "python3",
        str(paths["script"]),
        "--market",
        "futures",
        "--once",
        "--top",
        "3",
        "--lookback-minutes",
        str(RUNTIME_MONITOR_LOOKBACK_MINUTES),
        "--min-lookback-price-move",
        f"{RUNTIME_MONITOR_MIN_LOOKBACK_MOVE:.1f}",
        "--secondary-lookback-minutes",
        str(RUNTIME_MONITOR_SECONDARY_LOOKBACK_MINUTES),
        "--secondary-min-lookback-price-move",
        f"{RUNTIME_MONITOR_SECONDARY_MIN_LOOKBACK_MOVE:.1f}",
        "--alert-mode",
        RUNTIME_MONITOR_ALERT_MODE,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(paths["workspace"]),
            check=False,
        )
    except Exception as exc:
        return False, f"即时校验失败：{exc}"
    output = (result.stdout.strip() or result.stderr.strip() or f"exit {result.returncode}").splitlines()
    headline = output[0] if output else f"exit {result.returncode}"
    return result.returncode == 0, f"即时校验：{headline}"


def ensure_runtime_monitor_process(*, target_chat_id: str) -> Dict[str, Any]:
    paths = get_runtime_monitor_paths()
    processes = list_runtime_monitor_processes()
    desired = [proc for proc in processes if is_desired_runtime_monitor_process(proc["command"], target_chat_id=target_chat_id)]
    stale = [proc for proc in processes if proc not in desired]
    actions: List[str] = []

    for proc in stale:
        terminate_runtime_monitor_process(int(proc["pid"]))
        actions.append(f"已停止旧监控进程 PID {proc['pid']}")

    process_line = ""
    if desired:
        process_line = f"{desired[0]['pid']} {desired[0]['command']}"
    else:
        paths["log"].parent.mkdir(parents=True, exist_ok=True)
        with paths["log"].open("w", encoding="utf-8") as handle:
            proc = subprocess.Popen(
                build_runtime_monitor_command(target_chat_id),
                cwd=str(paths["workspace"]),
                stdout=handle,
                stderr=handle,
                start_new_session=True,
                text=True,
            )
        actions.append(f"已启动新的后台监控进程 PID {proc.pid}")
        time.sleep(1.0)
        process_line = f"{proc.pid} {' '.join(build_runtime_monitor_command(target_chat_id))}"

    smoke_ok, smoke_summary = run_runtime_monitor_smoke(paths)

    cron_summary = "未找到 binance_mover_watch 配置。"
    try:
        payload = json.loads(paths["jobs"].read_text(encoding="utf-8"))
        for job in payload.get("jobs", []):
            if job.get("name") == "binance_mover_watch":
                status = "已启用" if job.get("enabled") else "未启用"
                cron_summary = f"{status} | {job.get('schedule', '')} | {job.get('command', '')}"
                break
    except Exception:
        cron_summary = "读取 cron 配置失败。"

    report_lines: List[str] = []
    if paths["latest_report"].exists():
        try:
            report_lines = [
                line.strip()
                for line in paths["latest_report"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ][:6]
        except Exception:
            report_lines = []

    latest_log_line = ""
    if paths["log"].exists():
        try:
            lines = [line.strip() for line in paths["log"].read_text(encoding="utf-8").splitlines() if line.strip()]
            if lines:
                latest_log_line = lines[-1]
        except Exception:
            latest_log_line = ""

    if smoke_ok and latest_log_line.startswith("Binance request failed:"):
        latest_log_line = "后台监控刚按新参数重启，旧错误日志已失效；以本次即时校验成功为准。"

    return {
        "process_line": process_line or "未发现当前活跃的 binance_monitor.py 后台进程。",
        "cron_summary": cron_summary,
        "report_lines": report_lines,
        "latest_log_line": latest_log_line or "暂无日志输出。",
        "actions": actions,
        "smoke_summary": smoke_summary,
        "smoke_ok": smoke_ok,
    }


def render_runtime_monitor_status_summary(status: Dict[str, Any]) -> str:
    report_summary = " | ".join(status.get("report_lines") or []) or "未找到最新监控报告。"
    actions = status.get("actions") or ["监控进程参数已符合当前需求，无需重启。"]
    action_summary = "；".join(actions)

    return (
        "结论：我已经接管这条 Binance 合约异动监控链，现在线上按“1 分钟涨幅达到 3% 或 5 分钟涨幅达到 10% 就向 Gemini 私聊实时通知”执行。"
        f"\n执行动作：{action_summary}"
        f"\n运行状态：{status.get('process_line', '')}"
        f"\n定时任务：{status.get('cron_summary', '')}"
        f"\n即时校验：{status.get('smoke_summary', '')}"
        f"\n最新报告：{report_summary}"
        f"\n最新日志：{status.get('latest_log_line', '')}"
        "\n下一步：监控脚本会继续后台运行；一旦出现满足任一阈值的合约，就会实时发到 Gemini 私聊。"
    )


async def poll_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    await poll_tasks_for_app(app)


async def poll_tasks_for_app(app: Application) -> None:
    if BOT_MODE != "worker":
        return
    if app.bot_data.get("busy"):
        return

    registry = get_registry(app)
    reclaimed = registry.requeue_stale_claims(BOT_ROLE, TASK_STALE_CLAIM_SECS)
    if reclaimed:
        logging.warning(
            "Requeued stale claimed tasks role=%s ids=%s",
            BOT_ROLE,
            ",".join(str(task_id) for task_id in reclaimed),
        )
    tasks = registry.list_claimable_tasks(BOT_ROLE, limit=5)
    for task in tasks:
        task_id = int(task["id"])
        if not registry.claim_task(task_id, BOT_ROLE):
            continue
        app.bot_data["busy"] = True
        try:
            await process_task(app, task)
        finally:
            app.bot_data["busy"] = False
        return


async def process_task(app: Application, task: Dict[str, Any]) -> None:
    task_id = int(task["id"])
    chat_id = task["source_chat_id"]
    text = str(task["source_text"])
    route_reason = str(task.get("route_reason", ""))
    category = str(task.get("category", ""))
    is_return_task = category == DELEGATION_RETURN_CATEGORY or route_reason.startswith("delegation-return:")
    delegation_source_role, delegation_target_role = parse_route_pair(route_reason, "user-delegation:")
    logging.info("Worker %s claimed task #%s", BOT_ROLE, task_id)
    if not is_return_task:
        claim_text = f"[{BOT_DISPLAY_NAME}] 已认领任务 #{task_id}\nsummary={summarize_text(text)}"
        if delegation_source_role and delegation_target_role == BOT_ROLE:
            if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
                status_text = build_openclaw_step_status_text(text, BOT_ROLE, "进行中")
                claim_text = (
                    f"[{BOT_DISPLAY_NAME}] 已认领任务 #{task_id}。"
                    "我会先整理当前结果；如果需要技术协作，我会继续协调对应 bot，"
                    "然后直接向你同步，并把关键结论写回 OpenClaw 记忆。"
                )
                if status_text:
                    claim_text += f"\n{status_text}"
                get_memory_store(app).append_message(
                    "openclaw",
                    str(chat_id),
                    str(task.get("source_user_id", "")),
                    "assistant",
                    f"[任务 #{task_id} 步骤状态]\n{claim_text}",
                )
            else:
                claim_text = (
                    f"[{BOT_DISPLAY_NAME}] 已认领任务 #{task_id}，正在检查相关路径和代码链路。"
                    f"完成后我会把结果交回 {resolve_role_display_name(delegation_source_role)} 统一汇总。"
                )
        await app.bot.send_message(
            chat_id=chat_id,
            text=claim_text,
        )
    progress_task: Optional[asyncio.Task] = None
    if not is_return_task:
        progress_task = asyncio.create_task(
            notify_long_running_task(
                app,
                task_id=task_id,
                chat_id=str(chat_id),
                route_reason=route_reason,
            )
        )
    await app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    runner_cfg = get_runner_config()
    used_runtime_monitor_fastpath = False
    try:
        if route_reason == "group-self-queue:gemini:runtime-monitoring-self-queue" and BOT_ROLE == "gemini":
            result = await asyncio.to_thread(
                lambda: render_runtime_monitor_status_summary(
                    ensure_runtime_monitor_process(target_chat_id=str(task.get("source_user_id", "")))
                )
            )
            used_runtime_monitor_fastpath = True
        else:
            result = await asyncio.to_thread(run_task, text, runner_cfg)
        if is_return_task:
            summary = normalize_delegation_return_output(result, text, route_reason)
        elif used_runtime_monitor_fastpath:
            summary = result
        else:
            summary = summarize_text(result, limit=800)
        original_user_text = extract_original_user_text(text)
        get_registry(app).finish_task(task_id, BOT_ROLE, summary)
        get_memory_store(app).append_message(
            "openclaw",
            str(chat_id),
            str(task.get("source_user_id", "")),
            "assistant",
            f"[任务 #{task_id} 已由 {BOT_DISPLAY_NAME} 完成]\n{summary}",
        )
        if ENABLE_SHARED_MEMORY_LOG:
            get_shared_journal(app).append_event(
                bot_role=BOT_ROLE,
                scope="worker",
                task_summary=summarize_text(text),
                result_summary=summary,
                status="completed",
                task_id=task_id,
                category=str(task.get("category", "")),
                allowed_agents=list(task.get("allowed_agents", [])),
            )
        if delegation_source_role and delegation_target_role == BOT_ROLE:
            if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
                created = create_openclaw_followup_tasks_from_payload(
                    get_registry(app),
                    payload=text,
                    current_role=BOT_ROLE,
                    chat_id=str(chat_id),
                    source_user_id=str(task.get("source_user_id", "")),
                    original_user_text=original_user_text or text,
                    worker_result=summary,
                )
                if created:
                    status_text = build_openclaw_step_status_text(text, BOT_ROLE, "已完成")
                    for target_role, handoff_task_id in created:
                        logging.info(
                            "Created openclaw follow-up delegation role=%s target=%s task_id=%s parent_task=%s",
                            BOT_ROLE,
                            target_role,
                            handoff_task_id,
                            task_id,
                        )
                    followup_text = build_role_delegation_ack_text([role for role, _task_id in created])
                    if status_text:
                        followup_text += f"\n{status_text}"
                    get_memory_store(app).append_message(
                        "openclaw",
                        str(chat_id),
                        str(task.get("source_user_id", "")),
                        "assistant",
                        f"[任务 #{task_id} 步骤推进]\n{followup_text}",
                    )
                    await app.bot.send_message(chat_id=chat_id, text=followup_text)
                    logging.info("Worker %s finished task #%s via nested delegation", BOT_ROLE, task_id)
                    return
                if BOT_ROLE == "gemini" and not is_openclaw_final_summary_payload(text):
                    followup_roles = resolve_openclaw_followup_roles(
                        get_memory_store(app),
                        chat_id=str(chat_id),
                        user_text=original_user_text or text,
                        reply_text=summary,
                    )
                    if followup_roles:
                        created = create_user_delegation_tasks_for_roles(
                            get_registry(app),
                            source_role=BOT_ROLE,
                            chat_id=str(chat_id),
                            source_message_id="",
                            source_user_id=str(task.get("source_user_id", "")),
                            user_text=original_user_text or text,
                            history=[],
                            target_roles=followup_roles,
                        )
                        for target_role, handoff_task_id in created:
                            logging.info(
                                "Created openclaw follow-up delegation role=%s target=%s task_id=%s parent_task=%s",
                                BOT_ROLE,
                                target_role,
                                handoff_task_id,
                                task_id,
                            )
                        if created:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=build_role_delegation_ack_text([role for role, _task_id in created]),
                            )
                            logging.info("Worker %s finished task #%s via nested delegation", BOT_ROLE, task_id)
                            return
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[{BOT_DISPLAY_NAME}] 已完成任务 #{task_id}\n{summary}",
                )
                logging.info("Worker %s finished task #%s with direct reply for openclaw", BOT_ROLE, task_id)
                return
            return_task_id = create_delegation_return_task(
                get_registry(app),
                requester_role=delegation_source_role,
                worker_role=BOT_ROLE,
                chat_id=str(chat_id),
                source_user_id=str(task.get("source_user_id", "")),
                original_user_text=original_user_text,
                worker_result=summary,
            )
            logging.info(
                "Created delegation return role=%s target=%s task_id=%s",
                BOT_ROLE,
                delegation_source_role,
                return_task_id,
            )
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"[{BOT_DISPLAY_NAME}] 已完成任务 #{task_id} 的检查，"
                    f"结果已交回 {resolve_role_display_name(delegation_source_role)} 统一汇总。"
                ),
            )
            logging.info("Worker %s finished task #%s", BOT_ROLE, task_id)
            return
        if is_return_task:
            get_memory_store(app).append_message(
                BOT_ROLE,
                str(chat_id),
                str(task.get("source_user_id", "")),
                "assistant",
                summary,
            )
            await app.bot.send_message(chat_id=chat_id, text=summary)
            logging.info("Worker %s finished task #%s", BOT_ROLE, task_id)
            return
        await app.bot.send_message(
            chat_id=chat_id,
            text=f"[{BOT_DISPLAY_NAME}] 已完成任务 #{task_id}\n{summary}",
        )
        created = enqueue_handoff_tasks(
            get_registry(app),
            chat_id=str(chat_id),
            source_message_id="",
            source_user_id=str(task.get("source_user_id", "")),
            source_role=BOT_ROLE,
            user_text=text,
            reply_text=summary,
        )
        for target_role, handoff_task_id in created:
            logging.info(
                "Created worker handoff role=%s target=%s task_id=%s",
                BOT_ROLE,
                target_role,
                handoff_task_id,
            )
        logging.info("Worker %s finished task #%s", BOT_ROLE, task_id)
    except Exception as exc:
        error_text = summarize_text(str(exc), limit=800)
        get_registry(app).fail_task(task_id, BOT_ROLE, error_text)
        get_memory_store(app).append_message(
            "openclaw",
            str(chat_id),
            str(task.get("source_user_id", "")),
            "assistant",
            f"[任务 #{task_id} 执行失败，接手者 {BOT_DISPLAY_NAME}]\n{error_text}",
        )
        if ENABLE_SHARED_MEMORY_LOG:
            get_shared_journal(app).append_event(
                bot_role=BOT_ROLE,
                scope="worker",
                task_summary=summarize_text(text),
                result_summary=error_text,
                status="failed",
                task_id=task_id,
                category=str(task.get("category", "")),
                allowed_agents=list(task.get("allowed_agents", [])),
            )
        if delegation_source_role and delegation_target_role == BOT_ROLE:
            if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[{BOT_DISPLAY_NAME}] 任务 #{task_id} 这轮还没完全收口\n{error_text}",
                )
                logging.exception("Worker %s failed task #%s", BOT_ROLE, task_id)
                return
            return_task_id = create_delegation_return_task(
                get_registry(app),
                requester_role=delegation_source_role,
                worker_role=BOT_ROLE,
                chat_id=str(chat_id),
                source_user_id=str(task.get("source_user_id", "")),
                original_user_text=extract_original_user_text(text),
                worker_result=f"协作处理失败：{error_text}",
            )
            logging.info(
                "Created delegation return role=%s target=%s task_id=%s after failure",
                BOT_ROLE,
                delegation_source_role,
                return_task_id,
            )
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"[{BOT_DISPLAY_NAME}] 任务 #{task_id} 这轮还没完全收口，"
                    f"我已经把现有结果交回 {resolve_role_display_name(delegation_source_role)} 继续整理。"
                ),
            )
            logging.exception("Worker %s failed task #%s", BOT_ROLE, task_id)
            return
        await app.bot.send_message(
            chat_id=chat_id,
            text=f"[{BOT_DISPLAY_NAME}] 任务 #{task_id} 失败\n{error_text}",
        )
        logging.exception("Worker %s failed task #%s", BOT_ROLE, task_id)
    finally:
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Telegram handler error", exc_info=context.error)


async def worker_loop(app: Application) -> None:
    while True:
        try:
            await poll_tasks_for_app(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Worker polling loop failed")
        await asyncio.sleep(POLL_INTERVAL_SECS)


async def post_init(app: Application) -> None:
    if BOT_MODE == "worker":
        app.bot_data["poller_task"] = asyncio.create_task(worker_loop(app))


async def post_shutdown(app: Application) -> None:
    poller = app.bot_data.get("poller_task")
    if poller:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass


def main() -> None:
    configure_logging()
    validate_env()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.bot_data["registry"] = TaskRegistry(GROUP_TASK_DB_PATH)
    app.bot_data["memory_store"] = ConversationMemoryStore(MEMORY_DB_PATH, keep_messages=PERSISTED_HISTORY_LIMIT)
    app.bot_data["shared_memory_journal"] = SharedMemoryJournal(
        SHARED_MEMORY_DIR,
        timezone_name=MEMORY_TIMEZONE,
    )
    app.bot_data["long_term_memory_writer"] = LongTermMemoryWriter(
        LONG_TERM_MEMORY_SCRIPT_PATH,
        enabled=ALLOW_LONG_TERM_MEMORY_WRITE,
        timezone_name=MEMORY_TIMEZONE,
    )
    app.bot_data["busy"] = False

    app.add_handler(TypeHandler(Update, log_raw_update), group=-1)
    app.add_handler(CallbackQueryHandler(daily_report_callback, pattern=rf"^{DAILY_REPORT_CALLBACK_PREFIX}"))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("memory_recent", memory_recent_cmd))
    app.add_handler(CommandHandler("memory_search", memory_search_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    if BOT_ROLE == "openclaw":
        app.add_handler(CommandHandler("remember", remember_cmd))
    if BOT_MODE == "dispatcher":
        app.add_handler(CommandHandler(TASK_COMMAND, task_cmd))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, capture_dm_task)
        )
        if ALLOW_GROUP_CHAT:
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, capture_group_message)
            )
    elif ENABLE_DIRECT_PRIVATE_TASKS:
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, direct_private_message)
        )
        if ALLOW_GROUP_CHAT:
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, capture_group_message)
            )
    app.add_error_handler(on_error)

    logging.info(
        "Group bot starting role=%s mode=%s backend=%s workdir=%s db=%s memory_db=%s private_task_mode=%s long_term_memory=%s",
        BOT_ROLE,
        BOT_MODE,
        RUNNER_BACKEND or "-",
        WORKDIR,
        GROUP_TASK_DB_PATH,
        MEMORY_DB_PATH,
        PRIVATE_TASK_MODE,
        "on" if ALLOW_LONG_TERM_MEMORY_WRITE else "off",
    )
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
