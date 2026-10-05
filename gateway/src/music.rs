use std::process::Stdio;

use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::process::{Child, ChildStdout, Command};

pub const MUSIC_RATE: u32 = 24_000;
pub const MUSIC_FRAME: usize = (MUSIC_RATE as usize) * 60 / 1000;

pub struct MusicStream {
    child: Child,
    stdout: ChildStdout,
    title: String,
    done: bool,
}

impl MusicStream {
    pub fn spawn(url: &str, title: &str) -> std::io::Result<MusicStream> {
        let bin = std::env::var("FFMPEG").unwrap_or_else(|_| "ffmpeg".to_string());
        let mut cmd = Command::new(bin);
        cmd.args(["-nostdin", "-loglevel", "error"]);
        if url.starts_with("http://") || url.starts_with("https://") {
            cmd.args([
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
            ]);
        }
        cmd.args([
            "-i", url, "-f", "s16le", "-ar", "24000", "-ac", "1", "pipe:1",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
        let mut child = cmd.spawn()?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| std::io::Error::other("ffmpeg stdout unavailable"))?;
        Ok(MusicStream {
            child,
            stdout,
            title: title.to_string(),
            done: false,
        })
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub async fn next_frame(&mut self) -> std::io::Result<Option<Vec<i16>>> {
        if self.done {
            return Ok(None);
        }
        let mut buf = vec![0u8; MUSIC_FRAME * 2];
        let n = read_full(&mut self.stdout, &mut buf).await?;
        if n < buf.len() {
            self.done = true;
        }
        let n = n & !1;
        if n == 0 {
            return Ok(None);
        }
        Ok(Some(
            buf.chunks_exact(2)
                .map(|b| i16::from_le_bytes([b[0], b[1]]))
                .collect(),
        ))
    }

    pub async fn stop(mut self) {
        let _ = self.child.start_kill();
        let _ = self.child.wait().await;
    }
}

async fn read_full<R: AsyncRead + Unpin>(r: &mut R, buf: &mut [u8]) -> std::io::Result<usize> {
    let mut filled = 0;
    while filled < buf.len() {
        let n = r.read(&mut buf[filled..]).await?;
        if n == 0 {
            break;
        }
        filled += n;
    }
    Ok(filled)
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    fn fixture() -> String {
        format!(
            "{}/tests/fixtures/speech_16k.wav",
            env!("CARGO_MANIFEST_DIR")
        )
    }

    fn have_ffmpeg() -> bool {
        let bin = std::env::var("FFMPEG").unwrap_or_else(|_| "ffmpeg".to_string());
        let ok = std::process::Command::new(bin)
            .arg("-version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if !ok {
            eprintln!("ffmpeg not found, skipping");
        }
        ok
    }

    #[tokio::test]
    async fn streams_fixture_in_whole_frames() {
        if !have_ffmpeg() {
            return;
        }
        let mut s = MusicStream::spawn(&fixture(), "fixture").unwrap();
        assert_eq!(s.title(), "fixture");
        let mut count = 0;
        while let Some(f) = s.next_frame().await.unwrap() {
            assert_eq!(f.len(), MUSIC_FRAME);
            count += 1;
        }
        assert!((49..=51).contains(&count), "frames: {count}");
        assert!(s.next_frame().await.unwrap().is_none());
        s.stop().await;
    }

    #[tokio::test]
    async fn stop_kills_child() {
        if !have_ffmpeg() {
            return;
        }
        let mut s = MusicStream::spawn(&fixture(), "fixture").unwrap();
        assert!(s.next_frame().await.unwrap().is_some());
        let pid = s.child.id().unwrap();
        s.stop().await;
        let alive = std::process::Command::new("kill")
            .args(["-0", &pid.to_string()])
            .stderr(Stdio::null())
            .status()
            .map(|st| st.success())
            .unwrap_or(false);
        assert!(!alive);
    }

    #[tokio::test]
    async fn spawn_bad_url_ends_quickly() {
        if !have_ffmpeg() {
            return;
        }
        let mut s = MusicStream::spawn("/nonexistent.wav", "bad").unwrap();
        let r = tokio::time::timeout(Duration::from_secs(5), s.next_frame())
            .await
            .expect("timed out");
        assert!(matches!(r, Ok(None) | Err(_)));
    }
}
