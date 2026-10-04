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
    TurnStarted {
        turn: TurnRecord,
    },
    Transcript {
        turn_id: String,
        text: String,
    },
    Speech {
        turn_id: String,
        text: String,
        first_audio_ms: Option<u32>,
    },
    TurnEnd {
        turn: TurnRecord,
    },
    Device {
        device: DeviceView,
    },
    Link {
        link: LinkView,
    },
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
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn stat(mut values: Vec<u32>) -> Option<Stat> {
    if values.is_empty() {
        return None;
    }
    values.sort_unstable();
    let rank = |p: f64| values[((p * values.len() as f64).ceil() as usize).max(1) - 1];
    Some(Stat {
        median_ms: rank(0.5),
        p95_ms: rank(0.95),
    })
}

pub fn summarize(turns: &[TurnRecord]) -> Summary {
    let ok: Vec<&TurnRecord> = turns
        .iter()
        .filter(|t| t.status == TurnStatus::Ok)
        .collect();
    let pick = |f: fn(&TurnRecord) -> Option<u32>| stat(ok.iter().filter_map(|t| f(t)).collect());
    Summary {
        turns: turns.len(),
        errors: turns
            .iter()
            .filter(|t| t.status == TurnStatus::Error)
            .count(),
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

    pub fn subscribe(&self) -> broadcast::Receiver<DashEvent> {
        self.tx.subscribe()
    }

    pub fn snapshot(&self) -> Snapshot {
        let inner = self.inner.lock().unwrap();
        let turns: Vec<TurnRecord> = inner.turns.iter().rev().cloned().collect();
        let mut devices: Vec<DeviceView> = inner.devices.values().cloned().collect();
        devices.sort_by(|a, b| a.device_id.cmp(&b.device_id));
        Snapshot {
            link: LinkView {
                up: inner.link_up,
                reconnects: inner.reconnects,
            },
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
            LinkView {
                up,
                reconnects: inner.reconnects,
            }
        };
        let _ = self.tx.send(DashEvent::Link { link: view });
    }

    pub fn device(&self, device_id: &str, online: bool, state: &str) {
        let view = DeviceView {
            device_id: device_id.to_string(),
            online,
            state: state.to_string(),
        };
        self.inner
            .lock()
            .unwrap()
            .devices
            .insert(device_id.to_string(), view.clone());
        let _ = self.tx.send(DashEvent::Device { device: view });
    }

    pub fn turn_started(&self, device_id: &str, turn_id: &str, utterance_secs: f32) {
        let turn = TurnRecord {
            turn_id: turn_id.to_string(),
            device_id: device_id.to_string(),
            started_at: now_ms(),
            utterance_secs,
            transcript: String::new(),
            reply_text: String::new(),
            stt_ms: 0,
            llm_ms: 0,
            tts_ms: 0,
            first_audio_ms: None,
            total_ms: None,
            reply_secs: 0.0,
            status: TurnStatus::Active,
        };
        {
            let mut inner = self.inner.lock().unwrap();
            if inner.turns.len() == MAX_TURNS
                && let Some(old) = inner.turns.pop_front()
            {
                inner.started.remove(&old.turn_id);
            }
            inner.turns.push_back(turn.clone());
            inner.started.insert(turn_id.to_string(), Instant::now());
        }
        let _ = self.tx.send(DashEvent::TurnStarted { turn });
    }

    pub fn transcript(&self, turn_id: &str, text: &str) {
        let found = self.update(turn_id, |t, _| t.transcript = text.to_string());
        if found.is_some() {
            let _ = self.tx.send(DashEvent::Transcript {
                turn_id: turn_id.to_string(),
                text: text.to_string(),
            });
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
                turn_id: turn_id.to_string(),
                text: text.to_string(),
                first_audio_ms: turn.first_audio_ms,
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
        let turn = inner
            .turns
            .iter_mut()
            .rev()
            .find(|t| t.turn_id == turn_id)?;
        if turn.status != TurnStatus::Active {
            return None;
        }
        f(turn, elapsed);
        Some(turn.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(status: TurnStatus, stt: u32) -> TurnRecord {
        TurnRecord {
            turn_id: "t".into(),
            device_id: "d".into(),
            started_at: 0,
            utterance_secs: 1.0,
            transcript: String::new(),
            reply_text: String::new(),
            stt_ms: stt,
            llm_ms: stt * 2,
            tts_ms: 10,
            first_audio_ms: Some(stt + 5),
            total_ms: Some(stt + 50),
            reply_secs: 1.0,
            status,
        }
    }

    #[test]
    fn nearest_rank_percentiles() {
        assert_eq!(stat(vec![]), None);
        assert_eq!(
            stat(vec![7]),
            Some(Stat {
                median_ms: 7,
                p95_ms: 7
            })
        );
        let values: Vec<u32> = (1..=20).collect();
        assert_eq!(
            stat(values),
            Some(Stat {
                median_ms: 10,
                p95_ms: 19
            })
        );
    }

    #[test]
    fn summary_counts_only_ok_turns_for_stats() {
        let turns = vec![
            record(TurnStatus::Ok, 100),
            record(TurnStatus::Error, 900),
            record(TurnStatus::Ok, 300),
        ];
        let s = summarize(&turns);
        assert_eq!((s.turns, s.errors), (3, 1));
        assert_eq!(
            s.stt,
            Some(Stat {
                median_ms: 100,
                p95_ms: 300
            })
        );
        assert_eq!(
            s.llm,
            Some(Stat {
                median_ms: 200,
                p95_ms: 600
            })
        );
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
        assert_eq!(
            kinds,
            ["turn_started", "transcript", "speech", "speech", "turn_end"]
        );
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
