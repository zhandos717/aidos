"""AI агенті — ReAct цикл, ұзақ мерзімді жад, инструменттер."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from aidos.core.memory import MemoryStore
from aidos.core.tool_registry import ToolRegistry
from aidos.core.ollama_client import SYSTEM_PROMPT

if TYPE_CHECKING:
    pass

_log = logging.getLogger("aidos.agent.ai")

_MAX_STEPS = 5   # ReAct циклының максималды қадамдары
_MAX_HISTORY = 20  # сессиядан алынатын хабарлама саны

# RAG триггер сөздер — жадыдан іздеу керек
_RAG_TRIGGERS = (
    "есіңде бар ма", "айттым", "сөйлестік", "бұрын", "алдыңда",
    "помнишь", "говорил", "раньше", "до этого", "remember",
)

# Пайдаланушыдан факт алатын маркерлер
_FACT_PATTERNS: list[tuple[str, str]] = [
    ("менің атым", "user_name"),
    ("мен тұрамын", "user_city"),
    ("менің қалам", "user_city"),
    ("мен жұмыс істеймін", "user_job"),
]


class AIAgent:
    def __init__(
        self,
        client,
        memory: MemoryStore | None = None,
        registry: ToolRegistry | None = None,
        session_id: str | None = None,
    ) -> None:
        self._client = client
        self._memory = memory or MemoryStore()
        self._registry = registry or ToolRegistry()
        self._session_id = session_id or str(uuid.uuid4())
        _log.info("AIAgent іске қосылды, session=%s", self._session_id[:8])

    # ── Публичный API ─────────────────────────────────────────────────────────

    def handle(self, query: str) -> str:
        _log.info("AIAgent.handle: '%s'", query[:80])
        self._memory.add_message(self._session_id, "user", query)
        self._extract_facts(query)

        system = self._build_system(query)
        messages = self._memory.get_session(self._session_id, limit=_MAX_HISTORY)

        response = self._react(messages, system)

        self._memory.add_message(self._session_id, "assistant", response)
        return response

    def set_session(self, session_id: str) -> None:
        """UI-дан сессияны ауыстыру."""
        self._session_id = session_id
        _log.debug("Сессия ауыстырылды: %s", session_id[:8])

    def clear_history(self) -> None:
        """Ағымдағы сессия тарихын тазалау (жадыда сақталады)."""
        self._session_id = str(uuid.uuid4())
        _log.info("Жаңа сессия ашылды: %s", self._session_id[:8])

    # ── ReAct цикл ────────────────────────────────────────────────────────────

    def _react(self, messages: list[dict], system: str) -> str:
        """Reason → Act → Observe → Repeat → Answer."""
        working = list(messages)

        for step in range(_MAX_STEPS):
            try:
                raw = self._client.chat(working, system=system)
            except Exception as exc:
                _log.error("LLM қатесі: %s", exc)
                return "Кешіріңіз, жауап беру мүмкін болмады."

            tool_call = self._registry.parse_tool_call(raw)

            if tool_call is None:
                # Финальды жауап
                _log.info("ReAct аяқталды, %d қадам", step + 1)
                return raw.strip()

            tool_name, args = tool_call
            _log.info("ReAct қадам %d: %s(%s)", step + 1, tool_name, args)

            result = self._registry.execute(tool_name, args)

            # Инструмент нәтижесін контекстке қосу
            working.append({"role": "assistant", "content": raw})
            working.append({
                "role": "user",
                "content": f"[Инструмент нәтижесі — {tool_name}]: {result}",
            })

        _log.warning("ReAct max қадам жетті (%d)", _MAX_STEPS)
        return raw.strip()

    # ── Жүйелік prompt ────────────────────────────────────────────────────────

    def _build_system(self, query: str = "") -> str:
        parts = [SYSTEM_PROMPT]

        facts_ctx = self._memory.facts_as_context()
        if facts_ctx:
            parts.append(facts_ctx)

        # RAG: сұрауда жады триггері болса — автоматты іздеу
        if query and any(t in query.lower() for t in _RAG_TRIGGERS):
            rag_ctx = self._memory.search_as_context(query)
            if rag_ctx:
                _log.info("RAG контексті қосылды")
                parts.append(rag_ctx)

        tools_ctx = self._registry.get_system_block()
        if tools_ctx:
            parts.append(tools_ctx)

        return "\n\n".join(parts)

    # ── Факт экстракциясы ─────────────────────────────────────────────────────

    def _extract_facts(self, text: str) -> None:
        lower = text.lower()
        for marker, fact_key in _FACT_PATTERNS:
            if marker in lower:
                idx = lower.index(marker) + len(marker)
                value = text[idx:].strip(" ,.!").split(".")[0].strip()
                if value:
                    self._memory.set_fact(fact_key, value)
                    _log.debug("Факт сақталды: %s=%s", fact_key, value)
