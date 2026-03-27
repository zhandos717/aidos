"""AI агенті — Qwen арқылы жалпы сұрақтарға жауап."""

import logging
import threading
from collections import deque

from aidos.core.ollama_client import OllamaClient

logger = logging.getLogger("aidos.agent.ai")

_MAX_HISTORY = 10


class AIAgent:
    def __init__(self, client: OllamaClient) -> None:
        self._client = client
        self._history: deque[dict] = deque(maxlen=_MAX_HISTORY)
        self._lock = threading.Lock()
        logger.debug("AIAgent инициализацияланды, max_history=%d", _MAX_HISTORY)

    def handle(self, query: str) -> str:
        logger.info("AIAgent.handle шақырылды, query ұзындығы=%d", len(query))
        logger.debug("AIAgent query='%s'", query)

        with self._lock:
            self._history.append({"role": "user", "content": query})
            messages = list(self._history)
        logger.debug("Сөйлесу тарихы: %d хабарлама", len(messages))

        try:
            response = self._client.chat_with_default_system(messages)
            with self._lock:
                self._history.append({"role": "assistant", "content": response})
            logger.info("AIAgent жауап алды, ұзындығы=%d таңба", len(response))
            return response
        except Exception as exc:
            logger.error("AIAgent қатесі: %s", exc)
            # Қатені тарихтан алып тастау
            with self._lock:
                if self._history and self._history[-1]["role"] == "user":
                    self._history.pop()
            return "Кешіріңіз, жауап беру мүмкін болмады. Ollama іске қосылғанын тексеріңіз."

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
        logger.info("Сөйлесу тарихы тазаланды")
