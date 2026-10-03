"""Бір сөйлем → мозг оқиғаларының ағыны (transcript → speech* → end)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import numpy as np

from aidos.brain.gen import link_pb2
from aidos.brain.sentences import split_sentences
from aidos.core.device_ctx import current_device
from aidos.core.speech_text import clean_for_speech

_log = logging.getLogger("aidos.brain.turn")

_INPUT_RATE = 16000


@dataclass
class TurnRunner:
    transcribe: Callable[[np.ndarray], str | None]
    respond: Callable[[str], str]
    synthesize: Callable[[str], tuple[bytes, int] | None]

    async def run(self, utt: link_pb2.Utterance) -> AsyncIterator[link_pb2.BrainEvent]:
        ids = {"device_id": utt.device_id, "turn_id": utt.turn_id}
        current_device.set(utt.device_id)

        if utt.sample_rate != _INPUT_RATE:
            _log.error("Күтпеген sample_rate=%d (device=%s)", utt.sample_rate, utt.device_id)
            yield _end(ids, error=True)
            return

        try:
            audio = np.frombuffer(utt.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
            text = await asyncio.to_thread(self.transcribe, audio)
        except Exception as exc:
            _log.error("STT қатесі (device=%s): %s", utt.device_id, exc)
            yield _end(ids, error=True)
            return

        if not text:
            yield _end(ids, error=True)
            return
        yield link_pb2.BrainEvent(transcript=link_pb2.Transcript(text=text, **ids))

        try:
            reply = await asyncio.to_thread(self.respond, text)
        except Exception as exc:
            _log.error("Жауап қатесі (device=%s): %s", utt.device_id, exc)
            yield _end(ids, error=True)
            return

        spoken = 0
        for sentence in split_sentences(clean_for_speech(reply)):
            try:
                result = await asyncio.to_thread(self.synthesize, sentence)
            except Exception as exc:
                _log.error("TTS қатесі (device=%s): %s", utt.device_id, exc)
                continue

            if result is None:
                continue
            pcm, rate = result
            spoken += 1
            yield link_pb2.BrainEvent(
                speech=link_pb2.SpeechChunk(text=sentence, pcm_s16le=pcm, sample_rate=rate, **ids)
            )
        yield _end(ids, error=spoken == 0)


def _end(ids: dict[str, str], error: bool) -> link_pb2.BrainEvent:
    return link_pb2.BrainEvent(end=link_pb2.TurnEnd(error=error, **ids))
