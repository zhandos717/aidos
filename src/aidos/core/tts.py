"""Мәтіннен дауысқа — Piper TTS (офлайн) + edge-tts (fallback)."""

import logging
import os
from pathlib import Path

logger = logging.getLogger("aidos.tts")

# Piper дауыс моделі
_PIPER_VOICE = "kk_KZ-issai-medium"
_PIPER_MODELS_DIR = Path(os.getenv("PIPER_MODELS_DIR", "~/.aidos/piper")).expanduser()

# edge-tts fallback
_EDGE_VOICE = "kk-KZ-AigrimNeural"
_EDGE_FALLBACK = "ru-RU-SvetlanaNeural"


def _speak_piper(text: str, model_path: Path) -> None:
    """Piper арқылы офлайн TTS."""
    import numpy as np
    import sounddevice as sd
    from piper.voice import PiperVoice

    logger.debug("Piper модель жүктелуде: %s", model_path)
    voice = PiperVoice.load(str(model_path))

    stream = sd.OutputStream(
        samplerate=voice.config.sample_rate,
        channels=1,
        dtype="int16",
    )
    stream.start()
    logger.debug("Piper ойнату басталды, sample_rate=%d", voice.config.sample_rate)

    for audio_bytes in voice.synthesize_stream_raw(text):
        int_data = np.frombuffer(audio_bytes, dtype=np.int16)
        stream.write(int_data)

    stream.stop()
    stream.close()
    logger.debug("Piper ойнату аяқталды")


async def _speak_edge_async(text: str, voice: str) -> None:
    """edge-tts арқылы онлайн TTS."""
    import asyncio
    import tempfile
    from pathlib import Path as P
    import edge_tts
    import pygame

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = P(tmp.name)

    communicator = edge_tts.Communicate(text, voice)
    await communicator.save(str(tmp_path))
    logger.debug("edge-tts аудио жасалды: %d байт", tmp_path.stat().st_size)

    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(tmp_path))
        pygame.mixer.music.play()
        import asyncio as _asyncio
        while pygame.mixer.music.get_busy():
            await _asyncio.sleep(0.1)
    finally:
        tmp_path.unlink(missing_ok=True)


class TTSEngine:
    def __init__(self) -> None:
        self._piper_model: Path | None = self._find_piper_model()
        if self._piper_model:
            logger.info("Piper модель табылды: %s", self._piper_model)
        else:
            logger.info("Piper модель табылмады, edge-tts пайдаланылады")
        logger.debug("TTSEngine инициализацияланды")

    def _find_piper_model(self) -> Path | None:
        """Piper ONNX моделін іздеу."""
        onnx = _PIPER_MODELS_DIR / f"{_PIPER_VOICE}.onnx"
        if onnx.exists():
            return onnx
        logger.debug("Piper модель жоқ: %s", onnx)
        return None

    def speak(self, text: str) -> None:
        """Мәтінді дауыспен оқу."""
        logger.info("TTS іске қосылды, ұзындығы=%d таңба", len(text))
        logger.debug("TTS мәтін: '%s'", text[:100])

        # 1. Piper (офлайн)
        if self._piper_model:
            try:
                _speak_piper(text, self._piper_model)
                logger.info("TTS аяқталды (Piper)")
                return
            except Exception as exc:
                logger.error("Piper қатесі: %s", exc)

        # 2. edge-tts (онлайн fallback)
        import asyncio
        try:
            asyncio.run(_speak_edge_async(text, _EDGE_VOICE))
            logger.info("TTS аяқталды (edge-tts)")
        except Exception as exc:
            logger.error("edge-tts қатесі: %s", exc)
            try:
                asyncio.run(_speak_edge_async(text, _EDGE_FALLBACK))
            except Exception as exc2:
                logger.error("TTS барлық жолдар сәтсіз: %s", exc2)
                print(f"[Aidos]: {text}")
