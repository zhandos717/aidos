"""OpenAI-compatible API клиенті — OpenRouter, OpenAI, Claude, Gemini, Groq."""

import logging

from aidos.core.ollama_client import SYSTEM_PROMPT
from aidos.core.settings import settings

logger = logging.getLogger("aidos.openai_compat")


class OpenAICompatClient:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        default_headers: dict | None = None,
        token_param: str = "max_tokens",
    ) -> None:
        from openai import OpenAI

        if not api_key:
            raise ValueError(f"{name}: API кілті баптанбаған (.env)")

        self._name = name
        self._model = model
        self._token_param = token_param
        self._client = OpenAI(base_url=base_url, api_key=api_key, default_headers=default_headers)
        logger.info("%s клиенті жасалды, модель=%s", name, model)

    @property
    def model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception as exc:
            logger.error("%s қол жетімсіз: %s", self._name, exc)
            return False

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        logger.info("%s сұраныс: model=%s, messages=%d", self._name, self._model, len(full_messages))
        response = self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            timeout=30,
            **{self._token_param: settings.current.max_tokens},
        )
        return response.choices[0].message.content or ""

    def chat_stream(self, messages: list[dict], system: str | None = None):
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        logger.info("%s stream: model=%s, messages=%d", self._name, self._model, len(full_messages))
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            timeout=30,
            stream=True,
            **{self._token_param: settings.current.max_tokens},
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def chat_with_default_system(self, messages: list[dict]) -> str:
        return self.chat(messages, system=SYSTEM_PROMPT)
