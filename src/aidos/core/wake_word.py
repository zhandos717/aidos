"""WakeWordDetector — 'Айдос' триггер сөзін анықтау.

Екі режим:
  1. openWakeWord  — жылдам (~5 мс), WAKE_WORD_MODEL=... .onnx файлы керек
  2. STT fallback  — wav2vec2 арқылы, баяу бірақ дереу жұмыс істейді
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

from aidos.core.config import WAKE_WORD_MODEL

_log = logging.getLogger("aidos.wake_word")

_RATE = 16000
_CHUNK_SEC = 2.5          # STT fallback чанк ұзындығы
_ENERGY_THRESHOLD = 0.008  # үнсіздік шегі (RMS)
_OWW_THRESHOLD = 0.5       # openWakeWord сенімділік шегі
_COOLDOWN = 2.0            # триггерден кейінгі үзіліс (сек)

# Танылатын сөздер (STT fallback үшін)
_WAKE_WORDS: frozenset[str] = frozenset({"айдос", "aidos", "айдыс", "айдоз"})


class WakeWordDetector:
    """Фондық тыңдау + триггер сөзді анықтаушы."""

    def __init__(self, on_detected: Callable[[], None]) -> None:
        self._on_detected = on_detected
        self._running = False
        self._voice = None  # lazy VoiceInput

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        _log.info("Wake word детектор іске қосылды")

    def stop(self) -> None:
        self._running = False

    # ── Диспетчер ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            self._run_oww()
        except Exception as exc:
            _log.warning("openWakeWord қолжетімсіз (%s) → STT режимі", exc)
            self._run_stt()

    # ── openWakeWord (жылдам, .onnx модель керек) ─────────────────────────────

    def _run_oww(self) -> None:
        from openwakeword.model import Model  # type: ignore[import]

        if WAKE_WORD_MODEL and WAKE_WORD_MODEL.exists():
            oww = Model(wakeword_models=[str(WAKE_WORD_MODEL)], inference_framework="onnx")
            _log.info("openWakeWord моделі жүктелді: %s", WAKE_WORD_MODEL)
        else:
            # Әдепкі модельдерді жүктеу (ағылшынша, тек тест үшін)
            oww = Model(inference_framework="onnx")
            _log.warning(
                "WAKE_WORD_MODEL орнатылмаған — әдепкі ағылшынша модельдер пайдаланылды. "
                "Қазақша 'Айдос' үшін custom .onnx модель жасаңыз."
            )

        chunk = int(_RATE * 0.08)  # 80 мс
        _log.info("openWakeWord тыңдауда...")

        with sd.InputStream(samplerate=_RATE, channels=1, dtype="int16", blocksize=chunk) as stream:
            while self._running:
                audio, _ = stream.read(chunk)
                preds = oww.predict(audio.flatten())
                for score in preds.values():
                    if score >= _OWW_THRESHOLD:
                        oww.reset()
                        _log.info("Wake word анықталды! (score=%.2f)", score)
                        self._on_detected()
                        time.sleep(_COOLDOWN)
                        break

    # ── STT fallback (wav2vec2, баяу бірақ дереу жұмыс істейді) ──────────────

    def _run_stt(self) -> None:
        if self._voice is None:
            from aidos.core.voice import VoiceInput
            self._voice = VoiceInput()

        chunk_frames = int(_RATE * _CHUNK_SEC)
        _log.info("STT wake word тыңдауда... 'Айдос' деп айтыңыз")

        with sd.InputStream(samplerate=_RATE, channels=1, dtype="float32") as stream:
            while self._running:
                audio, _ = stream.read(chunk_frames)
                audio = audio.flatten()

                # Үнсіздікті өткізіп жіберу
                rms = float(np.sqrt(np.mean(audio ** 2)))
                if rms < _ENERGY_THRESHOLD:
                    continue

                # STT арқылы тексеру
                try:
                    text = self._voice.transcribe(audio)
                except Exception as exc:
                    _log.debug("STT чанк қатесі: %s", exc)
                    continue

                if not text:
                    continue

                _log.debug("STT чанк: '%s'", text)

                if any(w in text.lower() for w in _WAKE_WORDS):
                    _log.info("Wake word анықталды: '%s'", text)
                    self._on_detected()
                    time.sleep(_COOLDOWN)
