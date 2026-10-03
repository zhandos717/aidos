use std::collections::VecDeque;
use std::path::{Path, PathBuf};
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

pub async fn run_device(
    socket: WebSocket,
    device_id: String,
    link: LinkHandle,
    silero_model: PathBuf,
) {
    let session = match Session::new(device_id.clone(), link.clone(), &silero_model) {
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
    fn new(device_id: String, link: LinkHandle, silero_model: &Path) -> anyhow::Result<Self> {
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
                Some(ev) = brain_rx.recv() => self.on_brain(ev),
                _ = tick.tick() => {
                    self.budget = (self.budget + 1).min(LEAD_FRAMES + 1);
                    self.check_link();
                }
            }
            if self.flush(&mut tx).await.is_err() {
                break;
            }
        }

        if let Some(turn_id) = self.turn_id.take() {
            self.send_abort(turn_id);
        }
        // A closed receiver means a newer session for this device took over the route
        // and already reported it online.
        if !brain_rx.is_closed() {
            self.link.send(state_event(&self.device_id, false));
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
                self.queue
                    .push_back(Out::Json(xiaozhi::server_hello(&self.session_id)));
                self.link.send(state_event(&self.device_id, true));
            }
            DeviceMsg::Listen {
                state: ListenState::Start,
                ..
            } => {
                self.interrupt();
                self.state = State::Listening;
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
                        None => self.state = State::Idle,
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
        self.turn_id = None;
        self.queue.clear();
        self.start_tts();
        self.queue.push_back(Out::Stop);
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
            self.queue
                .push_back(Out::Json(xiaozhi::tts_start(&self.session_id)));
            self.queue.push_back(Out::Stop);
        }
    }

    fn on_brain(&mut self, ev: pb::BrainEvent) {
        if self.turn_id.as_deref() != event_turn_id(&ev) {
            return;
        }
        match ev.kind {
            Some(Kind::Transcript(t)) => self
                .queue
                .push_back(Out::Json(xiaozhi::stt(&self.session_id, &t.text))),
            Some(Kind::Speech(chunk)) => {
                if chunk.sample_rate == 0 {
                    tracing::warn!(
                        device_id = self.device_id,
                        "speech chunk without sample rate skipped"
                    );
                    return;
                }
                self.start_tts();
                self.state = State::Speaking;
                self.queue.push_back(Out::Json(xiaozhi::tts_sentence(
                    &self.session_id,
                    &chunk.text,
                )));
                let pcm = audio::resample(
                    &audio::pcm_from_le_bytes(&chunk.pcm_s16le),
                    chunk.sample_rate,
                    audio::DOWN_RATE,
                );
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
                tracing::debug!(
                    device_id = self.device_id,
                    "action/push ignored until M4/M5"
                );
            }
        }
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

fn state_event(device_id: &str, online: bool) -> pb::GatewayEvent {
    pb::GatewayEvent {
        kind: Some(pb::gateway_event::Kind::State(pb::DeviceState {
            device_id: device_id.to_string(),
            online,
        })),
    }
}
