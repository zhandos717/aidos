"""'Айдос' триггер сөзін анықтау.

Екі режим:
  1. Мәтін бойынша — VAD сөйлемді бөледі, wav2vec2 таниды, мәтіннен 'Айдос' ізделеді.
     'Айдос, ауа райы қандай?' бір сөйлеммен айтылса, команда бірден орындалады.
  2. openWakeWord  — WAKE_WORD_MODEL=... custom .onnx берілгенде ғана (~5 мс).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from difflib import SequenceMatcher
from typing import Callable

import sounddevice as sd

from aidos.core.config import WAKE_WORD_MODEL

_log = logging.getLogger("aidos.wake_word")

_RATE = 16000
_OWW_THRESHOLD = 0.5
_COOLDOWN = 2.0

_WAKE_WORD = "айдос"
# wav2vec2-kk 'Айдос'-ты жиі осылай естиді.
_WAKE_ALIASES: frozenset[str] = frozenset({
    "айдос", "aidos", "айдыс", "айдоз", "айдас", "айдус", "айдост", "айдосс", "эйдос",
})
# 5 әріпті сөзде бір әріп айырмасы ratio=0.8 береді — ондайлар тек _WAKE_ALIASES арқылы өтеді.
_FUZZY_MIN_RATIO = 0.85
# Триггер тек сөйлемнің басында: 'Айдос туралы айтшы' ортасындағы атау іске қоспайды.
_SEARCH_FIRST_WORDS = 3
_WORD_RE = re.compile(r"\S+")
_PUNCT = ".,!?;:«»\"'()—-"


def _is_wake_token(token: str) -> bool:
    word = token.strip(_PUNCT).lower()
    if word in _WAKE_ALIASES:
        return True
    return len(word) >= 5 and SequenceMatcher(None, word, _WAKE_WORD).ratio() > _FUZZY_MIN_RATIO


def find_wake_word(text: str) -> str | None:
    """Триггер табылса — одан кейінгі команданы ('' болуы мүмкін), әйтпесе None қайтарады."""
    tokens = _WORD_RE.findall(text)
    for i, token in enumerate(tokens[:_SEARCH_FIRST_WORDS]):
        if _is_wake_token(token):
            return " ".join(tokens[i + 1:]).strip(_PUNCT + " ")
    return None


def custom_model_available() -> bool:
    if not (WAKE_WORD_MODEL and WAKE_WORD_MODEL.exists()):
        return False
    try:
        import openwakeword  # type: ignore[import]  # noqa: F401
    except ImportError:
        return False
    return True


class WakeWordDetector:
    """openWakeWord арқылы фондық тыңдау (custom модель болғанда ғана)."""

    def __init__(self, on_detected: Callable[[], None]) -> None:
        self._on_detected = on_detected
        self._running = False

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        _log.info("Wake word детектор іске қосылды")

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        from openwakeword.model import Model  # type: ignore[import]

        oww = Model(wakeword_models=[str(WAKE_WORD_MODEL)], inference_framework="onnx")
        _log.info("openWakeWord моделі жүктелді: %s", WAKE_WORD_MODEL)

        chunk = int(_RATE * 0.08)
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
