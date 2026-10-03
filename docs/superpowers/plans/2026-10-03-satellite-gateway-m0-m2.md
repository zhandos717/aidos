# Satellite Gateway M0–M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A BOX-3–compatible client (py-xiaozhi on the Mac) holds a spoken Kazakh conversation through a new Rust gateway that talks gRPC to the existing Python aidos "brain".

**Architecture:** `gateway/` (Rust, tokio/axum/tonic) speaks the xiaozhi WebSocket protocol to devices, decodes Opus, runs Silero VAD to find the end of an utterance and forwards the utterance over one bidirectional gRPC stream `Link` to the brain. The brain (`src/aidos/brain/`, grpc.aio) runs wav2vec2 STT → `IntentRouter` → Piper TTS per sentence and streams `Transcript`/`SpeechChunk`/`TurnEnd` back; the gateway encodes them to Opus 24 kHz and paces them to the device.

**Tech Stack:** Rust 1.94 (edition 2024): tokio 1, axum 0.8 (`ws`), tonic 0.14 + tonic-prost + prost 0.14, tonic-prost-build + protoc-bin-vendored, ort `=2.0.0-rc.13`, opus 0.3 (system libopus via pkg-config), tokio-tungstenite 0.30 (tests). Python 3.12: grpcio ≥1.70, grpcio-tools ≥1.70, pytest-asyncio ≥0.24.

**Spec:** `docs/superpowers/specs/2026-10-03-aidos-satellite-gateway-design.md`

## Global Constraints

- Proto file lives at `proto/link.proto`, `package aidos.link.v1;` (deviation from spec §3 path `proto/aidos/link/v1/` — flat path is required so Python codegen imports resolve as `from aidos.brain.gen import link_pb2`; verified 2026-10-03).
- Python codegen command (only this form produces importable code): `python -m grpc_tools.protoc -Iaidos/brain/gen=proto --python_out=src --grpc_python_out=src --pyi_out=src proto/link.proto`. Generated files in `src/aidos/brain/gen/` are committed.
- Rust codegen: `build.rs` sets `PROTOC` from `protoc_bin_vendored::protoc_bin_path()`; no system protoc.
- Opus: crate `opus = "0.3"` (links Homebrew/apt libopus via pkg-config). `opus 0.4` needs cmake — do not use.
- Silero VAD ONNX: inputs `input` f32 `[1, 576]` (64 samples of context from the previous frame + 512 new), `state` f32 `[2, 1, 128]`, `sr` i64 scalar `16000`; outputs `output` `[1,1]`, `stateN` `[2,1,128]`. Model file copied from the `silero-vad` pip package to `gateway/models/silero_vad.onnx` (MIT).
- VAD parameters (must match Python `UtteranceSegmenter`): frame 512 samples / 32 ms, threshold 0.5, min speech 250 ms, end silence 1000 ms, max utterance 12000 ms, pre-roll 300 ms.
- Device uplink: Opus 16 kHz mono 60 ms frames. Downlink: Opus 24 kHz mono 60 ms frames (1440 samples). Protocol version 1 (raw Opus frames).
- xiaozhi JSON messages exactly as in `docs/websocket.md` of xiaozhi-esp32 (copied into tests below).
- gRPC: brain is the server (`BRAIN_BIND`, default `127.0.0.1:50051`), gateway the client (`BRAIN_ADDR`, default `http://127.0.0.1:50051`); metadata `authorization: Bearer <LINK_TOKEN>`. Python handler must call `await context.send_initial_metadata(())` before reading, otherwise the tonic client blocks on `link().await`.
- Device allowlist for M2: env `GATEWAY_DEVICES="<device_id>=<token>,..."` (device ids are MACs and contain `:`, so `=` is the separator). Pairing/tokens hashing is M3, out of scope here.
- Project rules: few code comments (only non-obvious "why"); Kazakh log/docstring style in Python code as in the existing codebase; commits without `Co-Authored-By` lines; branch `zhanzh/satellite-gateway`.
- Out of scope for this plan: pairing, SQLite, rate limits, canned error audio (M3); pushes (M4); music actions (M5) — gateway logs and ignores `Action`/`Push` events.

## Review Focus

- **Device speaks again while the answer is playing** (`listen` `detect`/`start` or `abort` during `speaking`): playback stops immediately, `tts stop` is sent, the brain receives `Abort` and the stale turn's late events are dropped — pinned in Task 12 e2e `barge_in_aborts_turn`.
- **Brain is down when the device connects or speaks**: gateway keeps serving the WebSocket, logs, returns the device to idle with `tts stop` instead of hanging in "thinking" — pinned in Task 12 e2e `brain_down_returns_to_idle`.
- **Silence or noise only (no speech) / STT returns nothing**: brain answers `TurnEnd{error:true}` without speech; device gets `tts start`+`tts stop` and is idle again — pinned in Task 5 `test_empty_transcript_ends_with_error` and Task 12 handling.
- **Wrong or missing bearer token on `/ws` or unknown `Device-Id` on `/ota`**: 401/403, no upgrade — pinned in Task 12 e2e `rejects_bad_token`, `ota_unknown_device_forbidden`.
- **Piper sample rate ≠ 24 kHz (22050 for issai-high, 16000 for x_low)**: frames sent equal `ceil(duration·24000/1440)` — pinned in Task 9 `resample_lengths` and Task 12 e2e frame count.

---

## File Structure

```
proto/link.proto                         # contract (Task 1)
src/aidos/core/device_ctx.py             # ContextVar current_device (Task 2)
src/aidos/agents/ai_agent.py             # per-device session (Task 2, modify)
src/aidos/brain/__init__.py              # (Task 1)
src/aidos/brain/gen/                     # generated pb2 (Task 1)
src/aidos/brain/sentences.py             # split_sentences (Task 3)
src/aidos/core/tts.py                    # TTSEngine.synthesize (Task 4, modify)
src/aidos/brain/turn.py                  # TurnRunner (Task 5)
src/aidos/brain/server.py                # BrainService + serve() (Task 6)
src/aidos/main.py                        # --brain mode (Task 6, modify)
tests/test_device_ctx.py, tests/test_sentences.py, tests/test_tts_synthesize.py,
tests/test_turn.py, tests/test_brain_server.py
gateway/Cargo.toml, gateway/build.rs     # (Task 7)
gateway/src/lib.rs, main.rs, config.rs   # (Task 7, main.rs finished in Task 12)
gateway/src/xiaozhi.rs                   # protocol messages (Task 8)
gateway/src/audio.rs                     # opus + resample (Task 9)
gateway/src/vad.rs                       # Segmenter, Endpointer, SileroVad (Task 10)
gateway/models/silero_vad.onnx           # (Task 10)
gateway/tests/fixtures/speech_16k.wav    # (Task 10)
gateway/src/link.rs                      # gRPC client + routing (Task 11)
gateway/src/device.rs, server.rs         # per-device session, HTTP/WS (Task 12)
gateway/tests/e2e.rs                     # (Task 12)
.github/workflows/ci.yml                 # (Task 13)
Makefile, pyproject.toml, README.md      # (Tasks 1, 6, 7, 14)
```

---

### Task 1: Proto contract and Python codegen

**Files:**
- Create: `proto/link.proto`, `src/aidos/brain/__init__.py`, `src/aidos/brain/gen/__init__.py`, generated `src/aidos/brain/gen/link_pb2.py`, `link_pb2.pyi`, `link_pb2_grpc.py`
- Modify: `pyproject.toml`, `Makefile`
- Test: `tests/test_proto.py`

**Interfaces:**
- Produces: module `aidos.brain.gen.link_pb2` (messages `GatewayEvent`, `Utterance`, `Abort`, `DeviceState`, `PushAck`, `BrainEvent`, `Transcript`, `SpeechChunk`, `Action`, `PlayStream`, `Empty`, `TurnEnd`, `Push`), `aidos.brain.gen.link_pb2_grpc` (`BrainServicer`, `BrainStub`, `add_BrainServicer_to_server`).

- [ ] **Step 1: Write the proto**

`proto/link.proto`:
```proto
syntax = "proto3";
package aidos.link.v1;

service Brain {
  rpc Link(stream GatewayEvent) returns (stream BrainEvent);
}

message GatewayEvent {
  oneof kind {
    Utterance utterance = 1;
    Abort abort = 2;
    DeviceState state = 3;
    PushAck push_ack = 4;
  }
}

message Utterance { string device_id = 1; string turn_id = 2; bytes pcm_s16le = 3; uint32 sample_rate = 4; }
message Abort { string device_id = 1; string turn_id = 2; }
message DeviceState { string device_id = 1; bool online = 2; }
message PushAck { string push_id = 1; }

message BrainEvent {
  oneof kind {
    Transcript transcript = 1;
    SpeechChunk speech = 2;
    Action action = 3;
    TurnEnd end = 4;
    Push push = 5;
  }
}

message Transcript { string device_id = 1; string turn_id = 2; string text = 3; }
message SpeechChunk { string device_id = 1; string turn_id = 2; string text = 3; bytes pcm_s16le = 4; uint32 sample_rate = 5; }
message TurnEnd { string device_id = 1; string turn_id = 2; bool error = 3; }
message Push { string push_id = 1; string device_id = 2; string text = 3; SpeechChunk speech = 4; int64 created_at_unix = 5; }

message Action {
  string device_id = 1;
  string turn_id = 2;
  oneof kind {
    PlayStream play = 3;
    Empty stop = 4;
    Empty pause = 5;
    Empty resume = 6;
  }
}
message PlayStream { string url = 1; string title = 2; }
message Empty {}
```

- [ ] **Step 2: Add dependencies and Makefile target**

In `pyproject.toml` add to `dependencies`: `"grpcio>=1.70"`, `"protobuf>=5.29"`; change dev extra to `dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6", "grpcio-tools>=1.70"]`; add under `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`.

In `Makefile` add `proto` to `.PHONY` and the target:
```make
proto:
	$(PYTHON) -m grpc_tools.protoc -Iaidos/brain/gen=proto --python_out=src --grpc_python_out=src --pyi_out=src proto/link.proto
```
Add help line: `@echo "  make proto                — gRPC кодын генерациялау (Python)"`.

Run: `.venv/bin/pip install -e ".[dev]"` (from repo root; in a worktree use the main repo venv: `/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/pip install grpcio grpcio-tools pytest-asyncio`).

- [ ] **Step 3: Write the failing test**

`tests/test_proto.py`:
```python
from aidos.brain.gen import link_pb2, link_pb2_grpc


def test_roundtrip_utterance():
    ev = link_pb2.GatewayEvent(
        utterance=link_pb2.Utterance(device_id="d1", turn_id="t1", pcm_s16le=b"\x01\x00", sample_rate=16000)
    )
    parsed = link_pb2.GatewayEvent.FromString(ev.SerializeToString())
    assert parsed.WhichOneof("kind") == "utterance"
    assert parsed.utterance.sample_rate == 16000


def test_service_is_generated():
    assert hasattr(link_pb2_grpc, "BrainServicer")
    assert hasattr(link_pb2_grpc, "BrainStub")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_proto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidos.brain'`

- [ ] **Step 5: Create packages and generate code**

```bash
mkdir -p src/aidos/brain/gen
printf '"""gRPC мозг: шлюз колонкаларына қызмет көрсетеді."""\n' > src/aidos/brain/__init__.py
: > src/aidos/brain/gen/__init__.py
make proto
```
Expected files: `src/aidos/brain/gen/link_pb2.py`, `link_pb2.pyi`, `link_pb2_grpc.py`; `link_pb2_grpc.py` contains `from aidos.brain.gen import link_pb2`.

Add to `pyproject.toml` a ruff exclusion so generated code is not linted:
```toml
[tool.ruff]
extend-exclude = ["src/aidos/brain/gen"]
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (31 tests).

- [ ] **Step 7: Commit**

```bash
git add proto src/aidos/brain pyproject.toml Makefile tests/test_proto.py
git commit -m "feat(brain): gRPC Link contract and Python codegen"
```

---

### Task 2: Per-device context and per-device AI sessions

**Files:**
- Create: `src/aidos/core/device_ctx.py`
- Modify: `src/aidos/agents/ai_agent.py` (`handle`, lines 52–63)
- Test: `tests/test_device_ctx.py`

**Interfaces:**
- Produces: `aidos.core.device_ctx.current_device: ContextVar[str | None]` (default `None`). `AIAgent.handle()` uses session id `f"device:{device_id}"` when `current_device` is set, otherwise its own `_session_id`.

- [ ] **Step 1: Write the failing test**

`tests/test_device_ctx.py`:
```python
import contextvars

from aidos.agents.ai_agent import AIAgent
from aidos.core.device_ctx import current_device
from aidos.core.memory import MemoryStore
from aidos.core.tool_registry import ToolRegistry


class EchoClient:
    def chat(self, messages, system=None):
        return f"ok:{len(messages)}"


def _agent(tmp_path):
    return AIAgent(client=EchoClient(), memory=MemoryStore(tmp_path / "m.db"), registry=ToolRegistry(), session_id="local")


def test_default_session_without_device(tmp_path):
    agent = _agent(tmp_path)
    agent.handle("сәлем")
    assert len(agent._memory.get_session("local")) == 2


def test_each_device_has_own_history(tmp_path):
    agent = _agent(tmp_path)

    def ask(device_id, text):
        current_device.set(device_id)
        return agent.handle(text)

    contextvars.copy_context().run(ask, "box-1", "бір")
    contextvars.copy_context().run(ask, "box-1", "екі")
    contextvars.copy_context().run(ask, "box-2", "үш")

    assert len(agent._memory.get_session("device:box-1")) == 4
    assert len(agent._memory.get_session("device:box-2")) == 2
    assert agent._memory.get_session("local") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_device_ctx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidos.core.device_ctx'`

- [ ] **Step 3: Implement**

`src/aidos/core/device_ctx.py`:
```python
"""Ағымдағы колонка — gRPC ход кезінде агенттер кімге жауап беретінін біледі."""

from contextvars import ContextVar

current_device: ContextVar[str | None] = ContextVar("current_device", default=None)
```

In `src/aidos/agents/ai_agent.py` add import `from aidos.core.device_ctx import current_device` and replace `handle`:
```python
    def handle(self, query: str) -> str:
        _log.info("AIAgent.handle: '%s'", query[:80])
        device_id = current_device.get()
        session_id = f"device:{device_id}" if device_id else self._session_id
        self._memory.add_message(session_id, "user", query)
        self._extract_facts(query)

        system = self._build_system(query)
        messages = self._memory.get_session(session_id, limit=_MAX_HISTORY)

        response = self._react(messages, system)

        self._memory.add_message(session_id, "assistant", response)
        return response
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/aidos/core/device_ctx.py src/aidos/agents/ai_agent.py tests/test_device_ctx.py
git commit -m "feat(brain): per-device AI session via current_device ContextVar"
```

---

### Task 3: Sentence splitting for streamed TTS

**Files:**
- Create: `src/aidos/brain/sentences.py`
- Test: `tests/test_sentences.py`

**Interfaces:**
- Produces: `split_sentences(text: str, min_len: int = 12) -> list[str]` — splits after `.`, `!`, `?`, `…` followed by whitespace; a piece shorter than `min_len` is merged with the next one so playback is not choppy.

- [ ] **Step 1: Write the failing test**

`tests/test_sentences.py`:
```python
from aidos.brain.sentences import split_sentences


def test_splits_on_terminal_punctuation():
    text = "Абай — қазақтың ұлы ақыны. Ол ойшыл болған! Сіз білесіз бе?"
    assert split_sentences(text) == ["Абай — қазақтың ұлы ақыны.", "Ол ойшыл болған!", "Сіз білесіз бе?"]


def test_short_piece_is_merged_with_next():
    assert split_sentences("Иә. Қазір сағат он екі.") == ["Иә. Қазір сағат он екі."]


def test_decimal_point_is_not_a_boundary():
    assert split_sentences("Температура 17.5 градус болады.") == ["Температура 17.5 градус болады."]


def test_trailing_short_piece_is_kept():
    assert split_sentences("Бұл ұзын бірінші сөйлем. Иә.") == ["Бұл ұзын бірінші сөйлем.", "Иә."]


def test_empty():
    assert split_sentences("   ") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentences.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/aidos/brain/sentences.py`:
```python
"""Жауапты сөйлемдерге бөлу — бірінші сөйлем қалғандары синтезделгенше ойнай береді."""

import re

_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str, min_len: int = 12) -> list[str]:
    pieces = [p.strip() for p in _BOUNDARY_RE.split(text) if p.strip()]
    result: list[str] = []
    carry = ""
    for piece in pieces:
        piece = f"{carry} {piece}".strip() if carry else piece
        if len(piece) < min_len:
            carry = piece
            continue
        result.append(piece)
        carry = ""
    if carry:
        result.append(carry)
    return result
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_sentences.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/aidos/brain/sentences.py tests/test_sentences.py
git commit -m "feat(brain): sentence splitting for per-sentence TTS"
```

---

### Task 4: `TTSEngine.synthesize` returning PCM

**Files:**
- Modify: `src/aidos/core/tts.py` (`_speak_piper` and add `synthesize`)
- Test: `tests/test_tts_synthesize.py`

**Interfaces:**
- Produces: `TTSEngine.synthesize(text: str) -> tuple[bytes, int] | None` — mono s16le PCM and its sample rate from Piper; `None` when Piper is not loaded or the cleaned text is empty. `_speak_piper` plays the result of `synthesize`.

- [ ] **Step 1: Write the failing test**

`tests/test_tts_synthesize.py`:
```python
from aidos.core.tts import TTSEngine


class FakeVoice:
    def __init__(self):
        self.texts = []

    def synthesize_wav(self, text, wav_file):
        self.texts.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x01\x00" * 100)


def _engine(voice):
    engine = TTSEngine.__new__(TTSEngine)
    engine._piper_voice = voice
    return engine


def test_synthesize_returns_pcm_and_rate():
    voice = FakeVoice()
    pcm, rate = _engine(voice).synthesize("**Сәлем!** 👋")
    assert rate == 22050
    assert len(pcm) == 200
    assert voice.texts == ["Сәлем!"]


def test_without_piper_returns_none():
    assert _engine(None).synthesize("Сәлем") is None


def test_empty_after_cleaning_returns_none():
    assert _engine(FakeVoice()).synthesize("🎉") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tts_synthesize.py -v`
Expected: FAIL with `AttributeError: 'TTSEngine' object has no attribute 'synthesize'`

- [ ] **Step 3: Implement**

In `src/aidos/core/tts.py` add `import io` and `import wave` to the top-level imports, then replace `_speak_piper` with:
```python
    def synthesize(self, text: str) -> tuple[bytes, int] | None:
        if not self._piper_voice:
            return None
        text = clean_for_speech(text)
        if not text:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            self._piper_voice.synthesize_wav(text, wav_file)
        buf.seek(0)
        with wave.open(buf, "rb") as wav_file:
            return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()

    def _speak_piper(self, text: str) -> None:
        import numpy as np
        import sounddevice as sd

        result = self.synthesize(text)
        if result is None:
            return
        pcm, rate = result
        sd.play(np.frombuffer(pcm, dtype=np.int16), samplerate=rate)
        sd.wait()
```
Remove the now-unused local `import io` / `import wave` lines that were inside the old `_speak_piper`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/aidos/core/tts.py tests/test_tts_synthesize.py
git commit -m "feat(tts): synthesize() returns PCM for streaming to devices"
```

---

### Task 5: `TurnRunner` — one utterance to a stream of brain events

**Files:**
- Create: `src/aidos/brain/turn.py`
- Test: `tests/test_turn.py`

**Interfaces:**
- Consumes: `current_device` (Task 2), `split_sentences` (Task 3), `clean_for_speech` (`aidos.core.speech_text`), `link_pb2` (Task 1).
- Produces:
  ```python
  @dataclass
  class TurnRunner:
      transcribe: Callable[[np.ndarray], str | None]   # float32 mono 16 kHz
      respond: Callable[[str], str]                    # IntentRouter.route
      synthesize: Callable[[str], tuple[bytes, int] | None]
      async def run(self, utt: link_pb2.Utterance) -> AsyncIterator[link_pb2.BrainEvent]
  ```
  Event order: `transcript` → `speech`* → `end`. Empty/failed STT, wrong sample rate, or no synthesized chunk → `end(error=True)`. `respond` and `transcribe` run in `asyncio.to_thread` with `current_device` set to `utt.device_id`.

- [ ] **Step 1: Write the failing test**

`tests/test_turn.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_turn.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidos.brain.turn'`

- [ ] **Step 3: Implement**

`src/aidos/brain/turn.py`:
```python
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

        audio = np.frombuffer(utt.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
        text = await asyncio.to_thread(self.transcribe, audio)
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
            result = await asyncio.to_thread(self.synthesize, sentence)
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_turn.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/aidos/brain/turn.py tests/test_turn.py
git commit -m "feat(brain): TurnRunner streams transcript, sentences and turn end"
```

---

### Task 6: gRPC `BrainService`, `aidos --brain` entry point

**Files:**
- Create: `src/aidos/brain/server.py`
- Modify: `src/aidos/main.py` (add `--brain` flag and branch in `main()`), `Makefile` (target `brain`), `.env.example`
- Test: `tests/test_brain_server.py`

**Interfaces:**
- Consumes: `TurnRunner` (Task 5), `link_pb2_grpc` (Task 1).
- Produces:
  ```python
  class BrainService(link_pb2_grpc.BrainServicer):
      def __init__(self, runner: TurnRunner, token: str) -> None
  async def start_server(service: BrainService, bind: str) -> tuple[grpc.aio.Server, int]  # returns bound port
  async def serve(service: BrainService, bind: str) -> None  # start + wait_for_termination
  ```
  Behavior: rejects missing/wrong `authorization` with `UNAUTHENTICATED`; one task per `Utterance`; `Abort{turn_id}` cancels that task and no further events for it are sent; `DeviceState`/`PushAck` are logged.

- [ ] **Step 1: Write the failing test**

`tests/test_brain_server.py`:
```python
import asyncio

import grpc
import pytest

from aidos.brain.gen import link_pb2, link_pb2_grpc
from aidos.brain.server import BrainService, start_server
from aidos.brain.turn import TurnRunner

TOKEN = "secret"


def _runner(respond=lambda t: "Сәлем, қалайсыз? Бүгін күн жақсы."):
    return TurnRunner(transcribe=lambda a: "сәлем", respond=respond, synthesize=lambda s: (b"\x00\x00" * 10, 22050))


async def _open(service, token=TOKEN):
    server, port = await start_server(service, "127.0.0.1:0")
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    stub = link_pb2_grpc.BrainStub(channel)
    outbox: asyncio.Queue = asyncio.Queue()

    async def requests():
        while True:
            item = await outbox.get()
            if item is None:
                return
            yield item

    call = stub.Link(requests(), metadata=(("authorization", f"Bearer {token}"),))
    return server, channel, call, outbox


def _utt(turn_id="t1"):
    return link_pb2.GatewayEvent(
        utterance=link_pb2.Utterance(device_id="box-1", turn_id=turn_id, pcm_s16le=b"\x10\x00" * 1600, sample_rate=16000)
    )


async def _read_until_end(call):
    events = []
    async for ev in call:
        events.append(ev)
        if ev.WhichOneof("kind") == "end":
            return events
    return events


async def test_turn_roundtrip():
    server, channel, call, outbox = await _open(BrainService(_runner(), TOKEN))
    try:
        await outbox.put(_utt())
        events = await asyncio.wait_for(_read_until_end(call), 5)
        assert [e.WhichOneof("kind") for e in events] == ["transcript", "speech", "speech", "end"]
        assert events[-1].end.error is False
    finally:
        await outbox.put(None)
        await channel.close()
        await server.stop(None)


async def test_wrong_token_rejected():
    server, channel, call, outbox = await _open(BrainService(_runner(), TOKEN), token="bad")
    try:
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await asyncio.wait_for(call.read(), 5)
        assert err.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await channel.close()
        await server.stop(None)


async def test_abort_cancels_turn():
    started = asyncio.Event()
    release = asyncio.Event()
    loop = asyncio.get_running_loop()

    def slow_respond(text):
        loop.call_soon_threadsafe(started.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result(5)
        return "Кеш жауап."

    server, channel, call, outbox = await _open(BrainService(_runner(slow_respond), TOKEN))
    try:
        await outbox.put(_utt("slow"))
        first = await asyncio.wait_for(call.read(), 5)
        assert first.WhichOneof("kind") == "transcript"
        await asyncio.wait_for(started.wait(), 5)
        await outbox.put(link_pb2.GatewayEvent(abort=link_pb2.Abort(device_id="box-1", turn_id="slow")))
        await asyncio.sleep(0.2)
        release.set()

        await outbox.put(_utt("next"))
        events = await asyncio.wait_for(_read_until_end(call), 5)
        assert {getattr(e, e.WhichOneof("kind")).turn_id for e in events} == {"next"}
    finally:
        await outbox.put(None)
        await channel.close()
        await server.stop(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_brain_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidos.brain.server'`

- [ ] **Step 3: Implement the service**

`src/aidos/brain/server.py`:
```python
"""gRPC мозг-сервері: шлюзбен бір Link ағыны арқылы сөйлеседі."""

from __future__ import annotations

import asyncio
import logging

import grpc

from aidos.brain.gen import link_pb2, link_pb2_grpc
from aidos.brain.turn import TurnRunner

_log = logging.getLogger("aidos.brain.server")


class BrainService(link_pb2_grpc.BrainServicer):
    def __init__(self, runner: TurnRunner, token: str) -> None:
        self._runner = runner
        self._token = token

    async def Link(self, request_iterator, context):
        metadata = dict(context.invocation_metadata())
        if metadata.get("authorization") != f"Bearer {self._token}":
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "bad link token")
        # Python aio initial metadata-ны бірінші хабарламаға дейін жібермейді, ал tonic клиенті
        # link().await-те соны күтеді — жібермесе, екі жақ та бір-бірін күтіп қалады.
        await context.send_initial_metadata(())

        out: asyncio.Queue[link_pb2.BrainEvent | None] = asyncio.Queue()
        turns: dict[str, asyncio.Task] = {}
        reader = asyncio.create_task(self._read(request_iterator, out, turns))
        _log.info("Шлюз қосылды")
        try:
            while (event := await out.get()) is not None:
                yield event
        finally:
            reader.cancel()
            for task in turns.values():
                task.cancel()
            _log.info("Шлюз ажыратылды")

    async def _read(self, request_iterator, out: asyncio.Queue, turns: dict[str, asyncio.Task]) -> None:
        try:
            async for event in request_iterator:
                kind = event.WhichOneof("kind")
                if kind == "utterance":
                    utt = event.utterance
                    turns[utt.turn_id] = asyncio.create_task(self._run_turn(utt, out, turns))
                elif kind == "abort":
                    task = turns.pop(event.abort.turn_id, None)
                    if task:
                        task.cancel()
                        _log.info("Ход тоқтатылды: %s", event.abort.turn_id)
                elif kind == "state":
                    _log.info("Колонка %s: online=%s", event.state.device_id, event.state.online)
                elif kind == "push_ack":
                    _log.debug("PushAck: %s", event.push_ack.push_id)
        finally:
            await out.put(None)

    async def _run_turn(self, utt: link_pb2.Utterance, out: asyncio.Queue, turns: dict[str, asyncio.Task]) -> None:
        try:
            async for event in self._runner.run(utt):
                await out.put(event)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _log.error("Ход қатесі (turn=%s): %s", utt.turn_id, exc)
            await out.put(link_pb2.BrainEvent(
                end=link_pb2.TurnEnd(device_id=utt.device_id, turn_id=utt.turn_id, error=True)
            ))
        finally:
            turns.pop(utt.turn_id, None)


async def start_server(service: BrainService, bind: str) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server()
    link_pb2_grpc.add_BrainServicer_to_server(service, server)
    port = server.add_insecure_port(bind)
    await server.start()
    _log.info("Мозг тыңдауда: %s (port=%d)", bind, port)
    return server, port


async def serve(service: BrainService, bind: str) -> None:
    server, _ = await start_server(service, bind)
    await server.wait_for_termination()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_brain_server.py -v`
Expected: 3 passed. If `test_abort_cancels_turn` hangs, check that the cancelled task's thread (`slow_respond`) is released by `release.set()` and that `_run_turn` swallows `CancelledError` without emitting an event.

- [ ] **Step 5: Wire `aidos --brain`**

In `src/aidos/main.py`:
1. Add to the argparse group: `group.add_argument("--brain", action="store_true", help="gRPC мозг-сервері (колонкалар шлюзы үшін)")`.
2. Add the function:
```python
def run_brain_mode(router: IntentRouter, tts) -> None:
    """Шлюзге арналған gRPC мозг-сервері."""
    import asyncio
    import os

    from aidos.brain.server import BrainService, serve
    from aidos.brain.turn import TurnRunner
    from aidos.core.voice import VoiceInput

    token = os.getenv("LINK_TOKEN", "")
    if not token:
        console.print("[red]✗ LINK_TOKEN .env-те берілмеген[/red]")
        sys.exit(1)
    bind = os.getenv("BRAIN_BIND", "127.0.0.1:50051")
    voice = VoiceInput()
    runner = TurnRunner(transcribe=voice.transcribe, respond=router.route, synthesize=tts.synthesize)
    console.print(f"[green]✓ Мозг тыңдауда: {bind}[/green]")
    asyncio.run(serve(BrainService(runner, token), bind))
```
3. In `main()` add the branch before `elif args.wake:`:
```python
        elif args.brain:
            run_brain_mode(router, tts)
```

In `Makefile` add `brain` to `.PHONY`, help line `@echo "  make brain                — gRPC мозг (колонка шлюзы үшін)"`, and:
```make
brain:
	$(PYTHON) -m aidos.main --brain
```

Append to `.env.example`:
```env
# Колонка шлюзы ↔ мозг (gRPC)
LINK_TOKEN=change_me_long_random_string
BRAIN_BIND=127.0.0.1:50051
```

- [ ] **Step 6: Smoke-run the brain**

Run (with `LINK_TOKEN` set in the main repo `.env`): `PYTHONPATH=src LINK_TOKEN=dev /Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python -m aidos.main --brain` in the background for 5 s.
Expected: prints `✓ Мозг тыңдауда: 127.0.0.1:50051`, no traceback. Stop it.

- [ ] **Step 7: Run all tests and commit**

Run: `.venv/bin/python -m pytest -q` → all pass.
```bash
git add src/aidos/brain/server.py src/aidos/main.py Makefile .env.example tests/test_brain_server.py
git commit -m "feat(brain): gRPC BrainService with abort and aidos --brain mode"
```

---

### Task 7: Gateway crate skeleton, Rust codegen, config

**Files:**
- Create: `gateway/Cargo.toml`, `gateway/build.rs`, `gateway/src/lib.rs`, `gateway/src/main.rs`, `gateway/src/config.rs`, `gateway/.gitignore`
- Modify: `Makefile` (targets `gateway`, `gateway-test`)

**Interfaces:**
- Produces: crate `aidos_gateway` with `pub mod pb` (tonic-generated, `aidos.link.v1`), `pub mod config`:
  ```rust
  pub struct Config { pub bind: SocketAddr, pub public_ws_url: String, pub brain_addr: String,
      pub link_token: String, pub devices: HashMap<String, String>, pub silero_model: PathBuf,
      pub tz_offset_min: i32 }
  impl Config { pub fn from_env() -> anyhow::Result<Config> }
  pub fn parse_devices(spec: &str) -> HashMap<String, String>   // "id=token,id2=token2"
  ```

- [ ] **Step 1: Create the crate files**

`gateway/Cargo.toml`:
```toml
[package]
name = "aidos-gateway"
version = "0.1.0"
edition = "2024"

[lib]
name = "aidos_gateway"
path = "src/lib.rs"

[dependencies]
anyhow = "1"
axum = { version = "0.8", features = ["ws"] }
bytes = "1"
futures-util = "0.3"
opus = "0.3"
ort = "=2.0.0-rc.13"
prost = "0.14"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
tokio-stream = { version = "0.1", features = ["net"] }
tonic = "0.14"
tonic-prost = "0.14"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
uuid = { version = "1", features = ["v4"] }

[dev-dependencies]
hound = "3.5"
tokio-tungstenite = "0.30"

[build-dependencies]
protoc-bin-vendored = "3"
tonic-prost-build = "0.14"
```

`gateway/build.rs`:
```rust
fn main() -> Result<(), Box<dyn std::error::Error>> {
    // SAFETY: build scripts are single-threaded.
    unsafe { std::env::set_var("PROTOC", protoc_bin_vendored::protoc_bin_path()?) };
    println!("cargo:rerun-if-changed=../proto/link.proto");
    tonic_prost_build::configure().compile_protos(&["../proto/link.proto"], &["../proto"])?;
    Ok(())
}
```

`gateway/.gitignore`:
```
/target
```

`gateway/src/lib.rs`:
```rust
pub mod pb {
    tonic::include_proto!("aidos.link.v1");
}
pub mod config;
```

`gateway/src/main.rs` (temporary; finished in Task 12):
```rust
fn main() -> anyhow::Result<()> {
    let cfg = aidos_gateway::config::Config::from_env()?;
    println!("aidos-gateway config: bind={} brain={} devices={}", cfg.bind, cfg.brain_addr, cfg.devices.len());
    Ok(())
}
```

- [ ] **Step 2: Write the failing config test**

`gateway/src/config.rs`:
```rust
use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;

use anyhow::{Context, bail};

#[derive(Clone, Debug)]
pub struct Config {
    pub bind: SocketAddr,
    pub public_ws_url: String,
    pub brain_addr: String,
    pub link_token: String,
    pub devices: HashMap<String, String>,
    pub silero_model: PathBuf,
    pub tz_offset_min: i32,
}

pub fn parse_devices(spec: &str) -> HashMap<String, String> {
    todo!()
}

impl Config {
    pub fn from_env() -> anyhow::Result<Config> {
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_mac_ids_with_colons() {
        let devices = parse_devices("aa:bb:cc:dd:ee:ff=tok1, box-2=tok2 ,");
        assert_eq!(devices.len(), 2);
        assert_eq!(devices["aa:bb:cc:dd:ee:ff"], "tok1");
        assert_eq!(devices["box-2"], "tok2");
    }

    #[test]
    fn ignores_malformed_entries() {
        assert!(parse_devices("nobody,=x,y=").is_empty());
    }
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd gateway && cargo test --lib config`
Expected: FAIL — panics with `not yet implemented`. (First build downloads crates and ONNX Runtime; it can take several minutes.)

- [ ] **Step 4: Implement**

Replace the two `todo!()` bodies:
```rust
pub fn parse_devices(spec: &str) -> HashMap<String, String> {
    spec.split(',')
        .filter_map(|entry| {
            let (id, token) = entry.trim().split_once('=')?;
            let (id, token) = (id.trim(), token.trim());
            (!id.is_empty() && !token.is_empty()).then(|| (id.to_string(), token.to_string()))
        })
        .collect()
}

impl Config {
    pub fn from_env() -> anyhow::Result<Config> {
        let env = |key: &str, default: &str| std::env::var(key).unwrap_or_else(|_| default.to_string());
        let link_token = env("LINK_TOKEN", "");
        if link_token.is_empty() {
            bail!("LINK_TOKEN is not set");
        }
        Ok(Config {
            bind: env("GATEWAY_BIND", "0.0.0.0:8000").parse().context("GATEWAY_BIND")?,
            public_ws_url: env("GATEWAY_PUBLIC_WS_URL", "ws://127.0.0.1:8000/ws"),
            brain_addr: env("BRAIN_ADDR", "http://127.0.0.1:50051"),
            link_token,
            devices: parse_devices(&env("GATEWAY_DEVICES", "")),
            silero_model: env("SILERO_MODEL", "models/silero_vad.onnx").into(),
            tz_offset_min: env("GATEWAY_TZ_OFFSET_MIN", "300").parse().context("GATEWAY_TZ_OFFSET_MIN")?,
        })
    }
}
```

- [ ] **Step 5: Run tests**

Run: `cd gateway && cargo test --lib && cargo build`
Expected: 2 passed; build OK (proves tonic codegen works).

- [ ] **Step 6: Makefile targets**

Add `gateway gateway-test` to `.PHONY`, help lines, and:
```make
gateway:
	cd gateway && cargo run --release

gateway-test:
	cd gateway && cargo test
```

- [ ] **Step 7: Commit**

```bash
git add gateway/Cargo.toml gateway/Cargo.lock gateway/build.rs gateway/.gitignore gateway/src Makefile
git commit -m "feat(gateway): Rust crate skeleton, gRPC codegen, env config"
```

---

### Task 8: xiaozhi protocol messages

**Files:**
- Create: `gateway/src/xiaozhi.rs`
- Modify: `gateway/src/lib.rs` (add `pub mod xiaozhi;`)

**Interfaces:**
- Produces:
  ```rust
  pub enum DeviceMsg { Hello { version: u32, audio_params: Option<AudioParams> },
      Listen { state: ListenState, mode: Option<String>, text: Option<String> },
      Abort { reason: Option<String> }, Other }
  pub enum ListenState { Start, Stop, Detect }
  pub struct AudioParams { pub format: String, pub sample_rate: u32, pub channels: u32, pub frame_duration: u32 }
  pub fn parse(text: &str) -> serde_json::Result<DeviceMsg>
  pub fn server_hello(session_id: &str) -> String
  pub fn stt(session_id: &str, text: &str) -> String
  pub fn tts_start(session_id: &str) -> String
  pub fn tts_sentence(session_id: &str, text: &str) -> String
  pub fn tts_stop(session_id: &str) -> String
  ```

- [ ] **Step 1: Write the failing tests**

`gateway/src/xiaozhi.rs`:
```rust
use serde::Deserialize;
use serde_json::json;

#[derive(Debug, Deserialize, PartialEq, Clone)]
pub struct AudioParams {
    pub format: String,
    pub sample_rate: u32,
    pub channels: u32,
    pub frame_duration: u32,
}

#[derive(Debug, Deserialize, PartialEq, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum ListenState {
    Start,
    Stop,
    Detect,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum DeviceMsg {
    Hello {
        #[serde(default)]
        version: u32,
        audio_params: Option<AudioParams>,
    },
    Listen {
        state: ListenState,
        #[serde(default)]
        mode: Option<String>,
        #[serde(default)]
        text: Option<String>,
    },
    Abort {
        #[serde(default)]
        reason: Option<String>,
    },
    #[serde(other)]
    Other,
}

pub fn parse(text: &str) -> serde_json::Result<DeviceMsg> {
    todo!()
}

pub fn server_hello(session_id: &str) -> String {
    todo!()
}

pub fn stt(session_id: &str, text: &str) -> String {
    todo!()
}

pub fn tts_start(session_id: &str) -> String {
    todo!()
}

pub fn tts_sentence(session_id: &str, text: &str) -> String {
    todo!()
}

pub fn tts_stop(session_id: &str) -> String {
    todo!()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[test]
    fn parses_device_hello_from_docs() {
        let msg = parse(r#"{"type":"hello","version":1,"features":{"mcp":true,"aec":true},"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}"#).unwrap();
        let DeviceMsg::Hello { version, audio_params } = msg else { panic!("not hello") };
        assert_eq!(version, 1);
        assert_eq!(audio_params.unwrap().sample_rate, 16000);
    }

    #[test]
    fn parses_listen_variants() {
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"listen","state":"start","mode":"manual"}"#).unwrap(),
            DeviceMsg::Listen { state: ListenState::Start, mode: Some("manual".into()), text: None }
        );
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"listen","state":"detect","text":"Hi XiaoZhi"}"#).unwrap(),
            DeviceMsg::Listen { state: ListenState::Detect, mode: None, text: Some("Hi XiaoZhi".into()) }
        );
        assert!(matches!(
            parse(r#"{"session_id":"xxx","type":"listen","state":"stop"}"#).unwrap(),
            DeviceMsg::Listen { state: ListenState::Stop, .. }
        ));
    }

    #[test]
    fn parses_abort_and_unknown() {
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"abort","reason":"wake_word_detected"}"#).unwrap(),
            DeviceMsg::Abort { reason: Some("wake_word_detected".into()) }
        );
        assert_eq!(parse(r#"{"session_id":"xxx","type":"mcp","payload":{}}"#).unwrap(), DeviceMsg::Other);
    }

    #[test]
    fn builds_server_messages() {
        let hello: Value = serde_json::from_str(&server_hello("s1")).unwrap();
        assert_eq!(hello["type"], "hello");
        assert_eq!(hello["transport"], "websocket");
        assert_eq!(hello["session_id"], "s1");
        assert_eq!(hello["audio_params"]["sample_rate"], 24000);
        assert_eq!(hello["audio_params"]["frame_duration"], 60);

        let s: Value = serde_json::from_str(&stt("s1", "сәлем")).unwrap();
        assert_eq!((s["type"].as_str(), s["text"].as_str()), (Some("stt"), Some("сәлем")));

        let start: Value = serde_json::from_str(&tts_start("s1")).unwrap();
        assert_eq!((start["type"].as_str(), start["state"].as_str()), (Some("tts"), Some("start")));
        let sentence: Value = serde_json::from_str(&tts_sentence("s1", "Иә.")).unwrap();
        assert_eq!((sentence["state"].as_str(), sentence["text"].as_str()), (Some("sentence_start"), Some("Иә.")));
        let stop: Value = serde_json::from_str(&tts_stop("s1")).unwrap();
        assert_eq!(stop["state"], "stop");
    }
}
```
Add `pub mod xiaozhi;` to `gateway/src/lib.rs`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && cargo test --lib xiaozhi`
Expected: FAIL — `not yet implemented`.

- [ ] **Step 3: Implement**

Replace the `todo!()` bodies:
```rust
pub const DOWN_SAMPLE_RATE: u32 = 24000;
pub const FRAME_DURATION_MS: u32 = 60;

pub fn parse(text: &str) -> serde_json::Result<DeviceMsg> {
    serde_json::from_str(text)
}

pub fn server_hello(session_id: &str) -> String {
    json!({
        "type": "hello",
        "transport": "websocket",
        "session_id": session_id,
        "audio_params": {"format": "opus", "sample_rate": DOWN_SAMPLE_RATE, "channels": 1, "frame_duration": FRAME_DURATION_MS}
    })
    .to_string()
}

pub fn stt(session_id: &str, text: &str) -> String {
    json!({"session_id": session_id, "type": "stt", "text": text}).to_string()
}

pub fn tts_start(session_id: &str) -> String {
    json!({"session_id": session_id, "type": "tts", "state": "start"}).to_string()
}

pub fn tts_sentence(session_id: &str, text: &str) -> String {
    json!({"session_id": session_id, "type": "tts", "state": "sentence_start", "text": text}).to_string()
}

pub fn tts_stop(session_id: &str) -> String {
    json!({"session_id": session_id, "type": "tts", "state": "stop"}).to_string()
}
```

- [ ] **Step 4: Run tests**

Run: `cd gateway && cargo test --lib xiaozhi`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add gateway/src/xiaozhi.rs gateway/src/lib.rs
git commit -m "feat(gateway): xiaozhi WebSocket protocol messages"
```

---

### Task 9: Opus codecs and resampling

**Files:**
- Create: `gateway/src/audio.rs`
- Modify: `gateway/src/lib.rs` (add `pub mod audio;`)

**Interfaces:**
- Produces:
  ```rust
  pub const UP_RATE: u32 = 16000;
  pub const DOWN_RATE: u32 = 24000;
  pub const DOWN_FRAME: usize = 1440;            // 60 ms at 24 kHz
  pub struct UpDecoder;   impl UpDecoder { pub fn new() -> anyhow::Result<Self>; pub fn decode(&mut self, packet: &[u8]) -> anyhow::Result<Vec<i16>> }
  pub struct DownEncoder; impl DownEncoder { pub fn new() -> anyhow::Result<Self>; pub fn encode_all(&mut self, pcm: &[i16]) -> anyhow::Result<Vec<Vec<u8>>> }
  pub fn resample(pcm: &[i16], from: u32, to: u32) -> Vec<i16>
  pub fn pcm_from_le_bytes(bytes: &[u8]) -> Vec<i16>
  pub fn pcm_to_le_bytes(pcm: &[i16]) -> Vec<u8>
  pub fn i16_to_f32(pcm: &[i16]) -> Vec<f32>
  ```

- [ ] **Step 1: Write the failing tests**

`gateway/src/audio.rs`:
```rust
pub const UP_RATE: u32 = 16000;
pub const DOWN_RATE: u32 = 24000;
pub const DOWN_FRAME: usize = (DOWN_RATE as usize) * 60 / 1000;
const MAX_DECODED: usize = 5760;

pub struct UpDecoder(opus::Decoder);

impl UpDecoder {
    pub fn new() -> anyhow::Result<Self> {
        todo!()
    }

    pub fn decode(&mut self, packet: &[u8]) -> anyhow::Result<Vec<i16>> {
        todo!()
    }
}

pub struct DownEncoder(opus::Encoder);

impl DownEncoder {
    pub fn new() -> anyhow::Result<Self> {
        todo!()
    }

    pub fn encode_all(&mut self, pcm: &[i16]) -> anyhow::Result<Vec<Vec<u8>>> {
        todo!()
    }
}

pub fn resample(pcm: &[i16], from: u32, to: u32) -> Vec<i16> {
    todo!()
}

pub fn pcm_from_le_bytes(bytes: &[u8]) -> Vec<i16> {
    bytes.chunks_exact(2).map(|b| i16::from_le_bytes([b[0], b[1]])).collect()
}

pub fn pcm_to_le_bytes(pcm: &[i16]) -> Vec<u8> {
    pcm.iter().flat_map(|s| s.to_le_bytes()).collect()
}

pub fn i16_to_f32(pcm: &[i16]) -> Vec<f32> {
    pcm.iter().map(|&s| s as f32 / 32768.0).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sine(rate: u32, ms: u32) -> Vec<i16> {
        let n = (rate * ms / 1000) as usize;
        (0..n)
            .map(|i| ((i as f32 * 440.0 * std::f32::consts::TAU / rate as f32).sin() * 8000.0) as i16)
            .collect()
    }

    #[test]
    fn up_roundtrip_60ms() {
        let mut enc = opus::Encoder::new(UP_RATE, opus::Channels::Mono, opus::Application::Voip).unwrap();
        let mut packet = vec![0u8; 4000];
        let len = enc.encode(&sine(UP_RATE, 60), &mut packet).unwrap();
        let pcm = UpDecoder::new().unwrap().decode(&packet[..len]).unwrap();
        assert_eq!(pcm.len(), 960);
    }

    #[test]
    fn encode_all_pads_last_frame() {
        let frames = DownEncoder::new().unwrap().encode_all(&sine(DOWN_RATE, 130)).unwrap();
        assert_eq!(frames.len(), 3);
        assert!(frames.iter().all(|f| !f.is_empty()));
    }

    #[test]
    fn resample_lengths() {
        assert_eq!(resample(&sine(22050, 1000), 22050, 24000).len(), 24000);
        assert_eq!(resample(&sine(16000, 500), 16000, 24000).len(), 12000);
        assert_eq!(resample(&[1, 2, 3], 24000, 24000), vec![1, 2, 3]);
        assert!(resample(&[], 16000, 24000).is_empty());
    }

    #[test]
    fn le_bytes_roundtrip() {
        let pcm = vec![0i16, -1, 1000, i16::MIN, i16::MAX];
        assert_eq!(pcm_from_le_bytes(&pcm_to_le_bytes(&pcm)), pcm);
    }
}
```
Add `pub mod audio;` to `lib.rs`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && cargo test --lib audio`
Expected: FAIL — `not yet implemented` (the `le_bytes_roundtrip` test passes).

- [ ] **Step 3: Implement**

```rust
impl UpDecoder {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self(opus::Decoder::new(UP_RATE, opus::Channels::Mono)?))
    }

    pub fn decode(&mut self, packet: &[u8]) -> anyhow::Result<Vec<i16>> {
        let mut out = vec![0i16; MAX_DECODED];
        let n = self.0.decode(packet, &mut out, false)?;
        out.truncate(n);
        Ok(out)
    }
}

impl DownEncoder {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self(opus::Encoder::new(DOWN_RATE, opus::Channels::Mono, opus::Application::Voip)?))
    }

    pub fn encode_all(&mut self, pcm: &[i16]) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut packets = Vec::with_capacity(pcm.len().div_ceil(DOWN_FRAME));
        let mut frame = vec![0i16; DOWN_FRAME];
        let mut buf = vec![0u8; 4000];
        for chunk in pcm.chunks(DOWN_FRAME) {
            frame[..chunk.len()].copy_from_slice(chunk);
            frame[chunk.len()..].fill(0);
            let len = self.0.encode(&frame, &mut buf)?;
            packets.push(buf[..len].to_vec());
        }
        Ok(packets)
    }
}

pub fn resample(pcm: &[i16], from: u32, to: u32) -> Vec<i16> {
    if from == to || pcm.is_empty() {
        return pcm.to_vec();
    }
    let out_len = (pcm.len() as u64 * to as u64 / from as u64) as usize;
    let step = from as f64 / to as f64;
    (0..out_len)
        .map(|i| {
            let pos = i as f64 * step;
            let idx = pos as usize;
            let frac = pos - idx as f64;
            let a = pcm[idx.min(pcm.len() - 1)] as f64;
            let b = pcm[(idx + 1).min(pcm.len() - 1)] as f64;
            (a + (b - a) * frac).round() as i16
        })
        .collect()
}
```

- [ ] **Step 4: Run tests**

Run: `cd gateway && cargo test --lib audio`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add gateway/src/audio.rs gateway/src/lib.rs
git commit -m "feat(gateway): opus up/down codecs and linear resampling"
```

---

### Task 10: VAD — segmenter, endpointer, Silero ONNX

**Files:**
- Create: `gateway/src/vad.rs`, `gateway/models/silero_vad.onnx`, `gateway/tests/fixtures/speech_16k.wav`
- Modify: `gateway/src/lib.rs` (add `pub mod vad;`)

**Interfaces:**
- Consumes: `audio::i16_to_f32` (Task 9).
- Produces:
  ```rust
  pub const FRAME: usize = 512;
  pub trait SpeechProb: Send { fn prob(&mut self, frame: &[f32]) -> f32; fn reset(&mut self); }
  #[derive(Clone, Copy)] pub struct SegmenterParams { pub threshold: f32, pub frame_ms: u32, pub min_speech_ms: u32,
      pub end_silence_ms: u32, pub max_utterance_ms: u32, pub pre_roll_ms: u32 }   // Default = Global Constraints values
  pub struct Segmenter; impl Segmenter { pub fn new(p: SegmenterParams) -> Self;
      pub fn feed(&mut self, frame: &[i16], prob: f32) -> Option<Vec<i16>>; pub fn triggered(&self) -> bool; pub fn reset(&mut self) }
  pub struct Endpointer<P: SpeechProb>; impl<P: SpeechProb> Endpointer<P> { pub fn new(prob: P, p: SegmenterParams) -> Self;
      pub fn push(&mut self, pcm: &[i16]) -> Vec<Vec<i16>>; pub fn reset(&mut self) }
  pub struct SileroVad; impl SileroVad { pub fn load(path: &Path) -> anyhow::Result<Self> }   // impl SpeechProb
  ```

- [ ] **Step 1: Add the model and the audio fixture**

```bash
mkdir -p gateway/models gateway/tests/fixtures
cp /Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/lib/python3.12/site-packages/silero_vad/data/silero_vad.onnx gateway/models/
/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python - <<'EOF'
import wave
from pathlib import Path
src = Path.home() / "Desktop/aidos_tts/kk_KZ-raya-x_low.wav"   # Piper raya 16 kHz sample
with wave.open(str(src)) as r:
    assert r.getframerate() == 16000
    frames = r.readframes(16000 * 3)
with wave.open("gateway/tests/fixtures/speech_16k.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(frames)
EOF
```
If `~/Desktop/aidos_tts/kk_KZ-raya-x_low.wav` is missing, regenerate it: `PiperVoice.load("~/.aidos/piper/kk_KZ-raya-x_low.onnx").synthesize_wav("Сәлем! Мен Айдос, сіздің қазақ тіліндегі көмекшіңізбін.", wav)`.
Expected: `gateway/tests/fixtures/speech_16k.wav` is 3.0 s, ~96 KB.

- [ ] **Step 2: Write the failing tests**

`gateway/src/vad.rs`:
```rust
use std::collections::VecDeque;
use std::path::Path;

use ort::session::Session;
use ort::value::Tensor;

use crate::audio::i16_to_f32;

pub const FRAME: usize = 512;
const CONTEXT: usize = 64;
const RATE: i64 = 16000;

pub trait SpeechProb: Send {
    fn prob(&mut self, frame: &[f32]) -> f32;
    fn reset(&mut self);
}

#[derive(Clone, Copy, Debug)]
pub struct SegmenterParams {
    pub threshold: f32,
    pub frame_ms: u32,
    pub min_speech_ms: u32,
    pub end_silence_ms: u32,
    pub max_utterance_ms: u32,
    pub pre_roll_ms: u32,
}

impl Default for SegmenterParams {
    fn default() -> Self {
        Self { threshold: 0.5, frame_ms: 32, min_speech_ms: 250, end_silence_ms: 1000, max_utterance_ms: 12000, pre_roll_ms: 300 }
    }
}

pub struct Segmenter {
    p: SegmenterParams,
    max_frames: usize,
    pre_roll: VecDeque<Vec<i16>>,
    pre_roll_cap: usize,
    frames: Vec<Vec<i16>>,
    speech_ms: u32,
    silence_ms: u32,
}

impl Segmenter {
    pub fn new(p: SegmenterParams) -> Self {
        todo!()
    }

    pub fn triggered(&self) -> bool {
        !self.frames.is_empty()
    }

    pub fn reset(&mut self) {
        todo!()
    }

    pub fn feed(&mut self, frame: &[i16], prob: f32) -> Option<Vec<i16>> {
        todo!()
    }
}

pub struct Endpointer<P: SpeechProb> {
    prob: P,
    seg: Segmenter,
    pending: Vec<i16>,
}

impl<P: SpeechProb> Endpointer<P> {
    pub fn new(prob: P, p: SegmenterParams) -> Self {
        Self { prob, seg: Segmenter::new(p), pending: Vec::new() }
    }

    pub fn push(&mut self, pcm: &[i16]) -> Vec<Vec<i16>> {
        todo!()
    }

    pub fn reset(&mut self) {
        self.seg.reset();
        self.pending.clear();
        self.prob.reset();
    }
}

pub struct SileroVad {
    session: Session,
    state: Vec<f32>,
    context: Vec<f32>,
}

impl SileroVad {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        todo!()
    }

    fn infer(&mut self, frame: &[f32]) -> anyhow::Result<f32> {
        todo!()
    }
}

impl SpeechProb for SileroVad {
    fn prob(&mut self, frame: &[f32]) -> f32 {
        self.infer(frame).unwrap_or_else(|err| {
            tracing::warn!(%err, "silero inference failed");
            0.0
        })
    }

    fn reset(&mut self) {
        self.state.fill(0.0);
        self.context.fill(0.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FMS: u32 = 32;

    fn ms(v: u32) -> usize {
        v.div_ceil(FMS) as usize
    }

    fn feed(seg: &mut Segmenter, probs: &[f32]) -> Vec<Vec<i16>> {
        probs.iter().enumerate().filter_map(|(i, &p)| seg.feed(&vec![i as i16; FRAME], p)).collect()
    }

    fn params(f: impl FnOnce(&mut SegmenterParams)) -> SegmenterParams {
        let mut p = SegmenterParams::default();
        f(&mut p);
        p
    }

    fn probs(parts: &[(f32, usize)]) -> Vec<f32> {
        parts.iter().flat_map(|&(p, n)| std::iter::repeat_n(p, n)).collect()
    }

    #[test]
    fn silence_yields_nothing() {
        let mut seg = Segmenter::new(SegmenterParams::default());
        assert!(feed(&mut seg, &probs(&[(0.0, ms(5000))])).is_empty());
        assert!(!seg.triggered());
    }

    #[test]
    fn utterance_ends_after_silence() {
        let mut seg = Segmenter::new(params(|p| p.pre_roll_ms = 96));
        let out = feed(&mut seg, &probs(&[(0.0, 10), (0.9, ms(800)), (0.1, ms(1000))]));
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].len(), (ms(96) + ms(800) + ms(1000)) * FRAME);
        assert!(!seg.triggered());
    }

    #[test]
    fn short_noise_is_dropped() {
        let mut seg = Segmenter::new(SegmenterParams::default());
        assert!(feed(&mut seg, &probs(&[(0.9, ms(100)), (0.0, ms(1000))])).is_empty());
    }

    #[test]
    fn short_pause_does_not_split() {
        let mut seg = Segmenter::new(SegmenterParams::default());
        let out = feed(&mut seg, &probs(&[(0.9, ms(500)), (0.0, ms(500)), (0.9, ms(500)), (0.0, ms(1000))]));
        assert_eq!(out.len(), 1);
    }

    #[test]
    fn max_length_cuts_utterance() {
        let mut seg = Segmenter::new(params(|p| p.max_utterance_ms = 2000));
        let out = feed(&mut seg, &probs(&[(0.9, ms(5000))]));
        assert_eq!(out.len(), 2);
        assert!(out.iter().all(|u| u.len() == (2000 / FMS) as usize * FRAME));
    }

    struct Loud;
    impl SpeechProb for Loud {
        fn prob(&mut self, frame: &[f32]) -> f32 {
            if frame.iter().any(|s| s.abs() > 0.01) { 1.0 } else { 0.0 }
        }
        fn reset(&mut self) {}
    }

    #[test]
    fn endpointer_reframes_arbitrary_chunks() {
        let mut ep = Endpointer::new(Loud, SegmenterParams::default());
        let mut pcm = vec![1000i16; 16000];
        pcm.extend(vec![0i16; 24000]);
        let mut out = Vec::new();
        for chunk in pcm.chunks(960) {
            out.extend(ep.push(chunk));
        }
        assert_eq!(out.len(), 1);
        assert!(out[0].len() >= 16000);
    }

    #[test]
    fn silero_detects_speech_in_fixture() {
        let manifest = env!("CARGO_MANIFEST_DIR");
        let mut vad = SileroVad::load(&Path::new(manifest).join("models/silero_vad.onnx")).unwrap();
        let mut reader = hound::WavReader::open(Path::new(manifest).join("tests/fixtures/speech_16k.wav")).unwrap();
        let pcm: Vec<i16> = reader.samples::<i16>().map(Result::unwrap).collect();
        let speech = pcm.chunks_exact(FRAME).filter(|f| vad.prob(&i16_to_f32(f)) > 0.5).count();
        assert!(speech * 2 > pcm.len() / FRAME, "speech frames: {speech}");
        vad.reset();
        assert!(vad.prob(&vec![0.0; FRAME]) < 0.5);
    }
}
```
Add `pub mod vad;` to `lib.rs`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd gateway && cargo test --lib vad`
Expected: FAIL — `not yet implemented`.

- [ ] **Step 4: Implement**

Replace the `todo!()` bodies:
```rust
impl Segmenter {
    pub fn new(p: SegmenterParams) -> Self {
        let pre_roll_cap = ((p.pre_roll_ms / p.frame_ms) as usize).max(1);
        Self {
            max_frames: (p.max_utterance_ms / p.frame_ms) as usize,
            pre_roll: VecDeque::with_capacity(pre_roll_cap),
            pre_roll_cap,
            frames: Vec::new(),
            speech_ms: 0,
            silence_ms: 0,
            p,
        }
    }

    pub fn reset(&mut self) {
        self.frames.clear();
        self.pre_roll.clear();
        self.speech_ms = 0;
        self.silence_ms = 0;
    }

    pub fn feed(&mut self, frame: &[i16], prob: f32) -> Option<Vec<i16>> {
        let is_speech = prob >= self.p.threshold;

        if self.frames.is_empty() {
            if !is_speech {
                if self.pre_roll.len() == self.pre_roll_cap {
                    self.pre_roll.pop_front();
                }
                self.pre_roll.push_back(frame.to_vec());
                return None;
            }
            self.frames.extend(self.pre_roll.drain(..));
            self.frames.push(frame.to_vec());
            self.speech_ms = self.p.frame_ms;
            return None;
        }

        self.frames.push(frame.to_vec());
        if is_speech {
            self.speech_ms += self.p.frame_ms;
            self.silence_ms = 0;
        } else {
            self.silence_ms += self.p.frame_ms;
        }

        let too_long = self.frames.len() >= self.max_frames;
        if self.silence_ms < self.p.end_silence_ms && !too_long {
            return None;
        }
        let utterance = (self.speech_ms >= self.p.min_speech_ms).then(|| self.frames.concat());
        self.reset();
        utterance
    }
}

impl<P: SpeechProb> Endpointer<P> {
    pub fn push(&mut self, pcm: &[i16]) -> Vec<Vec<i16>> {
        self.pending.extend_from_slice(pcm);
        let mut out = Vec::new();
        let full = self.pending.len() / FRAME * FRAME;
        for frame in self.pending[..full].chunks_exact(FRAME) {
            let prob = self.prob.prob(&i16_to_f32(frame));
            if let Some(utterance) = self.seg.feed(frame, prob) {
                out.push(utterance);
            }
        }
        self.pending.drain(..full);
        out
    }
}

impl SileroVad {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let session = Session::builder()?.commit_from_file(path)?;
        Ok(Self { session, state: vec![0.0; 2 * 128], context: vec![0.0; CONTEXT] })
    }

    fn infer(&mut self, frame: &[f32]) -> anyhow::Result<f32> {
        let mut input = Vec::with_capacity(CONTEXT + FRAME);
        input.extend_from_slice(&self.context);
        input.extend_from_slice(frame);
        let outputs = self.session.run(ort::inputs![
            "input" => Tensor::from_array(([1usize, CONTEXT + FRAME], input.clone()))?,
            "state" => Tensor::from_array(([2usize, 1, 128], self.state.clone()))?,
            "sr" => Tensor::from_array(((), vec![RATE]))?,
        ])?;
        let (_, prob) = outputs["output"].try_extract_tensor::<f32>()?;
        let (_, state) = outputs["stateN"].try_extract_tensor::<f32>()?;
        let prob = prob[0];
        self.state.copy_from_slice(state);
        self.context.copy_from_slice(&input[input.len() - CONTEXT..]);
        Ok(prob)
    }
}
```

- [ ] **Step 5: Run tests**

Run: `cd gateway && cargo test --lib vad`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add gateway/src/vad.rs gateway/src/lib.rs gateway/models/silero_vad.onnx gateway/tests/fixtures/speech_16k.wav
git commit -m "feat(gateway): Silero VAD endpointing (segmenter ported from Python)"
```

---

### Task 11: gRPC link to the brain with per-device routing

**Files:**
- Create: `gateway/src/link.rs`
- Modify: `gateway/src/lib.rs` (add `pub mod link;`)

**Interfaces:**
- Consumes: `pb` (Task 7).
- Produces:
  ```rust
  #[derive(Clone)] pub struct LinkHandle;
  impl LinkHandle {
      pub fn spawn(brain_addr: String, token: String) -> LinkHandle;      // background connect + reconnect 1→2→4…30 s
      pub fn is_connected(&self) -> bool;
      pub fn send(&self, ev: pb::GatewayEvent) -> bool;                  // try_send; false if link down or queue full
      pub fn register(&self, device_id: &str) -> tokio::sync::mpsc::Receiver<pb::BrainEvent>;
      pub fn unregister(&self, device_id: &str);
  }
  pub fn event_device_id(ev: &pb::BrainEvent) -> Option<&str>;
  pub fn event_turn_id(ev: &pb::BrainEvent) -> Option<&str>;
  ```

- [ ] **Step 1: Write the failing test**

`gateway/src/link.rs`:
```rust
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tonic::Request;

use crate::pb;
use crate::pb::brain_client::BrainClient;
use crate::pb::brain_event::Kind;

type Routes = Arc<Mutex<HashMap<String, mpsc::Sender<pb::BrainEvent>>>>;

#[derive(Clone)]
pub struct LinkHandle {
    out: mpsc::Sender<pb::GatewayEvent>,
    routes: Routes,
    connected: Arc<AtomicBool>,
}

pub fn event_device_id(ev: &pb::BrainEvent) -> Option<&str> {
    todo!()
}

pub fn event_turn_id(ev: &pb::BrainEvent) -> Option<&str> {
    todo!()
}

impl LinkHandle {
    pub fn spawn(brain_addr: String, token: String) -> LinkHandle {
        todo!()
    }

    pub fn is_connected(&self) -> bool {
        self.connected.load(Ordering::Relaxed)
    }

    pub fn send(&self, ev: pb::GatewayEvent) -> bool {
        todo!()
    }

    pub fn register(&self, device_id: &str) -> mpsc::Receiver<pb::BrainEvent> {
        todo!()
    }

    pub fn unregister(&self, device_id: &str) {
        self.routes.lock().unwrap().remove(device_id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::pin::Pin;
    use tokio_stream::{Stream, StreamExt, wrappers::TcpListenerStream};
    use tonic::{Response, Status, Streaming};

    struct Echo;

    #[tonic::async_trait]
    impl pb::brain_server::Brain for Echo {
        type LinkStream = Pin<Box<dyn Stream<Item = Result<pb::BrainEvent, Status>> + Send + 'static>>;

        async fn link(&self, req: Request<Streaming<pb::GatewayEvent>>) -> Result<Response<Self::LinkStream>, Status> {
            assert_eq!(req.metadata().get("authorization").unwrap(), "Bearer t0k");
            let mut inbound = req.into_inner();
            let out = async_stream_like(move |tx| async move {
                while let Some(Ok(ev)) = inbound.next().await {
                    if let Some(pb::gateway_event::Kind::Utterance(u)) = ev.kind {
                        let _ = tx.send(Ok(pb::BrainEvent { kind: Some(Kind::Transcript(pb::Transcript {
                            device_id: u.device_id, turn_id: u.turn_id, text: "ok".into(),
                        })) })).await;
                    }
                }
            });
            Ok(Response::new(out))
        }
    }

    fn async_stream_like<F, Fut>(f: F) -> Pin<Box<dyn Stream<Item = Result<pb::BrainEvent, Status>> + Send>>
    where
        F: FnOnce(mpsc::Sender<Result<pb::BrainEvent, Status>>) -> Fut,
        Fut: std::future::Future<Output = ()> + Send + 'static,
    {
        let (tx, rx) = mpsc::channel(16);
        tokio::spawn(f(tx));
        Box::pin(ReceiverStream::new(rx))
    }

    fn utterance(device: &str, turn: &str) -> pb::GatewayEvent {
        pb::GatewayEvent { kind: Some(pb::gateway_event::Kind::Utterance(pb::Utterance {
            device_id: device.into(), turn_id: turn.into(), pcm_s16le: vec![], sample_rate: 16000,
        })) }
    }

    #[tokio::test]
    async fn routes_events_to_the_right_device() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(tonic::transport::Server::builder()
            .add_service(pb::brain_server::BrainServer::new(Echo))
            .serve_with_incoming(TcpListenerStream::new(listener)));

        let link = LinkHandle::spawn(format!("http://{addr}"), "t0k".into());
        let mut a = link.register("box-a");
        let mut b = link.register("box-b");
        for _ in 0..50 {
            if link.is_connected() { break; }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        assert!(link.is_connected());

        assert!(link.send(utterance("box-b", "t2")));
        assert!(link.send(utterance("box-a", "t1")));

        let ev_a = tokio::time::timeout(Duration::from_secs(3), a.recv()).await.unwrap().unwrap();
        let ev_b = tokio::time::timeout(Duration::from_secs(3), b.recv()).await.unwrap().unwrap();
        assert_eq!((event_device_id(&ev_a), event_turn_id(&ev_a)), (Some("box-a"), Some("t1")));
        assert_eq!((event_device_id(&ev_b), event_turn_id(&ev_b)), (Some("box-b"), Some("t2")));
    }

    #[tokio::test]
    async fn send_fails_while_disconnected() {
        let link = LinkHandle::spawn("http://127.0.0.1:1".into(), "t0k".into());
        tokio::time::sleep(Duration::from_millis(200)).await;
        assert!(!link.is_connected());
        assert!(!link.send(utterance("box-a", "t1")));
    }
}
```
Add `pub mod link;` to `lib.rs`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && cargo test --lib link`
Expected: FAIL — `not yet implemented`.

- [ ] **Step 3: Implement**

Replace the `todo!()` bodies and add the private loop functions:
```rust
pub fn event_device_id(ev: &pb::BrainEvent) -> Option<&str> {
    Some(match ev.kind.as_ref()? {
        Kind::Transcript(e) => &e.device_id,
        Kind::Speech(e) => &e.device_id,
        Kind::Action(e) => &e.device_id,
        Kind::End(e) => &e.device_id,
        Kind::Push(e) => &e.device_id,
    })
}

pub fn event_turn_id(ev: &pb::BrainEvent) -> Option<&str> {
    Some(match ev.kind.as_ref()? {
        Kind::Transcript(e) => &e.turn_id,
        Kind::Speech(e) => &e.turn_id,
        Kind::Action(e) => &e.turn_id,
        Kind::End(e) => &e.turn_id,
        Kind::Push(_) => return None,
    })
}

impl LinkHandle {
    pub fn spawn(brain_addr: String, token: String) -> LinkHandle {
        let (out, rx) = mpsc::channel(256);
        let handle = LinkHandle { out, routes: Arc::default(), connected: Arc::default() };
        tokio::spawn(run(brain_addr, token, rx, handle.routes.clone(), handle.connected.clone()));
        handle
    }

    pub fn send(&self, ev: pb::GatewayEvent) -> bool {
        self.is_connected() && self.out.try_send(ev).is_ok()
    }

    pub fn register(&self, device_id: &str) -> mpsc::Receiver<pb::BrainEvent> {
        let (tx, rx) = mpsc::channel(64);
        self.routes.lock().unwrap().insert(device_id.to_string(), tx);
        rx
    }
}

async fn run(addr: String, token: String, mut outbox: mpsc::Receiver<pb::GatewayEvent>, routes: Routes, connected: Arc<AtomicBool>) {
    let mut backoff = Duration::from_secs(1);
    loop {
        match connect_once(&addr, &token, &mut outbox, &routes, &connected).await {
            Ok(()) => return,
            Err(err) => tracing::warn!(%err, ?backoff, "brain link down"),
        }
        if connected.swap(false, Ordering::Relaxed) {
            backoff = Duration::from_secs(1);
        }
        while outbox.try_recv().is_ok() {}
        tokio::time::sleep(backoff).await;
        backoff = (backoff * 2).min(Duration::from_secs(30));
    }
}

async fn connect_once(
    addr: &str,
    token: &str,
    outbox: &mut mpsc::Receiver<pb::GatewayEvent>,
    routes: &Routes,
    connected: &AtomicBool,
) -> anyhow::Result<()> {
    let mut client = BrainClient::connect(addr.to_string()).await?;
    let (tx, rx) = mpsc::channel(64);
    let mut req = Request::new(ReceiverStream::new(rx));
    req.metadata_mut().insert("authorization", format!("Bearer {token}").parse()?);
    let mut inbound = client.link(req).await?.into_inner();
    connected.store(true, Ordering::Relaxed);
    tracing::info!(addr, "brain link up");

    loop {
        tokio::select! {
            out = outbox.recv() => match out {
                Some(ev) => tx.send(ev).await?,
                None => return Ok(()),
            },
            msg = inbound.message() => match msg? {
                Some(ev) => route(routes, ev),
                None => anyhow::bail!("brain closed the link"),
            },
        }
    }
}

fn route(routes: &Routes, ev: pb::BrainEvent) {
    let Some(device_id) = event_device_id(&ev).map(str::to_string) else { return };
    let sender = routes.lock().unwrap().get(&device_id).cloned();
    match sender {
        Some(tx) if tx.try_send(ev).is_ok() => {}
        _ => tracing::debug!(device_id, "dropped brain event: device not connected or slow"),
    }
}
```
- [ ] **Step 4: Run tests**

Run: `cd gateway && cargo test --lib link`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add gateway/src/link.rs gateway/src/lib.rs
git commit -m "feat(gateway): gRPC link to brain with reconnect and device routing"
```

---

### Task 12: Device session, HTTP/WS server, binary, end-to-end test

**Files:**
- Create: `gateway/src/device.rs`, `gateway/src/server.rs`, `gateway/tests/e2e.rs`
- Modify: `gateway/src/lib.rs` (add `pub mod device; pub mod server;`), `gateway/src/main.rs`, `.env.example`

**Interfaces:**
- Consumes: `Config` (7), `xiaozhi` (8), `audio` (9), `vad` (10), `LinkHandle` (11).
- Produces:
  ```rust
  // server.rs
  #[derive(Clone)] pub struct AppState { pub cfg: Arc<Config>, pub link: LinkHandle }
  pub fn router(state: AppState) -> axum::Router
  // device.rs
  pub async fn run_device(socket: axum::extract::ws::WebSocket, device_id: String, link: LinkHandle, silero_model: PathBuf)
  ```
  Device behavior (spec §5): `hello` → server hello + `DeviceState{online}`; `listen start` → listening (aborting a running turn); `listen detect`/`abort` during thinking/speaking → abort turn (`Abort` to brain, clear queue, `tts stop`); binary frames only in listening → decode → endpointer → `Utterance` (new uuid `turn_id`) → thinking; brain events with stale `turn_id` dropped; `Transcript` → `stt`; first `SpeechChunk` → `tts start`; each chunk → `tts sentence_start` + Opus 24 kHz frames paced at 60 ms with 2 frames of lead; `TurnEnd` → `tts start` if not sent yet, then `tts stop` → idle; link down on utterance → `tts start`+`tts stop` → idle; socket close → `Abort` if a turn is active + `DeviceState{offline}`.

- [ ] **Step 1: Write the failing e2e test**

`gateway/tests/e2e.rs`:
```rust
use std::collections::HashMap;
use std::path::Path;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use aidos_gateway::config::Config;
use aidos_gateway::link::LinkHandle;
use aidos_gateway::pb;
use aidos_gateway::pb::brain_event::Kind;
use aidos_gateway::server::{AppState, router};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tokio_stream::Stream;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tokio_tungstenite::tungstenite::{Message, client::IntoClientRequest};
use tonic::{Request, Response, Status, Streaming};

const TOKEN: &str = "dev-token";
const DEVICE: &str = "aa:bb:cc:dd:ee:ff";
const REPLY_MS: usize = 500;

#[derive(Clone, Default)]
struct FakeBrain {
    utterances: Arc<Mutex<Vec<usize>>>,
    aborts: Arc<Mutex<Vec<String>>>,
    hold: bool,
}

#[tonic::async_trait]
impl pb::brain_server::Brain for FakeBrain {
    type LinkStream = Pin<Box<dyn Stream<Item = Result<pb::BrainEvent, Status>> + Send + 'static>>;

    async fn link(&self, req: Request<Streaming<pb::GatewayEvent>>) -> Result<Response<Self::LinkStream>, Status> {
        let mut inbound = req.into_inner();
        let (tx, rx) = mpsc::channel(64);
        let me = self.clone();
        tokio::spawn(async move {
            while let Some(Ok(ev)) = inbound.next().await {
                match ev.kind {
                    Some(pb::gateway_event::Kind::Utterance(u)) => {
                        me.utterances.lock().unwrap().push(u.pcm_s16le.len() / 2);
                        let ids = (u.device_id.clone(), u.turn_id.clone());
                        let send = |kind| tx.send(Ok(pb::BrainEvent { kind: Some(kind) }));
                        let _ = send(Kind::Transcript(pb::Transcript { device_id: ids.0.clone(), turn_id: ids.1.clone(), text: "сәлем".into() })).await;
                        let pcm: Vec<u8> = vec![0u8; 22050 * REPLY_MS / 1000 * 2];
                        let _ = send(Kind::Speech(pb::SpeechChunk { device_id: ids.0.clone(), turn_id: ids.1.clone(), text: "Сәлем!".into(), pcm_s16le: pcm, sample_rate: 22050 })).await;
                        if me.hold {
                            continue;
                        }
                        let _ = send(Kind::End(pb::TurnEnd { device_id: ids.0, turn_id: ids.1, error: false })).await;
                    }
                    Some(pb::gateway_event::Kind::Abort(a)) => me.aborts.lock().unwrap().push(a.turn_id),
                    _ => {}
                }
            }
        });
        Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
    }
}

async fn start_brain(brain: FakeBrain) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(tonic::transport::Server::builder()
        .add_service(pb::brain_server::BrainServer::new(brain))
        .serve_with_incoming(TcpListenerStream::new(listener)));
    format!("http://{addr}")
}

async fn start_gateway(brain_addr: String) -> (String, LinkHandle) {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cfg = Config {
        bind: addr,
        public_ws_url: format!("ws://{addr}/ws"),
        brain_addr: brain_addr.clone(),
        link_token: "link".into(),
        devices: HashMap::from([(DEVICE.to_string(), TOKEN.to_string())]),
        silero_model: Path::new(manifest).join("models/silero_vad.onnx"),
        tz_offset_min: 300,
    };
    let link = LinkHandle::spawn(brain_addr, "link".into());
    let app = router(AppState { cfg: Arc::new(cfg), link: link.clone() });
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("{addr}"), link)
}

async fn wait_link(link: &LinkHandle, up: bool) {
    for _ in 0..100 {
        if link.is_connected() == up { return; }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    panic!("link never became {up}");
}

fn speech_packets() -> Vec<Vec<u8>> {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let mut reader = hound::WavReader::open(Path::new(manifest).join("tests/fixtures/speech_16k.wav")).unwrap();
    let mut pcm: Vec<i16> = reader.samples::<i16>().map(Result::unwrap).collect();
    pcm.extend(vec![0i16; 16000 * 2]);
    let mut enc = opus::Encoder::new(16000, opus::Channels::Mono, opus::Application::Voip).unwrap();
    let mut buf = vec![0u8; 4000];
    pcm.chunks(960).filter(|c| c.len() == 960).map(|c| {
        let n = enc.encode(c, &mut buf).unwrap();
        buf[..n].to_vec()
    }).collect()
}

type Ws = tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

async fn connect(addr: &str, token: &str) -> Result<Ws, tokio_tungstenite::tungstenite::Error> {
    let mut req = format!("ws://{addr}/ws").into_client_request().unwrap();
    req.headers_mut().insert("Authorization", format!("Bearer {token}").parse().unwrap());
    req.headers_mut().insert("Device-Id", DEVICE.parse().unwrap());
    req.headers_mut().insert("Protocol-Version", "1".parse().unwrap());
    tokio_tungstenite::connect_async(req).await.map(|(ws, _)| ws)
}

async fn next_json(ws: &mut Ws) -> serde_json::Value {
    loop {
        match tokio::time::timeout(Duration::from_secs(15), ws.next()).await.unwrap().unwrap().unwrap() {
            Message::Text(t) => return serde_json::from_str(t.as_str()).unwrap(),
            Message::Binary(_) => continue,
            _ => continue,
        }
    }
}

async fn hello(ws: &mut Ws) -> String {
    ws.send(Message::Text(r#"{"type":"hello","version":1,"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}"#.into())).await.unwrap();
    let h = next_json(ws).await;
    assert_eq!(h["type"], "hello");
    h["session_id"].as_str().unwrap().to_string()
}

async fn speak(ws: &mut Ws, session: &str) {
    ws.send(Message::Text(format!(r#"{{"session_id":"{session}","type":"listen","state":"start","mode":"auto"}}"#).into())).await.unwrap();
    for p in speech_packets() {
        ws.send(Message::Binary(p.into())).await.unwrap();
    }
}

#[tokio::test]
async fn full_turn_over_websocket() {
    let brain = FakeBrain::default();
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;

    let stt = next_json(&mut ws).await;
    assert_eq!((stt["type"].as_str(), stt["text"].as_str()), (Some("stt"), Some("сәлем")));
    assert_eq!(next_json(&mut ws).await["state"], "start");
    let sentence = next_json(&mut ws).await;
    assert_eq!((sentence["state"].as_str(), sentence["text"].as_str()), (Some("sentence_start"), Some("Сәлем!")));

    let mut frames = 0;
    loop {
        match tokio::time::timeout(Duration::from_secs(5), ws.next()).await.unwrap().unwrap().unwrap() {
            Message::Binary(_) => frames += 1,
            Message::Text(t) => {
                let v: serde_json::Value = serde_json::from_str(t.as_str()).unwrap();
                assert_eq!(v["state"], "stop");
                break;
            }
            _ => {}
        }
    }
    assert_eq!(frames, (24000 * REPLY_MS / 1000).div_ceil(1440));
    let heard = brain.utterances.lock().unwrap()[0];
    assert!(heard > 16000 * 2 && heard < 16000 * 5, "utterance samples: {heard}");
}

#[tokio::test]
async fn barge_in_aborts_turn() {
    let brain = FakeBrain { hold: true, ..FakeBrain::default() };
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["type"], "stt");
    assert_eq!(next_json(&mut ws).await["state"], "start");

    ws.send(Message::Text(format!(r#"{{"session_id":"{session}","type":"abort","reason":"wake_word_detected"}}"#).into())).await.unwrap();
    loop {
        let v = next_json(&mut ws).await;
        if v["state"] == "stop" { break; }
    }
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert_eq!(brain.aborts.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn brain_down_returns_to_idle() {
    let (addr, link) = start_gateway("http://127.0.0.1:1".into()).await;
    wait_link(&link, false).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["state"], "start");
    assert_eq!(next_json(&mut ws).await["state"], "stop");
}

#[tokio::test]
async fn rejects_bad_token() {
    let (addr, _link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    assert!(connect(&addr, "wrong").await.is_err());
}

async fn post_ota(addr: &str, device: &str) -> (u16, String) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut stream = tokio::net::TcpStream::connect(addr).await.unwrap();
    let req = format!(
        "POST /ota HTTP/1.1\r\nHost: x\r\nDevice-Id: {device}\r\nClient-Id: c1\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
    );
    stream.write_all(req.as_bytes()).await.unwrap();
    let mut raw = String::new();
    stream.read_to_string(&mut raw).await.unwrap();
    let status = raw[9..12].parse().unwrap();
    let body = raw.split_once("\r\n\r\n").map(|(_, b)| b.to_string()).unwrap_or_default();
    (status, body)
}

#[tokio::test]
async fn ota_known_device_gets_websocket() {
    let (addr, _link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    let (status, body) = post_ota(&addr, DEVICE).await;
    assert_eq!(status, 200);
    let v: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v["websocket"]["token"], TOKEN);
    assert!(v["websocket"]["url"].as_str().unwrap().ends_with("/ws"));
    assert_eq!(v["server_time"]["timezone_offset"], 300);
}

#[tokio::test]
async fn ota_unknown_device_forbidden() {
    let (addr, _link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    assert_eq!(post_ota(&addr, "ff:ff:ff:ff:ff:ff").await.0, 403);
}
```

- [ ] **Step 2: Run e2e to verify it fails**

Run: `cd gateway && cargo test --test e2e`
Expected: compile FAIL — `could not find server in aidos_gateway`.

- [ ] **Step 3: Implement `server.rs`**

`gateway/src/server.rs`:
```rust
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use axum::Router;
use axum::extract::{State, WebSocketUpgrade};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Json, Response};
use axum::routing::{get, post};
use serde_json::json;

use crate::config::Config;
use crate::device::run_device;
use crate::link::LinkHandle;

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub link: LinkHandle,
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/ota", post(ota).get(ota))
        .route("/ota/", post(ota).get(ota))
        .route("/ws", get(ws))
        .with_state(state)
}

fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

async fn ota(State(st): State<AppState>, headers: HeaderMap) -> Response {
    let Some(device_id) = header(&headers, "Device-Id") else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    let Some(token) = st.cfg.devices.get(device_id) else {
        tracing::warn!(device_id, "ota: unknown device");
        return StatusCode::FORBIDDEN.into_response();
    };
    let now_ms = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64;
    Json(json!({
        "websocket": {"url": st.cfg.public_ws_url, "token": token},
        "server_time": {"timestamp": now_ms, "timezone_offset": st.cfg.tz_offset_min},
        "firmware": {"version": "0.0.0", "url": ""}
    }))
    .into_response()
}

async fn ws(State(st): State<AppState>, headers: HeaderMap, upgrade: WebSocketUpgrade) -> Response {
    let token = header(&headers, "Authorization").and_then(|v| v.strip_prefix("Bearer "));
    let device = token.and_then(|t| st.cfg.devices.iter().find(|(_, v)| v.as_str() == t).map(|(k, _)| k.clone()));
    let Some(device_id) = device else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    if header(&headers, "Device-Id").is_some_and(|claimed| claimed != device_id) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let model = st.cfg.silero_model.clone();
    upgrade.on_upgrade(move |socket| run_device(socket, device_id, st.link, model))
}
```

- [ ] **Step 4: Implement `device.rs`**

`gateway/src/device.rs`:
```rust
use std::collections::VecDeque;
use std::path::PathBuf;
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket};
use futures_util::{SinkExt, StreamExt};
use tokio::time::MissedTickBehavior;

use crate::audio::{self, DownEncoder, UpDecoder};
use crate::link::{LinkHandle, event_turn_id};
use crate::pb;
use crate::pb::brain_event::Kind;
use crate::vad::{Endpointer, SegmenterParams, SileroVad};
use crate::xiaozhi::{self, DeviceMsg, ListenState};

const LEAD_FRAMES: u32 = 2;

#[derive(Debug, Clone, Copy, PartialEq)]
enum State {
    Idle,
    Listening,
    Thinking,
    Speaking,
}

enum Out {
    Json(String),
    Audio(Vec<u8>),
    Stop,
}

struct Session {
    device_id: String,
    session_id: String,
    state: State,
    turn_id: Option<String>,
    tts_started: bool,
    queue: VecDeque<Out>,
    budget: u32,
    link: LinkHandle,
    decoder: UpDecoder,
    encoder: DownEncoder,
    endpointer: Endpointer<SileroVad>,
}

pub async fn run_device(socket: WebSocket, device_id: String, link: LinkHandle, silero_model: PathBuf) {
    let session = match Session::new(device_id.clone(), link.clone(), &silero_model) {
        Ok(s) => s,
        Err(err) => {
            tracing::error!(%err, device_id, "cannot start device session");
            return;
        }
    };
    let mut brain_rx = link.register(&device_id);
    tracing::info!(device_id, "device connected");
    session.run(socket, &mut brain_rx).await;
    link.unregister(&device_id);
    tracing::info!(device_id, "device disconnected");
}

impl Session {
    fn new(device_id: String, link: LinkHandle, silero_model: &PathBuf) -> anyhow::Result<Self> {
        Ok(Self {
            session_id: uuid::Uuid::new_v4().to_string(),
            device_id,
            state: State::Idle,
            turn_id: None,
            tts_started: false,
            queue: VecDeque::new(),
            budget: 0,
            link,
            decoder: UpDecoder::new()?,
            encoder: DownEncoder::new()?,
            endpointer: Endpointer::new(SileroVad::load(silero_model)?, SegmenterParams::default()),
        })
    }

    async fn run(mut self, socket: WebSocket, brain_rx: &mut tokio::sync::mpsc::Receiver<pb::BrainEvent>) {
        let (mut tx, mut rx) = socket.split();
        let mut tick = tokio::time::interval(Duration::from_millis(60));
        tick.set_missed_tick_behavior(MissedTickBehavior::Delay);

        loop {
            tokio::select! {
                msg = rx.next() => match msg {
                    Some(Ok(Message::Text(text))) => self.on_text(text.as_str()),
                    Some(Ok(Message::Binary(data))) => self.on_audio(&data),
                    Some(Ok(_)) => {}
                    Some(Err(_)) | None => break,
                },
                Some(ev) = brain_rx.recv() => self.on_brain(ev),
                _ = tick.tick() => self.budget = (self.budget + 1).min(LEAD_FRAMES + 1),
            }
            if self.flush(&mut tx).await.is_err() {
                break;
            }
        }

        if let Some(turn_id) = self.turn_id.take() {
            self.send_abort(turn_id);
        }
        self.link.send(state_event(&self.device_id, false));
    }

    async fn flush(&mut self, tx: &mut futures_util::stream::SplitSink<WebSocket, Message>) -> Result<(), axum::Error> {
        while let Some(front) = self.queue.front() {
            match front {
                Out::Audio(_) if self.budget == 0 => break,
                Out::Audio(_) => self.budget -= 1,
                _ => {}
            }
            match self.queue.pop_front().unwrap() {
                Out::Json(text) => tx.send(Message::Text(text.into())).await?,
                Out::Audio(packet) => tx.send(Message::Binary(packet.into())).await?,
                Out::Stop => {
                    tx.send(Message::Text(xiaozhi::tts_stop(&self.session_id).into())).await?;
                    // После barge-in через listen start колонка уже слушает — не сбрасываем её в Idle.
                    if matches!(self.state, State::Thinking | State::Speaking) {
                        self.state = State::Idle;
                    }
                    self.turn_id = None;
                    self.tts_started = false;
                }
            }
        }
        Ok(())
    }

    fn on_text(&mut self, text: &str) {
        let msg = match xiaozhi::parse(text) {
            Ok(m) => m,
            Err(err) => {
                tracing::debug!(%err, text, "unparsed device message");
                return;
            }
        };
        match msg {
            DeviceMsg::Hello { .. } => {
                self.queue.push_back(Out::Json(xiaozhi::server_hello(&self.session_id)));
                self.link.send(state_event(&self.device_id, true));
            }
            DeviceMsg::Listen { state: ListenState::Start, .. } => {
                self.interrupt();
                self.state = State::Listening;
                self.endpointer.reset();
            }
            DeviceMsg::Listen { state: ListenState::Detect, .. } | DeviceMsg::Abort { .. } => self.interrupt(),
            DeviceMsg::Listen { state: ListenState::Stop, .. } => {
                if self.state == State::Listening {
                    self.state = State::Idle;
                }
            }
            DeviceMsg::Other => {}
        }
    }

    fn interrupt(&mut self) {
        if !matches!(self.state, State::Thinking | State::Speaking) {
            return;
        }
        if let Some(turn_id) = self.turn_id.take() {
            self.send_abort(turn_id);
        }
        self.queue.clear();
        self.queue.push_back(Out::Stop);
    }

    fn on_audio(&mut self, packet: &[u8]) {
        if self.state != State::Listening {
            return;
        }
        let pcm = match self.decoder.decode(packet) {
            Ok(pcm) => pcm,
            Err(err) => {
                tracing::debug!(%err, "opus decode failed");
                return;
            }
        };
        let Some(utterance) = self.endpointer.push(&pcm).into_iter().next() else { return };
        let turn_id = uuid::Uuid::new_v4().to_string();
        self.state = State::Thinking;
        let sent = self.link.send(pb::GatewayEvent {
            kind: Some(pb::gateway_event::Kind::Utterance(pb::Utterance {
                device_id: self.device_id.clone(),
                turn_id: turn_id.clone(),
                pcm_s16le: audio::pcm_to_le_bytes(&utterance),
                sample_rate: audio::UP_RATE,
            })),
        });
        if sent {
            tracing::info!(device_id = self.device_id, turn_id, secs = utterance.len() as f32 / 16000.0, "utterance sent");
            self.turn_id = Some(turn_id);
        } else {
            tracing::warn!(device_id = self.device_id, "brain unavailable, dropping utterance");
            self.queue.push_back(Out::Json(xiaozhi::tts_start(&self.session_id)));
            self.queue.push_back(Out::Stop);
        }
    }

    fn on_brain(&mut self, ev: pb::BrainEvent) {
        if self.turn_id.as_deref() != event_turn_id(&ev) {
            return;
        }
        match ev.kind {
            Some(Kind::Transcript(t)) => self.queue.push_back(Out::Json(xiaozhi::stt(&self.session_id, &t.text))),
            Some(Kind::Speech(chunk)) => {
                self.start_tts();
                self.state = State::Speaking;
                self.queue.push_back(Out::Json(xiaozhi::tts_sentence(&self.session_id, &chunk.text)));
                let pcm = audio::resample(&audio::pcm_from_le_bytes(&chunk.pcm_s16le), chunk.sample_rate, audio::DOWN_RATE);
                match self.encoder.encode_all(&pcm) {
                    Ok(packets) => self.queue.extend(packets.into_iter().map(Out::Audio)),
                    Err(err) => tracing::error!(%err, "opus encode failed"),
                }
            }
            Some(Kind::End(_)) => {
                self.start_tts();
                self.queue.push_back(Out::Stop);
            }
            Some(Kind::Action(_)) | Some(Kind::Push(_)) | None => {
                tracing::debug!(device_id = self.device_id, "action/push ignored until M4/M5");
            }
        }
    }

    fn start_tts(&mut self) {
        if !self.tts_started {
            self.tts_started = true;
            self.budget = LEAD_FRAMES;
            self.queue.push_back(Out::Json(xiaozhi::tts_start(&self.session_id)));
        }
    }

    fn send_abort(&self, turn_id: String) {
        self.link.send(pb::GatewayEvent {
            kind: Some(pb::gateway_event::Kind::Abort(pb::Abort { device_id: self.device_id.clone(), turn_id })),
        });
    }
}

fn state_event(device_id: &str, online: bool) -> pb::GatewayEvent {
    pb::GatewayEvent {
        kind: Some(pb::gateway_event::Kind::State(pb::DeviceState { device_id: device_id.to_string(), online })),
    }
}
```
Add to `lib.rs`: `pub mod device;` and `pub mod server;`.

- [ ] **Step 5: Finish `main.rs`**

`gateway/src/main.rs`:
```rust
use std::sync::Arc;

use aidos_gateway::config::Config;
use aidos_gateway::link::LinkHandle;
use aidos_gateway::server::{AppState, router};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();
    let cfg = Config::from_env()?;
    let link = LinkHandle::spawn(cfg.brain_addr.clone(), cfg.link_token.clone());
    let listener = tokio::net::TcpListener::bind(cfg.bind).await?;
    tracing::info!(bind = %cfg.bind, brain = cfg.brain_addr, devices = cfg.devices.len(), "aidos-gateway listening");
    axum::serve(listener, router(AppState { cfg: Arc::new(cfg), link })).await?;
    Ok(())
}
```

Append to `.env.example`:
```env
# Колонка шлюзы (gateway/, Rust)
GATEWAY_BIND=0.0.0.0:8000
GATEWAY_PUBLIC_WS_URL=ws://192.168.1.10:8000/ws
BRAIN_ADDR=http://127.0.0.1:50051
GATEWAY_DEVICES=aa:bb:cc:dd:ee:ff=change_me_device_token
SILERO_MODEL=models/silero_vad.onnx
```

- [ ] **Step 6: Run all gateway tests**

Run: `cd gateway && cargo test`
Expected: all unit tests and 6 e2e tests pass. If `full_turn_over_websocket` frame count is off by one, check `encode_all` padding (`div_ceil`) and that `Out::Stop` is not sent before the queue drains (it is queued after the audio, so it is). If the utterance length assertion fails, print `heard` and compare with the fixture (3 s speech + 2 s silence; utterance ≈ pre-roll + speech + 1 s silence).

- [ ] **Step 7: Lint and commit**

Run: `cd gateway && cargo fmt && cargo clippy --all-targets -- -D warnings` and fix warnings.
```bash
git add gateway .env.example
git commit -m "feat(gateway): xiaozhi device sessions, OTA/WS server and e2e tests"
```

---

### Task 13: CI on GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  python:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: sudo apt-get update && sudo apt-get install -y libportaudio2
      - run: pip install --extra-index-url https://download.pytorch.org/whl/cpu -e ".[dev]"
      - run: ruff check src/ tests/
      - run: pytest -q
      - name: proto codegen is up to date
        run: |
          python -m grpc_tools.protoc -Iaidos/brain/gen=proto --python_out=src --grpc_python_out=src --pyi_out=src proto/link.proto
          git diff --exit-code src/aidos/brain/gen

  gateway:
    runs-on: ubuntu-24.04
    defaults:
      run:
        working-directory: gateway
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y libopus-dev pkg-config
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt, clippy
      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: gateway
      - run: cargo fmt --check
      - run: cargo clippy --all-targets -- -D warnings
      - run: cargo test
```

- [ ] **Step 2: Validate locally what can be validated**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/python -m pytest -q && (cd gateway && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test)`
Expected: all green. (The workflow itself runs on the first push.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: ruff, pytest, proto drift check, cargo fmt/clippy/test"
```

---

### Task 14: Manual M2 verification with py-xiaozhi and docs

**Files:**
- Modify: `README.md` (new section «Колонка (ESP32-S3-BOX-3)»)

- [ ] **Step 1: Configure secrets (user does this, not the agent)**

Ask the user to add to the main repo `.env` via an editor (never paste tokens in chat):
```env
LINK_TOKEN=<any long random string>
GATEWAY_DEVICES=pyxiaozhi-mac=<any long random string>
GATEWAY_PUBLIC_WS_URL=ws://127.0.0.1:8000/ws
```

- [ ] **Step 2: Start the brain and the gateway**

Terminal 1: `make brain` → expect `✓ Мозг тыңдауда: 127.0.0.1:50051`.
Terminal 2: `set -a; source .env; set +a; cd gateway && SILERO_MODEL=models/silero_vad.onnx cargo run --release` → expect `aidos-gateway listening` and `brain link up`.
Check OTA: `curl -s -X POST http://127.0.0.1:8000/ota -H "Device-Id: pyxiaozhi-mac" -d '{}'` → JSON with `websocket.url` and `websocket.token`.

- [ ] **Step 3: Run py-xiaozhi against the gateway**

```bash
git clone https://github.com/huangjunsen0406/py-xiaozhi.git ~/src/py-xiaozhi
cd ~/src/py-xiaozhi && uv sync
mkdir -p ~/.aidos/pyxiaozhi/config
```
Create `~/.aidos/pyxiaozhi/config/config.json` (py-xiaozhi reads it from `$XIAOZHI_DATA_DIR/config/config.json`; keys verified in `src/utils/config_manager.py`):
```json
{
  "CONFIG_VERSION": 1,
  "SYSTEM_OPTIONS": {
    "DEVICE_ID": "pyxiaozhi-mac",
    "NETWORK": {
      "OTA_VERSION_URL": "http://127.0.0.1:8000/ota/",
      "WEBSOCKET_URL": "ws://127.0.0.1:8000/ws",
      "WEBSOCKET_ACCESS_TOKEN": "<the token from GATEWAY_DEVICES>"
    }
  },
  "WAKE_WORD_OPTIONS": {"USE_WAKE_WORD": false}
}
```
Run: `XIAOZHI_DATA_DIR=~/.aidos/pyxiaozhi uv run python main.py --mode cli --protocol websocket`.
Speak «Сағат неше?» and «Абай кім болған?».
Expected: gateway logs `utterance sent`, brain logs the transcript, the Mac speaker plays the Kazakh answer. Measure end-of-speech → first sound with a stopwatch; record the number in the README section (spec target ≤ 4 s median).
If py-xiaozhi still tries `api.tenclass.net` or ignores the token, note the observed behavior in the README section and in spec §10 question 2, and fall back to verifying with `cargo test --test e2e` only.

- [ ] **Step 4: Document**

Add a README section «Колонка (ESP32-S3-BOX-3)» with: the architecture diagram from the spec §3, how to run `make brain` + `make gateway`, the `.env` keys from Task 12 Step 5, the py-xiaozhi config above, and the measured latency.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: run the speaker gateway locally with py-xiaozhi"
```
