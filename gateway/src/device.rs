use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tokio::time::MissedTickBehavior;

use crate::audio::{self, DownEncoder, UpDecoder};
use crate::link::{LinkHandle, event_turn_id};
use crate::metrics::{MetricsHub, TurnStatus};
use crate::music::MusicStream;
use crate::pb;
use crate::pb::brain_event::Kind;
use crate::vad::{Endpointer, SegmenterParams, SileroVad};
use crate::xiaozhi::{self, DeviceMsg, ListenState};

const LEAD_FRAMES: u32 = 2;
const MUSIC_AHEAD: usize = 3;

#[derive(Debug, Clone, Copy, PartialEq)]
enum State {
    Idle,
    Listening,
    Thinking,
    Speaking,
    Music,
}

impl State {
    fn label(self) -> &'static str {
        match self {
            State::Idle => "idle",
            State::Listening => "listening",
            State::Thinking => "thinking",
            State::Speaking => "speaking",
            State::Music => "music",
        }
    }
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
    hub: Arc<MetricsHub>,
    music: Option<Music>,
    pending_music: Option<(String, String)>,
    music_paused_for_turn: bool,
    music_user_paused: bool,
}

type MusicFrame = std::io::Result<Vec<i16>>;

/// ffmpeg is read by its own task so that `next_frame` (not cancel-safe) never races the
/// session's select loop. Dropping `frames` makes the task kill and reap ffmpeg.
struct Music {
    title: String,
    frames: mpsc::Receiver<MusicFrame>,
}

impl Music {
    fn spawn(url: &str, title: &str) -> std::io::Result<Music> {
        let stream = MusicStream::spawn(url, title)?;
        let (tx, frames) = mpsc::channel(MUSIC_AHEAD);
        tokio::spawn(pump_music(stream, tx));
        Ok(Music {
            title: title.to_string(),
            frames,
        })
    }
}

async fn pump_music(mut stream: MusicStream, tx: mpsc::Sender<MusicFrame>) {
    loop {
        let frame = tokio::select! {
            _ = tx.closed() => break,
            frame = stream.next_frame() => frame,
        };
        let item = match frame {
            Ok(Some(pcm)) => Ok(pcm),
            Ok(None) => break,
            Err(err) => Err(err),
        };
        let failed = item.is_err();
        if tx.send(item).await.is_err() || failed {
            break;
        }
    }
    stream.stop().await;
}

pub async fn run_device(
    socket: WebSocket,
    device_id: String,
    link: LinkHandle,
    silero_model: PathBuf,
    hub: Arc<MetricsHub>,
) {
    let session = match Session::new(device_id.clone(), link.clone(), &silero_model, hub) {
        Ok(s) => s,
        Err(err) => {
            tracing::error!(%err, device_id, "cannot start device session");
            return;
        }
    };
    let brain_rx = link.register(&device_id);
    tracing::info!(device_id, "device connected");
    session.run(socket, brain_rx).await;
    link.unregister(&device_id);
    tracing::info!(device_id, "device disconnected");
}

impl Session {
    fn new(
        device_id: String,
        link: LinkHandle,
        silero_model: &Path,
        hub: Arc<MetricsHub>,
    ) -> anyhow::Result<Self> {
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
            hub,
            music: None,
            pending_music: None,
            music_paused_for_turn: false,
            music_user_paused: false,
        })
    }

    fn set_state(&mut self, state: State) {
        if self.state != state {
            self.state = state;
            self.hub.device(&self.device_id, true, state.label());
        }
    }

    async fn run(
        mut self,
        socket: WebSocket,
        mut brain_rx: tokio::sync::mpsc::Receiver<pb::BrainEvent>,
    ) {
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
                // None: a newer session for this device took over the route.
                ev = brain_rx.recv() => match ev {
                    Some(ev) => self.on_brain(ev),
                    None => break,
                },
                frame = recv_music(&mut self.music), if self.wants_music_frame() => {
                    self.on_music_frame(frame);
                }
                _ = tick.tick() => {
                    self.budget = (self.budget + 1).min(LEAD_FRAMES + 1);
                    self.check_link();
                    if self.state == State::Idle && self.queue.is_empty() {
                        self.start_music();
                    }
                }
            }
            if self.flush(&mut tx).await.is_err() {
                break;
            }
        }

        self.music = None;
        if let Some(turn_id) = self.turn_id.take() {
            self.hub.turn_end(&turn_id, TurnStatus::Aborted, None);
            self.send_abort(turn_id);
        }
        // A closed receiver means a newer session for this device took over the route
        // and already reported it online.
        if !brain_rx.is_closed() {
            self.link.send(state_event(&self.device_id, false));
            self.hub.device(&self.device_id, false, "idle");
        }
    }

    async fn flush(
        &mut self,
        tx: &mut futures_util::stream::SplitSink<WebSocket, Message>,
    ) -> Result<(), axum::Error> {
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
                    tx.send(Message::Text(xiaozhi::tts_stop(&self.session_id).into()))
                        .await?;
                    self.turn_id = None;
                    self.tts_started = false;
                    // После barge-in через listen start колонка уже слушает — не сбрасываем её в Idle.
                    match self.state {
                        State::Thinking | State::Speaking => {
                            self.set_state(State::Idle);
                            self.start_music();
                        }
                        State::Music => self.set_state(State::Idle),
                        State::Idle | State::Listening => {}
                    }
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
            DeviceMsg::Hello { version, .. } => {
                if version != 1 {
                    tracing::warn!(
                        device_id = self.device_id,
                        version,
                        "only protocol v1 (raw Opus) is supported"
                    );
                }
                self.queue
                    .push_back(Out::Json(xiaozhi::server_hello(&self.session_id)));
                self.link.send(state_event(&self.device_id, true));
                self.hub.device(&self.device_id, true, self.state.label());
            }
            DeviceMsg::Listen {
                state: ListenState::Start,
                ..
            } => {
                self.interrupt();
                self.set_state(State::Listening);
                self.endpointer.reset();
            }
            DeviceMsg::Listen {
                state: ListenState::Detect,
                ..
            }
            | DeviceMsg::Abort { .. } => self.interrupt(),
            DeviceMsg::Listen {
                state: ListenState::Stop,
                ..
            } => {
                if self.state == State::Listening {
                    match self.endpointer.flush() {
                        Some(utterance) => self.send_utterance(utterance),
                        // The client shows "thinking" after listen stop until it gets tts stop.
                        None => {
                            self.set_state(State::Idle);
                            self.start_tts();
                            self.queue.push_back(Out::Stop);
                        }
                    }
                }
            }
            DeviceMsg::Other => {}
        }
    }

    // Без линка TurnEnd не придёт никогда — колонка зависла бы в Thinking/Speaking.
    // Если TurnEnd уже пришёл, Stop стоит в хвосте очереди за аудио — даём доиграть.
    fn check_link(&mut self) {
        if !matches!(self.state, State::Thinking | State::Speaking)
            || self.link.is_connected()
            || matches!(self.queue.back(), Some(Out::Stop))
        {
            return;
        }
        tracing::warn!(device_id = self.device_id, "brain link lost mid-turn");
        if let Some(turn_id) = self.turn_id.take() {
            self.hub.turn_end(&turn_id, TurnStatus::Error, None);
        }
        self.queue.clear();
        self.start_tts();
        self.queue.push_back(Out::Stop);
    }

    fn interrupt(&mut self) {
        if self.state == State::Music {
            self.pause_music();
            return;
        }
        if !matches!(self.state, State::Thinking | State::Speaking) {
            return;
        }
        if let Some(turn_id) = self.turn_id.take() {
            self.hub.turn_end(&turn_id, TurnStatus::Aborted, None);
            self.send_abort(turn_id);
        }
        self.queue.clear();
        self.queue.push_back(Out::Stop);
    }

    fn on_audio(&mut self, packet: &[u8]) {
        if packet.is_empty() || self.state != State::Listening {
            return;
        }
        let pcm = match self.decoder.decode(packet) {
            Ok(pcm) => pcm,
            Err(err) => {
                tracing::debug!(%err, "opus decode failed");
                return;
            }
        };
        if let Some(utterance) = self.endpointer.push(&pcm).into_iter().next() {
            self.send_utterance(utterance);
        }
    }

    fn send_utterance(&mut self, utterance: Vec<i16>) {
        let turn_id = uuid::Uuid::new_v4().to_string();
        self.hub.turn_started(
            &self.device_id,
            &turn_id,
            utterance.len() as f32 / audio::UP_RATE as f32,
        );
        self.set_state(State::Thinking);
        let sent = self.link.send(pb::GatewayEvent {
            kind: Some(pb::gateway_event::Kind::Utterance(pb::Utterance {
                device_id: self.device_id.clone(),
                turn_id: turn_id.clone(),
                pcm_s16le: audio::pcm_to_le_bytes(&utterance),
                sample_rate: audio::UP_RATE,
            })),
        });
        if sent {
            tracing::info!(
                device_id = self.device_id,
                turn_id,
                secs = utterance.len() as f32 / 16000.0,
                "utterance sent"
            );
            self.turn_id = Some(turn_id);
        } else {
            tracing::warn!(
                device_id = self.device_id,
                "brain unavailable, dropping utterance"
            );
            self.hub.turn_end(&turn_id, TurnStatus::Error, None);
            self.queue
                .push_back(Out::Json(xiaozhi::tts_start(&self.session_id)));
            self.queue.push_back(Out::Stop);
        }
    }

    fn on_brain(&mut self, ev: pb::BrainEvent) {
        if self.turn_id.as_deref() != event_turn_id(&ev) {
            return;
        }
        let turn_id = self.turn_id.clone().unwrap_or_default();
        match ev.kind {
            Some(Kind::Transcript(t)) => {
                self.hub.transcript(&turn_id, &t.text);
                self.queue
                    .push_back(Out::Json(xiaozhi::stt(&self.session_id, &t.text)));
            }
            Some(Kind::Speech(chunk)) => {
                if chunk.sample_rate == 0 {
                    tracing::warn!(
                        device_id = self.device_id,
                        "speech chunk without sample rate skipped"
                    );
                    return;
                }
                self.start_tts();
                self.set_state(State::Speaking);
                self.queue.push_back(Out::Json(xiaozhi::tts_sentence(
                    &self.session_id,
                    &chunk.text,
                )));
                let pcm = audio::resample(
                    &audio::pcm_from_le_bytes(&chunk.pcm_s16le),
                    chunk.sample_rate,
                    audio::DOWN_RATE,
                );
                self.hub.speech(
                    &turn_id,
                    &chunk.text,
                    pcm.len() as f32 / audio::DOWN_RATE as f32,
                );
                match self.encoder.encode_all(&pcm) {
                    Ok(packets) => self.queue.extend(packets.into_iter().map(Out::Audio)),
                    Err(err) => tracing::error!(%err, "opus encode failed"),
                }
            }
            Some(Kind::End(end)) => {
                let status = if end.error {
                    TurnStatus::Error
                } else {
                    TurnStatus::Ok
                };
                let timings = end.timings.map(|t| (t.stt_ms, t.llm_ms, t.tts_ms));
                self.hub.turn_end(&turn_id, status, timings);
                self.start_tts();
                self.queue.push_back(Out::Stop);
            }
            Some(Kind::Action(action)) => self.on_action(action),
            Some(Kind::Push(_)) | None => {
                tracing::debug!(device_id = self.device_id, "push ignored until M4");
            }
        }
    }

    fn on_action(&mut self, action: pb::Action) {
        use pb::action::Kind as A;
        match action.kind {
            Some(A::Play(p)) => {
                tracing::info!(device_id = self.device_id, title = p.title, "music queued");
                self.music = None;
                self.pending_music = Some((p.url, p.title));
                self.music_user_paused = false;
            }
            Some(A::Stop(_)) => {
                self.music = None;
                self.pending_music = None;
                self.music_paused_for_turn = false;
                self.music_user_paused = false;
            }
            Some(A::Pause(_)) => self.music_user_paused = true,
            Some(A::Resume(_)) => self.music_user_paused = false,
            None => {}
        }
    }

    /// Starts queued music or resumes music paused by a turn; the caller ensures
    /// the device is idle with nothing left to play.
    fn start_music(&mut self) {
        if let Some((url, title)) = self.pending_music.take() {
            match Music::spawn(&url, &title) {
                Ok(music) => {
                    tracing::info!(device_id = self.device_id, title, "music started");
                    self.music = Some(music);
                }
                Err(err) => {
                    tracing::error!(%err, device_id = self.device_id, url, "cannot start music");
                    return;
                }
            }
        } else if self.music.is_none() || !self.music_paused_for_turn || self.music_user_paused {
            return;
        }
        self.music_paused_for_turn = false;
        self.start_tts();
        self.set_state(State::Music);
    }

    fn pause_music(&mut self) {
        self.music_paused_for_turn = true;
        self.queue.retain(|out| !matches!(out, Out::Audio(_)));
        if !matches!(self.queue.back(), Some(Out::Stop)) {
            self.queue.push_back(Out::Stop);
        }
    }

    fn wants_music_frame(&self) -> bool {
        self.state == State::Music
            && !self.music_user_paused
            && self.music.is_some()
            && self
                .queue
                .iter()
                .filter(|out| matches!(out, Out::Audio(_)))
                .count()
                < MUSIC_AHEAD
    }

    fn on_music_frame(&mut self, frame: Option<MusicFrame>) {
        let title = || {
            self.music
                .as_ref()
                .map(|m| m.title.clone())
                .unwrap_or_default()
        };
        match frame
            .map(|f| f.and_then(|pcm| self.encoder.encode_all(&pcm).map_err(std::io::Error::other)))
        {
            Some(Ok(packets)) => {
                self.queue.extend(packets.into_iter().map(Out::Audio));
                return;
            }
            Some(Err(err)) => {
                tracing::warn!(%err, device_id = self.device_id, title = title(), "music failed")
            }
            None => tracing::info!(device_id = self.device_id, title = title(), "music ended"),
        }
        self.music = None;
        self.music_paused_for_turn = false;
        self.queue.push_back(Out::Stop);
    }

    fn start_tts(&mut self) {
        if !self.tts_started {
            self.tts_started = true;
            self.budget = LEAD_FRAMES;
            self.queue
                .push_back(Out::Json(xiaozhi::tts_start(&self.session_id)));
        }
    }

    fn send_abort(&self, turn_id: String) {
        self.link.send(pb::GatewayEvent {
            kind: Some(pb::gateway_event::Kind::Abort(pb::Abort {
                device_id: self.device_id.clone(),
                turn_id,
            })),
        });
    }
}

async fn recv_music(music: &mut Option<Music>) -> Option<MusicFrame> {
    match music {
        Some(m) => m.frames.recv().await,
        None => std::future::pending().await,
    }
}

fn state_event(device_id: &str, online: bool) -> pb::GatewayEvent {
    pb::GatewayEvent {
        kind: Some(pb::gateway_event::Kind::State(pb::DeviceState {
            device_id: device_id.to_string(),
            online,
        })),
    }
}
