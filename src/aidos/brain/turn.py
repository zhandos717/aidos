"""Бір сөйлем → мозг оқиғаларының ағыны (transcript → speech* → end)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import numpy as np

from aidos.brain.gen import link_pb2
from aidos.brain.sentences import split_sentences
from aidos.core.device_ctx import DeviceAction, current_device, turn_actions
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
        timings = link_pb2.TurnTimings()
        current_device.set(utt.device_id)

        if utt.sample_rate != _INPUT_RATE:
            _log.error("Күтпеген sample_rate=%d (device=%s)", utt.sample_rate, utt.device_id)
            yield _end(ids, True, timings)
            return

        started = time.perf_counter()
        try:
            audio = np.frombuffer(utt.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
            text = await asyncio.to_thread(self.transcribe, audio)
        except Exception as exc:
            _log.error("STT қатесі (device=%s): %s", utt.device_id, exc)
            text = None
        timings.stt_ms = _ms_since(started)

        if not text:
            yield _end(ids, True, timings)
            return
        yield link_pb2.BrainEvent(transcript=link_pb2.Transcript(text=text, **ids))

        actions: list[DeviceAction] = []
        turn_actions.set(actions)
        started = time.perf_counter()
        try:
            reply = await asyncio.to_thread(self.respond, text)
        except Exception as exc:
            _log.error("Жауап қатесі (device=%s): %s", utt.device_id, exc)
            timings.llm_ms = _ms_since(started)
            yield _end(ids, True, timings)
            return
        timings.llm_ms = _ms_since(started)

        spoken = 0
        tts_seconds = 0.0
        for sentence in split_sentences(clean_for_speech(reply)):
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(self.synthesize, sentence)
            except Exception as exc:
                _log.error("TTS қатесі (device=%s): %s", utt.device_id, exc)
                result = None
            tts_seconds += time.perf_counter() - started
            if result is None:
                continue
            pcm, rate = result
            spoken += 1
            yield link_pb2.BrainEvent(
                speech=link_pb2.SpeechChunk(text=sentence, pcm_s16le=pcm, sample_rate=rate, **ids)
            )
        timings.tts_ms = round(tts_seconds * 1000)
        for action in actions:
            yield _action_event(ids, action)
        yield _end(ids, spoken == 0, timings)


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _end(ids: dict[str, str], error: bool, timings: link_pb2.TurnTimings) -> link_pb2.BrainEvent:
    return link_pb2.BrainEvent(end=link_pb2.TurnEnd(error=error, timings=timings, **ids))


def _action_event(ids: dict[str, str], action: DeviceAction) -> link_pb2.BrainEvent:
    if action.kind == "play":
        return link_pb2.BrainEvent(
            action=link_pb2.Action(play=link_pb2.PlayStream(url=action.url, title=action.title), **ids)
        )
    return link_pb2.BrainEvent(action=link_pb2.Action(**{action.kind: link_pb2.Empty()}, **ids))
