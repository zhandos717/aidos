"""Дауыс тану модулі — STT провайдерлері баптаулардан таңдалады."""

import io
import logging
import os
import threading
import wave

import numpy as np
import sounddevice as sd

from aidos.core.settings import settings

logger = logging.getLogger("aidos.voice")

_SAMPLE_RATE = 16000
_RECORD_SECONDS = 5
_SILENCE_THRESHOLD = 0.01

STT_PROVIDERS: dict[str, str] = {
    "wav2vec2": "wav2vec2 қазақша (офлайн)",
    "whisper": "Whisper turbo (офлайн, ru+kk аралас)",
    "openai": "OpenAI gpt-4o-transcribe (бұлт)",
}

STT_LANGUAGES: dict[str, str] = {
    "kk": "Қазақша",
    "ru": "Орысша",
    "auto": "Авто",
}

# Whisper тілді 30 секундқа бір рет таңдайды; аралас мысал оған
# орыс сөздерін аудармай, сол күйі жазуға көмектеседі.
_MIXED_PROMPT = "Айдос, музыканы қос. Громкость побольше. Ертең погода қандай болады?"


def _is_silent(audio: np.ndarray) -> bool:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    logger.debug("Аудио RMS деңгейі: %.4f (threshold=%.4f)", rms, _SILENCE_THRESHOLD)
    return rms < _SILENCE_THRESHOLD


class Wav2Vec2Transcriber:
    _MODEL_ID = "aismlv/wav2vec2-large-xlsr-kazakh"

    def __init__(self) -> None:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        logger.info("Казақ STT моделі жүктелуде: %s", self._MODEL_ID)
        self._processor = Wav2Vec2Processor.from_pretrained(self._MODEL_ID)
        self._model = Wav2Vec2ForCTC.from_pretrained(self._MODEL_ID)
        self._model.eval()

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        import torch

        inputs = self._processor(audio, sampling_rate=_SAMPLE_RATE, return_tensors="pt", padding=True)
        with torch.no_grad():
            logits = self._model(inputs.input_values, attention_mask=inputs.attention_mask).logits
        return self._processor.batch_decode(torch.argmax(logits, dim=-1))[0]


class WhisperTranscriber:
    def __init__(self) -> None:
        import whisper

        model_name = os.getenv("WHISPER_MODEL", "turbo")
        logger.info("Whisper моделі жүктелуде: %s", model_name)
        self._model = whisper.load_model(model_name)

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        result = self._model.transcribe(
            audio.astype(np.float32),
            language=None if language == "auto" else language,
            initial_prompt=_MIXED_PROMPT,
            fp16=False,
        )
        return result["text"]


class OpenAITranscriber:
    def __init__(self) -> None:
        from openai import OpenAI

        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY баптанбаған (.env)")
        self._client = OpenAI()

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        buf.name = "speech.wav"
        buf.seek(0)
        kwargs = {} if language == "auto" else {"language": language}
        result = self._client.audio.transcriptions.create(
            model="gpt-4o-transcribe", file=buf, prompt=_MIXED_PROMPT, **kwargs
        )
        return result.text


_TRANSCRIBERS = {
    "wav2vec2": Wav2Vec2Transcriber,
    "whisper": WhisperTranscriber,
    "openai": OpenAITranscriber,
}


class VoiceInput:
    def __init__(self) -> None:
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def _transcriber(self, provider: str):
        with self._lock:
            if provider not in self._cache:
                self._cache[provider] = _TRANSCRIBERS[provider]()
            return self._cache[provider]

    def transcribe(self, audio: np.ndarray) -> str | None:
        """Берілген numpy аудио массивін мәтінге аудару."""
        if _is_silent(audio):
            return None
        cfg = settings.current
        provider = cfg.stt_provider if cfg.stt_provider in _TRANSCRIBERS else "wav2vec2"
        try:
            text = self._transcriber(provider).transcribe(audio, cfg.stt_language).strip()
            logger.info("STT (%s): '%s'", provider, text)
            return text or None
        except Exception as exc:
            logger.error("STT транскрипция қатесі (%s): %s", provider, exc)
            return None

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
        except Exception as exc:
            logger.error("Микрофон қатесі: %s", exc)
            return None
        return self.transcribe(audio.flatten())
