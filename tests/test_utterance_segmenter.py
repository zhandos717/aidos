import numpy as np

from aidos.core.voice import UtteranceSegmenter

FRAME_MS = 32


def _frame(value: float) -> np.ndarray:
    return np.full(512, value, dtype=np.float32)


def _feed(segmenter: UtteranceSegmenter, probs: list[float]):
    results = []
    for i, prob in enumerate(probs):
        out = segmenter.feed(_frame(i), prob)
        if out is not None:
            results.append(out)
    return results


def _ms(ms: int) -> int:
    return -(-ms // FRAME_MS)


def test_silence_yields_nothing():
    seg = UtteranceSegmenter(frame_ms=FRAME_MS)
    assert _feed(seg, [0.0] * _ms(5000)) == []
    assert not seg.triggered


def test_utterance_ends_after_silence():
    seg = UtteranceSegmenter(frame_ms=FRAME_MS, end_silence_ms=1000, pre_roll_ms=96)
    probs = [0.0] * 10 + [0.9] * _ms(800) + [0.1] * _ms(1000)
    [utterance] = _feed(seg, probs)

    pre_roll, speech, silence = _ms(96), _ms(800), _ms(1000)
    assert len(utterance) == (pre_roll + speech + silence) * 512
    assert not seg.triggered


def test_short_noise_is_dropped():
    seg = UtteranceSegmenter(frame_ms=FRAME_MS, min_speech_ms=250, end_silence_ms=1000)
    probs = [0.9] * _ms(100) + [0.0] * _ms(1000)
    assert _feed(seg, probs) == []


def test_short_pause_does_not_split():
    seg = UtteranceSegmenter(frame_ms=FRAME_MS, end_silence_ms=1000)
    probs = [0.9] * _ms(500) + [0.0] * _ms(500) + [0.9] * _ms(500) + [0.0] * _ms(1000)
    assert len(_feed(seg, probs)) == 1


def test_max_length_cuts_utterance():
    seg = UtteranceSegmenter(frame_ms=FRAME_MS, max_utterance_ms=2000)
    results = _feed(seg, [0.9] * _ms(5000))
    assert len(results) == 2
    assert all(len(r) == (2000 // FRAME_MS) * 512 for r in results)
