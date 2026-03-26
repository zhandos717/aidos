"""AI провайдер фабрикасы — Strategy паттерн."""

import logging

from aidos.core.ai_provider import AIProvider
from aidos.core.config import AI_PROVIDER, OLLAMA_MODEL, OPENROUTER_MODEL

logger = logging.getLogger("aidos.ai_factory")


def create_ai_client() -> AIProvider:
    """AI_PROVIDER env var негізінде дұрыс клиентті қайтарады."""
    logger.info("AI провайдер таңдалуда: %s", AI_PROVIDER)

    if AI_PROVIDER == "openrouter":
        from aidos.core.openrouter_client import OpenRouterClient
        client = OpenRouterClient()
        logger.info("OpenRouterClient жасалды, модель=%s", OPENROUTER_MODEL)
        return client

    from aidos.core.ollama_client import OllamaClient
    client = OllamaClient()
    logger.info("OllamaClient жасалды, модель=%s", OLLAMA_MODEL)
    return client
