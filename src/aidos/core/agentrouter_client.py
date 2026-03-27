"""AgentRouter клиенті — OpenAI-compatible API арқылы GPT-5, DeepSeek және т.б."""

import logging
import os

from aidos.core.ollama_client import SYSTEM_PROMPT

logger = logging.getLogger("aidos.agentrouter")

AGENTROUTER_API_KEY: str = os.getenv("AGENTROUTER_API_KEY", "")
AGENTROUTER_MODEL: str = os.getenv("AGENTROUTER_MODEL", "gpt-5")
AGENTROUTER_BASE_URL = "https://agentrouter.org/v1"


class AgentRouterClient:
    def __init__(self) -> None:
        from openai import OpenAI

        if not AGENTROUTER_API_KEY:
            raise ValueError("AGENTROUTER_API_KEY баптанбаған")

        self._client = OpenAI(
            base_url=AGENTROUTER_BASE_URL,
            api_key=AGENTROUTER_API_KEY,
            default_headers={
                "User-Agent":                  "QwenCode/0.12.0 (linux; x64)",
                "Accept":                      "application/json",
                "Accept-Language":             "*",
                "sec-fetch-mode":              "cors",
                "X-Stainless-Lang":            "js",
                "X-Stainless-Package-Version": "5.11.0",
                "X-Stainless-OS":              "Linux",
                "X-Stainless-Arch":            "x64",
                "X-Stainless-Runtime":         "node",
                "X-Stainless-Runtime-Version": "v20.20.0",
                "X-Stainless-Retry-Count":     "0",
            },
        )
        self._model = AGENTROUTER_MODEL
        logger.info("AgentRouterClient инициализацияланды, модель=%s", self._model)

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            logger.info("AgentRouter қол жетімді")
            return True
        except Exception as exc:
            logger.error("AgentRouter қол жетімсіз: %s", exc)
            return False

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        logger.info("AgentRouter сұраныс: model=%s, messages=%d", self._model, len(full_messages))
        logger.debug("Хабарламалар: %s", full_messages)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,
                timeout=30,
            )
            content: str = response.choices[0].message.content
            logger.info("AgentRouter жауабы алынды, ұзындығы=%d таңба", len(content))
            return content
        except Exception as exc:
            logger.error("AgentRouter chat қатесі: %s", exc)
            raise

    def chat_with_default_system(self, messages: list[dict]) -> str:
        return self.chat(messages, system=SYSTEM_PROMPT)
