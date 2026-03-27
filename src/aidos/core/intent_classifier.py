"""IntentClassifier — LLM арқылы ниет анықтау.

Роутинг стратегиясы:
  1. Skill матч       → тікелей skill
  2. Keyword regex    → жылдам, детерминирленген (жоғары сенімділік)
  3. AI classifier    → regex матч болмаса, LLM шешеді
  4. AI fallback      → classifier қатесі болса
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidos.core.router import Intent

_log = logging.getLogger("aidos.classifier")

_CLASSIFY_SYSTEM = (
    "Сен ниет классификаторысың. Берілген мәтінді талдап, "
    "тек бір ниет атауын жаз — басқа ештеңе жазба.\n\n"
    "Мүмкін ниеттер:\n"
    "  time     — уақыт, күн, апта, ай, жыл туралы сұрақтар\n"
    "  weather  — ауа райы, температура, жел, жаңбыр, қар\n"
    "  music    — музыка, ән, ойнату, тоқтату, кідірту\n"
    "  reminder — еске салу, таймер, белгілеу, ескерту\n"
    "  ai       — жалпы сұрақтар, сөйлесу, барлық басқасы\n\n"
    "Тек бір сөз жаз: time / weather / music / reminder / ai"
)


class IntentClassifier:
    """LLM арқылы ниет классификациясы (кэшпен)."""

    def __init__(self, client) -> None:
        self._client = client
        # Соңғы 256 бірегей сұрауды кэштеу
        self._classify_cached = lru_cache(maxsize=256)(self._classify_llm)

    def classify(self, query: str) -> "Intent":
        from aidos.core.router import Intent

        key = query.strip().lower()[:120]  # кэш кілті
        try:
            label = self._classify_cached(key)
        except Exception as exc:
            _log.warning("Classifier LLM қатесі: %s → AI fallback", exc)
            return Intent.AI

        mapping = {
            "time":     Intent.TIME,
            "weather":  Intent.WEATHER,
            "music":    Intent.MUSIC,
            "reminder": Intent.REMINDER,
            "ai":       Intent.AI,
        }
        for kw, intent in mapping.items():
            if kw in label:
                _log.info("AI classifier: '%s' → %s", query[:50], intent.value)
                return intent

        _log.warning("Classifier белгісіз жауап '%s' → AI", label)
        return Intent.AI

    def _classify_llm(self, query: str) -> str:
        """LLM-ге бір қысқа сұраныс (кэштеледі)."""
        resp = self._client.chat(
            [{"role": "user", "content": f"Мәтін: {query}"}],
            system=_CLASSIFY_SYSTEM,
        )
        return resp.strip().lower()
