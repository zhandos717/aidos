"""Ауа райы агенті — wttr.in арқылы тегін, API key қажет емес."""

import logging
import re

import requests

from aidos.core.config import DEFAULT_CITY

logger = logging.getLogger("aidos.agent.weather")

_WTTR_URL = "https://wttr.in/{city}?format=j1"

_CITY_PATTERNS = [
    re.compile(r"(?:қалада|қалаңда|қаласында|қалаша)\s+(\w+)", re.IGNORECASE),
    re.compile(r"(\w+)\s+(?:қаласы|қалада|ауа\s*райы)", re.IGNORECASE),
]

_DESC_KK: dict[str, str] = {
    "Sunny": "Күнгей",
    "Clear": "Ашық",
    "Partly cloudy": "Аз бұлтты",
    "Cloudy": "Бұлтты",
    "Overcast": "Бұлыңғыр",
    "Mist": "Тұман",
    "Fog": "Қою тұман",
    "Light rain": "Жеңіл жаңбыр",
    "Moderate rain": "Орташа жаңбыр",
    "Heavy rain": "Қатты жаңбыр",
    "Light snow": "Жеңіл қар",
    "Moderate snow": "Орташа қар",
    "Heavy snow": "Қатты қар",
    "Blizzard": "Боран",
    "Thundery outbreaks": "Найзағайлы",
}


def _extract_city(query: str) -> str:
    for pattern in _CITY_PATTERNS:
        match = pattern.search(query)
        if match:
            city = match.group(1)
            logger.debug("Query-дан қала табылды: '%s'", city)
            return city
    logger.debug("Қала табылмады, әдепкі: '%s'", DEFAULT_CITY)
    return DEFAULT_CITY


def _translate(desc: str) -> str:
    return _DESC_KK.get(desc, desc)


class WeatherAgent:
    def handle(self, query: str) -> str:
        city = _extract_city(query)
        url = _WTTR_URL.format(city=city)
        logger.info("wttr.in сұраныс: қала='%s'", city)

        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "curl/7.88.0"})
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("wttr.in қатесі: %s", exc)
            return f"Ауа райын алу мүмкін болмады: {exc}"

        try:
            current = data["current_condition"][0]
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
            wind = current.get("windspeedKmph", "?")
            humidity = current.get("humidity", "?")
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("wttr.in жауабын талдау қатесі: %s", exc)
            return "Ауа райы деректерін өңдеу мүмкін болмады."

        desc_kk = _translate(desc)
        result = (
            f"{city} қаласының ауа райы: {desc_kk}. "
            f"Температура {temp}°C, сезіну {feels}°C. "
            f"Жел {wind} км/сағ, ылғалдылық {humidity}%."
        )
        logger.info("Ауа райы жауабы: '%s'", result)
        return result
