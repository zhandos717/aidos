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
    pub emulator_device: Option<String>,
}

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
        let env =
            |key: &str, default: &str| std::env::var(key).unwrap_or_else(|_| default.to_string());
        let link_token = env("LINK_TOKEN", "");
        if link_token.is_empty() {
            bail!("LINK_TOKEN is not set");
        }
        Ok(Config {
            bind: env("GATEWAY_BIND", "0.0.0.0:8000")
                .parse()
                .context("GATEWAY_BIND")?,
            public_ws_url: env("GATEWAY_PUBLIC_WS_URL", "ws://127.0.0.1:8000/ws"),
            brain_addr: env("BRAIN_ADDR", "http://127.0.0.1:50051"),
            link_token,
            devices: parse_devices(&env("GATEWAY_DEVICES", "")),
            silero_model: env("SILERO_MODEL", "models/silero_vad.onnx").into(),
            tz_offset_min: env("GATEWAY_TZ_OFFSET_MIN", "300")
                .parse()
                .context("GATEWAY_TZ_OFFSET_MIN")?,
            emulator_device: Some(env("GATEWAY_EMULATOR_DEVICE", "web-emulator"))
                .filter(|s| !s.is_empty()),
        })
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
