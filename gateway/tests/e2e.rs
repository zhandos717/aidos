use std::collections::HashMap;
use std::path::Path;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use aidos_gateway::config::Config;
use aidos_gateway::link::LinkHandle;
use aidos_gateway::pb;
use aidos_gateway::pb::brain_event::Kind;
use aidos_gateway::server::AppState;
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
    states: Arc<Mutex<Vec<(String, bool)>>>,
    hold_first: bool,
    zero_rate_chunk: bool,
    kill: Arc<tokio::sync::Notify>,
}

#[tonic::async_trait]
impl pb::brain_server::Brain for FakeBrain {
    type LinkStream = Pin<Box<dyn Stream<Item = Result<pb::BrainEvent, Status>> + Send + 'static>>;

    async fn link(
        &self,
        req: Request<Streaming<pb::GatewayEvent>>,
    ) -> Result<Response<Self::LinkStream>, Status> {
        let mut inbound = req.into_inner();
        let (tx, rx) = mpsc::channel(64);
        let me = self.clone();
        tokio::spawn(async move {
            loop {
                let ev = tokio::select! {
                    ev = inbound.next() => match ev {
                        Some(Ok(ev)) => ev,
                        _ => break,
                    },
                    _ = me.kill.notified() => {
                        let _ = tx.send(Err(Status::unavailable("brain killed"))).await;
                        break;
                    }
                };
                match ev.kind {
                    Some(pb::gateway_event::Kind::Utterance(u)) => {
                        let first = {
                            let mut utterances = me.utterances.lock().unwrap();
                            utterances.push(u.pcm_s16le.len() / 2);
                            utterances.len() == 1
                        };
                        let ids = (u.device_id.clone(), u.turn_id.clone());
                        let send = |kind| tx.send(Ok(pb::BrainEvent { kind: Some(kind) }));
                        let _ = send(Kind::Transcript(pb::Transcript {
                            device_id: ids.0.clone(),
                            turn_id: ids.1.clone(),
                            text: "сәлем".into(),
                        }))
                        .await;
                        let pcm: Vec<u8> = vec![0u8; 22050 * REPLY_MS / 1000 * 2];
                        if me.zero_rate_chunk {
                            let _ = send(Kind::Speech(pb::SpeechChunk {
                                device_id: ids.0.clone(),
                                turn_id: ids.1.clone(),
                                text: "broken".into(),
                                pcm_s16le: pcm.clone(),
                                sample_rate: 0,
                            }))
                            .await;
                        }
                        let _ = send(Kind::Speech(pb::SpeechChunk {
                            device_id: ids.0.clone(),
                            turn_id: ids.1.clone(),
                            text: "Сәлем!".into(),
                            pcm_s16le: pcm,
                            sample_rate: 22050,
                        }))
                        .await;
                        if me.hold_first && first {
                            continue;
                        }
                        let _ = send(Kind::End(pb::TurnEnd {
                            device_id: ids.0,
                            turn_id: ids.1,
                            error: false,
                            timings: Some(pb::TurnTimings {
                                stt_ms: 900,
                                llm_ms: 1600,
                                tts_ms: 200,
                            }),
                        }))
                        .await;
                    }
                    Some(pb::gateway_event::Kind::Abort(a)) => {
                        me.aborts.lock().unwrap().push(a.turn_id)
                    }
                    Some(pb::gateway_event::Kind::State(st)) => {
                        me.states.lock().unwrap().push((st.device_id, st.online))
                    }
                    _ => {}
                }
            }
        });
        Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
    }
}

async fn start_brain(brain: FakeBrain) -> String {
    start_brain_killable(brain).await.0
}

async fn start_brain_killable(brain: FakeBrain) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let _ = tonic::transport::Server::builder()
            .add_service(pb::brain_server::BrainServer::new(brain))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await;
    });
    (format!("http://{addr}"), server)
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
        devices: HashMap::from([
            (DEVICE.to_string(), TOKEN.to_string()),
            ("web-emulator".to_string(), "emu-token".to_string()),
        ]),
        silero_model: Path::new(manifest).join("models/silero_vad.onnx"),
        tz_offset_min: 300,
        emulator_device: Some("web-emulator".into()),
    };
    let hub = aidos_gateway::metrics::MetricsHub::new();
    let link = LinkHandle::with_metrics(brain_addr, "link".into(), hub.clone());
    tokio::spawn(aidos_gateway::server::serve(
        listener,
        AppState {
            cfg: Arc::new(cfg),
            link: link.clone(),
            hub,
            emulator: Some(("web-emulator".into(), "emu-token".into())),
        },
    ));
    (format!("{addr}"), link)
}

async fn wait_link(link: &LinkHandle, up: bool) {
    for _ in 0..100 {
        if link.is_connected() == up {
            return;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    panic!("link never became {up}");
}

fn speech_packets() -> Vec<Vec<u8>> {
    opus_packets(16000 * 2)
}

fn opus_packets(trailing_silence: usize) -> Vec<Vec<u8>> {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let mut reader =
        hound::WavReader::open(Path::new(manifest).join("tests/fixtures/speech_16k.wav")).unwrap();
    let mut pcm: Vec<i16> = reader.samples::<i16>().map(Result::unwrap).collect();
    pcm.extend(vec![0i16; trailing_silence]);
    let mut enc = opus::Encoder::new(16000, opus::Channels::Mono, opus::Application::Voip).unwrap();
    let mut buf = vec![0u8; 4000];
    pcm.chunks(960)
        .filter(|c| c.len() == 960)
        .map(|c| {
            let n = enc.encode(c, &mut buf).unwrap();
            buf[..n].to_vec()
        })
        .collect()
}

type Ws =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

async fn connect(addr: &str, token: &str) -> Result<Ws, tokio_tungstenite::tungstenite::Error> {
    let mut req = format!("ws://{addr}/ws").into_client_request().unwrap();
    req.headers_mut()
        .insert("Authorization", format!("Bearer {token}").parse().unwrap());
    req.headers_mut()
        .insert("Device-Id", DEVICE.parse().unwrap());
    req.headers_mut()
        .insert("Protocol-Version", "1".parse().unwrap());
    tokio_tungstenite::connect_async(req)
        .await
        .map(|(ws, _)| ws)
}

async fn next_json(ws: &mut Ws) -> serde_json::Value {
    loop {
        match tokio::time::timeout(Duration::from_secs(15), ws.next())
            .await
            .unwrap()
            .unwrap()
            .unwrap()
        {
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
    listen_start(ws, session).await;
    send_speech(ws).await;
}

async fn listen_start(ws: &mut Ws, session: &str) {
    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"listen","state":"start","mode":"auto"}}"#)
            .into(),
    ))
    .await
    .unwrap();
}

fn reply_frames() -> usize {
    (24000 * REPLY_MS / 1000).div_ceil(1440)
}

async fn frames_until_stop(ws: &mut Ws) -> usize {
    let mut frames = 0;
    loop {
        match tokio::time::timeout(Duration::from_secs(5), ws.next())
            .await
            .unwrap()
            .unwrap()
            .unwrap()
        {
            Message::Binary(_) => frames += 1,
            Message::Text(t) => {
                let v: serde_json::Value = serde_json::from_str(t.as_str()).unwrap();
                assert_eq!(v["state"], "stop");
                return frames;
            }
            _ => {}
        }
    }
}

async fn send_speech(ws: &mut Ws) {
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
    assert_eq!(
        (stt["type"].as_str(), stt["text"].as_str()),
        (Some("stt"), Some("сәлем"))
    );
    assert_eq!(next_json(&mut ws).await["state"], "start");
    let sentence = next_json(&mut ws).await;
    assert_eq!(
        (sentence["state"].as_str(), sentence["text"].as_str()),
        (Some("sentence_start"), Some("Сәлем!"))
    );

    let started = Instant::now();
    let frames = frames_until_stop(&mut ws).await;
    let elapsed = started.elapsed();
    assert_eq!(frames, reply_frames());
    let paced = Duration::from_millis(60) * (frames as u32 - 3);
    assert!(
        elapsed >= paced,
        "{frames} frames in {elapsed:?}, expected >= {paced:?}"
    );
    let heard = brain.utterances.lock().unwrap()[0];
    assert!(
        heard > 16000 * 2 && heard < 16000 * 5,
        "utterance samples: {heard}"
    );
}

#[tokio::test]
async fn barge_in_aborts_turn() {
    let brain = FakeBrain {
        hold_first: true,
        ..FakeBrain::default()
    };
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["type"], "stt");
    assert_eq!(next_json(&mut ws).await["state"], "start");

    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"abort","reason":"wake_word_detected"}}"#)
            .into(),
    ))
    .await
    .unwrap();
    loop {
        let v = next_json(&mut ws).await;
        if v["state"] == "stop" {
            break;
        }
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
    let body = raw
        .split_once("\r\n\r\n")
        .map(|(_, b)| b.to_string())
        .unwrap_or_default();
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

#[tokio::test]
async fn barge_in_with_listen_start_keeps_listening() {
    let brain = FakeBrain {
        hold_first: true,
        ..FakeBrain::default()
    };
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["type"], "stt");
    assert_eq!(next_json(&mut ws).await["state"], "start");

    listen_start(&mut ws, &session).await;
    loop {
        if next_json(&mut ws).await["state"] == "stop" {
            break;
        }
    }
    send_speech(&mut ws).await;
    loop {
        if next_json(&mut ws).await["type"] == "stt" {
            break;
        }
    }
    assert_eq!(brain.utterances.lock().unwrap().len(), 2);
    assert_eq!(brain.aborts.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn zero_sample_rate_chunk_is_skipped() {
    let brain = FakeBrain {
        zero_rate_chunk: true,
        ..FakeBrain::default()
    };
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    for _ in 0..2 {
        speak(&mut ws, &session).await;
        assert_eq!(next_json(&mut ws).await["type"], "stt");
        assert_eq!(next_json(&mut ws).await["state"], "start");
        let sentence = next_json(&mut ws).await;
        assert_eq!(
            (sentence["state"].as_str(), sentence["text"].as_str()),
            (Some("sentence_start"), Some("Сәлем!"))
        );
        assert_eq!(frames_until_stop(&mut ws).await, reply_frames());
    }
}

#[tokio::test]
async fn reconnect_keeps_device_online() {
    let brain = FakeBrain::default();
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws1 = connect(&addr, TOKEN).await.unwrap();
    hello(&mut ws1).await;
    let mut ws2 = connect(&addr, TOKEN).await.unwrap();
    hello(&mut ws2).await;
    ws1.close(None).await.unwrap();
    while ws1.next().await.is_some() {}

    let last_state = || {
        brain
            .states
            .lock()
            .unwrap()
            .iter()
            .rev()
            .find(|(d, _)| d == DEVICE)
            .map(|(_, online)| *online)
    };
    let deadline = Instant::now() + Duration::from_secs(2);
    while brain.states.lock().unwrap().len() < 2 {
        assert!(
            Instant::now() < deadline,
            "online events never reached the brain"
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    for _ in 0..15 {
        assert_eq!(
            last_state(),
            Some(true),
            "states: {:?}",
            brain.states.lock().unwrap()
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    drop(ws2);
}

#[tokio::test]
async fn listen_stop_flushes_manual_mode_speech() {
    let brain = FakeBrain::default();
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    listen_start(&mut ws, &session).await;
    for p in opus_packets(0) {
        ws.send(Message::Binary(p.into())).await.unwrap();
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(500), ws.next())
            .await
            .is_err(),
        "VAD must not endpoint speech without trailing silence"
    );

    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"listen","state":"stop"}}"#).into(),
    ))
    .await
    .unwrap();
    let stt = next_json(&mut ws).await;
    assert_eq!(
        (stt["type"].as_str(), stt["text"].as_str()),
        (Some("stt"), Some("сәлем"))
    );
    let heard = brain.utterances.lock().unwrap()[0];
    assert!(
        heard > 16000 * 2 && heard <= 16000 * 3,
        "utterance samples: {heard}"
    );
}

#[tokio::test]
async fn link_drop_mid_turn_stops_device() {
    let brain = FakeBrain {
        hold_first: true,
        ..FakeBrain::default()
    };
    let (brain_addr, server) = start_brain_killable(brain.clone()).await;
    let (addr, link) = start_gateway(brain_addr).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["type"], "stt");
    assert_eq!(next_json(&mut ws).await["state"], "start");

    server.abort();
    brain.kill.notify_one();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let left = deadline.saturating_duration_since(Instant::now());
        let msg = tokio::time::timeout(left, ws.next())
            .await
            .expect("no tts stop after link drop")
            .unwrap()
            .unwrap();
        if let Message::Text(t) = msg {
            let v: serde_json::Value = serde_json::from_str(t.as_str()).unwrap();
            if v["type"] == "tts" && v["state"] == "stop" {
                break;
            }
        }
    }
    assert!(!link.is_connected());
    wait_turn_status(&addr, "error").await;
}

async fn get_json(addr: &str, path: &str) -> serde_json::Value {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut stream = tokio::net::TcpStream::connect(addr).await.unwrap();
    stream
        .write_all(
            format!("GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").as_bytes(),
        )
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
        if let Some(t) = state["turns"].as_array().and_then(|t| t.first())
            && t["status"] == status
        {
            return state;
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
    assert_eq!(
        (
            turn["stt_ms"].as_u64(),
            turn["llm_ms"].as_u64(),
            turn["tts_ms"].as_u64()
        ),
        (Some(900), Some(1600), Some(200))
    );
    assert!(turn["first_audio_ms"].as_u64().is_some());
    assert_eq!(state["summary"]["turns"], 1);
    assert_eq!(state["link"]["up"], true);
    assert!(
        state["devices"]
            .as_array()
            .unwrap()
            .iter()
            .any(|d| d["device_id"] == DEVICE && d["online"] == true)
    );
}

#[tokio::test]
async fn aborted_turn_in_state() {
    let brain = FakeBrain {
        hold_first: true,
        ..FakeBrain::default()
    };
    let (addr, link) = start_gateway(start_brain(brain.clone()).await).await;
    wait_link(&link, true).await;
    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;
    assert_eq!(next_json(&mut ws).await["type"], "stt");
    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"abort","reason":"wake_word_detected"}}"#)
            .into(),
    ))
    .await
    .unwrap();
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

async fn get_raw(addr: &str, path: &str) -> String {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut stream = tokio::net::TcpStream::connect(addr).await.unwrap();
    stream
        .write_all(
            format!("GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").as_bytes(),
        )
        .await
        .unwrap();
    let mut raw = String::new();
    stream.read_to_string(&mut raw).await.unwrap();
    raw
}

#[tokio::test]
async fn static_pages_served() {
    let (addr, _link) = start_gateway(start_brain(FakeBrain::default()).await).await;
    let page = get_raw(&addr, "/").await;
    assert!(
        page.starts_with("HTTP/1.1 200") && page.contains("text/html"),
        "{page}"
    );
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
    sse.write_all(b"GET /api/events HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n")
        .await
        .unwrap();
    let mut lines = BufReader::new(sse).lines();

    let mut ws = connect(&addr, TOKEN).await.unwrap();
    let session = hello(&mut ws).await;
    speak(&mut ws, &session).await;

    let mut kinds = Vec::new();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(15);
    while !kinds.contains(&"turn_end".to_string()) {
        let line = tokio::time::timeout_at(deadline, lines.next_line())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        if let Some(data) = line.strip_prefix("data:") {
            let v: serde_json::Value = serde_json::from_str(data.trim()).unwrap();
            kinds.push(v["type"].as_str().unwrap().to_string());
        }
    }
    let pos = |k: &str| kinds.iter().position(|x| x == k).unwrap();
    assert!(
        pos("turn_started") < pos("transcript") && pos("transcript") < pos("turn_end"),
        "{kinds:?}"
    );
}
