#!/usr/bin/env python3
import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from memory_store import (
    ConversationMemoryStore,
    SharedMemoryJournal,
    build_instant_memory_snapshot,
    render_memory_search_digest,
    render_recent_memory_digest,
)
from openai import OpenAI
from routing import classify_group_message_semantics, classify_task
from task_registry import TaskRegistry
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters
from xhs_adapter import detect_xhs_text_intent, parse_xhs_command_args


BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "bot.log"
OPENCLAW_WORKSPACE_DIR = Path(
    os.getenv("OPENCLAW_WORKSPACE_DIR", str(Path.home() / ".openclaw" / "workspace"))
).expanduser()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BACKEND = os.getenv("BACKEND", "codex").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
CODEX_BIN = os.getenv("CODEX_BIN", "codex").strip()
CODEX_MODEL = os.getenv("CODEX_MODEL", "").strip()
CODEX_REASONING_EFFORT = os.getenv("CODEX_REASONING_EFFORT", "").strip()
CODEX_WORKDIR = os.getenv("CODEX_WORKDIR", str(Path.home())).strip()
CODEX_SANDBOX_MODE = os.getenv("CODEX_SANDBOX_MODE", "read-only").strip()
CODEX_TIMEOUT_SECS = int(os.getenv("CODEX_TIMEOUT_SECS", "180"))
GROUP_CODEX_MODEL = os.getenv("GROUP_CODEX_MODEL", CODEX_MODEL or "gpt-5.4-mini").strip()
GROUP_CODEX_WORKDIR = os.getenv("GROUP_CODEX_WORKDIR", CODEX_WORKDIR).strip()
GROUP_CODEX_TIMEOUT_SECS = int(os.getenv("GROUP_CODEX_TIMEOUT_SECS", str(CODEX_TIMEOUT_SECS)))
GROUP_CODEX_REASONING_EFFORT = os.getenv(
    "GROUP_CODEX_REASONING_EFFORT",
    CODEX_REASONING_EFFORT or "medium",
).strip()
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "你是一个简洁、可靠、友好的中文助手。").strip()
ALLOWED_USER_IDS = {
    int(user_id.strip())
    for user_id in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if user_id.strip().isdigit()
}
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "8000"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "8"))
PERSISTED_HISTORY_LIMIT = int(os.getenv("PERSISTED_HISTORY_LIMIT", "24"))
INSTANT_MEMORY_OWN_LIMIT = int(os.getenv("INSTANT_MEMORY_OWN_LIMIT", "6"))
INSTANT_MEMORY_SHARED_LIMIT = int(os.getenv("INSTANT_MEMORY_SHARED_LIMIT", "6"))
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", str(BASE_DIR / "bot-memory.sqlite3")).strip()
MEMORY_AGENT_ROLE = os.getenv("MEMORY_AGENT_ROLE", BACKEND or "bot").strip().lower() or "bot"
ALLOW_GROUP_CHAT = os.getenv("ALLOW_GROUP_CHAT", "true").strip().lower() in {"1", "true", "yes", "on"}
GROUP_TASK_CLAIM_ENABLED = os.getenv("GROUP_TASK_CLAIM_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
GROUP_TASK_DB_PATH = os.getenv("GROUP_TASK_DB_PATH", str(BASE_DIR / "group-tasks.sqlite3")).strip()
GROUP_WORKER_ROLE = os.getenv("GROUP_WORKER_ROLE", "codex").strip().lower()
GROUP_POLL_INTERVAL_SECS = int(os.getenv("GROUP_POLL_INTERVAL_SECS", "5"))
GROUP_PROGRESS_DELAY_SECS = int(os.getenv("GROUP_PROGRESS_DELAY_SECS", "45"))
GROUP_TASK_STALE_SECS = int(os.getenv("GROUP_TASK_STALE_SECS", "120"))
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
DANGEROUS_ACTION_CONFIRMATION = os.getenv("DANGEROUS_ACTION_CONFIRMATION", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DANGEROUS_ACTION_POLICY = os.getenv("DANGEROUS_ACTION_POLICY", "destructive-or-batch").strip().lower()
PENDING_CONFIRM_TTL_SECS = int(os.getenv("PENDING_CONFIRM_TTL_SECS", "600"))
NO_REPLY_SENTINEL = "[[NO_REPLY]]"
STANDALONE_XHS_BOT_USERNAME = "ukbossxiaohongshubot"
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
PRIVATE_PROGRESS_QUERY_PATTERNS = [
    r"在制作了吗",
    r"在做了吗",
    r"还在做吗",
    r"还在制作吗",
    r"做完了吗",
    r"完成了吗",
    r"进度(如何|怎么样|怎样)?",
    r"做到哪了",
    r"好了没",
    r"有进展吗",
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
CODEX_GROUP_QUEUE_KEYWORDS = [
    "安装",
    "install",
    "开发",
    "编写",
    "创建",
    "新增",
    "接入",
    "配置",
    "部署",
    "修复",
    "修改",
    "重构",
    "实现",
    "升级",
    "排查",
    "调试",
    "debug",
    "运行",
    "执行",
    "搭建",
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

DESTRUCTIVE_PATTERNS = [
    (r"\brm\b", "shell 删除命令"),
    (r"\bdel\b", "删除命令"),
    (r"\bunlink\b", "删除命令"),
    (r"\bgit\s+reset\b", "git 重置"),
    (r"\bgit\s+clean\b", "git 清理"),
    (r"\breboot\b", "系统重启"),
    (r"\bshutdown\b", "系统关机"),
    (r"\bmkfs\b", "磁盘格式化"),
    (r"\bdrop\s+table\b", "数据库删除"),
    (r"删除", "删除操作"),
    (r"移除", "删除操作"),
    (r"清空", "清空内容"),
    (r"重置", "重置操作"),
    (r"格式化", "格式化操作"),
]


def is_private_progress_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in PRIVATE_PROGRESS_QUERY_PATTERNS)

STRICT_ONLY_PATTERNS = [
    (r"\bchmod\b", "权限变更"),
    (r"\bchown\b", "所有者变更"),
    (r"\bkill\b", "进程终止"),
    (r"\bpkill\b", "进程终止"),
    (r"\blaunchctl\s+unload\b", "服务卸载"),
    (r"卸载", "卸载操作"),
    (r"杀掉", "进程终止"),
]

BATCH_PATTERNS = [
    (r"批量", "批量操作"),
    (r"所有文件", "批量操作"),
    (r"全部文件", "批量操作"),
    (r"整个目录", "目录级操作"),
    (r"整个文件夹", "目录级操作"),
    (r"整个仓库", "仓库级操作"),
    (r"递归", "递归操作"),
    (r"\bfind\b.*-exec\b", "批量命令"),
    (r"\bxargs\b", "批量命令"),
    (r"\bfor\b.+\bin\b", "批量命令"),
    (r"\bwhile\b", "批量命令"),
    (r"\*\.", "通配符批量操作"),
    (r"/\*", "通配符批量操作"),
]

MEMORY_STORE = ConversationMemoryStore(MEMORY_DB_PATH, keep_messages=PERSISTED_HISTORY_LIMIT)
SHARED_MEMORY_JOURNAL = SharedMemoryJournal(SHARED_MEMORY_DIR, timezone_name=MEMORY_TIMEZONE)


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
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if BACKEND == "openai" and not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if BACKEND == "codex" and not resolve_codex_bin():
        missing.append("CODEX_BIN")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    if BACKEND not in {"codex", "openai"}:
        raise RuntimeError("BACKEND must be either 'codex' or 'openai'")
    if DANGEROUS_ACTION_POLICY not in {"destructive-or-batch", "strict"}:
        raise RuntimeError("DANGEROUS_ACTION_POLICY must be 'destructive-or-batch' or 'strict'")
    if GROUP_TASK_CLAIM_ENABLED and GROUP_WORKER_ROLE not in {"codex", "claude", "gemini"}:
        raise RuntimeError("GROUP_WORKER_ROLE must be one of: codex, claude, gemini")


def resolve_codex_bin() -> str:
    if not CODEX_BIN:
        return ""
    if os.path.isabs(CODEX_BIN):
        return CODEX_BIN if os.path.exists(CODEX_BIN) else ""
    return shutil.which(CODEX_BIN) or ""


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
            "Allowing anonymous group sender chat_id=%s sender_chat_id=%s",
            getattr(chat, "id", None),
            getattr(sender_chat, "id", None),
        )
        return True

    if chat and is_group_like_chat(chat.type):
        logging.info(
            "Rejected group sender chat_id=%s user_id=%s sender_chat_id=%s",
            getattr(chat, "id", None),
            getattr(user, "id", None) if user else None,
            getattr(sender_chat, "id", None) if sender_chat else None,
        )
    return False


def summarize_text(text: str, limit: int = 80) -> str:
    sanitized = text.replace("\n", " ").strip()
    if len(sanitized) <= limit:
        return sanitized
    return f"{sanitized[:limit]}..."


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


def extract_ordered_message_mentions(message: Any) -> list[str]:
    ordered: list[str] = []
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


def resolve_user_delegation_targets(message: Any, self_username: str) -> list[str]:
    primary_mention = resolve_primary_group_bot_mention(message)
    if not primary_mention or primary_mention != self_username:
        return []

    targets: list[str] = []
    for mention in extract_ordered_message_mentions(message):
        normalized = mention.lower()
        if not normalized.endswith("bot") or normalized == self_username:
            continue
        if normalized not in targets:
            targets.append(normalized)
    return targets


def build_group_delegation_ack_text(target_mentions: list[str]) -> str:
    rendered = "、".join(f"@{mention}" for mention in target_mentions)
    if len(target_mentions) == 1:
        return (
            f"收到，这条我先接住。"
            f"我会先把相关脚本和数据链路整理后交给 {rendered} 协助处理，"
            "等他回我结果后我再统一向你汇报。"
        )
    return f"收到，这条我先接住。我会先协调 {rendered} 协助处理，等结果回来后我再统一向你汇报。"


def build_history_transcript(history: list[dict[str, str]], limit: int = 8) -> str:
    transcript: list[str] = []
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


def extract_path_status_lines(text: str) -> list[str]:
    candidates: list[str] = []
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


def should_bypass_openclaw_return_task(source_role: str, target_role: str) -> bool:
    return source_role == "openclaw" and target_role == GROUP_WORKER_ROLE


def normalize_delegation_return_output(result_text: str, payload: str, route_reason: str) -> str:
    cleaned = result_text.strip()
    worker_role, _requester_role = parse_route_pair(route_reason, "delegation-return:")
    if not looks_like_planning_text(cleaned):
        return cleaned[:4000]
    worker_result = extract_worker_result(payload, worker_role) or cleaned
    logging.info(
        "Normalizing delegation-return output role=%s route=%s because runner returned planning text",
        GROUP_WORKER_ROLE,
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


def parse_openclaw_breakdown_steps(payload: str) -> list[dict[str, str]]:
    marker = "OpenClaw 拆分结果："
    if marker not in payload:
        return []
    block = payload.split(marker, 1)[1]
    steps: list[dict[str, str]] = []
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


def resolve_openclaw_followup_roles_from_payload(payload: str, current_role: str) -> list[str]:
    steps = parse_openclaw_breakdown_steps(payload)
    if not steps:
        return []
    try:
        current_index = next(idx for idx, step in enumerate(steps) if step.get("owner") == current_role)
    except StopIteration:
        return []
    roles: list[str] = []
    for step in steps[current_index + 1 :]:
        role = str(step.get("owner", ""))
        if role and role not in roles:
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
    next_step = step_lookup.get(next_role, {})
    next_title = str(next_step.get("title", "")).strip() or "结果整理与汇报"
    next_goal = str(next_step.get("goal", "")).strip() or "基于前序结果继续完成当前步骤。"
    breakdown_lines = ["拆分计划："]
    for idx, step in enumerate(steps, start=1):
        breakdown_lines.append(
            f"{idx}. {resolve_role_display_name(str(step.get('owner', '')))}：{str(step.get('title', '')).strip()} - {str(step.get('goal', '')).strip()}"
        )
    breakdown_text = "\n".join(breakdown_lines) if len(breakdown_lines) > 1 else ""
    payload_text = (
        "来自 Telegram 群聊中 openclaw 的拆分后续步骤。\n"
        f"原始用户消息：{original_user_text}\n"
        f"上一位执行者：{resolve_role_display_name(current_role)}\n"
        f"当前需要你接手的角色：{resolve_role_display_name(next_role)}\n"
        f"当前步骤：{next_title}\n"
        f"目标：{next_goal}\n"
        f"上一阶段结果：{summarize_text(worker_result, limit=1600)}\n"
    )
    if breakdown_text:
        payload_text += f"\nOpenClaw 拆分结果：\n{breakdown_text}\n"
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
) -> list[tuple[str, int]]:
    next_roles = resolve_openclaw_followup_roles_from_payload(payload, current_role)
    created: list[tuple[str, int]] = []
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


def create_user_delegation_tasks(
    registry: TaskRegistry,
    *,
    source_role: str,
    chat_id: str,
    source_message_id: str,
    source_user_id: str,
    user_text: str,
    history: list[dict[str, str]],
    target_mentions: list[str],
) -> list[tuple[str, int]]:
    recent_user_notes: list[str] = []
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
    fast_path_hints: list[str] = []
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
    deduped_hints: list[str] = []
    for hint in fast_path_hints:
        if hint not in deduped_hints:
            deduped_hints.append(hint)
    created: list[tuple[str, int]] = []
    for target_mention in target_mentions:
        target_role = resolve_agent_role_from_mention(target_mention)
        if not target_role or target_role == source_role:
            continue
        payload = (
            f"来自 Telegram 群聊中 {source_role} 的用户指定协作请求。\n"
            f"原始用户消息：{user_text}\n"
            f"主责 bot：{source_role}\n"
            f"协作目标：{target_role}\n"
            "目标：检查相关代码或脚本，确认是否真的使用了最新市场数据，并给出最小修复建议。\n"
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
            "Ignoring group message for other bots chat_id=%s self=%s mentioned=%s",
            getattr(update.effective_chat, "id", None),
            self_username or "-",
            ",".join(sorted(bot_mentions)),
        )
        return False, False
    primary_mention = resolve_primary_group_bot_mention(message)
    if primary_mention and self_username != primary_mention:
        logging.info(
            "Ignoring delegated secondary mention chat_id=%s self=%s primary=%s mentioned=%s",
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


def extract_handoff_targets(text: str, source_role: str) -> list[str]:
    lowered = text.strip().lower()
    if not lowered or not any(keyword in lowered for keyword in HANDOFF_KEYWORDS):
        return []
    targets: list[str] = []
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
) -> list[tuple[str, int]]:
    created: list[tuple[str, int]] = []
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
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    text = text[:4000]
    if not is_group_like_chat(getattr(chat, "type", None)):
        await message.reply_text(text)
        return

    thread_id = getattr(message, "message_thread_id", None)
    try:
        await context.bot.send_message(chat_id=chat.id, text=text, message_thread_id=thread_id)
        return
    except BadRequest as exc:
        if not is_group_reply_fallback_error(exc):
            raise
        logging.warning(
            "Falling back to root group send chat_id=%s thread_id=%s error=%s",
            getattr(chat, "id", None),
            thread_id,
            exc,
        )
    await context.bot.send_message(chat_id=chat.id, text=text)


async def send_chunked_text_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    clean = text.strip() or "没有可返回的内容。"
    chunk_size = 3500
    for index in range(0, len(clean), chunk_size):
        await send_text_response(update, context, clean[index : index + chunk_size])


async def log_raw_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not is_group_like_chat(chat.type):
        return
    user = update.effective_user
    sender_chat = getattr(message, "sender_chat", None)
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    logging.info(
        "Raw update chat_type=%s chat_id=%s user_id=%s sender_chat_id=%s text=%s",
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
    await send_text_response(update, context, "机器人已启动，直接发送消息即可。")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    await send_text_response(
        update,
        context,
        "可用命令：\n"
        "/start - 启动提示\n"
        "/help - 查看帮助\n"
        "/ping - 健康检查\n"
        "/backend - 查看当前后端\n"
        "/memory_recent - 查看最近记忆摘要\n"
        "/memory_search - 按关键词搜索记忆\n"
        "/reset - 清空当前聊天上下文\n"
        "/confirm - 确认执行待确认的危险操作\n"
        "/cancel - 取消待确认的危险操作\n"
        "/whoami - 查看你的 Telegram user_id\n"
        f"小红书相关请私聊 @{STANDALONE_XHS_BOT_USERNAME}\n"
        f"直接发送文本即可对话；群聊自由对话={'on' if ALLOW_GROUP_CHAT else 'off'}。"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    await send_text_response(update, context, "pong")


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        await send_text_response(update, context, "无法读取当前用户信息。")
        return
    await send_text_response(update, context, f"user_id={user.id}")


async def backend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    if BACKEND == "codex":
        await send_text_response(
            update,
            context,
            "backend=codex\n"
            f"workdir={CODEX_WORKDIR}\n"
            f"sandbox={CODEX_SANDBOX_MODE}\n"
            f"group_chat={'on' if ALLOW_GROUP_CHAT else 'off'}\n"
            f"group_worker={'on' if GROUP_TASK_CLAIM_ENABLED else 'off'}\n"
            f"danger_confirm={'on' if DANGEROUS_ACTION_CONFIRMATION else 'off'}\n"
            f"danger_policy={DANGEROUS_ACTION_POLICY}"
        )
        return
    await send_text_response(update, context, f"backend=openai\nmodel={OPENAI_MODEL}")


async def memory_recent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    await send_text_response(update, context, build_recent_memory_response(chat_id))


async def memory_search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    query = " ".join(context.args).strip()
    if not query:
        await send_text_response(update, context, "用法：/memory_search 关键词")
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    await send_text_response(update, context, build_memory_search_response(chat_id, query))


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    MEMORY_STORE.clear_history(MEMORY_AGENT_ROLE, chat_id)
    MEMORY_STORE.clear_chat_profile(MEMORY_AGENT_ROLE, chat_id)
    context.chat_data.pop("pending_action", None)
    await send_text_response(update, context, "当前聊天上下文已清空。")


def build_xhs_redirect_text(*, user_text: str, xhs_args: Optional[list[str]]) -> str:
    suggested_command = None
    if xhs_args and xhs_args != ["help"]:
        command_map = {
            "doctor": "/doctor",
            "login-guide": "/login",
            "search": "/search",
            "search-summary": "/search_summary",
            "article-topic": "/article_topic",
            "article-outline": "/article_outline",
            "article-draft": "/article_draft",
            "feed": "/feed",
            "notifications": "/notifications",
            "creator-profile": "/creator_profile",
            "creator-stats": "/creator_stats",
            "creator-notes": "/creator_notes",
            "creator-notes-summary": "/creator_summary",
            "creator-daily-report": "/creator_daily_report",
            "monitor-scan": "/monitor_scan",
            "download": "/download",
        }
        base_command = command_map.get(xhs_args[0])
        if base_command:
            suffix = " ".join(item for item in xhs_args[1:] if str(item).strip())
            suggested_command = base_command if not suffix else f"{base_command} {suffix}"

    lines = [
        f"小红书相关能力已经独立到 @{STANDALONE_XHS_BOT_USERNAME} 管理，主 bot 不再执行小红书请求，避免上下文和记忆被污染。",
        f"请直接私聊 @{STANDALONE_XHS_BOT_USERNAME} 继续处理。",
    ]
    if suggested_command:
        lines.extend(["", f"建议你直接发送：{suggested_command}"])
    elif user_text.strip():
        lines.extend(["", "也可以把你刚才这条需求原样转发给独立小红书 bot。"])
    return "\n".join(lines)


async def execute_xhs_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_text: str,
    xhs_args: list[str],
) -> None:
    logging.info(
        "Redirecting XHS request to standalone bot chat_id=%s user_id=%s args=%s",
        getattr(update.effective_chat, "id", None),
        getattr(update.effective_user, "id", None),
        " ".join(xhs_args),
    )
    reply_text = build_xhs_redirect_text(user_text=user_text, xhs_args=xhs_args)
    await send_text_response(update, context, reply_text)


async def xhs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return

    xhs_args, _error = parse_xhs_command_args(context.args)
    suffix = " ".join(context.args).strip()
    user_text = "/xhs" if not suffix else f"/xhs {suffix}"
    await execute_xhs_request(
        update,
        context,
        user_text=user_text,
        xhs_args=xhs_args or ["help"],
    )


def get_pending_action(context: ContextTypes.DEFAULT_TYPE) -> Optional[dict[str, object]]:
    pending = context.chat_data.get("pending_action")
    if not pending:
        return None
    created_at = float(pending.get("created_at", 0))
    if time.time() - created_at > PENDING_CONFIRM_TTL_SECS:
        context.chat_data.pop("pending_action", None)
        return None
    return pending


def is_dangerous_action(text: str) -> list[str]:
    reasons = []
    lowered = text.lower()
    active_patterns = list(DESTRUCTIVE_PATTERNS) + list(BATCH_PATTERNS)
    if DANGEROUS_ACTION_POLICY == "strict":
        active_patterns.extend(STRICT_ONLY_PATTERNS)
    for pattern, label in active_patterns:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            reasons.append(label)
    return list(dict.fromkeys(reasons))


async def confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return

    pending = get_pending_action(context)
    if not pending:
        await send_text_response(update, context, "当前没有待确认的危险操作。")
        return

    context.chat_data.pop("pending_action", None)
    user_text = str(pending["text"])
    logging.info(
        "Confirmed dangerous action chat_id=%s text=%s",
        getattr(update.effective_chat, "id", None),
        summarize_text(user_text),
    )
    await execute_user_message(update, context, user_text)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return
    if context.chat_data.pop("pending_action", None):
        await send_text_response(update, context, "已取消待确认的危险操作。")
        return
    await send_text_response(update, context, "当前没有待确认的危险操作。")


def get_history(chat_id: str) -> list[dict[str, str]]:
    return MEMORY_STORE.get_history(MEMORY_AGENT_ROLE, chat_id, MAX_HISTORY_MESSAGES)


def get_instant_memory_snapshot(chat_id: str) -> str:
    return build_instant_memory_snapshot(
        MEMORY_STORE,
        bot_role=MEMORY_AGENT_ROLE,
        chat_id=chat_id,
        own_limit=INSTANT_MEMORY_OWN_LIMIT,
        shared_limit=INSTANT_MEMORY_SHARED_LIMIT,
    )


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


def build_recent_memory_response(chat_id: str) -> str:
    return render_recent_memory_digest(
        MEMORY_STORE,
        bot_role=MEMORY_AGENT_ROLE,
        chat_id=chat_id,
        own_limit=INSTANT_MEMORY_OWN_LIMIT,
        shared_limit=INSTANT_MEMORY_SHARED_LIMIT,
    )


def build_memory_search_response(chat_id: str, query: str) -> str:
    return render_memory_search_digest(
        MEMORY_STORE,
        bot_role=MEMORY_AGENT_ROLE,
        chat_id=chat_id,
        query=query,
    )


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


def append_history(chat_id: str, user_id: str, role: str, content: str) -> None:
    MEMORY_STORE.append_message(MEMORY_AGENT_ROLE, chat_id, user_id, role, content)


def mirror_group_result_to_openclaw_memory(chat_id: str, user_id: str, content: str) -> None:
    clean = content.strip()
    if MEMORY_AGENT_ROLE == "openclaw" or not clean:
        return
    MEMORY_STORE.append_message(
        "openclaw",
        chat_id,
        user_id,
        "assistant",
        f"[群聊结果 · {resolve_role_display_name(MEMORY_AGENT_ROLE)}]\n{clean}",
    )


def should_force_group_reply(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
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
        "#codex",
    ]
    return any(keyword in lowered for keyword in force_keywords)


def is_daily_digest_summary_query(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    report_keywords = [
        "晨报",
        "早报",
        "日报",
        "币安异动",
        "github 热门",
        "github热门",
        "热门仓库",
        "x 情报",
        "x情报",
        "市场情绪",
    ]
    if not any(keyword in lowered for keyword in report_keywords):
        return False
    implementation_keywords = [
        "脚本",
        "代码",
        "开发",
        "实现",
        "修复",
        "优化",
        "修改",
        "重写",
        "配置",
        "部署",
        "接入",
        "调度",
        "监控",
        "任务",
    ]
    return not any(keyword in lowered for keyword in implementation_keywords)


def should_ignore_group_summary_query_for_codex(text: str, mentioned_self: bool) -> bool:
    if MEMORY_AGENT_ROLE != "codex":
        return False
    if mentioned_self:
        return False
    return is_daily_digest_summary_query(text)


def should_route_unmentioned_group_task_to_openclaw(
    text: str,
    *,
    chat_type: Optional[str] = None,
    mentioned_self: bool = False,
) -> bool:
    if mentioned_self or not is_group_like_chat(chat_type):
        return False
    if should_ignore_group_summary_query_for_codex(text, mentioned_self):
        return False
    return classify_group_message_semantics(text) == "task"


def should_queue_explicit_group_request_for_codex(
    text: str,
    *,
    mentioned_self: bool,
    message_semantics: str,
) -> bool:
    if MEMORY_AGENT_ROLE != "codex":
        return False
    if not mentioned_self or message_semantics != "task":
        return False
    route = classify_task(text)
    allowed_agents = route.get("allowed_agents", [])
    if not isinstance(allowed_agents, list) or "codex" not in allowed_agents:
        return False
    lowered = text.strip().lower()
    return any(keyword in lowered for keyword in CODEX_GROUP_QUEUE_KEYWORDS)


def build_codex_group_self_queue_payload(user_text: str) -> str:
    return (
        "来自 Telegram 群聊中用户对 codex 的显式执行请求。\n"
        f"原始用户消息：{user_text}\n"
        "请直接在当前工作目录内执行这条安装、开发、配置或排障任务。"
        "默认用简体中文向群里回复最终结果。\n"
        "建议格式：结论：...\\n已完成：...\\n验证：...\\n下一步：...\n"
        "不要暴露思考过程，不要只给建议，优先直接落地。"
    )


async def queue_group_message_for_codex_self(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    registry = context.application.bot_data.get("group_registry")
    if not registry:
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    append_history(chat_id, user_id, "user", text)
    task_id = registry.create_task(
        source_chat_id=chat_id,
        source_message_id=str(getattr(update.effective_message, "message_id", "")),
        source_user_id=user_id,
        source_text=build_codex_group_self_queue_payload(text),
        category="group-self-queue",
        route_reason="group-self-queue:codex:explicit-execution",
        allowed_agents=["codex"],
    )
    ack_text = (
        f"[Codex] 收到，这条我切到任务链继续处理。"
        f"\n任务编号：#{task_id}"
        f"\nsummary={summarize_text(text)}"
    )
    append_history(chat_id, user_id, "assistant", ack_text)
    mirror_group_result_to_openclaw_memory(chat_id, user_id, f"{ack_text}\nreason=explicit-execution")
    if ENABLE_SHARED_MEMORY_LOG:
        SHARED_MEMORY_JOURNAL.append_event(
            bot_role=MEMORY_AGENT_ROLE,
            scope="group-self-queue",
            task_summary=text,
            result_summary="explicit-execution",
            status="queued",
            task_id=task_id,
            category="group-self-queue",
            allowed_agents=["codex"],
        )
    await send_text_response(update, context, ack_text)


def build_codex_prompt(
    history: list[dict[str, str]],
    chat_scope: str,
    force_reply: bool = False,
    group_role_note: str = "",
    instant_memory: str = "",
) -> str:
    transcript = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        transcript.append(f"[{role}]\n{item['content']}")

    transcript_text = "\n\n".join(transcript)
    if chat_scope == "group":
        reply_rule = (
            "请直接回应最后一条群消息，并像正常群成员一样自然发言。"
            if force_reply
            else f"如果你不需要从自己的角色出面回应，或者你的回复不会增加明显价值，请只输出 {NO_REPLY_SENTINEL}。"
        )
        role_prefix = ""
        if group_role_note:
            role_prefix = (
                f"当前群内为你指定的职责：{group_role_note}\n"
                "这条职责只在当前群生效，不适用于私聊或其他群。\n"
            )
        return (
            "你正在 Telegram 群聊中与同一个用户以及其他 bot 协作。\n"
            f"系统要求：{SYSTEM_PROMPT}\n"
            f"当前工作目录：{CODEX_WORKDIR}\n"
            f"{role_prefix}"
            f"{instant_memory + chr(10) if instant_memory else ''}"
            f"{reply_rule}\n"
            "默认用简体中文在群里回复；只有用户明确要求其他语言时才切换语言。\n"
            "如果需要回复，可以自然参与群聊；如果是执行型请求，可以直接完成并给出结果。"
            "不要解释内部系统。\n\n"
            f"{transcript_text}"
        )
    return (
        "你正在通过 Telegram 与同一个用户持续对话。\n"
        f"系统要求：{SYSTEM_PROMPT}\n"
        f"当前工作目录：{CODEX_WORKDIR}\n\n"
        f"{instant_memory + chr(10) if instant_memory else ''}"
        "默认用简体中文直接回复用户；只有用户明确要求其他语言时才切换语言。\n"
        "下面是最近的对话历史，请继续回复最后一条用户消息。"
        "如需使用本机能力，请按需操作并保持回复简洁。\n\n"
        f"{transcript_text}"
    )


def run_codex(
    prompt: str,
    *,
    workdir: Optional[str] = None,
    timeout_secs: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    codex_bin = resolve_codex_bin()
    if not codex_bin:
        return "未找到 codex 可执行文件，无法使用 codex 后端。"
    active_workdir = workdir or CODEX_WORKDIR
    active_timeout = timeout_secs or CODEX_TIMEOUT_SECS

    with tempfile.NamedTemporaryFile(prefix="telegram-codex-", suffix=".txt", delete=False) as tmp:
        output_path = tmp.name

    command = [
        codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--disable",
        "memories",
        "-C",
        active_workdir,
        "-s",
        CODEX_SANDBOX_MODE,
        "-o",
        output_path,
    ]
    active_model = (model or CODEX_MODEL).strip()
    if active_model:
        command.extend(["-m", active_model])
    active_reasoning_effort = (reasoning_effort or CODEX_REASONING_EFFORT).strip()
    if active_reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{active_reasoning_effort}"'])
    command.append(prompt)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=active_timeout,
            check=False,
        )
        output_text = Path(output_path).read_text(encoding="utf-8").strip()
    except subprocess.TimeoutExpired:
        logging.exception("Codex request timed out")
        return f"Codex 执行超时，超过 {active_timeout} 秒。"
    except Exception:
        logging.exception("Codex request failed")
        return "Codex 执行失败，请稍后重试。"
    finally:
        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            logging.exception("Failed to cleanup temporary output file")

    if result.returncode == 0 and output_text:
        return output_text

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    error_text = stderr or stdout or output_text or "未知错误"
    return f"Codex 执行失败：{error_text[:1000]}"


def run_openai(history: list[dict[str, str]]) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-MAX_HISTORY_MESSAGES:])
    response = client.responses.create(model=OPENAI_MODEL, input=messages)
    return response.output_text or "暂时没有生成内容，请重试。"


def run_backend_for_task(prompt: str) -> str:
    if BACKEND == "codex":
        return run_codex(
            prompt,
            workdir=GROUP_CODEX_WORKDIR,
            timeout_secs=GROUP_CODEX_TIMEOUT_SECS,
            reasoning_effort=GROUP_CODEX_REASONING_EFFORT,
            model=GROUP_CODEX_MODEL,
        )
    return run_openai([{"role": "user", "content": prompt}])


async def notify_long_running_group_task(
    app: Application,
    *,
    task_id: int,
    chat_id: str,
    route_reason: str,
) -> None:
    await asyncio.sleep(GROUP_PROGRESS_DELAY_SECS)
    task = app.bot_data["group_registry"].get_task(task_id)
    if not task or str(task.get("status", "")) != "claimed":
        return

    delegation_source_role, delegation_target_role = parse_route_pair(route_reason, "user-delegation:")
    if delegation_source_role and delegation_target_role == GROUP_WORKER_ROLE:
        if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
            text = (
                f"[Codex] 任务 #{task_id} 仍在处理中，"
                "我会继续直接同步进展，并把关键结果写回 OpenClaw 记忆。"
            )
        else:
            text = (
                f"[Codex] 任务 #{task_id} 仍在检查相关路径和代码链路，"
                f"完成后我会先把结果交回 {resolve_role_display_name(delegation_source_role)} 统一汇总。"
            )
    else:
        text = f"[Codex] 任务 #{task_id} 仍在处理中，我会在完成后继续同步结果。"
    await app.bot.send_message(chat_id=chat_id, text=text)


async def execute_user_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_text: str,
    force_group_reply: bool = False,
    group_role_assignment: bool = False,
    message_semantics: str = "task",
) -> None:
    chat_id = str(getattr(update.effective_chat, "id", ""))
    user_id = str(getattr(update.effective_user, "id", ""))
    chat_scope = "group" if is_group_like_chat(getattr(update.effective_chat, "type", "")) else "private"
    force_reply = (force_group_reply or should_force_group_reply(user_text)) if chat_scope == "group" else False
    group_role_note = MEMORY_STORE.get_chat_profile(MEMORY_AGENT_ROLE, chat_id) if chat_scope == "group" else ""
    lock = context.application.bot_data.get("backend_lock")
    if (
        chat_scope == "private"
        and BACKEND == "codex"
        and lock
        and lock.locked()
        and is_private_progress_query(user_text)
    ):
        active_request = context.application.bot_data.get("active_private_request") or {}
        if active_request.get("chat_id") == chat_id:
            started_at = float(active_request.get("started_at") or time.time())
            elapsed = max(1, int(time.time() - started_at))
            summary = summarize_text(str(active_request.get("summary") or "上一条任务"), limit=80)
            reply_text = (
                "上一条私聊任务还在处理中。\n"
                f"任务摘要：{summary}\n"
                f"已运行：约 {elapsed} 秒\n"
                "我处理完会继续回复你，这条进度询问不再重新发起新的 Codex 任务。"
            )
            append_history(chat_id, user_id, "user", user_text)
            append_history(chat_id, user_id, "assistant", reply_text)
            await send_text_response(update, context, reply_text)
            logging.info(
                "Short-circuited private progress query chat_id=%s active_summary=%s",
                getattr(update.effective_chat, "id", None),
                summary,
            )
            return
    if chat_scope == "private":
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    append_history(chat_id, user_id, "user", user_text)
    history = get_history(chat_id)
    instant_memory = get_instant_memory_snapshot(chat_id)
    try:
        logging.info("Dispatching backend=%s history_items=%s", BACKEND, len(history))
        if lock:
            async with lock:
                if chat_scope == "private":
                    context.application.bot_data["active_private_request"] = {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "summary": user_text,
                        "started_at": time.time(),
                    }
                if BACKEND == "codex":
                    prompt = build_codex_prompt(
                        history,
                        chat_scope,
                        force_reply=force_reply,
                        group_role_note=group_role_note,
                        instant_memory=instant_memory,
                    )
                    answer = await asyncio.to_thread(run_codex, prompt)
                else:
                    answer = await asyncio.to_thread(run_openai, history)
        elif BACKEND == "codex":
            if chat_scope == "private":
                context.application.bot_data["active_private_request"] = {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "summary": user_text,
                    "started_at": time.time(),
                }
            prompt = build_codex_prompt(
                history,
                chat_scope,
                force_reply=force_reply,
                group_role_note=group_role_note,
                instant_memory=instant_memory,
            )
            answer = await asyncio.to_thread(run_codex, prompt)
        else:
            answer = await asyncio.to_thread(run_openai, history)
    except Exception:
        logging.exception("Backend request failed")
        answer = "调用后端失败，请稍后重试。"
    finally:
        active_request = context.application.bot_data.get("active_private_request") or {}
        if chat_scope == "private" and active_request.get("chat_id") == chat_id:
            context.application.bot_data.pop("active_private_request", None)

    reply_text = (answer or "").strip()
    if chat_scope == "group" and (not reply_text or reply_text == NO_REPLY_SENTINEL):
        logging.info("Suppressed group reply chat_id=%s", getattr(update.effective_chat, "id", None))
        return

    reply_text = reply_text[:4000]
    if chat_scope == "group":
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    append_history(chat_id, user_id, "assistant", reply_text)
    if chat_scope == "group" and not group_role_assignment:
        mirror_group_result_to_openclaw_memory(chat_id, user_id, reply_text)
    if ENABLE_SHARED_MEMORY_LOG and not (chat_scope == "group" and group_role_assignment):
        SHARED_MEMORY_JOURNAL.append_event(
            bot_role=MEMORY_AGENT_ROLE,
            scope="group" if chat_scope == "group" else "private",
            task_summary=user_text,
            result_summary=reply_text,
            status="completed",
        )
    await send_text_response(update, context, reply_text)
    logging.info("Sent reply chat_id=%s chars=%s", getattr(update.effective_chat, "id", None), len(reply_text))
    if chat_scope == "group":
        registry = context.application.bot_data.get("group_registry")
        if registry and message_semantics != "casual":
            created = enqueue_handoff_tasks(
                registry,
                chat_id=chat_id,
                source_message_id=str(getattr(update.effective_message, "message_id", "")),
                source_user_id=user_id,
                source_role=MEMORY_AGENT_ROLE,
                user_text=user_text,
                reply_text=reply_text,
            )
            for target_role, task_id in created:
                logging.info(
                    "Created bot handoff source=%s target=%s task_id=%s",
                    MEMORY_AGENT_ROLE,
                    target_role,
                    task_id,
                )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        logging.warning("Rejected unauthorized user_id=%s", getattr(update.effective_user, "id", None))
        await send_text_response(update, context, "未授权用户，无法使用该机器人。")
        return

    if is_group_like_chat(getattr(update.effective_chat, "type", "")) and not ALLOW_GROUP_CHAT:
        return

    user_text = (update.message.text or "").strip()
    if not user_text:
        logging.info("Ignored empty message chat_id=%s", getattr(update.effective_chat, "id", None))
        return
    chat_id = str(getattr(update.effective_chat, "id", ""))
    memory_search_query = extract_memory_search_query(user_text)
    if memory_search_query:
        append_history(chat_id, str(getattr(update.effective_user, "id", "")), "user", user_text)
        await send_text_response(update, context, build_memory_search_response(chat_id, memory_search_query))
        return
    if is_recent_memory_query(user_text):
        append_history(chat_id, str(getattr(update.effective_user, "id", "")), "user", user_text)
        await send_text_response(update, context, build_recent_memory_response(chat_id))
        return
    if is_system_health_query(user_text):
        append_history(chat_id, str(getattr(update.effective_user, "id", "")), "user", user_text)
        reply_text = build_system_health_summary()
        append_history(chat_id, str(getattr(update.effective_user, "id", "")), "assistant", reply_text)
        if is_group_like_chat(getattr(update.effective_chat, "type", "")):
            mirror_group_result_to_openclaw_memory(chat_id, str(getattr(update.effective_user, "id", "")), reply_text)
        await send_text_response(update, context, reply_text)
        return

    mentioned_self = False
    group_role_assignment = False
    self_username = ""
    delegation_targets: list[str] = []
    message_semantics = classify_group_message_semantics(user_text) if is_group_like_chat(getattr(update.effective_chat, "type", "")) else "task"
    if is_group_like_chat(getattr(update.effective_chat, "type", "")):
        should_handle, mentioned_self = should_handle_group_message_for_bot(update, context)
        if not should_handle:
            return
        if should_ignore_group_summary_query_for_codex(user_text, mentioned_self):
            logging.info(
                "Ignoring digest-style group query for codex chat_id=%s text=%s",
                getattr(update.effective_chat, "id", None),
                summarize_text(user_text),
            )
            return
        if should_route_unmentioned_group_task_to_openclaw(
            user_text,
            chat_type=getattr(update.effective_chat, "type", None),
            mentioned_self=mentioned_self,
        ):
            logging.info(
                "Ignoring unmentioned group task for codex chat_id=%s text=%s",
                getattr(update.effective_chat, "id", None),
                summarize_text(user_text),
            )
            return
        self_username = (
            (getattr(context.bot, "username", None) or "")
            .strip()
            .lower()
            .lstrip("@")
        )
        delegation_targets = resolve_user_delegation_targets(update.effective_message, self_username)
        group_role_assignment = is_group_role_assignment(user_text, mentioned_self)
        if group_role_assignment:
            note = build_group_role_note(user_text)
            MEMORY_STORE.set_chat_profile(MEMORY_AGENT_ROLE, str(getattr(update.effective_chat, "id", "")), note)
            logging.info(
                "Updated group profile chat_id=%s profile=%s",
                getattr(update.effective_chat, "id", None),
                summarize_text(note, limit=120),
            )
        elif message_semantics != "casual" and delegation_targets:
            chat_id = str(getattr(update.effective_chat, "id", ""))
            user_id = str(getattr(update.effective_user, "id", ""))
            append_history(chat_id, user_id, "user", user_text)
            history = get_history(chat_id)
            ack_text = build_group_delegation_ack_text(delegation_targets)
            append_history(chat_id, user_id, "assistant", ack_text)
            await send_text_response(update, context, ack_text)
            registry = context.application.bot_data.get("group_registry")
            if registry:
                created = create_user_delegation_tasks(
                    registry,
                    source_role=MEMORY_AGENT_ROLE,
                    chat_id=chat_id,
                    source_message_id=str(getattr(update.effective_message, "message_id", "")),
                    source_user_id=user_id,
                    user_text=user_text,
                    history=history,
                    target_mentions=delegation_targets,
                )
                for target_role, task_id in created:
                    logging.info(
                        "Created user delegation source=%s target=%s task_id=%s",
                        MEMORY_AGENT_ROLE,
                        target_role,
                        task_id,
                    )
            return
        elif should_queue_explicit_group_request_for_codex(
            user_text,
            mentioned_self=mentioned_self,
            message_semantics=message_semantics,
        ):
            await queue_group_message_for_codex_self(update, context, user_text)
            return

    logging.info(
        "Received message chat_id=%s user_id=%s text=%s",
        getattr(update.effective_chat, "id", None),
        getattr(update.effective_user, "id", None),
        summarize_text(user_text),
    )
    if is_group_like_chat(getattr(update.effective_chat, "type", "")):
        logging.info(
            "Received group message chat_id=%s user_id=%s force_reply=%s",
            getattr(update.effective_chat, "id", None),
            getattr(update.effective_user, "id", None),
            "yes" if (mentioned_self or should_force_group_reply(user_text) or message_semantics == "casual") else "no",
        )

    if len(user_text) > MAX_INPUT_CHARS:
        logging.warning("Rejected long message len=%s", len(user_text))
        await send_text_response(update, context, f"输入过长，请控制在 {MAX_INPUT_CHARS} 字以内。")
        return

    xhs_args = detect_xhs_text_intent(user_text)
    if xhs_args:
        logging.info(
            "Routing message to XHS adapter chat_id=%s user_id=%s args=%s",
            getattr(update.effective_chat, "id", None),
            getattr(update.effective_user, "id", None),
            " ".join(xhs_args),
        )
        await execute_xhs_request(
            update,
            context,
            user_text=user_text,
            xhs_args=xhs_args,
        )
        return

    if DANGEROUS_ACTION_CONFIRMATION and BACKEND == "codex" and CODEX_SANDBOX_MODE != "read-only":
        reasons = is_dangerous_action(user_text)
        if reasons:
            context.chat_data["pending_action"] = {
                "text": user_text,
                "created_at": time.time(),
                "reasons": reasons,
            }
            logging.info(
                "Queued dangerous action chat_id=%s reasons=%s",
                getattr(update.effective_chat, "id", None),
                ",".join(reasons),
            )
            await send_text_response(
                update,
                context,
                "检测到危险操作，尚未执行。\n"
                f"风险类型：{', '.join(reasons)}\n"
                f"待执行内容：{summarize_text(user_text, limit=120)}\n"
                "发送 /confirm 执行，或 /cancel 取消。"
            )
            return

    await execute_user_message(
        update,
        context,
        user_text,
        force_group_reply=mentioned_self or message_semantics == "casual",
        group_role_assignment=group_role_assignment,
        message_semantics=message_semantics,
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Telegram handler error", exc_info=context.error)


async def poll_group_tasks_for_app(app: Application) -> None:
    if not GROUP_TASK_CLAIM_ENABLED:
        return
    registry = app.bot_data["group_registry"]
    reclaimed = registry.requeue_stale_claims(GROUP_WORKER_ROLE, GROUP_TASK_STALE_SECS)
    if reclaimed:
        logging.warning(
            "Requeued stale claimed tasks role=%s ids=%s",
            GROUP_WORKER_ROLE,
            ",".join(str(task_id) for task_id in reclaimed),
        )
    tasks = registry.list_claimable_tasks(GROUP_WORKER_ROLE, limit=5)
    for task in tasks:
        task_id = int(task["id"])
        if not registry.claim_task(task_id, GROUP_WORKER_ROLE):
            continue
        try:
            await process_group_task(app, task)
        finally:
            return


async def process_group_task(app: Application, task: dict[str, Any]) -> None:
    task_id = int(task["id"])
    chat_id = str(task["source_chat_id"])
    source_user_id = str(task.get("source_user_id", ""))
    prompt = str(task["source_text"])
    route_reason = str(task.get("route_reason", ""))
    category = str(task.get("category", ""))
    is_return_task = category == DELEGATION_RETURN_CATEGORY or route_reason.startswith("delegation-return:")
    delegation_source_role, delegation_target_role = parse_route_pair(route_reason, "user-delegation:")
    logging.info("Group worker %s claimed task #%s", GROUP_WORKER_ROLE, task_id)
    if not is_return_task:
        claim_text = f"[Codex] 已认领任务 #{task_id}\nsummary={summarize_text(prompt, limit=120)}"
        if delegation_source_role and delegation_target_role == GROUP_WORKER_ROLE:
            if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
                status_text = build_openclaw_step_status_text(prompt, GROUP_WORKER_ROLE, "进行中")
                claim_text = (
                    f"[Codex] 已认领任务 #{task_id}。"
                    "我会直接处理并向群里同步结果，同时把关键结论写回 OpenClaw 记忆。"
                )
                if status_text:
                    claim_text += f"\n{status_text}"
                MEMORY_STORE.append_message(
                    "openclaw",
                    chat_id,
                    source_user_id,
                    "assistant",
                    f"[任务 #{task_id} 步骤状态]\n{claim_text}",
                )
            else:
                claim_text = (
                    f"[Codex] 已认领任务 #{task_id}，正在检查相关路径和代码链路。"
                    f"完成后我会把结果交回 {resolve_role_display_name(delegation_source_role)} 统一汇总。"
                )
        await app.bot.send_message(
            chat_id=chat_id,
            text=claim_text,
        )
    progress_task: Optional[asyncio.Task] = None
    if not is_return_task:
        progress_task = asyncio.create_task(
            notify_long_running_group_task(
                app,
                task_id=task_id,
                chat_id=chat_id,
                route_reason=route_reason,
            )
        )
    await app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    lock = app.bot_data.get("backend_lock")
    try:
        if lock:
            async with lock:
                result = await asyncio.to_thread(run_backend_for_task, prompt)
        else:
            result = await asyncio.to_thread(run_backend_for_task, prompt)
        if is_return_task:
            reply_text = normalize_delegation_return_output(result, prompt, route_reason)
        else:
            reply_text = result[:4000]
        original_user_text = extract_original_user_text(prompt)
        app.bot_data["group_registry"].finish_task(task_id, GROUP_WORKER_ROLE, reply_text)
        MEMORY_STORE.append_message(
            "openclaw",
            chat_id,
            source_user_id,
            "assistant",
            f"[任务 #{task_id} 已由 Codex 完成]\n{reply_text}",
        )
        if ENABLE_SHARED_MEMORY_LOG:
            SHARED_MEMORY_JOURNAL.append_event(
                bot_role=GROUP_WORKER_ROLE,
                scope="worker",
                task_summary=summarize_text(prompt, limit=120),
                result_summary=reply_text,
                status="completed",
                task_id=task_id,
                category=str(task.get("category", "")),
                allowed_agents=list(task.get("allowed_agents", [])),
            )
        if delegation_source_role and delegation_target_role == GROUP_WORKER_ROLE:
            if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
                created = create_openclaw_followup_tasks_from_payload(
                    app.bot_data["group_registry"],
                    payload=prompt,
                    current_role=GROUP_WORKER_ROLE,
                    chat_id=chat_id,
                    source_user_id=source_user_id,
                    original_user_text=original_user_text or prompt,
                    worker_result=reply_text,
                )
                if created:
                    status_text = build_openclaw_step_status_text(prompt, GROUP_WORKER_ROLE, "已完成")
                    followup_text = (
                        f"[Codex] 已完成任务 #{task_id} 的当前步骤，"
                        f"接下来交给 {resolve_role_display_name(created[0][0])} 继续整理。"
                    )
                    if status_text:
                        followup_text += f"\n{status_text}"
                    MEMORY_STORE.append_message(
                        "openclaw",
                        chat_id,
                        source_user_id,
                        "assistant",
                        f"[任务 #{task_id} 步骤推进]\n{followup_text}",
                    )
                    await app.bot.send_message(chat_id=chat_id, text=followup_text)
                    logging.info(
                        "Group worker %s finished task #%s via openclaw follow-up",
                        GROUP_WORKER_ROLE,
                        task_id,
                    )
                    return
                await app.bot.send_message(chat_id=chat_id, text=f"[Codex] 已完成任务 #{task_id}\n{reply_text}")
                logging.info(
                    "Group worker %s finished task #%s with direct reply for openclaw",
                    GROUP_WORKER_ROLE,
                    task_id,
                )
                return
            return_task_id = create_delegation_return_task(
                app.bot_data["group_registry"],
                requester_role=delegation_source_role,
                worker_role=GROUP_WORKER_ROLE,
                chat_id=chat_id,
                source_user_id=source_user_id,
                original_user_text=original_user_text,
                worker_result=reply_text,
            )
            logging.info(
                "Created delegation return source=%s target=%s task_id=%s",
                GROUP_WORKER_ROLE,
                delegation_source_role,
                return_task_id,
            )
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"[Codex] 已完成任务 #{task_id} 的检查，"
                    f"结果已交回 {resolve_role_display_name(delegation_source_role)} 统一汇总。"
                ),
            )
            logging.info("Group worker %s finished task #%s", GROUP_WORKER_ROLE, task_id)
            return
        if is_return_task:
            MEMORY_STORE.append_message(GROUP_WORKER_ROLE, chat_id, source_user_id, "assistant", reply_text)
            await app.bot.send_message(chat_id=chat_id, text=reply_text)
            logging.info("Group worker %s finished task #%s", GROUP_WORKER_ROLE, task_id)
            return
        await app.bot.send_message(chat_id=chat_id, text=f"[Codex] 已完成任务 #{task_id}\n{reply_text}")
        created = enqueue_handoff_tasks(
            app.bot_data["group_registry"],
            chat_id=chat_id,
            source_message_id="",
            source_user_id=source_user_id,
            source_role=GROUP_WORKER_ROLE,
            user_text=prompt,
            reply_text=reply_text,
        )
        for target_role, handoff_task_id in created:
            logging.info(
                "Created worker handoff source=%s target=%s task_id=%s",
                GROUP_WORKER_ROLE,
                target_role,
                handoff_task_id,
            )
        logging.info("Group worker %s finished task #%s", GROUP_WORKER_ROLE, task_id)
    except Exception as exc:
        error_text = summarize_text(str(exc), limit=800)
        app.bot_data["group_registry"].fail_task(task_id, GROUP_WORKER_ROLE, error_text)
        MEMORY_STORE.append_message(
            "openclaw",
            chat_id,
            source_user_id,
            "assistant",
            f"[任务 #{task_id} 执行失败，接手者 Codex]\n{error_text}",
        )
        if ENABLE_SHARED_MEMORY_LOG:
            SHARED_MEMORY_JOURNAL.append_event(
                bot_role=GROUP_WORKER_ROLE,
                scope="worker",
                task_summary=summarize_text(prompt, limit=120),
                result_summary=error_text,
                status="failed",
                task_id=task_id,
                category=str(task.get("category", "")),
                allowed_agents=list(task.get("allowed_agents", [])),
            )
        if delegation_source_role and delegation_target_role == GROUP_WORKER_ROLE:
            if should_bypass_openclaw_return_task(delegation_source_role, delegation_target_role):
                await app.bot.send_message(chat_id=chat_id, text=f"[Codex] 任务 #{task_id} 失败\n{error_text}")
                logging.exception("Group worker %s failed task #%s", GROUP_WORKER_ROLE, task_id)
                return
            return_task_id = create_delegation_return_task(
                app.bot_data["group_registry"],
                requester_role=delegation_source_role,
                worker_role=GROUP_WORKER_ROLE,
                chat_id=chat_id,
                source_user_id=source_user_id,
                original_user_text=extract_original_user_text(prompt),
                worker_result=f"协作处理失败：{error_text}",
            )
            logging.info(
                "Created delegation return source=%s target=%s task_id=%s after failure",
                GROUP_WORKER_ROLE,
                delegation_source_role,
                return_task_id,
            )
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"[Codex] 任务 #{task_id} 这轮还没完全收口，"
                    f"我已经把现有结果交回 {resolve_role_display_name(delegation_source_role)} 继续整理。"
                ),
            )
            logging.exception("Group worker %s failed task #%s", GROUP_WORKER_ROLE, task_id)
            return
        await app.bot.send_message(chat_id=chat_id, text=f"[Codex] 任务 #{task_id} 失败\n{error_text}")
        logging.exception("Group worker %s failed task #%s", GROUP_WORKER_ROLE, task_id)
    finally:
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass


async def group_worker_loop(app: Application) -> None:
    while True:
        try:
            await poll_group_tasks_for_app(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Group worker polling loop failed")
        await asyncio.sleep(GROUP_POLL_INTERVAL_SECS)


async def post_init(app: Application) -> None:
    app.bot_data["backend_lock"] = asyncio.Lock()
    if GROUP_TASK_CLAIM_ENABLED:
        app.bot_data["group_poller_task"] = asyncio.create_task(group_worker_loop(app))


async def post_shutdown(app: Application) -> None:
    poller = app.bot_data.get("group_poller_task")
    if poller:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass


def main() -> None:
    configure_logging()
    validate_env()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connection_pool_size(64)
        .pool_timeout(30.0)
        .connect_timeout(20.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .get_updates_connection_pool_size(8)
        .get_updates_pool_timeout(30.0)
        .get_updates_connect_timeout(20.0)
        .get_updates_read_timeout(30.0)
        .get_updates_write_timeout(30.0)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    if GROUP_TASK_CLAIM_ENABLED:
        app.bot_data["group_registry"] = TaskRegistry(GROUP_TASK_DB_PATH)
    app.add_handler(TypeHandler(Update, log_raw_update), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("backend", backend_cmd))
    app.add_handler(CommandHandler("memory_recent", memory_recent_cmd))
    app.add_handler(CommandHandler("memory_search", memory_search_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("confirm", confirm_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("xhs", xhs_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_error_handler(on_error)
    logging.info(
        "Bot starting backend=%s workdir=%s sandbox=%s group_worker=%s group_db=%s",
        BACKEND,
        CODEX_WORKDIR,
        CODEX_SANDBOX_MODE,
        "on" if GROUP_TASK_CLAIM_ENABLED else "off",
        GROUP_TASK_DB_PATH if GROUP_TASK_CLAIM_ENABLED else "-",
    )
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
