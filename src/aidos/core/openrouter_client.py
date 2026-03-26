"""OpenRouter клиенті — OpenAI-compatible API арқылы 300+ модель."""

import logging
import os

from aidos.core.ollama_client import SYSTEM_PROMPT

logger = logging.getLogger("aidos.openrouter")

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    def __init__(self) -> None:
        from openai import OpenAI

        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY баптанбаған")

        self._client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
        )
        self._model = OPENROUTER_MODEL
        logger.info("OpenRouterClient инициализацияланды, модель=%s", self._model)

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            logger.info("OpenRouter қол жетімді")
            return True
        except Exception as exc:
            logger.error("OpenRouter қол жетімсіз: %s", exc)
            return False

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        logger.info("OpenRouter сұраныс: model=%s, messages=%d", self._model, len(full_messages))
        logger.debug("Хабарламалар: %s", full_messages)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,
            )
            content: str = response.choices[0].message.content
            logger.info("OpenRouter жауабы алынды, ұзындығы=%d таңба", len(content))
            return content
        except Exception as exc:
            logger.error("OpenRouter chat қатесі: %s", exc)
            raise

    def chat_with_default_system(self, messages: list[dict]) -> str:
        return self.chat(messages, system=SYSTEM_PROMPT)
