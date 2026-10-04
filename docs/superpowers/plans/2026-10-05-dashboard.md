# Metrics Dashboard & Browser Emulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web dashboard served by the Rust gateway at `http://127.0.0.1:8000/` that shows live per-stage metrics of every speaker turn and contains a browser-based speaker emulator speaking the real xiaozhi protocol.

**Architecture:** The brain reports `TurnTimings{stt_ms,llm_ms,tts_ms}` in `TurnEnd`. The gateway gets a `MetricsHub` (ring buffer of 100 turns, device map, link status, `tokio::sync::broadcast` of `DashEvent`s) that `device.rs` and `link.rs` write into; `server.rs` exposes `/api/state`, `/api/events` (SSE), `/api/emulator`, static `/`, `/app.css`, `/app.js`, `/emulator.js`, all loopback-only. The page is framework-free HTML/CSS/JS; the emulator uses WebCodecs Opus and connects to `/ws?token=` as device `web-emulator`.

**Tech Stack:** Rust (axum 0.8 `sse`, tokio broadcast, tokio-stream `sync`, serde), Python (grpc, protobuf), vanilla JS (EventSource, WebCodecs AudioEncoder/AudioDecoder, AudioWorklet).

**Spec:** `docs/superpowers/specs/2026-10-05-aidos-dashboard-design.md` (builds on `docs/superpowers/specs/2026-10-03-aidos-satellite-gateway-design.md`).

## Global Constraints

- Branch `zhanzh/satellite-gateway`; commits without `Co-Authored-By` lines and without mentioning AI tools.
- Python commands use `/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python` (worktree has no .venv); proto regen: `make proto PYTHON=/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python`.
- Proto change is additive only: `message TurnTimings { uint32 stt_ms = 1; uint32 llm_ms = 2; uint32 tts_ms = 3; }` and `TurnTimings timings = 4;` in `TurnEnd`.
- Ring buffer keeps the last **100** turns; `summary()` uses the last 100 turns with status `ok`; percentiles are nearest-rank (`idx = ceil(p·n) − 1` on the sorted values).
- SSE keep-alive every **15 s**; broadcast capacity **256**; on `RecvError::Lagged` send event `resync`.
- Dashboard, `/api/*` and the static files answer **403** unless the peer address is loopback. `/ws?token=` is accepted **only** for the emulator device and only from loopback; all other devices keep header auth (401 otherwise).
- Emulator device id: env `GATEWAY_EMULATOR_DEVICE`, default `web-emulator`; empty string disables it. Token: random, generated at startup (64 hex chars from two `uuid::Uuid::new_v4().simple()`), never logged.
- UI: Russian copy, dark theme, no frameworks, no build step, no external CDNs; layout collapses to one column below 900 px.
- Emulator audio: uplink Opus 16 kHz mono, 60 ms frames (960 samples), bitrate 24000; downlink Opus 24 kHz mono 60 ms; protocol version 1; `listen start` with `mode:"manual"`, `listen stop` on release.
- Few code comments (only non-obvious "why"); Kazakh-style log strings in Python as in the codebase.

## Review Focus

- **SSE subscriber falls behind / reconnects** (laptop sleeps, tab in background): the page must resync from `/api/state`, not show stale or duplicated turns — pinned in Task 4 `sse_resync_on_lag` and Task 5 JS `resync` handling.
- **Turn interrupted or link lost mid-turn**: the turn must appear in the feed with status `aborted`/`error`, never hang as "in progress" — pinned in Task 2 `aborted_turn_is_recorded` and Task 3 e2e `aborted_turn_in_state`.
- **Request from a non-loopback address** (gateway bound to 0.0.0.0 on LAN/VPS): dashboard and APIs must return 403 and leak no transcripts or the emulator token — pinned in Task 4 unit test `is_loopback_*` and e2e `emulator_token_rejected_for_regular_device`.
- **Browser without WebCodecs Opus or without mic permission**: the emulator block shows a clear message and the rest of the dashboard keeps working — pinned in Task 6 manual check list (support probe via `isConfigSupported`).
- **Brain down during an emulator turn**: header turns red, the turn is recorded as `error`, the emulator returns to "готов" — pinned in Task 3 e2e `brain_down_turn_recorded_as_error`.

---

## File Structure

```
proto/link.proto                         # + TurnTimings (Task 1)
src/aidos/brain/turn.py                  # timings (Task 1)
src/aidos/brain/gen/*                    # regenerated (Task 1)
tests/test_turn.py                       # timings tests (Task 1)
gateway/src/metrics.rs                   # MetricsHub, TurnRecord, DashEvent, summary (Task 2)
gateway/src/device.rs                    # hub calls (Task 3)
gateway/src/link.rs                      # LinkHandle::with_metrics (Task 3)
gateway/src/server.rs                    # AppState.hub, /api/state, serve() (Task 3); SSE, static, emulator, loopback (Task 4)
gateway/src/config.rs                    # emulator_device (Task 4)
gateway/src/main.rs                      # hub + emulator token + serve() (Tasks 3–4)
gateway/web/index.html, app.css, app.js  # dashboard (Task 5)
gateway/web/emulator.js                  # browser speaker (Task 6)
gateway/examples/send_wav.rs             # dev tool: send a WAV as a device (Task 7)
gateway/tests/e2e.rs                     # new e2e tests (Tasks 3–4)
README.md                                # dashboard section (Task 7)
```

---

### Task 1: Turn timings from the brain

**Files:**
- Modify: `proto/link.proto`, `src/aidos/brain/turn.py`, regenerated `src/aidos/brain/gen/link_pb2.py`, `link_pb2.pyi`, `link_pb2_grpc.py`
- Test: `tests/test_turn.py`

**Interfaces:**
- Produces: `TurnEnd.timings: TurnTimings{stt_ms, llm_ms, tts_ms}` (uint32 ms). Rust gets `pb::TurnTimings` and `pb::TurnEnd { timings: Option<pb::TurnTimings>, .. }` from the existing build.rs codegen.

- [ ] **Step 1: Extend the proto**

In `proto/link.proto` replace the `TurnEnd` line with:
```proto
message TurnTimings { uint32 stt_ms = 1; uint32 llm_ms = 2; uint32 tts_ms = 3; }
message TurnEnd { string device_id = 1; string turn_id = 2; bool error = 3; TurnTimings timings = 4; }
```
Run `make proto PYTHON=/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python` and `cd gateway && cargo build` (Rust code compiles unchanged: prost adds a field with `Default`; fix any struct literal `pb::TurnEnd { .. }` in `gateway/tests/e2e.rs` by adding `timings: None` if the compiler asks).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_turn.py`:
```python
import time


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python -m pytest tests/test_turn.py -q`
Expected: the two new tests FAIL (`timings.stt_ms == 0`).

- [ ] **Step 4: Implement**

In `src/aidos/brain/turn.py` add `import time`, and rewrite `run` and `_end` as:
```python
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
        yield _end(ids, spoken == 0, timings)


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _end(ids: dict[str, str], error: bool, timings: link_pb2.TurnTimings) -> link_pb2.BrainEvent:
    return link_pb2.BrainEvent(end=link_pb2.TurnEnd(error=error, timings=timings, **ids))
```
Keep the existing behavior of every branch (errors still end with `error=True`; the odd-length PCM case is caught by the STT try block as before).

- [ ] **Step 5: Run tests**

Run: `/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python -m pytest -q` → all pass. Run `cd gateway && cargo test` → all pass.

- [ ] **Step 6: Commit**

```bash
git add proto/link.proto src/aidos/brain/turn.py src/aidos/brain/gen tests/test_turn.py gateway/tests/e2e.rs
git commit -m "feat(brain): report STT/LLM/TTS timings in TurnEnd"
```

---

### Task 2: `MetricsHub` (pure metrics model)

**Files:**
- Create: `gateway/src/metrics.rs`
- Modify: `gateway/src/lib.rs` (`pub mod metrics;`), `gateway/Cargo.toml` (tokio-stream feature `sync`)

**Interfaces:**
- Produces:
  ```rust
  #[derive(Clone, Copy, Debug, PartialEq, Serialize)] #[serde(rename_all = "lowercase")]
  pub enum TurnStatus { Active, Ok, Error, Aborted }
  #[derive(Clone, Debug, Serialize)]
  pub struct TurnRecord { pub turn_id: String, pub device_id: String, pub started_at: u64, pub utterance_secs: f32,
      pub transcript: String, pub reply_text: String, pub stt_ms: u32, pub llm_ms: u32, pub tts_ms: u32,
      pub first_audio_ms: Option<u32>, pub total_ms: Option<u32>, pub reply_secs: f32, pub status: TurnStatus }
  #[derive(Clone, Debug, Serialize)] pub struct DeviceView { pub device_id: String, pub online: bool, pub state: String }
  #[derive(Clone, Debug, Serialize, Default)] pub struct Stat { pub median_ms: u32, pub p95_ms: u32 }
  #[derive(Clone, Debug, Serialize, Default)] pub struct Summary { pub turns: usize, pub errors: usize,
      pub stt: Option<Stat>, pub llm: Option<Stat>, pub tts: Option<Stat>, pub first_audio: Option<Stat>, pub total: Option<Stat> }
  #[derive(Clone, Debug, Serialize)] pub struct LinkView { pub up: bool, pub reconnects: u32 }
  #[derive(Clone, Debug, Serialize)] pub struct Snapshot { pub link: LinkView, pub devices: Vec<DeviceView>, pub turns: Vec<TurnRecord>, pub summary: Summary }
  #[derive(Clone, Debug, Serialize)] #[serde(tag = "type", rename_all = "snake_case")]
  pub enum DashEvent { TurnStarted { turn: TurnRecord }, Transcript { turn_id: String, text: String },
      Speech { turn_id: String, text: String, first_audio_ms: Option<u32> }, TurnEnd { turn: TurnRecord },
      Device { device: DeviceView }, Link { link: LinkView } }
  pub struct MetricsHub;
  impl MetricsHub {
      pub fn new() -> std::sync::Arc<MetricsHub>;
      pub fn subscribe(&self) -> tokio::sync::broadcast::Receiver<DashEvent>;
      pub fn snapshot(&self) -> Snapshot;                       // turns newest first
      pub fn link(&self, up: bool);                             // reconnects += 1 on every down→up after the first up
      pub fn device(&self, device_id: &str, online: bool, state: &str);
      pub fn turn_started(&self, device_id: &str, turn_id: &str, utterance_secs: f32);
      pub fn transcript(&self, turn_id: &str, text: &str);
      pub fn speech(&self, turn_id: &str, text: &str, secs: f32);   // first call sets first_audio_ms
      pub fn turn_end(&self, turn_id: &str, status: TurnStatus, timings: Option<(u32, u32, u32)>);
  }
  pub fn summarize(turns: &[TurnRecord]) -> Summary;
  ```
  Unknown `turn_id` in transcript/speech/turn_end is ignored. `turn_end` on a turn that already ended is ignored. Every mutating call broadcasts the matching `DashEvent` (send errors from no subscribers are ignored).

- [ ] **Step 1: Write the module with tests (stubs first)**

Add `"sync"` to tokio-stream features in `gateway/Cargo.toml`: `tokio-stream = { version = "0.1", features = ["net", "sync"] }`.

Create `gateway/src/metrics.rs`:
```rust
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tokio::sync::broadcast;

const MAX_TURNS: usize = 100;
const EVENTS_CAPACITY: usize = 256;

#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum TurnStatus {
    Active,
    Ok,
    Error,
    Aborted,
}

#[derive(Clone, Debug, Serialize)]
pub struct TurnRecord {
    pub turn_id: String,
    pub device_id: String,
    pub started_at: u64,
    pub utterance_secs: f32,
    pub transcript: String,
    pub reply_text: String,
    pub stt_ms: u32,
    pub llm_ms: u32,
    pub tts_ms: u32,
    pub first_audio_ms: Option<u32>,
    pub total_ms: Option<u32>,
    pub reply_secs: f32,
    pub status: TurnStatus,
}

#[derive(Clone, Debug, Serialize)]
pub struct DeviceView {
    pub device_id: String,
    pub online: bool,
    pub state: String,
}

#[derive(Clone, Debug, Serialize, Default, PartialEq)]
pub struct Stat {
    pub median_ms: u32,
    pub p95_ms: u32,
}

#[derive(Clone, Debug, Serialize, Default)]
pub struct Summary {
    pub turns: usize,
    pub errors: usize,
    pub stt: Option<Stat>,
    pub llm: Option<Stat>,
    pub tts: Option<Stat>,
    pub first_audio: Option<Stat>,
    pub total: Option<Stat>,
}

#[derive(Clone, Debug, Serialize)]
pub struct LinkView {
    pub up: bool,
    pub reconnects: u32,
}

#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub link: LinkView,
    pub devices: Vec<DeviceView>,
    pub turns: Vec<TurnRecord>,
    pub summary: Summary,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DashEvent {
    TurnStarted { turn: TurnRecord },
    Transcript { turn_id: String, text: String },
    Speech { turn_id: String, text: String, first_audio_ms: Option<u32> },
    TurnEnd { turn: TurnRecord },
    Device { device: DeviceView },
    Link { link: LinkView },
}

struct Inner {
    turns: VecDeque<TurnRecord>,
    started: HashMap<String, Instant>,
    devices: HashMap<String, DeviceView>,
    link_up: bool,
    ever_up: bool,
    reconnects: u32,
}

pub struct MetricsHub {
    inner: Mutex<Inner>,
    tx: broadcast::Sender<DashEvent>,
}

fn now_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64
}

fn stat(mut values: Vec<u32>) -> Option<Stat> {
    todo!()
}

pub fn summarize(turns: &[TurnRecord]) -> Summary {
    todo!()
}

impl MetricsHub {
    pub fn new() -> Arc<MetricsHub> {
        todo!()
    }

    pub fn subscribe(&self) -> broadcast::Receiver<DashEvent> {
        self.tx.subscribe()
    }

    pub fn snapshot(&self) -> Snapshot {
        todo!()
    }

    pub fn link(&self, up: bool) {
        todo!()
    }

    pub fn device(&self, device_id: &str, online: bool, state: &str) {
        todo!()
    }

    pub fn turn_started(&self, device_id: &str, turn_id: &str, utterance_secs: f32) {
        todo!()
    }

    pub fn transcript(&self, turn_id: &str, text: &str) {
        todo!()
    }

    pub fn speech(&self, turn_id: &str, text: &str, secs: f32) {
        todo!()
    }

    pub fn turn_end(&self, turn_id: &str, status: TurnStatus, timings: Option<(u32, u32, u32)>) {
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(status: TurnStatus, stt: u32) -> TurnRecord {
        TurnRecord {
            turn_id: "t".into(), device_id: "d".into(), started_at: 0, utterance_secs: 1.0,
            transcript: String::new(), reply_text: String::new(), stt_ms: stt, llm_ms: stt * 2,
            tts_ms: 10, first_audio_ms: Some(stt + 5), total_ms: Some(stt + 50), reply_secs: 1.0, status,
        }
    }

    #[test]
    fn nearest_rank_percentiles() {
        assert_eq!(stat(vec![]), None);
        assert_eq!(stat(vec![7]), Some(Stat { median_ms: 7, p95_ms: 7 }));
        let values: Vec<u32> = (1..=20).collect();
        assert_eq!(stat(values), Some(Stat { median_ms: 10, p95_ms: 19 }));
    }

    #[test]
    fn summary_counts_only_ok_turns_for_stats() {
        let turns = vec![record(TurnStatus::Ok, 100), record(TurnStatus::Error, 900), record(TurnStatus::Ok, 300)];
        let s = summarize(&turns);
        assert_eq!((s.turns, s.errors), (3, 1));
        assert_eq!(s.stt, Some(Stat { median_ms: 100, p95_ms: 300 }));
        assert_eq!(s.llm, Some(Stat { median_ms: 200, p95_ms: 600 }));
    }

    #[test]
    fn full_turn_lifecycle_and_events() {
        let hub = MetricsHub::new();
        let mut rx = hub.subscribe();
        hub.turn_started("box", "t1", 2.5);
        hub.transcript("t1", "сағат неше");
        hub.speech("t1", "Қазір он екі.", 1.2);
        hub.speech("t1", "Түс болды.", 0.8);
        hub.turn_end("t1", TurnStatus::Ok, Some((900, 1600, 200)));

        let snap = hub.snapshot();
        let t = &snap.turns[0];
        assert_eq!(t.transcript, "сағат неше");
        assert_eq!(t.reply_text, "Қазір он екі. Түс болды.");
        assert_eq!((t.stt_ms, t.llm_ms, t.tts_ms), (900, 1600, 200));
        assert!(t.first_audio_ms.is_some() && t.total_ms.is_some());
        assert!((t.reply_secs - 2.0).abs() < 1e-6);
        assert_eq!(t.status, TurnStatus::Ok);

        let kinds: Vec<&str> = std::iter::from_fn(|| rx.try_recv().ok())
            .map(|e| match e {
                DashEvent::TurnStarted { .. } => "turn_started",
                DashEvent::Transcript { .. } => "transcript",
                DashEvent::Speech { .. } => "speech",
                DashEvent::TurnEnd { .. } => "turn_end",
                DashEvent::Device { .. } => "device",
                DashEvent::Link { .. } => "link",
            })
            .collect();
        assert_eq!(kinds, ["turn_started", "transcript", "speech", "speech", "turn_end"]);
    }

    #[test]
    fn aborted_turn_is_recorded() {
        let hub = MetricsHub::new();
        hub.turn_started("box", "t1", 1.0);
        hub.turn_end("t1", TurnStatus::Aborted, None);
        hub.turn_end("t1", TurnStatus::Ok, Some((1, 2, 3)));
        let t = &hub.snapshot().turns[0];
        assert_eq!(t.status, TurnStatus::Aborted);
        assert_eq!(t.stt_ms, 0);
    }

    #[test]
    fn ring_buffer_keeps_last_100_newest_first() {
        let hub = MetricsHub::new();
        for i in 0..101 {
            hub.turn_started("box", &format!("t{i}"), 1.0);
        }
        let snap = hub.snapshot();
        assert_eq!(snap.turns.len(), 100);
        assert_eq!(snap.turns[0].turn_id, "t100");
        assert_eq!(snap.turns[99].turn_id, "t1");
    }

    #[test]
    fn unknown_turn_ids_are_ignored() {
        let hub = MetricsHub::new();
        hub.transcript("nope", "x");
        hub.speech("nope", "x", 1.0);
        hub.turn_end("nope", TurnStatus::Ok, None);
        assert!(hub.snapshot().turns.is_empty());
    }

    #[test]
    fn link_reconnects_and_devices() {
        let hub = MetricsHub::new();
        hub.link(true);
        hub.link(false);
        hub.link(true);
        hub.device("box", true, "idle");
        hub.device("box", true, "speaking");
        let snap = hub.snapshot();
        assert!(snap.link.up);
        assert_eq!(snap.link.reconnects, 1);
        assert_eq!(snap.devices.len(), 1);
        assert_eq!(snap.devices[0].state, "speaking");
    }
}
```
Add `pub mod metrics;` to `gateway/src/lib.rs`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && cargo test --lib metrics`
Expected: FAIL — `not yet implemented`.

- [ ] **Step 3: Implement**

Replace the `todo!()` bodies:
```rust
fn stat(mut values: Vec<u32>) -> Option<Stat> {
    if values.is_empty() {
        return None;
    }
    values.sort_unstable();
    let rank = |p: f64| values[((p * values.len() as f64).ceil() as usize).max(1) - 1];
    Some(Stat { median_ms: rank(0.5), p95_ms: rank(0.95) })
}

pub fn summarize(turns: &[TurnRecord]) -> Summary {
    let ok: Vec<&TurnRecord> = turns.iter().filter(|t| t.status == TurnStatus::Ok).collect();
    let pick = |f: fn(&TurnRecord) -> Option<u32>| stat(ok.iter().filter_map(|t| f(t)).collect());
    Summary {
        turns: turns.len(),
        errors: turns.iter().filter(|t| t.status == TurnStatus::Error).count(),
        stt: pick(|t| Some(t.stt_ms)),
        llm: pick(|t| Some(t.llm_ms)),
        tts: pick(|t| Some(t.tts_ms)),
        first_audio: pick(|t| t.first_audio_ms),
        total: pick(|t| t.total_ms),
    }
}

impl MetricsHub {
    pub fn new() -> Arc<MetricsHub> {
        let (tx, _) = broadcast::channel(EVENTS_CAPACITY);
        Arc::new(MetricsHub {
            inner: Mutex::new(Inner {
                turns: VecDeque::with_capacity(MAX_TURNS),
                started: HashMap::new(),
                devices: HashMap::new(),
                link_up: false,
                ever_up: false,
                reconnects: 0,
            }),
            tx,
        })
    }

    pub fn snapshot(&self) -> Snapshot {
        let inner = self.inner.lock().unwrap();
        let turns: Vec<TurnRecord> = inner.turns.iter().rev().cloned().collect();
        let mut devices: Vec<DeviceView> = inner.devices.values().cloned().collect();
        devices.sort_by(|a, b| a.device_id.cmp(&b.device_id));
        Snapshot {
            link: LinkView { up: inner.link_up, reconnects: inner.reconnects },
            summary: summarize(&turns),
            devices,
            turns,
        }
    }

    pub fn link(&self, up: bool) {
        let view = {
            let mut inner = self.inner.lock().unwrap();
            if up && !inner.link_up && inner.ever_up {
                inner.reconnects += 1;
            }
            inner.ever_up |= up;
            inner.link_up = up;
            LinkView { up, reconnects: inner.reconnects }
        };
        let _ = self.tx.send(DashEvent::Link { link: view });
    }

    pub fn device(&self, device_id: &str, online: bool, state: &str) {
        let view = DeviceView { device_id: device_id.to_string(), online, state: state.to_string() };
        self.inner.lock().unwrap().devices.insert(device_id.to_string(), view.clone());
        let _ = self.tx.send(DashEvent::Device { device: view });
    }

    pub fn turn_started(&self, device_id: &str, turn_id: &str, utterance_secs: f32) {
        let turn = TurnRecord {
            turn_id: turn_id.to_string(), device_id: device_id.to_string(), started_at: now_ms(),
            utterance_secs, transcript: String::new(), reply_text: String::new(),
            stt_ms: 0, llm_ms: 0, tts_ms: 0, first_audio_ms: None, total_ms: None,
            reply_secs: 0.0, status: TurnStatus::Active,
        };
        {
            let mut inner = self.inner.lock().unwrap();
            if inner.turns.len() == MAX_TURNS {
                if let Some(old) = inner.turns.pop_front() {
                    inner.started.remove(&old.turn_id);
                }
            }
            inner.turns.push_back(turn.clone());
            inner.started.insert(turn_id.to_string(), Instant::now());
        }
        let _ = self.tx.send(DashEvent::TurnStarted { turn });
    }

    pub fn transcript(&self, turn_id: &str, text: &str) {
        let found = self.update(turn_id, |t, _| t.transcript = text.to_string());
        if found.is_some() {
            let _ = self.tx.send(DashEvent::Transcript { turn_id: turn_id.to_string(), text: text.to_string() });
        }
    }

    pub fn speech(&self, turn_id: &str, text: &str, secs: f32) {
        let found = self.update(turn_id, |t, elapsed| {
            if t.first_audio_ms.is_none() {
                t.first_audio_ms = Some(elapsed);
            }
            if !t.reply_text.is_empty() {
                t.reply_text.push(' ');
            }
            t.reply_text.push_str(text);
            t.reply_secs += secs;
        });
        if let Some(turn) = found {
            let _ = self.tx.send(DashEvent::Speech {
                turn_id: turn_id.to_string(), text: text.to_string(), first_audio_ms: turn.first_audio_ms,
            });
        }
    }

    pub fn turn_end(&self, turn_id: &str, status: TurnStatus, timings: Option<(u32, u32, u32)>) {
        let found = self.update(turn_id, |t, elapsed| {
            t.status = status;
            t.total_ms = Some(elapsed);
            if let Some((stt, llm, tts)) = timings {
                (t.stt_ms, t.llm_ms, t.tts_ms) = (stt, llm, tts);
            }
        });
        if let Some(turn) = found {
            self.inner.lock().unwrap().started.remove(turn_id);
            let _ = self.tx.send(DashEvent::TurnEnd { turn });
        }
    }

    // Только активные ходы: поздние события закрытого хода не должны его менять.
    fn update(&self, turn_id: &str, f: impl FnOnce(&mut TurnRecord, u32)) -> Option<TurnRecord> {
        let mut inner = self.inner.lock().unwrap();
        let elapsed = inner.started.get(turn_id)?.elapsed().as_millis() as u32;
        let turn = inner.turns.iter_mut().rev().find(|t| t.turn_id == turn_id)?;
        if turn.status != TurnStatus::Active {
            return None;
        }
        f(turn, elapsed);
        Some(turn.clone())
    }
}
```

- [ ] **Step 4: Run tests**

Run: `cd gateway && cargo test --lib metrics` → 7 passed; `cargo clippy --all-targets -- -D warnings` clean.

- [ ] **Step 5: Commit**

```bash
git add gateway/src/metrics.rs gateway/src/lib.rs gateway/Cargo.toml gateway/Cargo.lock
git commit -m "feat(gateway): metrics hub with turn ring buffer, summary and events"
```

---

### Task 3: Instrument device and link, expose `/api/state`

**Files:**
- Modify: `gateway/src/device.rs`, `gateway/src/link.rs`, `gateway/src/server.rs`, `gateway/src/main.rs`, `gateway/tests/e2e.rs`

**Interfaces:**
- Consumes: `MetricsHub`, `TurnStatus` (Task 2); `pb::TurnEnd.timings` (Task 1).
- Produces:
  - `LinkHandle::with_metrics(brain_addr: String, token: String, hub: Arc<MetricsHub>) -> LinkHandle` (calls `hub.link(true/false)` on up/down); `LinkHandle::spawn` keeps its signature (no hub).
  - `AppState { cfg: Arc<Config>, link: LinkHandle, hub: Arc<MetricsHub> }`.
  - `pub async fn serve(listener: tokio::net::TcpListener, state: AppState) -> std::io::Result<()>` in server.rs — runs `axum::serve(listener, router(state).into_make_service_with_connect_info::<SocketAddr>())`. main.rs and e2e use it.
  - `GET /api/state` → JSON `Snapshot`.
  - `run_device(socket, device_id, link, silero_model, hub: Arc<MetricsHub>)`.

- [ ] **Step 1: Write the failing e2e tests**

In `gateway/tests/e2e.rs`:
1. Change `FakeBrain`'s `TurnEnd` construction to include `timings: Some(pb::TurnTimings { stt_ms: 900, llm_ms: 1600, tts_ms: 200 })`.
2. Change `start_gateway` to build `let hub = aidos_gateway::metrics::MetricsHub::new();`, `let link = LinkHandle::with_metrics(brain_addr, "link".into(), hub.clone());`, and serve with `tokio::spawn(aidos_gateway::server::serve(listener, AppState { cfg: Arc::new(cfg), link: link.clone(), hub }))`.
3. Add a helper and tests:
```rust
async fn get_json(addr: &str, path: &str) -> serde_json::Value {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut stream = tokio::net::TcpStream::connect(addr).await.unwrap();
    stream
        .write_all(format!("GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").as_bytes())
        .await
        .unwrap();
    let mut raw = String::new();
    stream.read_to_string(&mut raw).await.unwrap();
    assert!(raw.starts_with("HTTP/1.1 200"), "{raw}");
    let body = raw.split_once("\r\n\r\n").unwrap().1;
    serde_json::from_str(body).unwrap()
}

async fn wait_turn_status(addr: &str, status: &str) -> serde_json::Value {
    for _ in 0..100 {
        let state = get_json(addr, "/api/state").await;
        if let Some(t) = state["turns"].as_array().and_then(|t| t.first()) {
            if t["status"] == status {
                return state;
            }
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    panic!("no turn with status {status}");
}

#[tokio::test]
async fn state_records_completed_turn() {
    let brain = FakeBrain::default();
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    let state = wait_turn_status(&addr, "ok").await;
    let turn = &state["turns"][0];
    assert_eq!(turn["device_id"], DEVICE);
    assert_eq!(turn["transcript"], "сәлем");
    assert_eq!(turn["reply_text"], "Сәлем!");
    assert_eq!((turn["stt_ms"].as_u64(), turn["llm_ms"].as_u64(), turn["tts_ms"].as_u64()), (Some(900), Some(1600), Some(200)));
    assert!(turn["first_audio_ms"].as_u64().is_some());
    assert_eq!(state["summary"]["turns"], 1);
    assert_eq!(state["link"]["up"], true);
    assert!(state["devices"].as_array().unwrap().iter().any(|d| d["device_id"] == DEVICE && d["online"] == true));
}

#[tokio::test]
async fn aborted_turn_in_state() {
    let brain = FakeBrain { hold_first: true, ..FakeBrain::default() };
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["type"], "stt");
    ws.send(Message::Text(format!(r#"{{"session_id":"{session}","type":"abort","reason":"wake_word_detected"}}"#).into())).await.unwrap();
    wait_turn_status(&addr, "aborted").await;
}

#[tokio::test]
async fn brain_down_turn_recorded_as_error() {
    let (addr, link) = start_gateway("http://127.0.0.1:1".into()).await;
    wait_link(&link, false).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    let state = wait_turn_status(&addr, "error").await;
    assert_eq!(state["link"]["up"], false);
}
```
(Use the existing field names of `FakeBrain` — e.g. `hold_first` — and the existing `speak`, `hello`, `next_json`, `connect` helpers as they are in the file.)

- [ ] **Step 2: Run e2e to verify failure**

Run: `cd gateway && cargo test --test e2e`
Expected: compile errors (`with_metrics`, `serve`, `AppState.hub` missing).

- [ ] **Step 3: Implement link instrumentation**

In `gateway/src/link.rs`:
- Add field `metrics: Option<Arc<MetricsHub>>` passed into `run`/`connect_once`.
- `pub fn spawn(brain_addr, token) -> LinkHandle { Self::start(brain_addr, token, None) }`, `pub fn with_metrics(brain_addr, token, hub) -> LinkHandle { Self::start(brain_addr, token, Some(hub)) }`, private `fn start(..)` holds the old body.
- In `connect_once` right after `connected.store(true, ..)`: `if let Some(m) = metrics { m.link(true); }`. In `run` where `connected.swap(false, ..)` returns true: `if let Some(m) = &metrics { m.link(false); }`.

- [ ] **Step 4: Implement device instrumentation**

In `gateway/src/device.rs`:
- `Session` gets `hub: Arc<MetricsHub>`; `run_device` gets a 5th parameter `hub: Arc<MetricsHub>` and passes it to `Session::new`.
- Add a helper that records the state change and use it for every assignment to `self.state`:
```rust
    fn set_state(&mut self, state: State) {
        if self.state != state {
            self.state = state;
            self.hub.device(&self.device_id, true, state.label());
        }
    }
```
with
```rust
impl State {
    fn label(self) -> &'static str {
        match self {
            State::Idle => "idle",
            State::Listening => "listening",
            State::Thinking => "thinking",
            State::Speaking => "speaking",
        }
    }
}
```
  Replace every `self.state = X` with `self.set_state(X)`.
- On `hello`: `self.hub.device(&self.device_id, true, self.state.label())`. At the end of `run` (after the offline `link.send` decision, same condition): `self.hub.device(&self.device_id, false, "idle")`.
- `send_utterance`: after creating `turn_id`, call `self.hub.turn_started(&self.device_id, &turn_id, utterance.len() as f32 / audio::UP_RATE as f32)`; in the `!sent` branch also `self.hub.turn_end(&turn_id, TurnStatus::Error, None)`.
- `on_brain`: `Transcript` → `self.hub.transcript(turn_id, &t.text)`; `Speech` (after the sample-rate guard) → `self.hub.speech(turn_id, &chunk.text, pcm.len() as f32 / audio::DOWN_RATE as f32)` using the resampled length; `End(end)` → `let timings = end.timings.map(|t| (t.stt_ms, t.llm_ms, t.tts_ms)); self.hub.turn_end(turn_id, if end.error { TurnStatus::Error } else { TurnStatus::Ok }, timings)`. Take `turn_id` from `self.turn_id.clone()` before matching.
- `interrupt`: before `self.turn_id.take()`'s abort, record `self.hub.turn_end(&turn_id, TurnStatus::Aborted, None)`.
- `check_link` (link lost mid-turn): if `self.turn_id` is Some, record `TurnStatus::Error` before clearing it.
- At the end of `run`, if a turn is still active when the socket closes: record `TurnStatus::Aborted`.

- [ ] **Step 5: Implement `/api/state`, `serve()` and wire main**

In `gateway/src/server.rs`:
```rust
use std::net::SocketAddr;
use crate::metrics::MetricsHub;

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub link: LinkHandle,
    pub hub: Arc<MetricsHub>,
}

pub async fn serve(listener: tokio::net::TcpListener, state: AppState) -> std::io::Result<()> {
    axum::serve(listener, router(state).into_make_service_with_connect_info::<SocketAddr>()).await
}

async fn api_state(State(st): State<AppState>) -> Response {
    Json(st.hub.snapshot()).into_response()
}
```
Register `.route("/api/state", get(api_state))`, pass `st.hub.clone()` to `run_device` in `ws`.
In `main.rs`: `let hub = MetricsHub::new(); let link = LinkHandle::with_metrics(cfg.brain_addr.clone(), cfg.link_token.clone(), hub.clone());` and replace `axum::serve(...)` with `server::serve(listener, AppState { cfg: Arc::new(cfg), link, hub }).await?;`.

- [ ] **Step 6: Run all gateway tests**

Run: `cd gateway && cargo test` (all unit + all e2e, including the 3 new ones) → pass; `cargo fmt && cargo clippy --all-targets -- -D warnings` → clean.

- [ ] **Step 7: Commit**

```bash
git add gateway/src gateway/tests/e2e.rs
git commit -m "feat(gateway): record turn metrics from device sessions and link, /api/state"
```

---

### Task 4: SSE, static routes, emulator device, loopback guard

**Files:**
- Modify: `gateway/src/server.rs`, `gateway/src/config.rs`, `gateway/src/main.rs`, `gateway/tests/e2e.rs`, `.env.example`
- Create: `gateway/web/index.html` (placeholder page from Step 3 — replaced in Task 5), `gateway/web/app.css`, `gateway/web/app.js`, `gateway/web/emulator.js` (empty modules until Tasks 5–6)

**Interfaces:**
- Consumes: `AppState`, `MetricsHub::subscribe`, `DashEvent` (Tasks 2–3).
- Produces:
  - `Config.emulator_device: Option<String>` (env `GATEWAY_EMULATOR_DEVICE`, default `web-emulator`, empty → None).
  - `AppState.emulator: Option<(String, String)>` (device_id, token). main generates the token, inserts `(device_id, token)` into `cfg.devices` before wrapping cfg in `Arc`.
  - `pub fn is_loopback(addr: &SocketAddr) -> bool`.
  - Routes (all loopback-only via middleware): `GET /` (text/html), `/app.css` (text/css), `/app.js`, `/emulator.js` (text/javascript), `/api/state`, `/api/events` (SSE), `/api/emulator` → `{"device_id","token","ws_url":"/ws"}` or 404 when disabled.
  - `/ws` accepts `?token=` only when the token belongs to the emulator device and the peer is loopback.

- [ ] **Step 1: Write the failing tests**

Unit tests at the bottom of `server.rs`:
```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_loopback_v4_and_v6() {
        assert!(is_loopback(&"127.0.0.1:5000".parse().unwrap()));
        assert!(is_loopback(&"[::1]:5000".parse().unwrap()));
        assert!(!is_loopback(&"192.168.1.20:5000".parse().unwrap()));
        assert!(!is_loopback(&"10.0.0.1:80".parse().unwrap()));
    }
}
```
e2e tests in `gateway/tests/e2e.rs` (set `emulator_device: Some("web-emulator".into())` in the test `Config`, insert `("web-emulator", "emu-token")` into `devices`, and pass `emulator: Some(("web-emulator".into(), "emu-token".into()))` in `AppState`):
```rust
async fn get_raw(addr: &str, path: &str) -> String {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut stream = tokio::net::TcpStream::connect(addr).await.unwrap();
    stream.write_all(format!("GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
    let mut raw = String::new();
    stream.read_to_string(&mut raw).await.unwrap();
    raw
}

#[tokio::test]
async fn static_pages_served() {
    let (addr, _link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    let page = get_raw(&addr, "/").await;
    assert!(page.starts_with("HTTP/1.1 200") && page.contains("text/html"), "{page}");
    assert!(get_raw(&addr, "/app.js").await.contains("javascript"));
    assert!(get_raw(&addr, "/app.css").await.contains("text/css"));
}

#[tokio::test]
async fn emulator_endpoint_and_query_token_auth() {
    let (addr, link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    wait_link(&link, true).await;
    let info = get_json(&addr, "/api/emulator").await;
    assert_eq!(info["device_id"], "web-emulator");
    let token = info["token"].as_str().unwrap();
    let url = format!("ws://{addr}/ws?token={token}");
    let (mut ws, _) = tokio_tungstenite::connect_async(url).await.unwrap();
    ws.send(Message::Text(r#"{"type":"hello","version":1,"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}"#.into())).await.unwrap();
    assert_eq!(next_json(&mut ws).await["type"], "hello");
}

#[tokio::test]
async fn emulator_token_rejected_for_regular_device() {
    let (addr, _link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    let url = format!("ws://{addr}/ws?token={TOKEN}");
    assert!(tokio_tungstenite::connect_async(url).await.is_err());
}

#[tokio::test]
async fn sse_streams_turn_events() {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    let brain = FakeBrain::default();
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut sse = tokio::net::TcpStream::connect(&addr).await.unwrap();
    sse.write_all(b"GET /api/events HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n").await.unwrap();
    let mut lines = BufReader::new(sse).lines();

    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;

    let mut kinds = Vec::new();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(15);
    while !kinds.contains(&"turn_end".to_string()) {
        let line = tokio::time::timeout_at(deadline, lines.next_line()).await.unwrap().unwrap().unwrap();
        if let Some(data) = line.strip_prefix("data:") {
            let v: serde_json::Value = serde_json::from_str(data.trim()).unwrap();
            kinds.push(v["type"].as_str().unwrap().to_string());
        }
    }
    let pos = |k: &str| kinds.iter().position(|x| x == k).unwrap();
    assert!(pos("turn_started") < pos("transcript") && pos("transcript") < pos("turn_end"), "{kinds:?}");
}
```
And a unit test for lag handling in `server.rs` tests module:
```rust
    #[tokio::test]
    async fn sse_resync_on_lag() {
        let hub = crate::metrics::MetricsHub::new();
        let rx = hub.subscribe();
        for i in 0..300 {
            hub.device(&format!("d{i}"), true, "idle");
        }
        let mut stream = Box::pin(dash_stream(rx));
        let first = stream.next().await.unwrap();
        assert_eq!(first, DashItem::Resync);
    }
```
where `dash_stream(rx: broadcast::Receiver<DashEvent>) -> impl Stream<Item = DashItem>` and `#[derive(Debug, PartialEq)] enum DashItem { Event(String /*json*/), Resync }` are the testable core of the SSE handler (needs `use futures_util::StreamExt;`).

- [ ] **Step 2: Run tests to verify failure**

Run: `cd gateway && cargo test`
Expected: compile errors for the new items.

- [ ] **Step 3: Implement**

`config.rs`: add `pub emulator_device: Option<String>` read as `Some(env("GATEWAY_EMULATOR_DEVICE", "web-emulator")).filter(|s| !s.is_empty())`.

`main.rs`, before `Arc::new(cfg)`:
```rust
    let mut cfg = cfg;
    let emulator = cfg.emulator_device.clone().map(|id| {
        let token = format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple());
        cfg.devices.insert(id.clone(), token.clone());
        (id, token)
    });
```
and pass `emulator` into `AppState`.

`server.rs` additions:
```rust
use axum::extract::{ConnectInfo, Query};
use axum::middleware::{self, Next};
use axum::extract::Request;
use axum::response::sse::{Event, KeepAlive, Sse};
use futures_util::{Stream, StreamExt};
use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::wrappers::errors::BroadcastStreamRecvError;

pub fn is_loopback(addr: &SocketAddr) -> bool {
    addr.ip().is_loopback()
}

async fn local_only(ConnectInfo(addr): ConnectInfo<SocketAddr>, req: Request, next: Next) -> Response {
    if is_loopback(&addr) { next.run(req).await } else { StatusCode::FORBIDDEN.into_response() }
}

#[derive(Debug, PartialEq)]
enum DashItem { Event(String), Resync }

fn dash_stream(rx: broadcast::Receiver<DashEvent>) -> impl Stream<Item = DashItem> {
    BroadcastStream::new(rx).map(|item| match item {
        Ok(ev) => DashItem::Event(serde_json::to_string(&ev).unwrap_or_default()),
        Err(BroadcastStreamRecvError::Lagged(_)) => DashItem::Resync,
    })
}

async fn api_events(State(st): State<AppState>) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    let stream = dash_stream(st.hub.subscribe()).map(|item| Ok(match item {
        DashItem::Event(json) => Event::default().data(json),
        DashItem::Resync => Event::default().data(r#"{"type":"resync"}"#),
    }));
    Sse::new(stream).keep_alive(KeepAlive::new().interval(std::time::Duration::from_secs(15)))
}

async fn api_emulator(State(st): State<AppState>) -> Response {
    match &st.emulator {
        Some((device_id, token)) => Json(json!({"device_id": device_id, "token": token, "ws_url": "/ws"})).into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

fn asset(body: &'static str, content_type: &'static str) -> Response {
    ([(axum::http::header::CONTENT_TYPE, content_type)], body).into_response()
}
```
Router:
```rust
pub fn router(state: AppState) -> Router {
    let dashboard = Router::new()
        .route("/", get(|| async { asset(include_str!("../web/index.html"), "text/html; charset=utf-8") }))
        .route("/app.css", get(|| async { asset(include_str!("../web/app.css"), "text/css; charset=utf-8") }))
        .route("/app.js", get(|| async { asset(include_str!("../web/app.js"), "text/javascript; charset=utf-8") }))
        .route("/emulator.js", get(|| async { asset(include_str!("../web/emulator.js"), "text/javascript; charset=utf-8") }))
        .route("/api/state", get(api_state))
        .route("/api/events", get(api_events))
        .route("/api/emulator", get(api_emulator))
        .layer(middleware::from_fn(local_only));
    Router::new()
        .route("/ota", post(ota).get(ota))
        .route("/ota/", post(ota).get(ota))
        .route("/ws", get(ws))
        .merge(dashboard)
        .with_state(state)
}
```
`ws` handler gets `ConnectInfo(peer): ConnectInfo<SocketAddr>` and `Query(q): Query<HashMap<String, String>>`; token resolution:
```rust
    let header_token = header(&headers, "Authorization").and_then(|v| v.strip_prefix("Bearer "));
    let device = match (header_token, q.get("token")) {
        (Some(t), _) => find_device(&st.cfg, t),
        (None, Some(t)) if is_loopback(&peer) => st
            .emulator
            .as_ref()
            .filter(|(_, emu_token)| emu_token == t)
            .map(|(id, _)| id.clone()),
        _ => None,
    };
```
(`find_device` is the existing lookup extracted into a function.)

Create the four files under `gateway/web/` so `include_str!` compiles: `index.html` with a minimal valid page that links `/app.css` and loads `/app.js` as `type="module"`; `app.css`, `app.js`, `emulator.js` may start empty (Tasks 5–6 fill them).

`.env.example`: add `GATEWAY_EMULATOR_DEVICE=web-emulator` to the gateway block.

- [ ] **Step 4: Run tests**

Run: `cd gateway && cargo test` → all pass; `cargo fmt && cargo clippy --all-targets -- -D warnings` clean.

- [ ] **Step 5: Commit**

```bash
git add gateway .env.example
git commit -m "feat(gateway): SSE events, dashboard routes, emulator device, loopback guard"
```

---

### Task 5: Dashboard page (metrics, pipeline, feed)

**Files:**
- Replace: `gateway/web/index.html`, `gateway/web/app.css`, `gateway/web/app.js`

**Interfaces:**
- Consumes: `GET /api/state` → `Snapshot` JSON; `GET /api/events` SSE with `DashEvent` JSON (`type` ∈ `turn_started|transcript|speech|turn_end|device|link|resync`); `/emulator.js` exports `initEmulator(root: HTMLElement): void` (Task 6; until then the import is guarded: if the module has no `initEmulator`, the emulator block shows "Эмулятор недоступен").
- Produces: page structure ids used by Task 6: `#emulator` (container).

- [ ] **Step 1: Write `index.html`**

```html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aidos · панель</title>
  <link rel="stylesheet" href="/app.css">
  <script type="module" src="/app.js"></script>
</head>
<body>
  <header class="top">
    <h1>Айдос <span class="muted">· панель колонки</span></h1>
    <div class="status">
      <span id="link-status" class="pill bad">мозг: нет связи</span>
      <span id="devices-online" class="pill">колонок онлайн: 0</span>
      <span id="reconnects" class="pill muted">переподключений: 0</span>
    </div>
  </header>

  <section class="card">
    <h2>Цепочка</h2>
    <svg id="pipeline" viewBox="0 0 900 120" role="img" aria-label="Этапы обработки хода"></svg>
  </section>

  <main class="grid">
    <section class="card" id="emulator"><h2>Эмулятор колонки</h2><p class="muted">Загрузка…</p></section>
    <section class="card">
      <h2>Сводка <span class="muted">(последние 100 ходов)</span></h2>
      <table class="summary" id="summary"></table>
      <h2>Колонки</h2>
      <ul id="devices" class="devices"></ul>
    </section>
  </main>

  <section class="card">
    <h2>Ходы</h2>
    <ol id="turns" class="turns"></ol>
  </section>
</body>
</html>
```

- [ ] **Step 2: Write `app.css`**

```css
:root {
  --bg: #0f1115; --card: #171a21; --line: #262b36; --text: #e6e8ee; --muted: #8b93a7;
  --ok: #3ecf8e; --bad: #ff5d5d; --warn: #f5b942; --accent: #6ea8ff;
  --stt: #6ea8ff; --llm: #b38bff; --tts: #3ecf8e;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; padding: 16px; }
h1 { font-size: 20px; margin: 0; } h2 { font-size: 15px; margin: 0 0 12px; }
.muted { color: var(--muted); font-weight: normal; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.status { display: flex; gap: 8px; flex-wrap: wrap; }
.pill { border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px; font-size: 12px; }
.pill.ok { border-color: var(--ok); color: var(--ok); } .pill.bad { border-color: var(--bad); color: var(--bad); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid > .card { margin-bottom: 0; } .grid { margin-bottom: 16px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
#pipeline { width: 100%; height: auto; }
#pipeline .node rect { fill: #1e2330; stroke: var(--line); rx: 10; transition: fill .2s, stroke .2s; }
#pipeline .node.active rect { fill: #233251; stroke: var(--accent); }
#pipeline .node text { fill: var(--text); font-size: 13px; text-anchor: middle; }
#pipeline .edge { stroke: var(--line); stroke-width: 2; }
#pipeline .ms { fill: var(--muted); font-size: 12px; text-anchor: middle; }
table.summary { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
table.summary td, table.summary th { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: right; }
table.summary td:first-child, table.summary th:first-child { text-align: left; }
.devices { list-style: none; padding: 0; margin: 0; }
.devices li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--line); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--muted); }
.dot.on { background: var(--ok); }
.turns { list-style: none; padding: 0; margin: 0; }
.turns li { padding: 10px 0; border-bottom: 1px solid var(--line); }
.turn-head { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; }
.turn-text { margin: 4px 0; } .turn-text b { color: var(--muted); font-weight: normal; }
.turn.error .turn-head, .turn.aborted .turn-head { color: var(--bad); }
.waterfall { position: relative; height: 12px; background: #11141a; border-radius: 6px; overflow: hidden; }
.waterfall span { position: absolute; top: 0; bottom: 0; }
.waterfall .stt { background: var(--stt); } .waterfall .llm { background: var(--llm); } .waterfall .tts { background: var(--tts); }
.waterfall .first { width: 2px; background: var(--warn); }
.legend { display: flex; gap: 12px; font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
button.talk { width: 100%; padding: 18px; font-size: 16px; border-radius: 12px; border: 1px solid var(--accent); background: #1b2742; color: var(--text); cursor: pointer; user-select: none; touch-action: none; }
button.talk.down { background: var(--accent); color: #0b1020; }
button.talk:disabled { opacity: .5; cursor: not-allowed; }
.chat { margin-top: 12px; max-height: 220px; overflow: auto; }
.chat p { margin: 4px 0; } .chat .me { color: var(--accent); } .chat .bot { color: var(--ok); }
.note { color: var(--warn); }
```

- [ ] **Step 3: Write `app.js`**

```js
const STAGES = [
  { id: "device", label: "🎙 Колонка" },
  { id: "vad", label: "〰 VAD" },
  { id: "stt", label: "📝 STT" },
  { id: "llm", label: "🧠 LLM" },
  { id: "tts", label: "🔊 TTS" },
  { id: "out", label: "🎧 Ответ" },
];
const STATE_RU = { idle: "ожидание", listening: "слушает", thinking: "думает", speaking: "говорит" };
const STATUS_RU = { active: "идёт", ok: "ok", error: "ошибка", aborted: "прерван" };
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmtMs = (ms) => (ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} с` : `${ms} мс`);

let state = { link: { up: false, reconnects: 0 }, devices: [], turns: [], summary: {} };

function drawPipeline() {
  const svg = $("#pipeline");
  const w = 900 / STAGES.length;
  svg.innerHTML = STAGES.map((s, i) => {
    const x = i * w + 10;
    const cx = x + (w - 40) / 2;
    const edge = i < STAGES.length - 1
      ? `<line class="edge" x1="${x + w - 40}" y1="55" x2="${x + w + 10}" y2="55"/>`
      : "";
    return `<g class="node" id="node-${s.id}"><rect x="${x}" y="30" width="${w - 40}" height="50"/><text x="${cx}" y="60">${s.label}</text><text class="ms" id="ms-${s.id}" x="${cx}" y="100"></text></g>${edge}`;
  }).join("");
}

function activate(stageIds) {
  for (const s of STAGES) $(`#node-${s.id}`)?.classList.toggle("active", stageIds.includes(s.id));
}

function showStageTimings(turn) {
  const set = (id, text) => { const el = $(`#ms-${id}`); if (el) el.textContent = text; };
  set("device", turn.utterance_secs ? `фраза ${turn.utterance_secs.toFixed(1)} с` : "");
  set("stt", turn.stt_ms ? fmtMs(turn.stt_ms) : "");
  set("llm", turn.llm_ms ? fmtMs(turn.llm_ms) : "");
  set("tts", turn.tts_ms ? fmtMs(turn.tts_ms) : "");
  set("out", turn.first_audio_ms ? `до звука ${fmtMs(turn.first_audio_ms)}` : "");
}

function renderHeader() {
  const link = $("#link-status");
  link.textContent = state.link.up ? "мозг: на связи" : "мозг: нет связи";
  link.className = `pill ${state.link.up ? "ok" : "bad"}`;
  $("#devices-online").textContent = `колонок онлайн: ${state.devices.filter((d) => d.online).length}`;
  $("#reconnects").textContent = `переподключений: ${state.link.reconnects}`;
}

function renderSummary() {
  const s = state.summary || {};
  const row = (name, st) => `<tr><td>${name}</td><td>${fmtMs(st?.median_ms)}</td><td>${fmtMs(st?.p95_ms)}</td></tr>`;
  $("#summary").innerHTML =
    `<tr><th>этап</th><th>медиана</th><th>p95</th></tr>` +
    row("до первого звука", s.first_audio) + row("STT", s.stt) + row("LLM", s.llm) + row("TTS", s.tts) + row("весь ход", s.total) +
    `<tr><td>ходов / ошибок</td><td colspan="2">${s.turns ?? 0} / ${s.errors ?? 0}</td></tr>`;
}

function renderDevices() {
  $("#devices").innerHTML = state.devices.length
    ? state.devices.map((d) => `<li><span><span class="dot ${d.online ? "on" : ""}"></span>${esc(d.device_id)}</span><span class="muted">${d.online ? STATE_RU[d.state] ?? d.state : "офлайн"}</span></li>`).join("")
    : `<li class="muted">Нет колонок</li>`;
}

function waterfall(t) {
  const total = t.total_ms || (t.stt_ms + t.llm_ms + t.tts_ms) || 1;
  const pct = (ms) => `${Math.min(100, (ms / total) * 100)}%`;
  let left = 0;
  const seg = (cls, ms) => { const html = ms ? `<span class="${cls}" style="left:${pct(left)};width:${pct(ms)}"></span>` : ""; left += ms; return html; };
  const first = t.first_audio_ms ? `<span class="first" style="left:${pct(t.first_audio_ms)}"></span>` : "";
  return `<div class="waterfall">${seg("stt", t.stt_ms)}${seg("llm", t.llm_ms)}${seg("tts", t.tts_ms)}${first}</div>`;
}

function renderTurns() {
  const legend = `<div class="legend"><span><i style="background:var(--stt)"></i>STT</span><span><i style="background:var(--llm)"></i>LLM</span><span><i style="background:var(--tts)"></i>TTS</span><span><i style="background:var(--warn)"></i>первый звук</span></div>`;
  $("#turns").innerHTML = state.turns.length
    ? legend + state.turns.map((t) => `
      <li class="turn ${t.status}">
        <div class="turn-head"><span>${new Date(t.started_at).toLocaleTimeString("ru-RU")} · ${esc(t.device_id)}</span>
          <span>${STATUS_RU[t.status] ?? t.status} · до звука ${fmtMs(t.first_audio_ms)} · всего ${fmtMs(t.total_ms)}</span></div>
        <div class="turn-text"><b>Сіз:</b> ${esc(t.transcript) || "…"}</div>
        <div class="turn-text"><b>Айдос:</b> ${esc(t.reply_text) || "…"}</div>
        ${t.status === "active" ? "" : waterfall(t)}
      </li>`).join("")
    : `<li class="muted">Ходов пока нет — скажите что-нибудь в эмулятор или колонку.</li>`;
}

function renderAll() { renderHeader(); renderSummary(); renderDevices(); renderTurns(); }

function upsertTurn(turn) {
  const i = state.turns.findIndex((t) => t.turn_id === turn.turn_id);
  if (i >= 0) state.turns[i] = turn; else state.turns.unshift(turn);
  state.turns = state.turns.slice(0, 100);
}

async function resync() {
  const res = await fetch("/api/state");
  if (res.ok) { state = await res.json(); renderAll(); }
}

function onEvent(ev) {
  switch (ev.type) {
    case "resync": return void resync();
    case "link": state.link = ev.link; renderHeader(); return;
    case "device": {
      const i = state.devices.findIndex((d) => d.device_id === ev.device.device_id);
      if (i >= 0) state.devices[i] = ev.device; else state.devices.push(ev.device);
      renderDevices(); renderHeader(); return;
    }
    case "turn_started": upsertTurn(ev.turn); activate(["device", "vad", "stt"]); renderTurns(); return;
    case "transcript": {
      const t = state.turns.find((x) => x.turn_id === ev.turn_id);
      if (t) t.transcript = ev.text;
      activate(["llm"]); renderTurns(); return;
    }
    case "speech": {
      const t = state.turns.find((x) => x.turn_id === ev.turn_id);
      if (t) { t.reply_text = t.reply_text ? `${t.reply_text} ${ev.text}` : ev.text; t.first_audio_ms ??= ev.first_audio_ms; }
      activate(["tts", "out"]); renderTurns(); return;
    }
    case "turn_end":
      upsertTurn(ev.turn); activate([]); showStageTimings(ev.turn);
      void fetch("/api/state").then((r) => r.json()).then((s) => { state.summary = s.summary; renderSummary(); });
      renderTurns(); return;
  }
}

function connectEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  es.onopen = () => void resync();
}

async function loadEmulator() {
  const root = $("#emulator");
  try {
    const mod = await import("/emulator.js");
    if (typeof mod.initEmulator !== "function") throw new Error("no initEmulator");
    mod.initEmulator(root);
  } catch {
    root.innerHTML = `<h2>Эмулятор колонки</h2><p class="note">Эмулятор недоступен.</p>`;
  }
}

drawPipeline();
renderAll();
connectEvents();
loadEmulator();
```
Each node shows its own last-turn duration under its label (VAD has no separate timing; `Ответ` shows time to first audio).

- [ ] **Step 4: Verify**

Run: `cd gateway && cargo test` (the static-page e2e test still passes; `include_str!` picks up the new files) and `cargo build --release`.
Open the page in the built-in browser against a gateway started with `GATEWAY_EMULATOR_DEVICE=web-emulator` and a fake or real brain; check: no console errors, header shows link state, an e2e-driven turn (Task 7's `send_wav`, or run any e2e test against it) appears in the feed live. Record what you checked in the report.

- [ ] **Step 5: Commit**

```bash
git add gateway/web
git commit -m "feat(gateway): dashboard page with live pipeline, summary and turn waterfall"
```

---

### Task 6: Browser speaker emulator

**Files:**
- Replace: `gateway/web/emulator.js`

**Interfaces:**
- Consumes: `GET /api/emulator` → `{device_id, token, ws_url}`; `/ws?token=` (Task 4); xiaozhi JSON messages `hello`, `listen`, `stt`, `tts{start|sentence_start|stop}`.
- Produces: `export function initEmulator(root: HTMLElement): void`.

- [ ] **Step 1: Write `emulator.js`**

```js
const UP_RATE = 16000;
const DOWN_RATE = 24000;
const FRAME = 960; // 60 ms at 16 kHz

const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
}
registerProcessor("tap", Tap);`;

async function supported() {
  if (!("AudioEncoder" in window) || !("AudioDecoder" in window)) return false;
  const enc = await AudioEncoder.isConfigSupported({ codec: "opus", sampleRate: UP_RATE, numberOfChannels: 1, bitrate: 24000 });
  const dec = await AudioDecoder.isConfigSupported({ codec: "opus", sampleRate: DOWN_RATE, numberOfChannels: 1 });
  return Boolean(enc.supported && dec.supported);
}

function downsample(input, fromRate) {
  const ratio = fromRate / UP_RATE;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) out[i] = input[Math.floor(i * ratio)];
  return out;
}

export function initEmulator(root) {
  root.innerHTML = `
    <h2>Эмулятор колонки</h2>
    <button class="talk" id="talk" disabled>🎙 Удерживай и говори</button>
    <p class="muted" id="emu-status">Подключение…</p>
    <div class="chat" id="chat"></div>`;
  const talk = root.querySelector("#talk");
  const status = (text, cls = "muted") => { const el = root.querySelector("#emu-status"); el.textContent = text; el.className = cls; };
  const say = (who, text) => {
    const chat = root.querySelector("#chat");
    chat.insertAdjacentHTML("beforeend", `<p class="${who === "Сіз" ? "me" : "bot"}">${who}: ${text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c])}</p>`);
    chat.scrollTop = chat.scrollHeight;
  };
  start().catch((err) => status(`Ошибка эмулятора: ${err.message}`, "note"));

  async function start() {
    if (!(await supported())) {
      status("Браузер не поддерживает Opus в WebCodecs — откройте панель в Chrome.", "note");
      return;
    }
    const info = await (await fetch("/api/emulator")).json();
    const ws = new WebSocket(`${location.origin.replace(/^http/, "ws")}${info.ws_url}?token=${encodeURIComponent(info.token)}`);
    ws.binaryType = "arraybuffer";

    const ctx = new AudioContext();
    let playAt = 0;
    const decoder = new AudioDecoder({
      output: (data) => {
        const pcm = new Float32Array(data.numberOfFrames);
        data.copyTo(pcm, { planeIndex: 0, format: "f32-planar" });
        data.close();
        const buf = ctx.createBuffer(1, pcm.length, DOWN_RATE);
        buf.copyToChannel(pcm, 0);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        playAt = Math.max(playAt, ctx.currentTime + 0.05);
        src.start(playAt);
        playAt += buf.duration;
      },
      error: (e) => status(`Ошибка декодера: ${e.message}`, "note"),
    });
    decoder.configure({ codec: "opus", sampleRate: DOWN_RATE, numberOfChannels: 1 });
    let downTs = 0;

    const encoder = new AudioEncoder({
      output: (chunk) => {
        const bytes = new Uint8Array(chunk.byteLength);
        chunk.copyTo(bytes);
        if (ws.readyState === WebSocket.OPEN) ws.send(bytes);
      },
      error: (e) => status(`Ошибка кодера: ${e.message}`, "note"),
    });
    encoder.configure({ codec: "opus", sampleRate: UP_RATE, numberOfChannels: 1, bitrate: 24000, opus: { frameDuration: 60000 } });
    let upTs = 0;
    let pending = new Float32Array(0);
    let recording = false;
    let session = "";

    ws.onopen = () => ws.send(JSON.stringify({ type: "hello", version: 1, transport: "websocket", audio_params: { format: "opus", sample_rate: UP_RATE, channels: 1, frame_duration: 60 } }));
    ws.onclose = () => { talk.disabled = true; status("Соединение закрыто — обновите страницу.", "note"); };
    ws.onmessage = (m) => {
      if (typeof m.data !== "string") {
        decoder.decode(new EncodedAudioChunk({ type: "key", timestamp: downTs, data: new Uint8Array(m.data) }));
        downTs += 60000;
        return;
      }
      const msg = JSON.parse(m.data);
      if (msg.type === "hello") { session = msg.session_id; talk.disabled = false; status("Готов. Удерживайте кнопку или пробел."); }
      else if (msg.type === "stt") { say("Сіз", msg.text); status("Думаю…"); }
      else if (msg.type === "tts" && msg.state === "sentence_start") { say("Айдос", msg.text); status("Говорю…"); }
      else if (msg.type === "tts" && msg.state === "stop") status("Готов. Удерживайте кнопку или пробел.");
    };

    let stream;
    let tapNode = null;
    async function micStart() {
      if (recording || talk.disabled) return;
      try {
        await ctx.resume();
        stream ??= await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false } });
      } catch {
        status("Нет доступа к микрофону — разрешите его в браузере.", "note");
        return;
      }
      if (!tapNode) {
        await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })));
        tapNode = new AudioWorkletNode(ctx, "tap");
        ctx.createMediaStreamSource(stream).connect(tapNode);
        tapNode.port.onmessage = (e) => { if (recording) feed(downsample(e.data, ctx.sampleRate)); };
      }
      recording = true;
      talk.classList.add("down");
      ws.send(JSON.stringify({ session_id: session, type: "listen", state: "start", mode: "manual" }));
      status("Слушаю…");
    }

    function feed(samples) {
      const merged = new Float32Array(pending.length + samples.length);
      merged.set(pending);
      merged.set(samples, pending.length);
      let off = 0;
      while (merged.length - off >= FRAME) {
        const frame = merged.slice(off, off + FRAME);
        encoder.encode(new AudioData({ format: "f32", sampleRate: UP_RATE, numberOfFrames: FRAME, numberOfChannels: 1, timestamp: upTs, data: frame }));
        upTs += 60000;
        off += FRAME;
      }
      pending = merged.slice(off);
    }

    async function micStop() {
      if (!recording) return;
      recording = false;
      talk.classList.remove("down");
      pending = new Float32Array(0);
      await encoder.flush();
      ws.send(JSON.stringify({ session_id: session, type: "listen", state: "stop" }));
      status("Отправлено, думаю…");
    }

    talk.addEventListener("pointerdown", (e) => { e.preventDefault(); void micStart(); });
    for (const ev of ["pointerup", "pointerleave", "pointercancel"]) talk.addEventListener(ev, () => void micStop());
    window.addEventListener("keydown", (e) => { if (e.code === "Space" && !e.repeat && e.target === document.body) { e.preventDefault(); void micStart(); } });
    window.addEventListener("keyup", (e) => { if (e.code === "Space") void micStop(); });
  }
}
```

- [ ] **Step 2: Verify**

Run: `cd gateway && cargo build --release && cargo test`.
Manual check list (record results in the report):
1. Chrome on the Mac, real brain + gateway running: hold the button, say «Сағат неше?», release → chat shows «Сіз: …» and «Айдос: …», answer audible, the turn appears in the feed with a waterfall.
2. Deny mic permission → message «Нет доступа к микрофону…», rest of the page works.
3. Safari: if `isConfigSupported` is false → message about Chrome; dashboard works.
4. Stop the brain mid-turn → emulator returns to «Готов», feed shows the turn as error, header red.
If item 1 cannot be performed by the implementer (no microphone access in the agent environment), say so and leave it for the controller/user.

- [ ] **Step 3: Commit**

```bash
git add gateway/web/emulator.js
git commit -m "feat(gateway): browser speaker emulator over xiaozhi protocol with WebCodecs Opus"
```

---

### Task 7: `send_wav` dev tool and README

**Files:**
- Create: `gateway/examples/send_wav.rs`
- Modify: `README.md`

**Interfaces:**
- Consumes: `/api/emulator` (token), `/ws?token=`, xiaozhi protocol.
- Produces: `cargo run --example send_wav -- <wav-16k-mono> [ws://127.0.0.1:8000]` — plays the role of a device: hello, listen start (manual), Opus frames of the WAV, listen stop; prints `stt`, sentences and the number of received audio frames; exits on `tts stop` (timeout 30 s).

- [ ] **Step 1: Write the example**

`gateway/examples/send_wav.rs`:
```rust
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let wav = args.next().ok_or_else(|| anyhow::anyhow!("usage: send_wav <file.wav> [http://127.0.0.1:8000]"))?;
    let base = args.next().unwrap_or_else(|| "http://127.0.0.1:8000".into());

    let info: serde_json::Value = {
        let host = base.trim_start_matches("http://");
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let mut s = tokio::net::TcpStream::connect(host).await?;
        s.write_all(format!("GET /api/emulator HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n").as_bytes()).await?;
        let mut raw = String::new();
        s.read_to_string(&mut raw).await?;
        serde_json::from_str(raw.split_once("\r\n\r\n").map(|(_, b)| b).unwrap_or(""))?
    };
    let token = info["token"].as_str().ok_or_else(|| anyhow::anyhow!("emulator disabled"))?;
    let url = format!("{}{}?token={token}", base.replacen("http", "ws", 1), info["ws_url"].as_str().unwrap_or("/ws"));
    let (mut ws, _) = tokio_tungstenite::connect_async(url).await?;

    let mut reader = hound::WavReader::open(&wav)?;
    anyhow::ensure!(reader.spec().sample_rate == 16000 && reader.spec().channels == 1, "need 16 kHz mono WAV");
    let pcm: Vec<i16> = reader.samples::<i16>().collect::<Result<_, _>>()?;

    ws.send(Message::Text(r#"{"type":"hello","version":1,"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}"#.into())).await?;
    let session = loop {
        if let Some(Message::Text(t)) = ws.next().await.transpose()? {
            let v: serde_json::Value = serde_json::from_str(t.as_str())?;
            if v["type"] == "hello" { break v["session_id"].as_str().unwrap_or_default().to_string(); }
        }
    };
    ws.send(Message::Text(format!(r#"{{"session_id":"{session}","type":"listen","state":"start","mode":"manual"}}"#).into())).await?;
    let mut enc = opus::Encoder::new(16000, opus::Channels::Mono, opus::Application::Voip)?;
    let mut buf = vec![0u8; 4000];
    for chunk in pcm.chunks(960).filter(|c| c.len() == 960) {
        let n = enc.encode(chunk, &mut buf)?;
        ws.send(Message::Binary(buf[..n].to_vec().into())).await?;
        tokio::time::sleep(Duration::from_millis(60)).await;
    }
    ws.send(Message::Text(format!(r#"{{"session_id":"{session}","type":"listen","state":"stop"}}"#).into())).await?;
    let started = std::time::Instant::now();

    let mut frames = 0;
    tokio::time::timeout(Duration::from_secs(30), async {
        while let Some(msg) = ws.next().await {
            match msg? {
                Message::Binary(_) => frames += 1,
                Message::Text(t) => {
                    let v: serde_json::Value = serde_json::from_str(t.as_str())?;
                    match (v["type"].as_str(), v["state"].as_str()) {
                        (Some("stt"), _) => println!("Сіз: {}  (+{} мс)", v["text"], started.elapsed().as_millis()),
                        (Some("tts"), Some("sentence_start")) => println!("Айдос: {}  (+{} мс)", v["text"], started.elapsed().as_millis()),
                        (Some("tts"), Some("stop")) => break,
                        _ => {}
                    }
                }
                _ => {}
            }
        }
        anyhow::Ok(())
    })
    .await??;
    println!("кадров ответа: {frames} (~{:.1} с), всего {} мс", frames as f32 * 0.06, started.elapsed().as_millis());
    Ok(())
}
```
`anyhow`, `opus`, `serde_json`, `tokio`, `futures-util` are normal deps; `hound` and `tokio-tungstenite` are dev-deps — examples can use dev-deps.

- [ ] **Step 2: Verify**

Run: `cd gateway && cargo build --examples` and, against a running gateway + brain: `cargo run --example send_wav -- tests/fixtures/speech_16k.wav`. Expected: prints «Сіз: …», at least one «Айдос: …», frame count > 0; the turn shows up at `http://127.0.0.1:8000/`. If no live gateway + brain is running in the implementer's environment, verify only `cargo build --examples` and say so in the report; the controller runs it against the live stack.

- [ ] **Step 3: README section**

Add to `README.md` a section «Панель и эмулятор колонки»: how to start (`make brain`, `make gateway`), open `http://127.0.0.1:8000/`, what each block shows, emulator requirements (Chrome, mic permission), `cargo run --example send_wav -- gateway/tests/fixtures/speech_16k.wav`, and that the dashboard is local-only (403 for non-loopback).

- [ ] **Step 4: Commit**

```bash
git add gateway/examples/send_wav.rs README.md
git commit -m "feat(gateway): send_wav dev client; docs: dashboard and emulator"
```
