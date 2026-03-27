"""MemoryStore — SQLite негізіндегі агент жадысы.

Деңгейлер:
  episodic  — сессия хабарламалары (сөйлесу тарихы)
  semantic  — пайдаланушы туралы фактілер (аты, қаласы, т.б.)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from aidos.core.config import DATA_DIR

_log = logging.getLogger("aidos.memory")

_DB_PATH = DATA_DIR / "memory.db"


class MemoryStore:
    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._setup()
        _log.info("MemoryStore инициализацияланды: %s", db_path)

    def _setup(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT    NOT NULL,
                    role       TEXT    NOT NULL,
                    content    TEXT    NOT NULL,
                    ts         TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_episodes_session
                    ON episodes(session_id);

                CREATE TABLE IF NOT EXISTS facts (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            self._conn.commit()

    # ── Episodic ──────────────────────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodes (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.now().isoformat()),
            )
            self._conn.commit()

    def get_session(self, session_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM episodes "
                "WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def search_episodes(self, query: str, limit: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, role, content, ts FROM episodes "
                "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [{"session_id": r[0], "role": r[1], "content": r[2], "ts": r[3]} for r in rows]

    # ── Semantic (фактілер) ───────────────────────────────────────────────────

    def set_fact(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO facts (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat()),
            )
            self._conn.commit()
        _log.debug("Факт сақталды: %s = %s", key, value)

    def get_fact(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM facts WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_all_facts(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM facts").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    def forget_fact(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM facts WHERE key=?", (key,))
            self._conn.commit()

    def facts_as_context(self) -> str:
        """Фактілерді system prompt-қа қосылатын мәтінге айналдыру."""
        facts = self.get_all_facts()
        if not facts:
            return ""
        lines = ["Пайдаланушы туралы белгілі фактілер:"]
        for k, v in facts.items():
            lines.append(f"  - {k}: {v}")
        return "\n".join(lines)
