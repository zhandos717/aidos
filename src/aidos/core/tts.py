"""Мәтіннен дауысқа — edge-tts арқылы қазақ TTS."""

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("aidos.tts")

_KK_VOICE = "kk-KZ-AigrimNeural"
_FALLBACK_VOICE = "ru-RU-SvetlanaNeural"


async def _speak_async(text: str, voice: str) -> None:
    import edge_tts

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    logger.debug("TTS: дауыс='%s', файл='%s'", voice, tmp_path)

    communicator = edge_tts.Communicate(text, voice)
    await communicator.save(str(tmp_path))
    logger.debug("TTS аудио файл жасалды: %d байт", tmp_path.stat().st_size)

    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(tmp_path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)
        logger.debug("TTS ойнату аяқталды")
    finally:
        tmp_path.unlink(missing_ok=True)


class TTSEngine:
    def __init__(self) -> None:
        self._voice = _KK_VOICE
        logger.debug("TTSEngine инициализацияланды, дауыс=%s", self._voice)

    def speak(self, text: str) -> None:
        """Мәтінді дауыспен оқу (синхронды)."""
        logger.info("TTS іске қосылды, мәтін ұзындығы=%d таңба", len(text))
        logger.debug("TTS мәтін: '%s'", text[:100])

        try:
            asyncio.run(_speak_async(text, self._voice))
            logger.info("TTS аяқталды")
        except Exception as exc:
            logger.error("TTS қатесі (негізгі дауыс): %s", exc)
            logger.info("Fallback дауысқа өтілуде: %s", _FALLBACK_VOICE)
            try:
                asyncio.run(_speak_async(text, _FALLBACK_VOICE))
            except Exception as exc2:
                logger.error("TTS fallback та сәтсіз болды: %s", exc2)
                print(f"[Aidos]: {text}")
