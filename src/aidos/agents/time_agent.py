"""Уақыт агенті — қазіргі уақыт пен күнді қазақша қайтарады."""

import logging
from datetime import datetime

logger = logging.getLogger("aidos.agent.time")

_MONTHS_KK = {
    1: "қаңтар",
    2: "ақпан",
    3: "наурыз",
    4: "сәуір",
    5: "мамыр",
    6: "маусым",
    7: "шілде",
    8: "тамыз",
    9: "қыркүйек",
    10: "қазан",
    11: "қараша",
    12: "желтоқсан",
}

_WEEKDAYS_KK = {
    0: "дүйсенбі",
    1: "сейсенбі",
    2: "сәрсенбі",
    3: "бейсенбі",
    4: "жұма",
    5: "сенбі",
    6: "жексенбі",
}


class TimeAgent:
    def handle(self, query: str) -> str:
        logger.debug("TimeAgent.handle шақырылды, query='%s'", query)

        now = datetime.now()
        hour = now.hour
        minute = now.minute
        day = now.day
        month_kk = _MONTHS_KK[now.month]
        year = now.year
        weekday_kk = _WEEKDAYS_KK[now.weekday()]

        time_str = f"Қазір сағат {hour:02d}:{minute:02d}, {year} жылдың {day} {month_kk}ы, {weekday_kk}."

        logger.info("Уақыт жауабы: '%s'", time_str)
        return time_str
