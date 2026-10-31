"""Ollama + Qwen клиенті."""

import logging

import ollama

from aidos.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from aidos.core.settings import settings

logger = logging.getLogger("aidos.ollama")

SYSTEM_PROMPT = (
    "Сен Aidos — дауыстық AI көмекшісің. Жауабың дауыспен оқылады.\n"
    "Ережелер:\n"
    "- Пайдаланушы қай тілде жазса, сол тілде жауап бер (қазақша немесе орысша).\n"
    "- 1–3 қысқа сөйлем. Тек сұралған нәрсені айт, кіріспесіз.\n"
    "- Markdown, тізім, кесте, эмодзи, код қолданба — тек қарапайым сөйлемдер.\n"
    "- Сандар мен бірліктерді сөзбен оқуға ыңғайлы жаз.\n"
    "- Білмесең — қысқа айт, ойдан шығарма.\n"
    "- Жылы, сыпайы тон, сәл әзіл болуы мүмкін."
)


class OllamaClient:
    def __init__(self, model: str | None = None) -> None:
        self._client = ollama.Client(host=OLLAMA_BASE_URL, timeout=30)
        self._model = model or OLLAMA_MODEL
        logger.debug("OllamaClient инициализацияланды: host=%s, model=%s", OLLAMA_BASE_URL, self._model)

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
            options = {"num_predict": settings.current.max_tokens}
            try:
                response = self._client.chat(
                    model=self._model, messages=full_messages, options=options, think=False,
                )
            except ollama.ResponseError:
                # think параметрін қолдамайтын модельдер
                response = self._client.chat(model=self._model, messages=full_messages, options=options)
            content: str = response.message.content
            logger.info("Ollama жауабы алынды, ұзындығы=%d таңба", len(content))
            logger.debug("Жауап мазмұны: %s", content)
            return content
        except Exception as exc:
            logger.error("Ollama chat қатесі: %s", exc)
            raise

    def chat_stream(self, messages: list[dict], system: str | None = None):
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        options = {"num_predict": settings.current.max_tokens}
        try:
            stream = self._client.chat(
                model=self._model, messages=full_messages, options=options, think=False, stream=True,
            )
            first = next(stream, None)
        except ollama.ResponseError:
            stream = self._client.chat(model=self._model, messages=full_messages, options=options, stream=True)
            first = next(stream, None)
        if first is not None and first.message.content:
            yield first.message.content
        for chunk in stream:
            if chunk.message.content:
                yield chunk.message.content

    def chat_with_default_system(self, messages: list[dict]) -> str:
        """Әдепкі қазақ system prompt-пен сөйлесу."""
        return self.chat(messages, system=SYSTEM_PROMPT)
