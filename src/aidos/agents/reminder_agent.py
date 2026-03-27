"""Еске салғыш агенті — уақытша еске салғыштар жасау."""

import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Callable

from aidos.core.config import DATA_DIR

logger = logging.getLogger("aidos.agent.reminder")

_REMINDERS_FILE = DATA_DIR / "reminders.json"

# Уақыт паттерндері
_MIN_PATTERN = re.compile(r"(\d+)\s*(минут|мин)", re.IGNORECASE)
_HOUR_PATTERN = re.compile(r"(\d+)\s*(сағат|саг)", re.IGNORECASE)
_CLOCK_PATTERN = re.compile(r"сағат\s+(\d{1,2})(?::(\d{2}))?", re.IGNORECASE)

# Тізім паттерн
_LIST_PATTERN = re.compile(r"\b(тізім|барлық|қандай|еске\s*салғыштар)\b", re.IGNORECASE)


def _parse_delay(query: str) -> timedelta | None:
    """Query-дан уақыт кідірісін анықтау."""
    m = _MIN_PATTERN.search(query)
    if m:
        minutes = int(m.group(1))
        logger.debug("Минут паттерн табылды: %d мин", minutes)
        return timedelta(minutes=minutes)

    m = _HOUR_PATTERN.search(query)
    if m:
        hours = int(m.group(1))
        logger.debug("Сағат паттерн табылды: %d сағ", hours)
        return timedelta(hours=hours)

    m = _CLOCK_PATTERN.search(query)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        delta = target - now
        logger.debug("Нақты уақыт паттерн: %02d:%02d, delay=%s", hour, minute, delta)
        return delta

    return None


def _extract_message(query: str) -> str:
    """Еске салғыш мазмұнын query-дан шығару."""
    # Уақыт бөліктерін алып тастау
    text = _MIN_PATTERN.sub("", query)
    text = _HOUR_PATTERN.sub("", text)
    text = _CLOCK_PATTERN.sub("", text)
    # Стоп-сөздерді алып тастау
    for stop in ("еске сал", "ескертіп қой", "белгіле", "хабарла", "еске"):
        text = text.replace(stop, "")
    text = text.strip(" ,")
    return text if text else "Уақыт келді!"


class ReminderAgent:
    def __init__(self, tts_callback: Callable[[str], None] | None = None) -> None:
        self._tts_callback = tts_callback
        self._reminders: list[dict] = []
        self._lock = threading.Lock()
        self._load()
        logger.debug("ReminderAgent инициализацияланды, %d еске салғыш жүктелді", len(self._reminders))

    def _load(self) -> None:
        if _REMINDERS_FILE.exists():
            try:
                with open(_REMINDERS_FILE) as f:
                    self._reminders = json.load(f)
                logger.debug("Еске салғыштар файлдан жүктелді: %s", _REMINDERS_FILE)
            except json.JSONDecodeError as exc:
                logger.error(
                    "Еске салғыштар файлы бүлінген (JSON қатесі: жол %d, баған %d): %s",
                    exc.lineno, exc.colno, exc.msg,
                )
                self._reminders = []
            except Exception as exc:
                logger.error("Еске салғыштарды жүктеу қатесі: %s", exc)
                self._reminders = []

    def _save(self) -> None:
        try:
            with open(_REMINDERS_FILE, "w") as f:
                json.dump(self._reminders, f, ensure_ascii=False, indent=2)
            logger.debug("Еске салғыштар сақталды: %s", _REMINDERS_FILE)
        except Exception as exc:
            logger.error("Еске салғыштарды сақтау қатесі: %s", exc)

    def _fire(self, message: str, reminder_id: str) -> None:
        logger.info("Еске салғыш іске қосылды: id=%s, message='%s'", reminder_id, message)
        text = f"Еске салғыш: {message}"
        if self._tts_callback:
            self._tts_callback(text)
        else:
            print(f"\n⏰ {text}")

        with self._lock:
            self._reminders = [r for r in self._reminders if r.get("id") != reminder_id]
            self._save()

    def _schedule(self, delay: timedelta, message: str) -> str:
        import uuid
        reminder_id = str(uuid.uuid4())[:8]
        fire_time = datetime.now() + delay

        with self._lock:
            self._reminders.append({
                "id": reminder_id,
                "message": message,
                "fire_at": fire_time.isoformat(),
            })
        self._save()

        timer = threading.Timer(delay.total_seconds(), self._fire, args=(message, reminder_id))
        timer.daemon = True
        timer.start()

        logger.info("Еске салғыш қосылды: id=%s, delay=%s, message='%s'", reminder_id, delay, message)
        return reminder_id

    def handle(self, query: str) -> str:
        logger.debug("ReminderAgent.handle шақырылды, query='%s'", query)

        # Тізім сұрауы
        if _LIST_PATTERN.search(query):
            return self._list_reminders()

        delay = _parse_delay(query)
        if delay is None:
            logger.warning("Уақыт анықталмады: query='%s'", query)
            return "Уақытты түсіне алмадым. Мысалы: '5 минуттан кейін еске сал' немесе 'сағат 15:00-де еске сал'."

        message = _extract_message(query)
        self._schedule(delay, message)

        total_seconds = int(delay.total_seconds())
        if total_seconds < 3600:
            time_str = f"{total_seconds // 60} минуттан кейін"
        else:
            time_str = f"{total_seconds // 3600} сағаттан кейін"

        result = f"Жарайды, {time_str} ескертемін: {message}"
        logger.info("Еске салғыш жауабы: '%s'", result)
        return result

    def _list_reminders(self) -> str:
        if not self._reminders:
            return "Белсенді еске салғыштар жоқ."
        lines = ["Белсенді еске салғыштар:"]
        for r in self._reminders:
            fire_at = datetime.fromisoformat(r["fire_at"])
            lines.append(f"• {r['message']} — {fire_at.strftime('%H:%M')}")
        return "\n".join(lines)
