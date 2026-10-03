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

    async fn link(
        &self,
        req: Request<Streaming<pb::GatewayEvent>>,
    ) -> Result<Response<Self::LinkStream>, Status> {
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
                        let _ = send(Kind::Transcript(pb::Transcript {
                            device_id: ids.0.clone(),
                            turn_id: ids.1.clone(),
                            text: "сәлем".into(),
                        }))
                        .await;
                        let pcm: Vec<u8> = vec![0u8; 22050 * REPLY_MS / 1000 * 2];
                        let _ = send(Kind::Speech(pb::SpeechChunk {
                            device_id: ids.0.clone(),
                            turn_id: ids.1.clone(),
                            text: "Сәлем!".into(),
                            pcm_s16le: pcm,
                            sample_rate: 22050,
                        }))
                        .await;
                        if me.hold {
                            continue;
                        }
                        let _ = send(Kind::End(pb::TurnEnd {
                            device_id: ids.0,
                            turn_id: ids.1,
                            error: false,
                        }))
                        .await;
                    }
                    Some(pb::gateway_event::Kind::Abort(a)) => {
                        me.aborts.lock().unwrap().push(a.turn_id)
                    }
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
    tokio::spawn(
        tonic::transport::Server::builder()
            .add_service(pb::brain_server::BrainServer::new(brain))
            .serve_with_incoming(TcpListenerStream::new(listener)),
    );
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
    let app = router(AppState {
        cfg: Arc::new(cfg),
        link: link.clone(),
    });
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
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
    let manifest = env!("CARGO_MANIFEST_DIR");
    let mut reader =
        hound::WavReader::open(Path::new(manifest).join("tests/fixtures/speech_16k.wav")).unwrap();
    let mut pcm: Vec<i16> = reader.samples::<i16>().map(Result::unwrap).collect();
    pcm.extend(vec![0i16; 16000 * 2]);
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
    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"listen","state":"start","mode":"auto"}}"#)
            .into(),
    ))
    .await
    .unwrap();
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
                break;
            }
            _ => {}
        }
    }
    assert_eq!(frames, (24000 * REPLY_MS / 1000).div_ceil(1440));
    let heard = brain.utterances.lock().unwrap()[0];
    assert!(
        heard > 16000 * 2 && heard < 16000 * 5,
        "utterance samples: {heard}"
    );
}

#[tokio::test]
async fn barge_in_aborts_turn() {
    let brain = FakeBrain {
        hold: true,
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
