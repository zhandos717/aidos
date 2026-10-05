"""Мәтіннен дауысқа — Piper TTS (офлайн) + edge-tts (fallback).

Робот дауыс эффекті:
  • Ring modulation  — 80 Гц тасымалдаушы сигнал (металдық роботты үн)
  • Bit crush        — 10 биттік квантталу (сандық-цифрлық дыбыс)
  • Soft clip        — tanh қанығу (үйлесімді бұрмалану)
"""

import asyncio
import logging
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger("aidos.tts")

_PIPER_VOICE = "kk/kk_KZ/issai/high/kk_KZ-issai-high"
_PIPER_MODELS_DIR = Path(os.getenv("PIPER_MODELS_DIR", "~/.aidos/piper")).expanduser()
_EDGE_VOICE = "kk-KZ-AigrimNeural"
_EDGE_FALLBACK = "ru-RU-SvetlanaNeural"

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


class TTSEngine:
    def __init__(self) -> None:
        self._piper_voice = None
        self._piper_model_path: Path | None = self._find_piper_model()
        self._loop = asyncio.new_event_loop()

        if self._piper_model_path:
            logger.info("Piper модель табылды: %s", self._piper_model_path)
            self._load_piper()
        else:
            logger.info("Piper модель табылмады, edge-tts пайдаланылады")

    # ── Model management ──────────────────────────────────────────────────────

    def _find_piper_model(self) -> Path | None:
        onnx = _PIPER_MODELS_DIR / f"{_PIPER_VOICE}.onnx"
        if onnx.exists():
            return onnx
        logger.debug("Piper модель жоқ: %s", onnx)
        return None

    def _find_piper_config(self) -> Path | None:
        return Path(str(self._piper_model_path) + ".json") if self._piper_model_path else None

    def _load_piper(self) -> None:
        try:
            from piper.voice import PiperVoice
            self._piper_voice = PiperVoice.load(str(self._piper_model_path))
            logger.info("Piper модель жүктелді және кешталды")
        except Exception as exc:
            logger.error("Piper модель жүктеу қатесі: %s", exc)
            self._piper_voice = None

    # ── Piper ─────────────────────────────────────────────────────────────────

    def _speak_piper(self, text: str) -> None:
        import io
        import sounddevice as sd

        logger.debug("Piper синтез басталды")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper_voice.synthesize_wav(text, wf)

        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            sr = wf.getframerate()
            audio = np.frombuffer(frames, dtype=np.int16).copy()

        audio = _robot_effect(audio, sr)
        sd.play(audio, samplerate=sr)
        sd.wait()
        logger.debug("Piper ойнату аяқталды (robot effect)")

    # ── edge-tts ──────────────────────────────────────────────────────────────

    async def _speak_edge_async(self, text: str, voice: str) -> None:
        import edge_tts

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = Path(tmp.name)
        wav_path = mp3_path.with_suffix(".wav")

        try:
            communicator = edge_tts.Communicate(text, voice)
            await communicator.save(str(mp3_path))
            logger.debug("edge-tts аудио жасалды: %d байт", mp3_path.stat().st_size)

            # MP3 → WAV → робот эффекті → sounddevice
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(mp3_path),
                     "-ar", "22050", "-ac", "1", str(wav_path)],
                    capture_output=True, check=True,
                )
                with wave.open(str(wav_path), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    sr = wf.getframerate()
                    audio = np.frombuffer(frames, dtype=np.int16).copy()

                import sounddevice as sd
                audio = _robot_effect(audio, sr)
                sd.play(audio, samplerate=sr)
                sd.wait()
                logger.debug("edge-tts ойнатылды (robot effect)")

            except Exception as conv_exc:
                # ffmpeg жоқ болса — pygame арқылы эффектсіз ойнату
                logger.warning("ffmpeg конвертация сәтсіз (%s), pygame fallback", conv_exc)
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.music.load(str(mp3_path))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    await asyncio.sleep(0.1)

        finally:
            mp3_path.unlink(missing_ok=True)
            if wav_path.exists():
                wav_path.unlink(missing_ok=True)

    # ── Public ────────────────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        logger.info("TTS іске қосылды, ұзындығы=%d таңба", len(text))
        logger.debug("TTS мәтін: '%s'", text[:100])

        # 1. Piper (офлайн)
        if self._piper_voice:
            try:
                self._speak_piper(text)
                logger.info("TTS аяқталды (Piper + robot)")
                return
            except Exception as exc:
                logger.error("Piper қатесі: %s", exc)

        # 2. edge-tts (онлайн fallback)
        try:
            self._loop.run_until_complete(self._speak_edge_async(text, _EDGE_VOICE))
            logger.info("TTS аяқталды (edge-tts + robot)")
        except Exception as exc:
            logger.error("edge-tts қатесі: %s", exc)
            try:
                self._loop.run_until_complete(self._speak_edge_async(text, _EDGE_FALLBACK))
            except Exception as exc2:
                logger.error("TTS барлық жолдар сәтсіз: %s", exc2)
                print(f"[Aidos]: {text}")
