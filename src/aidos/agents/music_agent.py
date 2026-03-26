"""Музыка агенті — YouTube (yt-dlp) + жергілікті файлдар."""

import logging
import re
import subprocess
import threading
from pathlib import Path

import pygame

from aidos.core.config import MUSIC_DIR

logger = logging.getLogger("aidos.agent.music")

_STOP_PATTERNS = re.compile(r"\b(тоқтат|өшір|stop|жоқ\s*болсын)\b", re.IGNORECASE)
_PAUSE_PATTERNS = re.compile(r"\b(кідірт|pause)\b", re.IGNORECASE)
_RESUME_PATTERNS = re.compile(r"\b(жалғастыр|қайта\s*бастай|resume)\b", re.IGNORECASE)
_PLAY_PATTERNS = re.compile(r"\b(ойна|қос|play|бастай|тыңда)\b", re.IGNORECASE)

# Артист/ән атын query-дан шығару
_EXTRACT_PATTERNS = [
    re.compile(r"(?:ойна|қос|тыңда|play)\s+(.+)", re.IGNORECASE),
    re.compile(r"(.+?)\s+(?:ойна|қос|тыңда)", re.IGNORECASE),
]


def _detect_command(query: str) -> str:
    if _STOP_PATTERNS.search(query):
        return "stop"
    if _PAUSE_PATTERNS.search(query):
        return "pause"
    if _RESUME_PATTERNS.search(query):
        return "resume"
    if _PLAY_PATTERNS.search(query):
        return "play"
    return "play"


def _extract_search_query(query: str) -> str:
    """Query-дан іздеу сөзін шығару."""
    for pattern in _EXTRACT_PATTERNS:
        match = pattern.search(query)
        if match:
            return match.group(1).strip()
    return query.strip()


def _search_youtube(search_query: str) -> dict | None:
    """yt-dlp арқылы YouTube-тен бірінші нәтиже алу."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "default_search": "ytsearch1",
    }

    logger.info("YouTube іздеуде: '%s'", search_query)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
            if result and "entries" in result and result["entries"]:
                entry = result["entries"][0]
                logger.info("Табылды: '%s' (id=%s)", entry.get("title"), entry.get("id"))
                return entry
    except Exception as exc:
        logger.error("YouTube іздеу қатесі: %s", exc)
    return None


def _get_audio_url(video_id: str) -> str | None:
    """Видео ID арқылы аудио stream URL алу."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
    }

    url = f"https://www.youtube.com/watch?v={video_id}"
    logger.debug("Аудио URL алынуда: %s", url)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info.get("url")
            logger.debug("Аудио URL алынды")
            return audio_url
    except Exception as exc:
        logger.error("Аудио URL қатесі: %s", exc)
    return None


class MusicAgent:
    def __init__(self) -> None:
        self._initialized = False
        self._current_title: str | None = None
        self._mpv_process: subprocess.Popen | None = None
        logger.debug("MusicAgent инициализацияланды")

    def _ensure_pygame(self) -> bool:
        if self._initialized:
            return True
        try:
            pygame.mixer.init()
            self._initialized = True
            return True
        except Exception as exc:
            logger.error("pygame.mixer қатесі: %s", exc)
            return False

    def handle(self, query: str) -> str:
        logger.debug("MusicAgent.handle: query='%s'", query)
        command = _detect_command(query)
        logger.info("Музыка командасы: %s", command)

        if command == "stop":
            return self._stop()
        if command == "pause":
            return self._pause()
        if command == "resume":
            return self._resume()

        # play — YouTube немесе жергілікті
        search_query = _extract_search_query(query)
        return self._play_youtube(search_query)

    def _play_youtube(self, search_query: str) -> str:
        """YouTube-тен іздеп ойнату."""
        self._stop()

        entry = _search_youtube(search_query)
        if not entry:
            logger.warning("YouTube-тен '%s' табылмады, жергілікті файлдар тексерілуде", search_query)
            return self._play_local()

        title = entry.get("title", search_query)
        video_id = entry.get("id")

        if not video_id:
            return self._play_local()

        audio_url = _get_audio_url(video_id)
        if not audio_url:
            return f"'{title}' ойнату мүмкін болмады."

        self._current_title = title

        # mpv арқылы стриминг (фонда)
        try:
            self._mpv_process = subprocess.Popen(
                ["mpv", "--no-video", "--really-quiet", audio_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("YouTube ойнатылуда: '%s'", title)
            return f"Ойнатылуда: {title}"
        except FileNotFoundError:
            logger.warning("mpv табылмады, pygame fallback")
            return self._play_pygame_url(audio_url, title)
        except Exception as exc:
            logger.error("mpv қатесі: %s", exc)
            return f"Ойнату мүмкін болмады: {exc}"

    def _play_pygame_url(self, url: str, title: str) -> str:
        """pygame арқылы URL ойнату (fallback)."""
        if not self._ensure_pygame():
            return "Аудио жүйесі іске қоспады."
        try:
            pygame.mixer.music.load(url)
            pygame.mixer.music.play()
            return f"Ойнатылуда: {title}"
        except Exception as exc:
            logger.error("pygame URL ойнату қатесі: %s", exc)
            return self._play_local()

    def _play_local(self) -> str:
        """Жергілікті музыка қалтасынан ойнату."""
        import random
        playlist = []
        if MUSIC_DIR.exists():
            for ext in ("*.mp3", "*.wav", "*.ogg", "*.flac"):
                playlist.extend(MUSIC_DIR.glob(ext))

        if not playlist:
            return "Музыка табылмады. YouTube іздеу де сәтсіз болды."

        track = random.choice(playlist)
        if not self._ensure_pygame():
            return "Аудио жүйесі іске қоспады."
        try:
            pygame.mixer.music.load(str(track))
            pygame.mixer.music.play()
            logger.info("Жергілікті ойнатылуда: '%s'", track.name)
            return f"Ойнатылуда: {track.stem}"
        except Exception as exc:
            logger.error("Жергілікті ойнату қатесі: %s", exc)
            return f"Ойнату мүмкін болмады: {exc}"

    def _stop(self) -> str:
        if self._mpv_process:
            self._mpv_process.terminate()
            self._mpv_process = None
            logger.info("mpv тоқтатылды")
        if self._initialized:
            pygame.mixer.music.stop()
        self._current_title = None
        return "Музыка тоқтатылды."

    def _pause(self) -> str:
        if self._mpv_process:
            self._mpv_process.send_signal(__import__("signal").SIGSTOP)
            logger.info("mpv кідіртілді")
        elif self._initialized:
            pygame.mixer.music.pause()
        return "Музыка кідіртілді."

    def _resume(self) -> str:
        if self._mpv_process:
            self._mpv_process.send_signal(__import__("signal").SIGCONT)
            logger.info("mpv жалғастырылды")
        elif self._initialized:
            pygame.mixer.music.unpause()
        return "Музыка жалғастырылды."
