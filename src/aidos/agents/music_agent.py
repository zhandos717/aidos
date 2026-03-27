"""Музыка агенті — YouTube стриминг (yt-dlp + ffplay) + жергілікті файлдар."""

import logging
import re
import subprocess
import threading
from pathlib import Path

_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')

from aidos.core.config import MUSIC_DIR

logger = logging.getLogger("aidos.agent.music")

_STOP_PATTERNS = re.compile(r"\b(тоқтат|өшір|stop|жоқ\s*болсын|выключи|останови|стоп)\b", re.IGNORECASE)
_PAUSE_PATTERNS = re.compile(r"\b(кідірт|pause|паузу|на\s*паузу)\b", re.IGNORECASE)
_RESUME_PATTERNS = re.compile(r"\b(жалғастыр|қайта\s*бастай|resume|продолжи|дальше)\b", re.IGNORECASE)

_EXTRACT_PATTERNS = [
    re.compile(r"(?:ойна|қос|тыңда|play|включи|поставь|запусти)\s+(.+)", re.IGNORECASE),
    re.compile(r"(.+?)\s+(?:ойна|қос|тыңда|включи)", re.IGNORECASE),
]


def _detect_command(query: str) -> str:
    if _STOP_PATTERNS.search(query):
        return "stop"
    if _PAUSE_PATTERNS.search(query):
        return "pause"
    if _RESUME_PATTERNS.search(query):
        return "resume"
    return "play"


def _extract_search_query(query: str) -> str:
    for pattern in _EXTRACT_PATTERNS:
        match = pattern.search(query)
        if match:
            return match.group(1).strip()
    return query.strip()


def _get_stream_url(search_query: str) -> tuple[str, str] | None:
    """yt-dlp арқылы тікелей стрим URL мен атауын алу."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio",
        "noplaylist": True,
    }
    logger.info("YouTube іздеуде: '%s'", search_query)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{search_query}", download=False)
            if not info or "entries" not in info:
                return None
            for entry in info["entries"]:
                if not entry:
                    continue
                video_id = entry.get("id", "")
                if not _VIDEO_ID_RE.match(video_id):
                    continue
                # Толық ақпаратты алу (stream url үшін)
                full = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                url = full.get("url")
                title = full.get("title", search_query)
                if url:
                    logger.info("Стрим URL алынды: '%s'", title)
                    return url, title
    except Exception as exc:
        logger.error("YouTube іздеу қатесі: %s", exc)
    return None


class MusicAgent:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._current_title: str | None = None
        self._thread: threading.Thread | None = None
        logger.debug("MusicAgent инициализацияланды (ffplay стриминг)")

    def handle(self, query: str) -> str:
        command = _detect_command(query)
        logger.info("Музыка командасы: %s", command)

        if command == "stop":
            return self._stop()
        if command == "pause":
            return self._pause()
        if command == "resume":
            return self._resume()

        search_query = _extract_search_query(query)
        return self._stream_youtube(search_query)

    def _stream_youtube(self, search_query: str) -> str:
        self._stop()

        result = _get_stream_url(search_query)
        if not result:
            return self._play_local()

        stream_url, title = result
        self._current_title = title

        def _play() -> None:
            try:
                self._proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("ffplay стриминг басталды: '%s'", title)
                try:
                    self._proc.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    logger.warning("ffplay уақыт шектімі өтті, тоқтатылды: '%s'", title)
                    self._proc.kill()
                    self._proc.wait()
                logger.info("ffplay аяқталды: '%s'", title)
            except Exception as exc:
                logger.error("ffplay қатесі: %s", exc)

        self._thread = threading.Thread(target=_play, daemon=True)
        self._thread.start()
        return f"Ойнатылуда: {title}"

    def _play_local(self) -> str:
        import random
        playlist: list[Path] = []
        if MUSIC_DIR.exists():
            for ext in ("*.mp3", "*.wav", "*.ogg", "*.flac"):
                playlist.extend(MUSIC_DIR.glob(ext))
        if not playlist:
            return "Музыка табылмады."
        track = random.choice(playlist)
        try:
            self._proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(track)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Жергілікті ойнатылуда: '%s'", track.name)
            return f"Ойнатылуда: {track.stem}"
        except Exception as exc:
            logger.error("Жергілікті ойнату қатесі: %s", exc)
            return f"Ойнату мүмкін болмады: {exc}"

    def _stop(self) -> str:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None
        self._current_title = None
        logger.info("Музыка тоқтатылды")
        return "Музыка тоқтатылды."

    def _pause(self) -> str:
        import signal
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGSTOP)
            logger.info("Музыка кідіртілді")
            return "Музыка кідіртілді."
        return "Ойнатылып жатқан музыка жоқ."

    def _resume(self) -> str:
        import signal
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGCONT)
            logger.info("Музыка жалғастырылды")
            return "Музыка жалғастырылды."
        return "Кідіртілген музыка жоқ."
