"""Дауыс тану модулі — Whisper арқылы STT."""

import logging
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd

logger = logging.getLogger("aidos.voice")

_SAMPLE_RATE = 16000
_RECORD_SECONDS = 5
_SILENCE_THRESHOLD = 0.01
_SILENCE_DURATION = 1.5  # секунд


def _is_silent(audio: np.ndarray) -> bool:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    logger.debug("Аудио RMS деңгейі: %.4f (threshold=%.4f)", rms, _SILENCE_THRESHOLD)
    return rms < _SILENCE_THRESHOLD


class VoiceInput:
    def __init__(self) -> None:
        self._model = None
        logger.debug("VoiceInput инициализацияланды")

    def _load_model(self) -> None:
        if self._model is None:
            logger.info("Whisper моделі жүктелуде...")
            import whisper
            self._model = whisper.load_model("base")
            logger.info("Whisper моделі жүктелді: base")

    def listen(self) -> str | None:
        """Микрофоннан аудио жазып, мәтінге аудару."""
        logger.info("Тыңдау басталды (%d сек)", _RECORD_SECONDS)

        try:
            audio = sd.rec(
                int(_RECORD_SECONDS * _SAMPLE_RATE),
                samplerate=_SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            audio = audio.flatten()
            logger.debug("Аудио жазылды: %d үлгі, ұзындық=%.2f сек", len(audio), len(audio) / _SAMPLE_RATE)
        except Exception as exc:
            logger.error("Микрофон қатесі: %s", exc)
            return None

        if _is_silent(audio):
            logger.info("Тыныштық анықталды, мәтін қайтарылмады")
            return None

        self._load_model()

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            import soundfile as sf
            sf.write(str(tmp_path), audio, _SAMPLE_RATE)

            result = self._model.transcribe(str(tmp_path), language="kk")
            text: str = result["text"].strip()
            tmp_path.unlink(missing_ok=True)

            logger.info("Дауыс танылды: '%s'", text)
            return text if text else None
        except Exception as exc:
            logger.error("Whisper транскрипция қатесі: %s", exc)
            return None
