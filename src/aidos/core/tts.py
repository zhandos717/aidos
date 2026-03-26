"""Мәтіннен дауысқа — Piper TTS (офлайн) + edge-tts (fallback)."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("aidos.tts")

_PIPER_VOICE = "kk_KZ-issai-medium"
_PIPER_MODELS_DIR = Path(os.getenv("PIPER_MODELS_DIR", "~/.aidos/piper")).expanduser()
_EDGE_VOICE = "kk-KZ-AigrimNeural"
_EDGE_FALLBACK = "ru-RU-SvetlanaNeural"


class TTSEngine:
    def __init__(self) -> None:
        self._piper_voice = None  # кешталған Piper моделі
        self._piper_model_path: Path | None = self._find_piper_model()

        if self._piper_model_path:
            logger.info("Piper модель табылды: %s", self._piper_model_path)
            self._load_piper()
        else:
            logger.info("Piper модель табылмады, edge-tts пайдаланылады")

    def _find_piper_model(self) -> Path | None:
        onnx = _PIPER_MODELS_DIR / f"{_PIPER_VOICE}.onnx"
        if onnx.exists():
            return onnx
        logger.debug("Piper модель жоқ: %s", onnx)
        return None

    def _load_piper(self) -> None:
        """Piper моделін бір рет жүктеп кештеу."""
        try:
            from piper.voice import PiperVoice
            self._piper_voice = PiperVoice.load(str(self._piper_model_path))
            logger.info("Piper модель жүктелді және кешталды")
        except Exception as exc:
            logger.error("Piper модель жүктеу қатесі: %s", exc)
            self._piper_voice = None

    def _speak_piper(self, text: str) -> None:
        import numpy as np
        import sounddevice as sd

        stream = sd.OutputStream(
            samplerate=self._piper_voice.config.sample_rate,
            channels=1,
            dtype="int16",
        )
        stream.start()
        logger.debug("Piper ойнату басталды")
        try:
            for audio_bytes in self._piper_voice.synthesize_stream_raw(text):
                stream.write(np.frombuffer(audio_bytes, dtype=np.int16))
        finally:
            stream.stop()
            stream.close()
        logger.debug("Piper ойнату аяқталды")

    async def _speak_edge_async(self, text: str, voice: str) -> None:
        import edge_tts
        import pygame

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        communicator = edge_tts.Communicate(text, voice)
        await communicator.save(str(tmp_path))
        logger.debug("edge-tts аудио жасалды: %d байт", tmp_path.stat().st_size)

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(tmp_path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
        finally:
            tmp_path.unlink(missing_ok=True)

    def speak(self, text: str) -> None:
        logger.info("TTS іске қосылды, ұзындығы=%d таңба", len(text))
        logger.debug("TTS мәтін: '%s'", text[:100])

        # 1. Piper (офлайн, кешталған модель)
        if self._piper_voice:
            try:
                self._speak_piper(text)
                logger.info("TTS аяқталды (Piper)")
                return
            except Exception as exc:
                logger.error("Piper қатесі: %s", exc)

        # 2. edge-tts (онлайн fallback)
        try:
            asyncio.run(self._speak_edge_async(text, _EDGE_VOICE))
            logger.info("TTS аяқталды (edge-tts)")
        except Exception as exc:
            logger.error("edge-tts қатесі: %s", exc)
            try:
                asyncio.run(self._speak_edge_async(text, _EDGE_FALLBACK))
            except Exception as exc2:
                logger.error("TTS барлық жолдар сәтсіз: %s", exc2)
                print(f"[Aidos]: {text}")
