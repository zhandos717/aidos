import time

import numpy as np

from aidos.brain.gen import link_pb2
from aidos.brain.turn import TurnRunner
from aidos.core.device_ctx import current_device


def _utt(sample_rate=16000):
    pcm = (np.ones(1600, dtype=np.int16) * 1000).tobytes()
    return link_pb2.Utterance(device_id="box-1", turn_id="t1", pcm_s16le=pcm, sample_rate=sample_rate)


def _synth(text):
    return (b"\x00\x00" * len(text), 22050)


async def _collect(runner, utt):
    return [ev async for ev in runner.run(utt)]


async def test_full_turn_event_order():
    seen = {}

    def transcribe(audio):
        seen["audio"] = audio
        return "сағат неше"

    def respond(text):
        seen["device"] = current_device.get()
        return "Қазір сағат он екі. **Түскі** ас уақыты жақын!"

    events = await _collect(TurnRunner(transcribe, respond, _synth), _utt())

    kinds = [e.WhichOneof("kind") for e in events]
    assert kinds == ["transcript", "speech", "speech", "end"]
    assert events[0].transcript.text == "сағат неше"
    assert events[1].speech.text == "Қазір сағат он екі."
    assert events[2].speech.text == "Түскі ас уақыты жақын!"
    assert events[1].speech.sample_rate == 22050
    assert events[3].end.error is False
    assert all(e.WhichOneof("kind") and getattr(e, e.WhichOneof("kind")).turn_id == "t1" for e in events)
    assert seen["device"] == "box-1"
    assert seen["audio"].dtype == np.float32
    assert abs(float(seen["audio"][0]) - 1000 / 32768) < 1e-6


async def test_empty_transcript_ends_with_error():
    events = await _collect(TurnRunner(lambda a: None, lambda t: "x", _synth), _utt())
    assert [e.WhichOneof("kind") for e in events] == ["end"]
    assert events[0].end.error is True


async def test_wrong_sample_rate_is_error():
    events = await _collect(TurnRunner(lambda a: "x", lambda t: "x", _synth), _utt(sample_rate=8000))
    assert events[-1].end.error is True


async def test_no_audio_synthesized_is_error():
    events = await _collect(TurnRunner(lambda a: "сәлем", lambda t: "Сәлем, қалайсыз?", lambda s: None), _utt())
    assert [e.WhichOneof("kind") for e in events] == ["transcript", "end"]
    assert events[-1].end.error is True


async def test_respond_exception_is_error():
    def boom(text):
        raise RuntimeError("llm down")

    events = await _collect(TurnRunner(lambda a: "сәлем", boom, _synth), _utt())
    assert events[-1].end.error is True


async def test_odd_length_pcm_is_error():
    utt = link_pb2.Utterance(device_id="box-1", turn_id="t1", pcm_s16le=b"\x01\x00\x02", sample_rate=16000)
    events = await _collect(TurnRunner(lambda a: "x", lambda t: "x", _synth), utt)
    assert [e.WhichOneof("kind") for e in events] == ["end"]
    assert events[0].end.error is True


async def test_transcribe_exception_is_error():
    def boom(audio):
        raise RuntimeError("stt model error")

    events = await _collect(TurnRunner(boom, lambda t: "x", _synth), _utt())
    assert [e.WhichOneof("kind") for e in events] == ["end"]
    assert events[0].end.error is True


async def test_synthesize_exception_skips_sentence():
    def boom_first(text):
        if text == "Қазір сағат он екі.":
            raise RuntimeError("tts model error")
        return (b"\x00\x00" * len(text), 22050)

    events = await _collect(
        TurnRunner(lambda a: "сәлем", lambda t: "Қазір сағат он екі. Түскі ас уақыты жақын!", boom_first),
        _utt()
    )
    kinds = [e.WhichOneof("kind") for e in events]
    assert kinds == ["transcript", "speech", "end"]
    assert events[1].speech.text == "Түскі ас уақыты жақын!"
    assert events[2].end.error is False


def _slow(value, delay=0.02):
    def fn(*_):
        time.sleep(delay)
        return value
    return fn


async def test_timings_reported_on_success():
    runner = TurnRunner(
        transcribe=_slow("сағат неше"),
        respond=_slow("Қазір сағат он екі. Түскі ас уақыты жақын!"),
        synthesize=_slow((b"\x00\x00" * 10, 22050), delay=0.01),
    )
    events = await _collect(runner, _utt())
    end = events[-1].end
    assert end.error is False
    assert end.timings.stt_ms >= 20
    assert end.timings.llm_ms >= 20
    assert end.timings.tts_ms >= 20


async def test_timings_on_empty_transcript():
    runner = TurnRunner(transcribe=_slow(None), respond=lambda t: "x", synthesize=_synth)
    events = await _collect(runner, _utt())
    end = events[-1].end
    assert end.error is True
    assert end.timings.stt_ms >= 20
    assert (end.timings.llm_ms, end.timings.tts_ms) == (0, 0)
