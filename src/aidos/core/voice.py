"""Дауыс тану модулі — wav2vec2-large-xlsr-kazakh арқылы STT."""

import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger("aidos.voice")

_SAMPLE_RATE = 16000
_RECORD_SECONDS = 5
_SILENCE_THRESHOLD = 0.01
_MODEL_ID = "aismlv/wav2vec2-large-xlsr-kazakh"


def _is_silent(audio: np.ndarray) -> bool:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    logger.debug("Аудио RMS деңгейі: %.4f (threshold=%.4f)", rms, _SILENCE_THRESHOLD)
    return rms < _SILENCE_THRESHOLD


class VoiceInput:
    def __init__(self) -> None:
        self._model = None
        self._processor = None
        logger.debug("VoiceInput инициализацияланды, модель=%s", _MODEL_ID)

    def _load_model(self) -> None:
        if self._model is not None:
            return
        logger.info("Казақ STT моделі жүктелуде: %s", _MODEL_ID)
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        self._processor = Wav2Vec2Processor.from_pretrained(_MODEL_ID)
        self._model = Wav2Vec2ForCTC.from_pretrained(_MODEL_ID)
        self._model.eval()
        logger.info("Казақ STT моделі жүктелді")

    def listen(self) -> str | None:
        """Микрофоннан аудио жазып, қазақ мәтінге аудару."""
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

            logger.info("Дауыс танылды: '%s'", text)
            return text if text else None
        except Exception as exc:
            logger.error("STT транскрипция қатесі: %s", exc)
            return None
