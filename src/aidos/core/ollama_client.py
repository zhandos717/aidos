"""Ollama + Qwen клиенті."""

import logging
from typing import Generator

import ollama

from aidos.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger("aidos.ollama")

SYSTEM_PROMPT = (
    "Сен Айдой — қазақ тілінде сөйлейтін AI көмекшісің. "
    "Барлық жауаптарыңды тек қазақ тілінде бер. "
    "Қысқа, нақты және пайдалы жауаптар бер. "
    "Жылы, достық тонда сөйле."
)


class OllamaClient:
    def __init__(self) -> None:
        self._client = ollama.Client(host=OLLAMA_BASE_URL)
        self._model = OLLAMA_MODEL
        logger.debug("OllamaClient инициализацияланды: host=%s, model=%s", OLLAMA_BASE_URL, OLLAMA_MODEL)

    def is_available(self) -> bool:
        """Ollama серверінің қол жетімділігін тексеру."""
        try:
            self._client.list()
            logger.info("Ollama сервері қол жетімді")
            return True
        except Exception as exc:
            logger.error("Ollama сервері қол жетімсіз: %s", exc)
            return False

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> str:
        """Ollama-ға хабарлама жіберу және жауап алу."""
        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        logger.info("Ollama-ға сұраныс: model=%s, messages=%d", self._model, len(full_messages))
        logger.debug("Толық хабарламалар: %s", full_messages)

        try:
            response = self._client.chat(
                model=self._model,
                messages=full_messages,
            )
            content: str = response.message.content
            logger.info("Ollama жауабы алынды, ұзындығы=%d таңба", len(content))
            logger.debug("Жауап мазмұны: %s", content)
            return content
        except Exception as exc:
            logger.error("Ollama chat қатесі: %s", exc)
            raise

    def chat_with_default_system(self, messages: list[dict]) -> str:
        """Әдепкі қазақ system prompt-пен сөйлесу."""
        return self.chat(messages, system=SYSTEM_PROMPT)
