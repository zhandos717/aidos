"""Дауыс тану модулі — Silero VAD + wav2vec2-large-xlsr-kazakh арқылы STT."""

import logging
import threading
import time
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd

logger = logging.getLogger("aidos.voice")

_SAMPLE_RATE = 16000
_FRAME = 512  # Silero VAD 16 кГц-те тек 512 үлгілік кадрды қабылдайды
_FRAME_MS = _FRAME * 1000 // _SAMPLE_RATE
_SILENCE_THRESHOLD = 0.01
_ENERGY_SPEECH_RMS = 0.015
_MODEL_ID = "aismlv/wav2vec2-large-xlsr-kazakh"


def _is_silent(audio: np.ndarray) -> bool:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    logger.debug("Аудио RMS деңгейі: %.4f (threshold=%.4f)", rms, _SILENCE_THRESHOLD)
    return rms < _SILENCE_THRESHOLD


class UtteranceSegmenter:
    """VAD ықтималдықтары бойынша кадрлар ағынынан бір сөйлемді бөледі."""

    def __init__(
        self,
        threshold: float = 0.5,
        frame_ms: int = _FRAME_MS,
        min_speech_ms: int = 250,
        end_silence_ms: int = 1000,
        max_utterance_ms: int = 12000,
        pre_roll_ms: int = 300,
    ) -> None:
        self._threshold = threshold
        self._frame_ms = frame_ms
        self._min_speech_ms = min_speech_ms
        self._end_silence_ms = end_silence_ms
        self._max_frames = max_utterance_ms // frame_ms
        # Сөйлеу басталғанға дейінгі кадрлар: бірінші буын кесіліп қалмас үшін.
        self._pre_roll: deque[np.ndarray] = deque(maxlen=max(1, pre_roll_ms // frame_ms))
        self._reset()

    def _reset(self) -> None:
        self._frames: list[np.ndarray] = []
        self._speech_ms = 0
        self._silence_ms = 0
        self._pre_roll.clear()

    @property
    def triggered(self) -> bool:
        return bool(self._frames)

    def feed(self, frame: np.ndarray, prob: float) -> np.ndarray | None:
        is_speech = prob >= self._threshold

        if not self._frames:
            if not is_speech:
                self._pre_roll.append(frame)
                return None
            self._frames = [*self._pre_roll, frame]
            self._pre_roll.clear()
            self._speech_ms = self._frame_ms
            return None

        self._frames.append(frame)
        if is_speech:
            self._speech_ms += self._frame_ms
            self._silence_ms = 0
        else:
            self._silence_ms += self._frame_ms

        too_long = len(self._frames) >= self._max_frames
        if self._silence_ms < self._end_silence_ms and not too_long:
            return None

        enough_speech = self._speech_ms >= self._min_speech_ms
        utterance = np.concatenate(self._frames) if enough_speech else None
        self._reset()
        return utterance


def _load_speech_prob() -> Callable[[np.ndarray], float]:
    try:
        import torch
        from silero_vad import load_silero_vad

        model = load_silero_vad()
        logger.info("Silero VAD жүктелді")

        def silero_prob(frame: np.ndarray) -> float:
            with torch.no_grad():
                return float(model(torch.from_numpy(frame), _SAMPLE_RATE).item())

        silero_prob.reset = model.reset_states  # type: ignore[attr-defined]
        return silero_prob
    except Exception as exc:
        logger.warning("Silero VAD қолжетімсіз (%s) → энергия бойынша VAD", exc)

        def energy_prob(frame: np.ndarray) -> float:
            return 1.0 if float(np.sqrt(np.mean(frame ** 2))) >= _ENERGY_SPEECH_RMS else 0.0

        return energy_prob


class VoiceInput:
    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._model_lock = threading.Lock()
        self._speech_prob: Callable[[np.ndarray], float] | None = None
        logger.debug("VoiceInput инициализацияланды, модель=%s", _MODEL_ID)

    def _load_model(self) -> None:
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            logger.info("Казақ STT моделі жүктелуде: %s", _MODEL_ID)
            from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

            self._processor = Wav2Vec2Processor.from_pretrained(_MODEL_ID)
            self._model = Wav2Vec2ForCTC.from_pretrained(_MODEL_ID)
            self._model.eval()
            logger.info("Казақ STT моделі жүктелді")

    def preload(self) -> None:
        self._load_model()

    def transcribe(self, audio: "np.ndarray", *, check_silence: bool = True) -> str | None:
        """Берілген numpy аудио массивін мәтінге аудару."""
        if check_silence and _is_silent(audio):
            return None
        self._load_model()
        try:
            import torch
            inputs = self._processor(
                audio,
                sampling_rate=_SAMPLE_RATE,
                return_tensors="pt",
                padding=True,
            )
            with torch.no_grad():
                logits = self._model(
                    inputs.input_values,
                    attention_mask=inputs.attention_mask,
                ).logits
            predicted_ids = torch.argmax(logits, dim=-1)
            text: str = self._processor.batch_decode(predicted_ids)[0].strip()
            return text if text else None
        except Exception as exc:
            logger.error("STT транскрипция қатесі: %s", exc)
            return None

    def record_utterance(self, no_speech_timeout: float | None = 8.0) -> np.ndarray | None:
        """Сөйлеу басталғанша күтіп, 1 сек тыныштыққа дейін жазады."""
        if self._speech_prob is None:
            self._speech_prob = _load_speech_prob()
        reset = getattr(self._speech_prob, "reset", None)
        if reset:
            reset()
        segmenter = UtteranceSegmenter()
        started = time.monotonic()

        try:
            with sd.InputStream(
                samplerate=_SAMPLE_RATE, channels=1, dtype="float32", blocksize=_FRAME
            ) as stream:
                while True:
                    frame, _ = stream.read(_FRAME)
                    frame = frame[:, 0].copy()
                    utterance = segmenter.feed(frame, self._speech_prob(frame))
                    if utterance is not None:
                        logger.debug("Сөйлем жазылды: %.2f сек", len(utterance) / _SAMPLE_RATE)
                        return utterance
                    waited = time.monotonic() - started
                    if no_speech_timeout and not segmenter.triggered and waited > no_speech_timeout:
                        return None
        except Exception as exc:
            logger.error("Микрофон қатесі: %s", exc)
            return None

    def listen(self, no_speech_timeout: float | None = 8.0) -> str | None:
        """Микрофоннан бір сөйлемді жазып, қазақ мәтінге аудару."""
        logger.info("Тыңдау басталды")
        audio = self.record_utterance(no_speech_timeout)
        if audio is None:
            logger.info("Сөйлеу анықталмады")
            return None

        text = self.transcribe(audio)
        if text:
            logger.info("Дауыс танылды: '%s'", text)
        else:
            logger.info("Тыныштық анықталды, мәтін қайтарылмады")
        return text
