#!/usr/bin/env python3
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chat_id TEXT NOT NULL,
    source_message_id TEXT,
    source_user_id TEXT,
    source_text TEXT NOT NULL,
    category TEXT NOT NULL,
    route_reason TEXT NOT NULL,
    allowed_agents_json TEXT NOT NULL,
    status TEXT NOT NULL,
    claimed_by TEXT,
    claim_started_at REAL,
    finished_at REAL,
    result_summary TEXT,
    error_text TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at);
"""


class TaskRegistry:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def create_task(
        self,
        *,
        source_chat_id: str,
        source_message_id: str,
        source_user_id: str,
        source_text: str,
        category: str,
        route_reason: str,
        allowed_agents: List[str],
    ) -> int:
        created_at = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    source_chat_id, source_message_id, source_user_id, source_text,
                    category, route_reason, allowed_agents_json, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    source_chat_id,
                    source_message_id,
                    source_user_id,
                    source_text,
                    category,
                    route_reason,
                    json.dumps(allowed_agents, ensure_ascii=True),
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_claimable_tasks(self, agent_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        tasks = []
        for row in rows:
            task = self._row_to_task(row)
            if agent_name in task["allowed_agents"]:
                tasks.append(task)
        return tasks

    def claim_task(self, task_id: int, agent_name: str) -> bool:
        claim_started_at = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'claimed', claimed_by = ?, claim_started_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (agent_name, claim_started_at, task_id),
            )
            return cursor.rowcount == 1

    def requeue_stale_claims(self, agent_name: str, stale_secs: int) -> List[int]:
        stale_before = time.time() - max(0, stale_secs)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM tasks
                WHERE status = 'claimed'
                  AND claimed_by = ?
                  AND claim_started_at IS NOT NULL
                  AND claim_started_at < ?
                ORDER BY claim_started_at ASC
                """,
                (agent_name, stale_before),
            ).fetchall()
            task_ids = [int(row["id"]) for row in rows]
            if task_ids:
                conn.executemany(
                    """
                    UPDATE tasks
                    SET status = 'pending', claimed_by = NULL, claim_started_at = NULL
                    WHERE id = ?
                    """,
                    [(task_id,) for task_id in task_ids],
                )
        return task_ids

    def finish_task(self, task_id: int, agent_name: str, result_summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'completed', finished_at = ?, result_summary = ?
                WHERE id = ? AND claimed_by = ?
                """,
                (time.time(), result_summary, task_id, agent_name),
            )

    def fail_task(self, task_id: int, agent_name: str, error_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'failed', finished_at = ?, error_text = ?
                WHERE id = ? AND claimed_by = ?
                """,
                (time.time(), error_text, task_id, agent_name),
            )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
        task = dict(row)
        task["allowed_agents"] = json.loads(task.pop("allowed_agents_json"))
        return task
