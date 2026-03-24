#!/usr/bin/env python3
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Sequence


DEFAULT_XHS_SCRIPT_PATH = str(
    Path.home() / ".openclaw" / "workspace" / "scripts" / "xiaohongshu_opencli.sh"
)
XHS_PLATFORM_KEYWORDS = ("小红书", "xiaohongshu", "xhs", "rednote")


def get_xhs_script_path() -> str:
    return os.getenv("XHS_SCRIPT_PATH", DEFAULT_XHS_SCRIPT_PATH).strip()


def get_xhs_command_timeout_secs() -> int:
    raw_value = os.getenv("XHS_COMMAND_TIMEOUT_SECS", "120").strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 120


def build_xhs_help_text(
    *,
    bot_display_name: str = "小红书助手",
    command_prefix: str = "/xhs",
) -> str:
    command_prefix = command_prefix.strip() or "/xhs"
    return (
        f"{bot_display_name} 已连接。\n\n"
        "当前能力：小红书搜索、推荐 Feed、通知、创作者资料、创作者数据、创作者笔记。\n\n"
        "命令示例：\n"
        f"{command_prefix} doctor\n"
        f"{command_prefix} login\n"
        f"{command_prefix} search AI\n"
        f"{command_prefix} search-summary AI\n"
        f"{command_prefix} article-topic AI\n"
        f"{command_prefix} article-outline AI\n"
        f"{command_prefix} article-draft AI\n"
        f"{command_prefix} feed 5\n"
        f"{command_prefix} notifications\n"
        f"{command_prefix} creator-profile\n"
        f"{command_prefix} creator-stats\n"
        f"{command_prefix} creator-notes 10\n"
        f"{command_prefix} creator-summary\n"
    )


def run_xhs_command(
    args: Sequence[str],
    *,
    script_path: Optional[str] = None,
    timeout_secs: Optional[int] = None,
) -> str:
    active_script = (script_path or get_xhs_script_path()).strip()
    if not active_script:
        return "执行失败：\n缺少 XHS_SCRIPT_PATH 配置。"
    if not Path(active_script).exists():
        return f"执行失败：\nMissing XHS script: {active_script}"

    active_timeout = timeout_secs or get_xhs_command_timeout_secs()
    cmd = [active_script, *args]
    logging.info("Running XHS command: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=active_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"执行失败：\n命令执行超时（>{active_timeout} 秒）"
    except Exception as exc:
        logging.exception("XHS command failed before completion")
        return f"执行失败：\n{exc}"

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"exit code {result.returncode}"
        return f"执行失败：\n{detail}"
    return stdout or "执行完成，但没有返回内容。"


def parse_xhs_command_args(args: Sequence[str]) -> tuple[Optional[list[str]], Optional[str]]:
    if not args:
        return ["help"], None

    command = args[0].strip().lower().replace("_", "-")
    rest = [item.strip() for item in args[1:] if item.strip()]
    alias_map = {
        "doctor": "doctor",
        "login": "login-guide",
        "login-guide": "login-guide",
        "help": "help",
        "-h": "help",
        "--help": "help",
        "search": "search",
        "search-summary": "search-summary",
        "article-topic": "article-topic",
        "article-outline": "article-outline",
        "article-draft": "article-draft",
        "feed": "feed",
        "notifications": "notifications",
        "creator-profile": "creator-profile",
        "creator-stats": "creator-stats",
        "creator-notes": "creator-notes",
        "creator-summary": "creator-notes-summary",
        "creator-notes-summary": "creator-notes-summary",
        "creator-daily-report": "creator-daily-report",
        "monitor-scan": "monitor-scan",
        "download": "download",
    }
    normalized = alias_map.get(command)
    if not normalized:
        return None, f"不支持的小红书子命令：{args[0]}"

    if normalized == "help":
        return ["help"], None
    if normalized == "search":
        if not rest:
            return None, "请在 search 后面带关键词，例如：/xhs search AI"
        return ["search", " ".join(rest)], None
    if normalized == "search-summary":
        if not rest:
            return None, "请在 search-summary 后面带关键词，例如：/xhs search-summary AI"
        return ["search-summary", " ".join(rest)], None
    if normalized == "article-topic":
        if not rest:
            return None, "请在 article-topic 后面带关键词，例如：/xhs article-topic AI"
        return ["article-topic", " ".join(rest)], None
    if normalized == "article-outline":
        if not rest:
            return None, "请在 article-outline 后面带关键词，例如：/xhs article-outline AI"
        return ["article-outline", " ".join(rest)], None
    if normalized == "article-draft":
        if not rest:
            return None, "请在 article-draft 后面带关键词，例如：/xhs article-draft AI"
        return ["article-draft", " ".join(rest)], None
    if normalized == "feed":
        return ["feed", rest[0] if rest else "5"], None
    if normalized == "creator-notes":
        return ["creator-notes", rest[0] if rest else "10"], None
    if normalized == "monitor-scan":
        target = rest[0].lower() if rest else "all"
        if target not in {"notifications", "notes", "all"}:
            return None, "monitor-scan 只支持 notifications / notes / all"
        return ["monitor-scan", target], None
    if normalized == "download":
        if not rest:
            return None, "请在 download 后面带笔记 URL。"
        return ["download", rest[0]], None
    return [normalized], None


def dispatch_xhs_free_text(text: str) -> list[str]:
    clean = " ".join(text.strip().split())
    lowered = clean.lower()
    search_query = _extract_search_query(clean)
    if search_query and _contains_any(lowered, ("总结", "摘要", "summary")):
        return ["search-summary", search_query]
    article_topic_query = _extract_article_query(clean, mode="topic")
    if article_topic_query:
        return ["article-topic", article_topic_query]
    article_outline_query = _extract_article_query(clean, mode="outline")
    if article_outline_query:
        return ["article-outline", article_outline_query]
    article_draft_query = _extract_article_query(clean, mode="draft")
    if article_draft_query:
        return ["article-draft", article_draft_query]
    if lowered in {"doctor", "检查登录", "检查状态"}:
        return ["doctor"]
    if "登录" in clean or "login" in lowered:
        return ["login-guide"]
    if "监控" in clean and ("通知" in clean or "笔记" in clean):
        if "通知" in clean and "笔记" not in clean:
            return ["monitor-scan", "notifications"]
        if "笔记" in clean and "通知" not in clean:
            return ["monitor-scan", "notes"]
        return ["monitor-scan", "all"]
    if clean.startswith("搜索 ") or clean.startswith("搜 "):
        query = clean.split(" ", 1)[1].strip()
        if _contains_any(lowered, ("总结", "摘要", "summary")):
            return ["search-summary", _sanitize_search_query(query)] if query else ["help"]
        return ["search", query] if query else ["help"]
    if lowered.startswith("search "):
        query = clean.split(" ", 1)[1].strip()
        if _contains_any(lowered, ("总结", "摘要", "summary")):
            return ["search-summary", _sanitize_search_query(query)] if query else ["help"]
        return ["search", query] if query else ["help"]
    if "推荐" in clean or "feed" in lowered:
        return ["feed", _extract_limit(clean, default="5")]
    if "通知" in clean:
        return ["notifications"]
    if "创作者资料" in clean or "creator profile" in lowered:
        return ["creator-profile"]
    if "创作者后台数据" in clean or "创作者数据" in clean or "creator stats" in lowered:
        return ["creator-stats"]
    if "创作者笔记摘要" in clean or "creator summary" in lowered:
        return ["creator-notes-summary"]
    if "创作者笔记" in clean or "creator notes" in lowered:
        return ["creator-notes", _extract_limit(clean, default="10")]
    if search_query:
        return ["search", search_query]
    return ["help"]


def detect_xhs_text_intent(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(lowered, XHS_PLATFORM_KEYWORDS)


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _extract_limit(text: str, *, default: str) -> str:
    match = re.search(r"(\d+)", text)
    if match:
        return match.group(1)
    return default


def _sanitize_search_query(query: str) -> str:
    cleaned = query.strip()
    cleaned = re.sub(r"(并|然后)?(总结|摘要|summary).*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _extract_search_query(text: str) -> Optional[str]:
    match = re.search(r"(?:小红书)?(?:搜索|搜|search)\s+(.+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    query = _sanitize_search_query(match.group(1))
    return query or None


def _extract_article_query(text: str, *, mode: str) -> Optional[str]:
    if mode == "topic":
        patterns = [r"(?:给我|帮我)?(?:几个|一些)?(.+?)的?小红书选题"]
    elif mode == "outline":
        patterns = [r"(?:给我|帮我)?(?:一个)?(.+?)的?小红书提纲"]
    else:
        patterns = [r"(?:给我|帮我)?(?:写一篇|写个|写一条)(.+?)的?小红书文章"]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None
