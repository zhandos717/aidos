import numpy as np

from aidos.core.voice import VoiceInput


class _Out:
    def __init__(self, v):
        self.logits = v


class _Inputs:
    input_values = None
    attention_mask = None


def _voice(monkeypatch):
    import torch

    monkeypatch.setattr(VoiceInput, "_load_model", lambda self: None)
    voice = VoiceInput.__new__(VoiceInput)
    calls = []

    def processor(audio, **kw):
        return _Inputs()

    processor.batch_decode = lambda ids: ["сәлем"]

    def model(values, attention_mask=None):
        calls.append(1)
        return _Out(torch.zeros(1, 3, 4))

    voice._processor = processor
    voice._model = model
    return voice, calls


def test_quiet_audio_skipped_by_default(monkeypatch):
    voice, calls = _voice(monkeypatch)
    quiet = np.full(16000, 0.001, dtype=np.float32)
    assert voice.transcribe(quiet) is None
    assert calls == []


def test_quiet_audio_reaches_model_without_gate(monkeypatch):
    voice, calls = _voice(monkeypatch)
    quiet = np.full(16000, 0.001, dtype=np.float32)
    assert voice.transcribe(quiet, check_silence=False) == "сәлем"
    assert calls == [1]
