"""Мәтіннен дауысқа — Piper TTS (офлайн) / edge-tts, эффект баптаулардан таңдалады.

Робот дауыс эффекті:
  • Ring modulation  — 80 Гц тасымалдаушы сигнал (металдық роботты үн)
  • Bit crush        — 10 биттік квантталу (сандық-цифрлық дыбыс)
  • Soft clip        — tanh қанығу (үйлесімді бұрмалану)
"""

import asyncio
import io
import logging
import os
import queue
import re
import threading
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from aidos.core.settings import settings

logger = logging.getLogger("aidos.tts")

_PIPER_VOICE = "kk/kk_KZ/issai/high/kk_KZ-issai-high"
_PIPER_MODELS_DIR = Path(os.getenv("PIPER_MODELS_DIR", "~/.aidos/piper")).expanduser()
_EDGE_FALLBACK = "kk-KZ-AigulNeural"

TTS_PROVIDERS: dict[str, str] = {
    "piper": "Piper қазақша (офлайн)",
    "edge": "Microsoft edge-tts (онлайн)",
}

EDGE_VOICES: dict[str, str] = {
    "kk-KZ-DauletNeural": "Даулет · kk ♂",
    "kk-KZ-AigulNeural": "Айгүл · kk ♀",
    "ru-RU-DmitryNeural": "Дмитрий · ru ♂",
    "ru-RU-SvetlanaNeural": "Светлана · ru ♀",
    "en-GB-RyanNeural": "Ryan · en-GB ♂",
    "en-GB-ThomasNeural": "Thomas · en-GB ♂",
    "en-US-AndrewMultilingualNeural": "Andrew · көптілді ♂",
}

TTS_EFFECTS: dict[str, str] = {
    "robot": "Робот",
    "jarvis": "J.A.R.V.I.S",
    "none": "Таза дауыс",
}

# highpass + жоғары жиілік көтеру + chorus + қысқа эхо — «цифрлық» призвук
_JARVIS_FILTER = (
    "highpass=f=120,"
    "equalizer=f=3000:t=q:w=1:g=3,"
    "chorus=0.6:0.9:25:0.3:0.25:2,"
    "aecho=0.8:0.6:18|35:0.25|0.15"
)

# Робот эффектінің параметрлері
_RING_FREQ   = 80.0   # Гц — тасымалдаушы жиілік (төмен → терең робот, жоғары → Dalek)
_RING_MIX    = 0.45   # Ring модуляция қоспасы (0 = таза, 1 = толық)
_BIT_DEPTH   = 10     # Квантталу биттері (8–12 аралығы жақсы)
_DRIVE       = 2.2    # Tanh драйв (≥1.5 — дыбыс «майысады»)
_OUTPUT_GAIN = 0.90   # Соңғы нормализация


def _robot_effect(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """int16 немесе float32 аудиоға роботтық дауыс эффектін қолдану."""
    # float32-ге түрлендіру
    if audio.dtype == np.int16:
        sig = audio.astype(np.float32) / 32768.0
        to_int16 = True
    else:
        sig = audio.astype(np.float32)
        to_int16 = False

    # 1. Ring modulation
    t = np.arange(len(sig), dtype=np.float32) / sample_rate
    carrier = np.sin(2.0 * np.pi * _RING_FREQ * t)
    sig = sig * (1.0 - _RING_MIX + _RING_MIX * carrier)

    # 2. Bit crush
    levels = float(1 << _BIT_DEPTH)
    sig = np.round(sig * levels) / levels

    # 3. Soft clip (tanh overdrive)
    sig = np.tanh(sig * _DRIVE) / np.tanh(_DRIVE)

    # 4. Normalize
    peak = float(np.max(np.abs(sig)))
    if peak > 1e-6:
        sig = sig / peak * _OUTPUT_GAIN

    return (sig * 32767).astype(np.int16) if to_int16 else sig


def _jarvis_effect(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
         "-i", "-", "-af", _JARVIS_FILTER, "-f", "s16le", "-"],
        input=audio.astype(np.int16).tobytes(), capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.int16).copy()


def _apply_effect(audio: np.ndarray, sample_rate: int, effect: str) -> np.ndarray:
    if effect == "jarvis":
        try:
            return _jarvis_effect(audio, sample_rate)
        except Exception as exc:
            logger.warning("Jarvis эффекті сәтсіз (%s), таза дауыс", exc)
            return audio
    if effect == "robot":
        return _robot_effect(audio, sample_rate)
    return audio


# RLock: SpeechStream бүкіл жауапқа ұстайды, ішіндегі _play қайта алады
_play_lock = threading.RLock()


_out_stream = None


def _play(audio: np.ndarray, sample_rate: int) -> None:
    """Жеке, ашық тұратын OutputStream.

    sd.play/sd.rec бір ортақ ағынды пайдаланады — микрофон қосылса сөйлеу үзіледі.
    Ағынды әр сөйлемге қайта ашу ~1 с кідіріс береді, сондықтан ол ашық қалады.
    """
    global _out_stream
    import sounddevice as sd

    with _play_lock:
        if _out_stream is None or _out_stream.samplerate != sample_rate or not _out_stream.active:
            if _out_stream is not None:
                _out_stream.close()
            _out_stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16")
            _out_stream.start()
        _out_stream.write(np.ascontiguousarray(audio.astype(np.int16)).reshape(-1, 1))


def stop_playback() -> None:
    """Ойнап жатқан дыбысты бірден тоқтату; келесі _play ағынды қайта ашады."""
    stream = _out_stream
    if stream is not None and stream.active:
        try:
            stream.abort()
        except Exception as exc:
            logger.debug("abort қатесі: %s", exc)


_KAZAKH_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")


def _is_russian(text: str) -> bool:
    return bool(_CYRILLIC.search(text)) and not any(ch in _KAZAKH_LETTERS for ch in text)


def _read_wav(src) -> tuple[np.ndarray, int]:
    with wave.open(src, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        return np.frombuffer(frames, dtype=np.int16).copy(), wf.getframerate()


class TTSEngine:
    def __init__(self) -> None:
        self._piper_voice = None
        self._piper_model_path: Path | None = self._find_piper_model()
        self._loop = asyncio.new_event_loop()
        self._synth_lock = threading.Lock()

        if self._piper_model_path:
            logger.info("Piper модель табылды: %s", self._piper_model_path)
            self._load_piper()
        else:
            logger.info("Piper модель табылмады, edge-tts пайдаланылады")

    @property
    def piper_ready(self) -> bool:
        return self._piper_voice is not None

    def _find_piper_model(self) -> Path | None:
        onnx = _PIPER_MODELS_DIR / f"{_PIPER_VOICE}.onnx"
        if onnx.exists():
            return onnx
        logger.debug("Piper модель жоқ: %s", onnx)
        return None

    def _load_piper(self) -> None:
        try:
            from piper.voice import PiperVoice
            self._piper_voice = PiperVoice.load(str(self._piper_model_path))
            logger.info("Piper модель жүктелді және кешталды")
        except Exception as exc:
            logger.error("Piper модель жүктеу қатесі: %s", exc)
            self._piper_voice = None

    def _synth_piper(self, text: str) -> tuple[np.ndarray, int]:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper_voice.synthesize_wav(text, wf)
        buf.seek(0)
        return _read_wav(buf)

    async def _synth_edge_async(self, text: str, voice: str) -> tuple[np.ndarray, int]:
        import edge_tts

        with tempfile.TemporaryDirectory() as tmp:
            mp3_path = Path(tmp) / "speech.mp3"
            wav_path = Path(tmp) / "speech.wav"
            await edge_tts.Communicate(text, voice).save(str(mp3_path))
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "22050", "-ac", "1", str(wav_path)],
                capture_output=True, check=True,
            )
            return _read_wav(str(wav_path))

    def _synth_edge(self, text: str, voice: str) -> tuple[np.ndarray, int]:
        # edge-tts кейде бірінші сұранысқа «No audio was received» қайтарады
        for attempt in range(3):
            try:
                return self._loop.run_until_complete(self._synth_edge_async(text, voice))
            except Exception as exc:
                if attempt == 2:
                    raise
                logger.warning("edge-tts қайталау %d (%s): %s", attempt + 1, voice, exc)

    def _synthesize(self, text: str) -> tuple[np.ndarray, int]:
        with self._synth_lock:
            return self._synthesize_locked(text)

    def _synthesize_locked(self, text: str) -> tuple[np.ndarray, int]:
        cfg = settings.current
        # Piper қазақ моделі мен қазақ edge дауыстары орысша мәтінді бұзып оқиды
        if _is_russian(text) and not cfg.tts_voice.startswith(("ru-", "en-US-AndrewMultilingual")):
            try:
                return self._synth_edge(text, cfg.tts_voice_ru)
            except Exception as exc:
                logger.error("Орысша edge-tts қатесі: %s", exc)
        if cfg.tts_provider == "piper" and self._piper_voice:
            try:
                return self._synth_piper(text)
            except Exception as exc:
                logger.error("Piper қатесі: %s", exc)
        voice = cfg.tts_voice if cfg.tts_voice in EDGE_VOICES else _EDGE_FALLBACK
        try:
            return self._synth_edge(text, voice)
        except Exception as exc:
            logger.error("edge-tts қатесі (%s): %s", voice, exc)
            return self._synth_edge(text, _EDGE_FALLBACK)

    def render(self, text: str) -> tuple[np.ndarray, int]:
        if not re.search(r"\w", text):
            # edge-tts тек тыныс белгілері мен эмодзиге «No audio» қайтарады
            return np.zeros(0, dtype=np.int16), 22050
        audio, sr = self._synthesize(text)
        return _apply_effect(audio, sr, settings.current.tts_effect), sr

    def stream(self) -> "SpeechStream":
        return SpeechStream(self)

    def speak(self, text: str) -> None:
        logger.info("TTS іске қосылды, ұзындығы=%d таңба", len(text))
        try:
            _play(*self.render(text))
        except Exception as exc:
            logger.error("TTS барлық жолдар сәтсіз: %s", exc)
            print(f"[Aidos]: {text}")


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
_MIN_CHUNK = 25


class SpeechStream:
    """LLM стримін сөйлемдерге бөліп сөйлейді: келесі сөйлем алдыңғысы ойнап жатқанда синтезделеді."""

    def __init__(self, engine: TTSEngine) -> None:
        self._engine = engine
        self._cancelled = False
        self._buffer = ""
        self._texts: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=2)
        self._synth_thread = threading.Thread(target=self._synth_worker, daemon=True)
        self._play_thread = threading.Thread(target=self._play_worker, daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def cancel(self) -> None:
        self._cancelled = True
        self._buffer = ""
        while not self._texts.empty():
            self._texts.get_nowait()
        self._texts.put(None)
        stop_playback()

    def feed(self, delta: str) -> None:
        if self._cancelled:
            return
        self._buffer += delta
        parts = _SENTENCE_END.split(self._buffer)
        ready, self._buffer = parts[:-1], parts[-1]
        chunk = ""
        for sentence in ready:
            chunk = f"{chunk} {sentence}".strip()
            if len(chunk) >= _MIN_CHUNK:
                self._texts.put(chunk)
                chunk = ""
        if chunk:
            self._buffer = f"{chunk} {self._buffer}".strip()

    def close(self) -> None:
        if self._cancelled:
            return
        if self._buffer.strip():
            self._texts.put(self._buffer.strip())
        self._buffer = ""
        self._texts.put(None)

    def wait(self) -> None:
        self._play_thread.join()

    def _synth_worker(self) -> None:
        while (text := self._texts.get()) is not None:
            if self._cancelled:
                break
            try:
                self._audio.put(self._engine.render(text))
            except Exception as exc:
                logger.error("Стрим TTS синтез қатесі: %s", exc)
        self._audio.put(None)

    def _play_worker(self) -> None:
        with _play_lock:
            while (item := self._audio.get()) is not None:
                if self._cancelled:
                    continue
                try:
                    _play(*item)
                except Exception as exc:
                    logger.error("Стрим TTS ойнату қатесі: %s", exc)
