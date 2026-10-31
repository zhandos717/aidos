"""Пайдаланушы баптаулары — UI-дан ауыстырылады, settings.json-да сақталады."""

import json
import logging
import threading
from dataclasses import asdict, dataclass, fields

from aidos.core.config import AI_PROVIDER, DATA_DIR

logger = logging.getLogger("aidos.settings")

SETTINGS_FILE = DATA_DIR / "settings.json"


@dataclass
class Settings:
    llm_provider: str = AI_PROVIDER
    llm_model: str = ""
    stt_provider: str = "wav2vec2"
    stt_language: str = "kk"
    tts_provider: str = "piper"
    tts_voice: str = "kk-KZ-AigulNeural"
    tts_voice_ru: str = "ru-RU-DmitryNeural"
    tts_effect: str = "robot"
    ui_theme: str = "shanyrak"
    fast_mode: bool = True
    max_tokens: int = 300


class SettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: list = []
        self.current = self._load()

    def _load(self) -> Settings:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except Exception as exc:
            logger.warning("settings.json оқылмады: %s", exc)
            return Settings()
        known = {f.name for f in fields(Settings)}
        return Settings(**{k: v for k, v in data.items() if k in known})

    def update(self, **changes) -> Settings:
        with self._lock:
            data = asdict(self.current) | changes
            self.current = Settings(**data)
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        logger.info("Баптаулар жаңартылды: %s", changes)
        for listener in self._listeners:
            listener(self.current)
        return self.current

    def subscribe(self, listener) -> None:
        self._listeners.append(listener)


settings = SettingsStore()
