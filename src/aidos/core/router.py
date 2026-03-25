"""Agent Router — команданы дұрыс агентке бағыттайтын роутер."""

import logging
import re
from enum import Enum

logger = logging.getLogger("aidos.router")


class Intent(str, Enum):
    TIME = "time"
    WEATHER = "weather"
    MUSIC = "music"
    REMINDER = "reminder"
    AI = "ai"


# Keyword → Intent картасы
_PATTERNS: list[tuple[re.Pattern, Intent]] = [
    (re.compile(r"\b(уақыт|сағат|күн|апта|ай|жыл|қандай күн|неше)\b", re.IGNORECASE), Intent.TIME),
    (re.compile(r"\b(ауа|ауа\s*райы|температура|жел|бұлт|жаңбыр|қар|жылы|суық)\b", re.IGNORECASE), Intent.WEATHER),
    (re.compile(r"\b(музыка|ән|ойна|тоқтат|кідірт|жалғастыр|play|stop|pause|resume)\b", re.IGNORECASE), Intent.MUSIC),
    (re.compile(r"\b(еске\s*сал|ескерт|белгіле|хабарла|таймер|минут|еске)\b", re.IGNORECASE), Intent.REMINDER),
]


class IntentRouter:
    """Гибридті роутер: алдымен keyword, сосын AI fallback."""

    def __init__(self) -> None:
        self._agents: dict[Intent, object] = {}
        logger.debug("IntentRouter инициализацияланды")

    def register(self, intent: Intent, agent: object) -> None:
        self._agents[intent] = agent
        logger.debug("Агент тіркелді: intent=%s, agent=%s", intent, type(agent).__name__)

    def route(self, text: str) -> str:
        """Мәтінді талдап, дұрыс агентке бағыттау."""
        logger.info("Роутер: кіріс мәтін='%s'", text)

        intent = self._detect_intent_by_keywords(text)

        if intent is None:
            logger.warning("Keyword арқылы ниет анықталмады, AI агентіне жіберілді")
            intent = Intent.AI

        logger.info("Анықталған ниет: %s", intent.value)

        agent = self._agents.get(intent)
        if agent is None:
            logger.error("'%s' ниеті үшін агент тіркелмеген, AI агентіне fallback", intent)
            agent = self._agents.get(Intent.AI)

        if agent is None:
            logger.error("AI агенті де тіркелмеген!")
            return "Кешіріңіз, қызмет уақытша қол жетімсіз."

        return agent.handle(text)  # type: ignore[union-attr]

    def _detect_intent_by_keywords(self, text: str) -> Intent | None:
        """Keyword арқылы ниетті анықтау."""
        for pattern, intent in _PATTERNS:
            if pattern.search(text):
                logger.debug("Keyword матч: pattern='%s' → intent=%s", pattern.pattern, intent)
                return intent
        return None
