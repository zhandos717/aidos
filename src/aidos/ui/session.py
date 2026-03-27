"""ChatSession — чат тарихын басқару."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from aidos.ui.theme import HISTORY_DIR


class ChatSession:
    def __init__(self, session_id: str, title: str = "Жаңа чат") -> None:
        self.session_id = session_id
        self.title = title
        self.messages: list[dict] = []
        self.path = HISTORY_DIR / f"{session_id}.json"

    def add(self, sender: str, text: str) -> None:
        self.messages.append({
            "sender": sender,
            "text": text,
            "time": datetime.now().isoformat(),
        })
        if len(self.messages) == 2:
            first = next((m["text"] for m in self.messages if m["sender"] == "Сіз"), "")
            self.title = first[:36] + ("…" if len(first) > 36 else "")
        self.save()

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {"title": self.title, "messages": self.messages},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> ChatSession:
        data = json.loads(path.read_text(encoding="utf-8"))
        s = cls(session_id=path.stem, title=data.get("title", "Чат"))
        s.messages = data.get("messages", [])
        return s

    @classmethod
    def all_sessions(cls) -> list[ChatSession]:
        sessions = []
        for p in sorted(HISTORY_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                sessions.append(cls.load(p))
            except Exception:
                pass
        return sessions
