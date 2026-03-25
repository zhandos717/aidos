"""Ауа райы агенті — OpenWeatherMap арқылы қазақша ауа райы."""

import logging
import re

import requests

from aidos.core.config import DEFAULT_CITY, WEATHER_API_KEY

logger = logging.getLogger("aidos.agent.weather")

_OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

_WEATHER_KK: dict[str, str] = {
    "clear sky": "Ашық аспан",
    "few clouds": "Аз бұлтты",
    "scattered clouds": "Бұлтты",
    "broken clouds": "Қалың бұлт",
    "overcast clouds": "Бұлыңғыр",
    "light rain": "Жеңіл жаңбыр",
    "moderate rain": "Орташа жаңбыр",
    "heavy intensity rain": "Қатты жаңбыр",
    "light snow": "Жеңіл қар",
    "snow": "Қар",
    "thunderstorm": "Найзағайлы дауыл",
    "mist": "Тұман",
    "fog": "Қою тұман",
    "drizzle": "Шаша жаңбыр",
}

# Қала атын query-дан шығару үшін паттерндер
_CITY_PATTERNS = [
    re.compile(r"(?:қалада|қалаңда|қаласында|қалаша)\s+(\w+)", re.IGNORECASE),
    re.compile(r"(\w+)\s+(?:қаласы|қалада|ауа\s*райы)", re.IGNORECASE),
]


def _extract_city(query: str) -> str:
    """Query-дан қала атын шығарып алу."""
    for pattern in _CITY_PATTERNS:
        match = pattern.search(query)
        if match:
            city = match.group(1)
            logger.debug("Query-дан қала табылды: '%s'", city)
            return city
    logger.debug("Қала табылмады, әдепкі қала пайдаланылады: '%s'", DEFAULT_CITY)
    return DEFAULT_CITY


def _translate_description(desc: str) -> str:
    return _WEATHER_KK.get(desc.lower(), desc)


class WeatherAgent:
    def handle(self, query: str) -> str:
        logger.debug("WeatherAgent.handle шақырылды, query='%s'", query)

        if not WEATHER_API_KEY:
            logger.warning("WEATHER_API_KEY баптанбаған")
            return "Ауа райы қызметін пайдалану үшін WEATHER_API_KEY баптаңыз."

        city = _extract_city(query)
        params = {
            "q": city,
            "appid": WEATHER_API_KEY,
            "units": "metric",
            "lang": "ru",
        }

        logger.info("OpenWeatherMap API сұраныс: қала='%s'", city)

        try:
            response = requests.get(_OWM_URL, params=params, timeout=10)
            logger.debug("API жауабы: status=%d, body=%s", response.status_code, response.text[:500])
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Ауа райы API қатесі: %s", exc)
            return f"Ауа райын алу мүмкін болмады: {exc}"

        data = response.json()
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        desc_en = data["weather"][0]["description"]
        desc_kk = _translate_description(desc_en)
        wind_speed = data["wind"]["speed"]
        humidity = data["main"]["humidity"]

        result = (
            f"{city} қаласының ауа райы: {desc_kk}. "
            f"Температура {temp:.0f}°C, сезіну {feels_like:.0f}°C. "
            f"Жел {wind_speed:.1f} м/с, ылғалдылық {humidity}%."
        )
        logger.info("Ауа райы жауабы: '%s'", result)
        return result
