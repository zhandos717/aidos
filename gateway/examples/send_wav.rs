use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let wav = args
        .next()
        .ok_or_else(|| anyhow::anyhow!("usage: send_wav <file.wav> [http://127.0.0.1:8000]"))?;
    let base = args
        .next()
        .unwrap_or_else(|| "http://127.0.0.1:8000".into());
    let base = base.trim_end_matches('/').to_string();

    let info: serde_json::Value = {
        let host = base.trim_start_matches("http://");
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let mut s = tokio::net::TcpStream::connect(host).await?;
        s.write_all(
            format!("GET /api/emulator HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .await?;
        let mut raw = String::new();
        s.read_to_string(&mut raw).await?;
        let (head, body) = raw.split_once("\r\n\r\n").unwrap_or((raw.as_str(), ""));
        let status = head.lines().next().unwrap_or("");
        anyhow::ensure!(
            status.starts_with("HTTP/1.1 200"),
            "/api/emulator returned {status}: {body}"
        );
        serde_json::from_str(body)?
    };
    let token = info["token"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("emulator disabled"))?;
    let url = format!(
        "{}{}?token={token}",
        base.replacen("http", "ws", 1),
        info["ws_url"].as_str().unwrap_or("/ws")
    );
    let (mut ws, _) = tokio_tungstenite::connect_async(url).await?;

    let mut reader = hound::WavReader::open(&wav)?;
    anyhow::ensure!(
        reader.spec().sample_rate == 16000 && reader.spec().channels == 1,
        "need 16 kHz mono WAV"
    );
    let pcm: Vec<i16> = reader.samples::<i16>().collect::<Result<_, _>>()?;

    ws.send(Message::Text(r#"{"type":"hello","version":1,"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}"#.into())).await?;
    let session = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            match ws.next().await.transpose()? {
                Some(Message::Text(t)) => {
                    let v: serde_json::Value = serde_json::from_str(t.as_str())?;
                    if v["type"] == "hello" {
                        return anyhow::Ok(
                            v["session_id"].as_str().unwrap_or_default().to_string(),
                        );
                    }
                }
                Some(_) => {}
                None => anyhow::bail!("connection closed before hello"),
            }
        }
    })
    .await
    .map_err(|_| anyhow::anyhow!("no hello within 10 s"))??;
    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"listen","state":"start","mode":"manual"}}"#)
            .into(),
    ))
    .await?;
    let mut enc = opus::Encoder::new(16000, opus::Channels::Mono, opus::Application::Voip)?;
    let mut buf = vec![0u8; 4000];
    for chunk in pcm.chunks(960) {
        let mut frame = [0i16; 960];
        frame[..chunk.len()].copy_from_slice(chunk);
        let n = enc.encode(&frame, &mut buf)?;
        ws.send(Message::Binary(buf[..n].to_vec().into())).await?;
        tokio::time::sleep(Duration::from_millis(60)).await;
    }
    ws.send(Message::Text(
        format!(r#"{{"session_id":"{session}","type":"listen","state":"stop"}}"#).into(),
    ))
    .await?;
    let started = std::time::Instant::now();

    let mut frames = 0;
    let outcome = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            let Some(msg) = ws.next().await else {
                anyhow::bail!("connection closed before tts stop ({frames} frames)");
            };
            match msg? {
                Message::Binary(_) => frames += 1,
                Message::Text(t) => {
                    let v: serde_json::Value = serde_json::from_str(t.as_str())?;
                    match (v["type"].as_str(), v["state"].as_str()) {
                        (Some("stt"), _) => {
                            println!(
                                "Сіз: {}  (+{} мс)",
                                v["text"],
                                started.elapsed().as_millis()
                            )
                        }
                        (Some("tts"), Some("sentence_start")) => println!(
                            "Айдос: {}  (+{} мс)",
                            v["text"],
                            started.elapsed().as_millis()
                        ),
                        (Some("tts"), Some("stop")) => break,
                        _ => {}
                    }
                }
                _ => {}
            }
        }
        anyhow::Ok(())
    })
    .await;
    match outcome {
        Ok(r) => r?,
        Err(_) => anyhow::bail!("no tts stop within 30 s ({frames} frames received)"),
    }
    println!(
        "кадров ответа: {frames} (~{:.1} с), всего {} мс",
        frames as f32 * 0.06,
        started.elapsed().as_millis()
    );
    Ok(())
}
