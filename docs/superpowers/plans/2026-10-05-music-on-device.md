# Music on Device (M5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** «Димаш ойна» on a speaker or the browser emulator plays the music on that device (not on the Mac), with pause during a conversation and resume after it.

**Architecture:** Brain agents record device actions in a per-turn ContextVar list; `TurnRunner` sends them as `BrainEvent.action` after the spoken reply. The gateway starts music after the reply finishes: `ffmpeg` decodes the URL to PCM 24 kHz mono, the gateway encodes 60 ms Opus frames and paces them inside `tts start … tts stop`. Barge-in pauses (stop reading ffmpeg), the end of the next turn resumes unless it stopped the music.

**Spec:** `docs/superpowers/specs/2026-10-03-aidos-satellite-gateway-design.md` §5 «Музыка»; dashboard spec `docs/superpowers/specs/2026-10-05-aidos-dashboard-design.md`.

## Global Constraints

- Branch `zhanzh/satellite-gateway`; commits without `Co-Authored-By`, no AI mentions; few comments; Kazakh-style Python logs.
- Python via `/Users/zhandoszhandarbek/PycharmProjects/aidos/.venv/bin/python`; ruff must pass.
- Text/UI mode on the Mac (no `current_device`) keeps the current `ffplay` behaviour unchanged.
- ffmpeg command: `ffmpeg -nostdin -loglevel error [-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 for http(s) URLs] -i <url> -f s16le -ar 24000 -ac 1 pipe:1`; binary from env `FFMPEG` (default `ffmpeg`); child killed on stop/replace/session end (`kill_on_drop(true)`).
- Music frames: 1440 samples (60 ms at 24 kHz), last partial frame zero-padded; never buffer more than 3 audio frames ahead in the device queue.
- Do not stop the running brain (:50051) / gateway (:8000); use other ports for manual runs.

## Review Focus

- Barge-in during music: device gets `tts stop` immediately, no music frames while listening; after the turn music resumes unless that turn issued `stop` — pinned in Task 3 e2e `music_pauses_on_barge_in_and_resumes`.
- `stop` command while music plays: ffmpeg child is killed (no zombie), device returns to idle — Task 3 e2e `music_stop_action_ends_stream` + Task 2 unit `stop_kills_child`.
- Bad URL / ffmpeg missing: logged, device back to idle, session survives — Task 2 unit `spawn_bad_url_ends_quickly`, Task 3 handles `Ok(None)`/`Err`.
- Device disconnects while music plays: ffmpeg is killed — Task 3 (Drop/kill_on_drop) checked in review.
- New `play` while music plays replaces the stream — Task 3 e2e asserts only one stream (frames continue, no duplicate tts start bursts).

---

### Task 1: Brain device actions

**Files:** `src/aidos/core/device_ctx.py`, `src/aidos/agents/music_agent.py`, `src/aidos/brain/turn.py`; tests `tests/test_music_actions.py`, `tests/test_turn.py`.

**Produces:**
```python
# src/aidos/core/device_ctx.py
@dataclass(frozen=True)
class DeviceAction:
    kind: str          # "play" | "stop" | "pause" | "resume"
    url: str = ""
    title: str = ""

turn_actions: ContextVar[list[DeviceAction] | None] = ContextVar("turn_actions", default=None)

def emit_action(kind: str, url: str = "", title: str = "") -> bool:
    """Ағымдағы ходқа колонка әрекетін қосады; колонка ходы болмаса False."""
    actions = turn_actions.get()
    if actions is None:
        return False
    actions.append(DeviceAction(kind, url, title))
    return True
```
- `MusicAgent.handle`: if `current_device.get()` is set → never touch ffplay/subprocess:
  - stop → `emit_action("stop")`, return `"Музыка тоқтатылды."`; pause → `emit_action("pause")`, `"Музыка кідіртілді."`; resume → `emit_action("resume")`, `"Музыка жалғастырылды."`;
  - play → `result = _get_stream_url(query)`; None → `"Музыка табылмады."`; else `emit_action("play", url, title)` → `f"Ойнатылуда: {title}"`. No local-file fallback for devices.
  - otherwise the existing code path (unchanged).
- `TurnRunner.run`: before calling `respond`, `actions: list[DeviceAction] = []; turn_actions.set(actions)` (asyncio.to_thread copies the context; the list object is shared). After the speech loop and before `_end`, for each action yield `link_pb2.BrainEvent(action=link_pb2.Action(device_id, turn_id, play=link_pb2.PlayStream(url, title)))`, or `stop=link_pb2.Empty()` / `pause=…` / `resume=…`. Actions are sent even if no speech was synthesized; `error` of TurnEnd stays `spoken == 0`.

- [ ] Tests first (`tests/test_music_actions.py`): with `current_device` and `turn_actions` set inside `contextvars.copy_context().run`, monkeypatch `aidos.agents.music_agent._get_stream_url` → `("https://x/a", "Song")` and `subprocess.Popen` → raise AssertionError; `handle("Димаш ойна")` → `"Ойнатылуда: Song"` and actions == `[DeviceAction("play","https://x/a","Song")]`; `handle("тоқтат")` → stop action; no device → `emit_action` returns False and the Mac path is used (monkeypatch Popen with a fake object exposing `poll/wait/terminate/kill`). In `tests/test_turn.py`: respond callable calls `emit_action("play","https://x/a","Song")` and returns `"Ойнатылуда: Song."` → event kinds end with `[..., "speech", "action", "end"]`, `events[-2].action.play.url == "https://x/a"`.
- [ ] Implement, run `pytest -q` and `ruff check src/ tests/`, commit `feat(brain): music on device via turn actions`.

### Task 2: Gateway `music.rs` (ffmpeg stream)

**Files:** create `gateway/src/music.rs`, modify `gateway/src/lib.rs`, `.github/workflows/ci.yml` (add `ffmpeg` to the gateway job's apt-get line).

**Produces:**
```rust
pub struct MusicStream { /* child, stdout, title, done */ }
impl MusicStream {
    pub fn spawn(url: &str, title: &str) -> std::io::Result<MusicStream>;   // tokio::process, kill_on_drop(true)
    pub fn title(&self) -> &str;
    /// Next 1440-sample frame; zero-pads the final partial frame; Ok(None) at EOF.
    pub async fn next_frame(&mut self) -> std::io::Result<Option<Vec<i16>>>;
    pub async fn stop(mut self);  // start_kill + wait
}
```
- [ ] Tests (unit, `#[tokio::test]`, skip with a printed note if `ffmpeg` is not on PATH): spawn on `gateway/tests/fixtures/speech_16k.wav` (3.0 s) → frame count between 49 and 51, each 1440 samples, then `Ok(None)`; `stop_kills_child` (spawn, read one frame, stop, assert the child has exited via `try_wait`-style check exposed under `#[cfg(test)]`); `spawn_bad_url_ends_quickly` (`/nonexistent.wav` → `next_frame` returns `Ok(None)` or `Err` within 5 s).
- [ ] Implement (read with `read_exact` semantics handling short reads at EOF), `cargo test`, fmt, clippy; commit `feat(gateway): ffmpeg-backed music stream`.

### Task 3: Device integration + e2e

**Files:** `gateway/src/device.rs`, `gateway/tests/e2e.rs`.

**Behaviour:**
- New `State::Music` (label `"music"`). Session fields: `music: Option<MusicStream>`, `pending_music: Option<(String, String)>`, `music_paused_for_turn: bool`, `music_user_paused: bool`.
- `on_brain` `Kind::Action(a)` (already turn-filtered): `Play(p)` → stop current music, `pending_music = Some((p.url, p.title))`; `Stop` → stop music, clear pending and flags; `Pause` → `music_user_paused = true`; `Resume` → `music_user_paused = false`.
- When a turn finishes (the `Out::Stop` of a Thinking/Speaking turn is flushed) and on every tick while Idle with an empty queue: if `pending_music` → spawn it (log + stay Idle on error), `start_tts()`, `set_state(Music)`, clear `music_paused_for_turn`; else if `music.is_some() && music_paused_for_turn && !music_user_paused` → `start_tts()`, `set_state(Music)`, clear the flag.
- Barge-in (`listen start` / `listen detect` / `abort`) while `State::Music`: queue `tts stop` immediately (clear queued music frames first), set `music_paused_for_turn = true`, keep the ffmpeg child (backpressure pauses it).
- Feeding: add a select branch active only when `state == Music && !music_user_paused && audio frames in queue < 3`, awaiting `music.next_frame()`: frame → resample not needed (already 24 kHz) → `encoder.encode_all` → push `Out::Audio`; `Ok(None)`/`Err` → stop music, queue `Out::Stop`, go Idle.
- `Out::Stop` flush handling: also leave `State::Music` → Idle when the stop ends the music stream.
- Session end: drop/stop music (ffmpeg killed).
- Metrics: `set_state` already mirrors state; music needs no TurnRecord.

**e2e (FakeBrain gets `music_url: Option<String>`; when set, after the Speech chunk it sends `Action{play url=<abs path of speech_16k.wav>, title="Test"}` then End; a second variant sends `Action{stop}`):**
- `music_plays_after_reply`: reply `tts start/sentence/frames/stop`, then music `tts start`, ≥ 40 frames, `tts stop`.
- `music_pauses_on_barge_in_and_resumes`: during music send `listen start` → receive `tts stop` and no binary frames for 300 ms while listening; send `listen stop` (short press, no speech) → receive `tts start/stop` of the empty turn, then music `tts start` and more frames.
- `music_stop_action_ends_stream`: start music, speak a turn whose brain reply carries `Action{stop}` → after that turn no further music `tts start`.
- [ ] Write e2e, see them fail, implement, `cargo test` (e2e 3×), fmt, clippy; commit `feat(gateway): stream music to devices with pause on barge-in`.

### Task 4: UI

**Files:** `gateway/web/app.js`, `gateway/web/emulator.js`.
- `app.js`: `STATE_RU.music = "играет музыку"`.
- `emulator.js`: on `tts start` when no turn is in progress (status was «Готов…») show «Играет музыка ♪»; drop incoming binary frames while recording (fixes playback over the user's speech); keep everything else.
- [ ] `cargo build --release`, open the page in the built-in browser against a test gateway (port ≠ 8000), no console errors; commit `feat(gateway): music state in dashboard and emulator`.
