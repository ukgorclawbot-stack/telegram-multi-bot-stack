#!/usr/bin/env python3
import fcntl
import re
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo


TELEGRAM_MEMORY_SECTION = "## Telegram 协作记录"


class ConversationMemoryStore:
    def __init__(self, db_path: str, keep_messages: int = 24) -> None:
        self.db_path = Path(db_path)
        self.keep_messages = keep_messages
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_role TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_lookup
                ON conversation_messages(bot_role, chat_id, id);
                CREATE TABLE IF NOT EXISTS conversation_profiles (
                    bot_role TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (bot_role, chat_id)
                );
                """
            )
            self._ensure_column(
                conn,
                "conversation_messages",
                "summary",
                "TEXT NOT NULL DEFAULT ''",
            )
            conn.execute(
                """
                UPDATE conversation_messages
                SET summary = ?
                WHERE summary = ''
                """,
                ("",),
            )

    def append_message(
        self,
        bot_role: str,
        chat_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        clean = content.strip()
        if not clean:
            return
        summary = build_memory_summary(clean)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages (
                    bot_role, chat_id, user_id, role, summary, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (bot_role, str(chat_id), str(user_id), role, summary, clean, time.time()),
            )
            if self.keep_messages > 0:
                conn.execute(
                    """
                    DELETE FROM conversation_messages
                    WHERE id IN (
                        SELECT id FROM conversation_messages
                        WHERE bot_role = ? AND chat_id = ?
                        ORDER BY id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (bot_role, str(chat_id), self.keep_messages),
                )

    def get_history(self, bot_role: str, chat_id: str, limit: int) -> List[Dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE bot_role = ? AND chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (bot_role, str(chat_id), limit),
            ).fetchall()
        return [
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

    def get_history_summaries(
        self,
        bot_role: str,
        chat_id: str,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, summary, created_at
                FROM conversation_messages
                WHERE bot_role = ? AND chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (bot_role, str(chat_id), limit),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "role": str(row["role"]),
                "summary": str(row["summary"]),
                "created_at": str(row["created_at"]),
            }
            for row in reversed(rows)
        ]

    def get_chat_summaries(
        self,
        chat_id: str,
        limit: int = 20,
        *,
        bot_roles: Optional[List[str]] = None,
        exclude_bot_role: str = "",
        role: str = "",
    ) -> List[Dict[str, str]]:
        clauses = ["chat_id = ?"]
        params: List[object] = [str(chat_id)]
        if bot_roles:
            placeholders = ",".join("?" for _ in bot_roles)
            clauses.append(f"bot_role IN ({placeholders})")
            params.extend(bot_roles)
        if exclude_bot_role:
            clauses.append("bot_role != ?")
            params.append(exclude_bot_role)
        if role:
            clauses.append("role = ?")
            params.append(role)
        params.append(limit)
        where_sql = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, bot_role, role, summary, content, created_at
                FROM conversation_messages
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "bot_role": str(row["bot_role"]),
                "role": str(row["role"]),
                "summary": str(row["summary"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }
            for row in reversed(rows)
        ]

    def search_history_summaries(
        self,
        bot_role: str,
        chat_id: str,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        clean = " ".join(query.split()).strip()
        if not clean:
            return []
        like = f"%{clean}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, summary, content, created_at
                FROM conversation_messages
                WHERE bot_role = ? AND chat_id = ?
                  AND (summary LIKE ? OR content LIKE ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (bot_role, str(chat_id), like, like, limit),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "role": str(row["role"]),
                "summary": str(row["summary"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def search_chat_summaries(
        self,
        chat_id: str,
        query: str,
        limit: int = 20,
        *,
        bot_roles: Optional[List[str]] = None,
        exclude_bot_role: str = "",
        role: str = "",
    ) -> List[Dict[str, str]]:
        clean = " ".join(query.split()).strip()
        if not clean:
            return []
        clauses = ["chat_id = ?", "(summary LIKE ? OR content LIKE ?)"]
        params: List[object] = [str(chat_id), f"%{clean}%", f"%{clean}%"]
        if bot_roles:
            placeholders = ",".join("?" for _ in bot_roles)
            clauses.append(f"bot_role IN ({placeholders})")
            params.extend(bot_roles)
        if exclude_bot_role:
            clauses.append("bot_role != ?")
            params.append(exclude_bot_role)
        if role:
            clauses.append("role = ?")
            params.append(role)
        params.append(limit)
        where_sql = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, bot_role, role, summary, content, created_at
                FROM conversation_messages
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "bot_role": str(row["bot_role"]),
                "role": str(row["role"]),
                "summary": str(row["summary"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def clear_history(self, bot_role: str, chat_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM conversation_messages WHERE bot_role = ? AND chat_id = ?",
                (bot_role, str(chat_id)),
            )

    def set_chat_profile(self, bot_role: str, chat_id: str, profile: str) -> None:
        clean = profile.strip()
        if not clean:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_profiles (bot_role, chat_id, profile, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(bot_role, chat_id)
                DO UPDATE SET profile = excluded.profile, updated_at = excluded.updated_at
                """,
                (bot_role, str(chat_id), clean, time.time()),
            )

    def get_chat_profile(self, bot_role: str, chat_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT profile
                FROM conversation_profiles
                WHERE bot_role = ? AND chat_id = ?
                """,
                (bot_role, str(chat_id)),
            ).fetchone()
        if not row:
            return ""
        return str(row["profile"])

    def clear_chat_profile(self, bot_role: str, chat_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM conversation_profiles WHERE bot_role = ? AND chat_id = ?",
                (bot_role, str(chat_id)),
            )

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {str(row["name"]) for row in rows}
        if column in names:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        if table == "conversation_messages" and column == "summary":
            rows = conn.execute("SELECT id, content FROM conversation_messages").fetchall()
            conn.executemany(
                "UPDATE conversation_messages SET summary = ? WHERE id = ?",
                [
                    (build_memory_summary(str(row["content"])), int(row["id"]))
                    for row in rows
                ],
            )


class SharedMemoryJournal:
    def __init__(self, memory_dir: str, timezone_name: str = "Asia/Shanghai") -> None:
        self.memory_dir = Path(memory_dir)
        self.timezone_name = timezone_name

    def append_event(
        self,
        bot_role: str,
        scope: str,
        task_summary: str,
        result_summary: Optional[str] = None,
        status: str = "completed",
        task_id: Optional[int] = None,
        category: str = "",
        allowed_agents: Optional[List[str]] = None,
    ) -> None:
        now = datetime.now(ZoneInfo(self.timezone_name))
        daily_path = self.memory_dir / f"{now:%Y-%m-%d}.md"
        daily_path.parent.mkdir(parents=True, exist_ok=True)

        task_part = _clip(task_summary, 120)
        result_part = _clip(result_summary or "", 180)
        extras: List[str] = []
        if task_id is not None:
            extras.append(f"task=#{task_id}")
        if category:
            extras.append(f"category={category}")
        if allowed_agents:
            extras.append(f"eligible={','.join(allowed_agents)}")
        extras_text = f" ({'; '.join(extras)})" if extras else ""

        if status == "queued":
            line = f"- {now:%H:%M} [{bot_role}/{scope}] 已创建任务{extras_text} | 任务：{task_part}"
        elif status == "failed":
            line = f"- {now:%H:%M} [{bot_role}/{scope}] 任务失败{extras_text} | 任务：{task_part} | 错误：{result_part}"
        else:
            line = f"- {now:%H:%M} [{bot_role}/{scope}] 已完成{extras_text} | 任务：{task_part}"
            if result_part:
                line += f" | 结果：{result_part}"

        self._append_line(daily_path, now, line)

    def _append_line(self, daily_path: Path, now: datetime, line: str) -> None:
        if not daily_path.exists():
            daily_path.write_text(
                f"# 今日记忆 - {now.year}年{now.month:02d}月{now.day:02d}日\n\n"
                f"{TELEGRAM_MEMORY_SECTION}\n"
                f"{line}\n",
                encoding="utf-8",
            )
            return

        with daily_path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            text = handle.read()
            if not text.endswith("\n"):
                text += "\n"
            if TELEGRAM_MEMORY_SECTION not in text:
                if text.strip():
                    text += "\n"
                text += f"{TELEGRAM_MEMORY_SECTION}\n"
            text += f"{line}\n"
            handle.seek(0)
            handle.write(text)
            handle.truncate()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _clip(text: str, limit: int) -> str:
    clean = text.replace("\n", " ").strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit]}..."


def build_memory_summary(text: str, limit: int = 96) -> str:
    clean = " ".join(text.split()).strip()
    if not clean:
        return ""

    summary_match = re.search(r"(?:^|\s)summary=(.+)$", clean, flags=re.IGNORECASE)
    if summary_match:
        candidate = summary_match.group(1).strip()
        return _clip(candidate, limit)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return _clip(clean, limit)

    first = lines[0]
    if first.startswith("[任务 #") and len(lines) > 1:
        return _clip(f"{first} | {lines[1]}", limit)

    if first.startswith("[") and len(lines) > 1 and any(
        marker in first for marker in ("群聊结果", "OpenClaw", "Codex", "Gemini", "Claude")
    ):
        return _clip(f"{first} | {lines[1]}", limit)

    if first.startswith("[") and "]" in first:
        first = first.split("]", 1)[1].strip() or lines[0]

    return _clip(first, limit)


def build_instant_memory_snapshot(
    store: ConversationMemoryStore,
    *,
    bot_role: str,
    chat_id: str,
    own_limit: int = 6,
    shared_limit: int = 6,
) -> str:
    own_entries = store.get_history_summaries(bot_role, chat_id, own_limit)
    shared_entries = store.get_chat_summaries(
        chat_id,
        limit=max(shared_limit * 3, shared_limit),
        exclude_bot_role=bot_role,
        role="assistant",
    )

    own_lines = [
        f"- {entry['role']}: {entry['summary']}"
        for entry in own_entries
        if entry.get("summary")
    ]

    shared_lines: List[str] = []
    seen_shared: set[str] = set()
    for entry in reversed(shared_entries):
        summary = str(entry.get("summary", "")).strip()
        if not summary or summary in seen_shared:
            continue
        seen_shared.add(summary)
        shared_lines.append(f"- {entry['bot_role']}: {summary}")
        if len(shared_lines) >= shared_limit:
            break
    shared_lines.reverse()

    sections: List[str] = []
    if own_lines:
        sections.append("即时记忆（当前会话最近摘要）:\n" + "\n".join(own_lines[-own_limit:]))
    if shared_lines:
        sections.append("共享即时记忆（同聊天其他 bot 最近结果）:\n" + "\n".join(shared_lines[-shared_limit:]))
    return "\n\n".join(sections).strip()


def render_recent_memory_digest(
    store: ConversationMemoryStore,
    *,
    bot_role: str,
    chat_id: str,
    own_limit: int = 6,
    shared_limit: int = 6,
) -> str:
    snapshot = build_instant_memory_snapshot(
        store,
        bot_role=bot_role,
        chat_id=chat_id,
        own_limit=own_limit,
        shared_limit=shared_limit,
    )
    return snapshot or "当前还没有可用的最近记忆摘要。"


def render_memory_search_digest(
    store: ConversationMemoryStore,
    *,
    bot_role: str,
    chat_id: str,
    query: str,
    limit: int = 8,
) -> str:
    hits = store.search_chat_summaries(
        chat_id,
        query,
        limit=limit,
    )
    if not hits:
        return f"没有找到和“{query}”相关的记忆摘要。"

    lines = [f"记忆搜索：{query}"]
    for item in hits[:limit]:
        lines.append(
            f"- {item['bot_role']} / {item['role']}: {item['summary']}"
        )
    return "\n".join(lines)


class LongTermMemoryWriter:
    def __init__(
        self,
        script_path: str,
        enabled: bool = False,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.script_path = Path(script_path)
        self.enabled = enabled
        self.timezone_name = timezone_name

    def append_note(self, note: str) -> None:
        clean = note.strip()
        if not clean:
            raise ValueError("长期记忆内容不能为空")
        if not self.enabled:
            raise PermissionError("当前 bot 未开启长期记忆写入权限")
        if not self.script_path.exists():
            raise FileNotFoundError(f"长期记忆脚本不存在: {self.script_path}")

        now = datetime.now(ZoneInfo(self.timezone_name))
        lines = [line.strip() for line in clean.splitlines() if line.strip()]
        body = "\n".join(f"- {line}" for line in lines)
        content = f"### Telegram 长期记忆补充 - {now:%Y-%m-%d %H:%M}\n{body}\n"

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            tmp.write(content)
            temp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                [str(self.script_path), "append", str(temp_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            temp_path.unlink(missing_ok=True)

        if result.returncode != 0:
            error_text = (result.stderr or "").strip() or (result.stdout or "").strip() or "unknown error"
            raise RuntimeError(f"长期记忆写入失败: {error_text}")
