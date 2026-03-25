"""Музыка агенті — pygame арқылы жергілікті музыка ойнату."""

import logging
import random
import re
from pathlib import Path

import pygame

from aidos.core.config import MUSIC_DIR

logger = logging.getLogger("aidos.agent.music")

_PLAY_PATTERNS = re.compile(r"\b(ойна|музыка\s*қос|play|бастай)\b", re.IGNORECASE)
_STOP_PATTERNS = re.compile(r"\b(тоқтат|өшір|stop|жоқ\s*болсын)\b", re.IGNORECASE)
_PAUSE_PATTERNS = re.compile(r"\b(кідірт|тоқта|pause)\b", re.IGNORECASE)
_RESUME_PATTERNS = re.compile(r"\b(жалғастыр|қайта\s*бастай|resume)\b", re.IGNORECASE)


def _detect_command(query: str) -> str:
    if _STOP_PATTERNS.search(query):
        return "stop"
    if _PAUSE_PATTERNS.search(query):
        return "pause"
    if _RESUME_PATTERNS.search(query):
        return "resume"
    return "play"


class MusicAgent:
    def __init__(self) -> None:
        self._initialized = False
        self._playlist: list[Path] = []
        self._current_track: Path | None = None
        logger.debug("MusicAgent инициализацияланды, MUSIC_DIR=%s", MUSIC_DIR)

    def _ensure_pygame(self) -> bool:
        if self._initialized:
            return True
        try:
            pygame.mixer.init()
            self._initialized = True
            logger.info("pygame.mixer іске қосылды")
            return True
        except Exception as exc:
            logger.error("pygame.mixer іске қосылу қатесі: %s", exc)
            return False

    def _load_playlist(self) -> None:
        self._playlist = []
        if MUSIC_DIR.exists():
            for ext in ("*.mp3", "*.wav", "*.ogg", "*.flac"):
                self._playlist.extend(MUSIC_DIR.glob(ext))
        logger.debug("Playlist жүктелді: %d трек, қалта=%s", len(self._playlist), MUSIC_DIR)

    def handle(self, query: str) -> str:
        logger.debug("MusicAgent.handle шақырылды, query='%s'", query)
        command = _detect_command(query)
        logger.info("Музыка командасы анықталды: %s", command)

        if not self._ensure_pygame():
            return "Аудио жүйесін іске қосу мүмкін болмады."

        if command == "play":
            return self._play()
        elif command == "stop":
            return self._stop()
        elif command == "pause":
            return self._pause()
        elif command == "resume":
            return self._resume()

        return "Музыка командасы анықталмады."

    def _play(self) -> str:
        self._load_playlist()
        if not self._playlist:
            logger.warning("Playlist бос, MUSIC_DIR=%s", MUSIC_DIR)
            return f"Музыка табылмады. {MUSIC_DIR} қалтасына MP3/WAV файлдарын қосыңыз."

        track = random.choice(self._playlist)
        self._current_track = track
        try:
            pygame.mixer.music.load(str(track))
            pygame.mixer.music.play()
            logger.info("Ойнатылуда: '%s'", track.name)
            return f"Ойнатылуда: {track.stem}"
        except Exception as exc:
            logger.error("Музыка ойнату қатесі: file='%s', error=%s", track, exc)
            return f"Музыка ойнату мүмкін болмады: {exc}"

    def _stop(self) -> str:
        pygame.mixer.music.stop()
        logger.info("Музыка тоқтатылды")
        return "Музыка тоқтатылды."

    def _pause(self) -> str:
        pygame.mixer.music.pause()
        logger.info("Музыка кідіртілді")
        return "Музыка кідіртілді."

    def _resume(self) -> str:
        pygame.mixer.music.unpause()
        logger.info("Музыка жалғастырылды")
        return "Музыка жалғастырылды."
