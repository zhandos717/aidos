"""AI провайдерлер каталогы және жұмыс кезінде ауыстырылатын клиент."""

import logging
import os
import threading
from dataclasses import dataclass, field

from aidos.core.ai_provider import AIProvider

logger = logging.getLogger("aidos.ai_factory")


@dataclass(frozen=True)
class LLMProvider:
    id: str
    title: str
    default_model: str
    models: list[str] = field(default_factory=list)
    key_env: str | None = None
    base_url: str | None = None

    def has_key(self) -> bool:
        return self.key_env is None or bool(os.getenv(self.key_env))


LLM_PROVIDERS: dict[str, LLMProvider] = {p.id: p for p in [
    LLMProvider(
        "ollama", "Ollama (офлайн)",
        os.getenv("OLLAMA_MODEL", "qwen3.5:4b"),
        ["qwen3.5:4b", "hf.co/inceptionai/Llama-3.1-Sherkala-8B-Chat"],
    ),
    LLMProvider(
        "openrouter", "OpenRouter",
        os.getenv("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b"),
        ["qwen/qwen3-235b-a22b", "anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash", "deepseek/deepseek-chat"],
        "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",
    ),
    LLMProvider(
        "agentrouter", "AgentRouter",
        os.getenv("AGENTROUTER_MODEL", "gpt-5"),
        ["gpt-5", "deepseek-v3.2"],
        "AGENTROUTER_API_KEY",
    ),
    LLMProvider(
        "anthropic", "Claude (Anthropic)",
        os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
        "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/",
    ),
    LLMProvider(
        "deepseek", "DeepSeek",
        os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        ["deepseek-chat", "deepseek-reasoner"],
        "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1",
    ),
    LLMProvider(
        "openai", "OpenAI",
        os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        ["gpt-4.1-mini", "gpt-4.1", "gpt-5"],
        "OPENAI_API_KEY", "https://api.openai.com/v1",
    ),
    LLMProvider(
        "gemini", "Google Gemini",
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        ["gemini-2.5-flash", "gemini-2.5-pro"],
        "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
]}


def create_ai_client(provider_id: str, model: str = "") -> AIProvider:
    provider = LLM_PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Белгісіз AI провайдер: {provider_id}")
    model = model or provider.default_model
    logger.info("AI провайдер таңдалуда: %s, модель=%s", provider_id, model)

    if provider_id == "ollama":
        from aidos.core.ollama_client import OllamaClient
        return OllamaClient(model=model)

    if provider_id == "agentrouter":
        from aidos.core.agentrouter_client import AgentRouterClient
        return AgentRouterClient(model=model)

    from aidos.core.openai_compat_client import OpenAICompatClient
    return OpenAICompatClient(
        name=provider.title,
        base_url=provider.base_url,
        api_key=os.getenv(provider.key_env, ""),
        model=model,
        # OpenAI reasoning-модельдері max_tokens қабылдамайды
        token_param="max_completion_tokens" if provider_id == "openai" else "max_tokens",
    )


class SwitchableAI:
    """Агенттер бір рет алатын прокси — ішкі клиентті UI-дан ауыстыруға болады."""

    def __init__(self, provider_id: str, model: str = "") -> None:
        self._lock = threading.Lock()
        self._client: AIProvider = create_ai_client(provider_id, model)
        self.provider_id = provider_id
        self.model = model or LLM_PROVIDERS[provider_id].default_model

    def switch(self, provider_id: str, model: str = "") -> None:
        client = create_ai_client(provider_id, model)
        with self._lock:
            self._client = client
            self.provider_id = provider_id
            self.model = model or LLM_PROVIDERS[provider_id].default_model

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        return self._client.chat(messages, system=system)

    def chat_stream(self, messages: list[dict], system: str | None = None):
        client = self._client
        if hasattr(client, "chat_stream"):
            yield from client.chat_stream(messages, system=system)
        else:
            yield client.chat(messages, system=system)

    def chat_with_default_system(self, messages: list[dict]) -> str:
        return self._client.chat_with_default_system(messages)

    def is_available(self) -> bool:
        return self._client.is_available()
