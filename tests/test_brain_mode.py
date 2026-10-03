import logging
from types import SimpleNamespace

import aidos.brain.server as brain_server
import aidos.core.voice as voice_mod
from aidos import main


def _run(monkeypatch, piper_voice):
    calls = []

    async def fake_serve(service, bind):
        calls.append(("serve", bind))

    monkeypatch.setenv("LINK_TOKEN", "t0k")
    monkeypatch.setattr(brain_server, "serve", fake_serve)
    monkeypatch.setattr(voice_mod.VoiceInput, "_load_model", lambda self: calls.append(("load",)))
    tts = SimpleNamespace(_piper_voice=piper_voice, synthesize=lambda text: None)
    main.run_brain_mode(SimpleNamespace(route=lambda text: text), tts)
    return calls


def test_stt_model_preloaded_before_serving(monkeypatch):
    calls = _run(monkeypatch, piper_voice=object())
    assert [c[0] for c in calls] == ["load", "serve"]


def test_warns_when_piper_missing(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="aidos.main"):
        _run(monkeypatch, piper_voice=None)
    assert any("Piper жүктелмеген" in r.getMessage() for r in caplog.records)


def test_no_piper_warning_when_loaded(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="aidos.main"):
        _run(monkeypatch, piper_voice=object())
    assert not any("Piper" in r.getMessage() for r in caplog.records)
