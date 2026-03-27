"""Agent Router — команданы дұрыс агентке бағыттайтын роутер."""

import logging
import re
from enum import Enum

from aidos.core.skill_loader import SkillLoader

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
    (re.compile(r"\b(музыка|ән|ойна|тоқтат|кідірт|жалғастыр|play|stop|pause|resume|включи|выключи|поставь|останови|паузу|продолжи|музыку|песню|слушать)\b", re.IGNORECASE), Intent.MUSIC),
    (re.compile(r"\b(еске\s*сал|ескерт|белгіле|хабарла|таймер|минут|еске)\b", re.IGNORECASE), Intent.REMINDER),
]


class IntentRouter:
    """Гибридті роутер: Skills → Keyword → AI fallback."""

    def __init__(self, ai_client=None) -> None:
        self._agents: dict[Intent, object] = {}
        self._skill_loader = SkillLoader()
        self._skill_loader.set_ai_client(ai_client)
        self._skill_loader.load_all()
        logger.debug("IntentRouter инициализацияланды, skills=%d", len(self._skill_loader.skills))

    def register(self, intent: Intent, agent: object) -> None:
        self._agents[intent] = agent
        logger.debug("Агент тіркелді: intent=%s, agent=%s", intent, type(agent).__name__)

    def route(self, text: str) -> str:
        """Мәтінді талдап, дұрыс агентке бағыттау."""
        logger.info("Роутер: кіріс мәтін='%s'", text)

        # 1. Skills тексеру (ең жоғары приоритет)
        skill = self._skill_loader.match(text)
        if skill:
            logger.info("Skill матч: '%s'", skill.name)
            try:
                return skill.handle(text)
            except Exception as exc:
                logger.error("Skill '%s' қатесі: %s", skill.name, exc)
                return f"Кешіріңіз, '{skill.name}' орындалу кезінде қате шықты."

        # 2. Keyword арқылы intent анықтау
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

        try:
            return agent.handle(text)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("Агент қатесі (intent=%s): %s", intent, exc)
            return "Кешіріңіз, сұранысты өңдеу кезінде қате шықты."

    def _detect_intent_by_keywords(self, text: str) -> Intent | None:
        """Keyword арқылы ниетті анықтау."""
        for pattern, intent in _PATTERNS:
            if pattern.search(text):
                logger.debug("Keyword матч: pattern='%s' → intent=%s", pattern.pattern, intent)
                return intent
        return None
