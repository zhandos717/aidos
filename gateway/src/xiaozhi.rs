use serde::Deserialize;
use serde_json::json;

#[derive(Debug, Deserialize, PartialEq, Clone)]
pub struct AudioParams {
    pub format: String,
    pub sample_rate: u32,
    pub channels: u32,
    pub frame_duration: u32,
}

#[derive(Debug, Deserialize, PartialEq, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum ListenState {
    Start,
    Stop,
    Detect,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum DeviceMsg {
    Hello {
        #[serde(default)]
        version: u32,
        audio_params: Option<AudioParams>,
    },
    Listen {
        state: ListenState,
        #[serde(default)]
        mode: Option<String>,
        #[serde(default)]
        text: Option<String>,
    },
    Abort {
        #[serde(default)]
        reason: Option<String>,
    },
    #[serde(other)]
    Other,
}

pub const DOWN_SAMPLE_RATE: u32 = 24000;
pub const FRAME_DURATION_MS: u32 = 60;

pub fn parse(text: &str) -> serde_json::Result<DeviceMsg> {
    serde_json::from_str(text)
}

pub fn server_hello(session_id: &str) -> String {
    json!({
        "type": "hello",
        "transport": "websocket",
        "session_id": session_id,
        "audio_params": {"format": "opus", "sample_rate": DOWN_SAMPLE_RATE, "channels": 1, "frame_duration": FRAME_DURATION_MS}
    })
    .to_string()
}

pub fn stt(session_id: &str, text: &str) -> String {
    json!({"session_id": session_id, "type": "stt", "text": text}).to_string()
}

pub fn tts_start(session_id: &str) -> String {
    json!({"session_id": session_id, "type": "tts", "state": "start"}).to_string()
}

pub fn tts_sentence(session_id: &str, text: &str) -> String {
    json!({"session_id": session_id, "type": "tts", "state": "sentence_start", "text": text})
        .to_string()
}

pub fn tts_stop(session_id: &str) -> String {
    json!({"session_id": session_id, "type": "tts", "state": "stop"}).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[test]
    fn parses_device_hello_from_docs() {
        let msg = parse(r#"{"type":"hello","version":1,"features":{"mcp":true,"aec":true},"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}"#).unwrap();
        let DeviceMsg::Hello {
            version,
            audio_params,
        } = msg
        else {
            panic!("not hello")
        };
        assert_eq!(version, 1);
        assert_eq!(audio_params.unwrap().sample_rate, 16000);
    }

    #[test]
    fn parses_listen_variants() {
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"listen","state":"start","mode":"manual"}"#)
                .unwrap(),
            DeviceMsg::Listen {
                state: ListenState::Start,
                mode: Some("manual".into()),
                text: None
            }
        );
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"listen","state":"detect","text":"Hi XiaoZhi"}"#)
                .unwrap(),
            DeviceMsg::Listen {
                state: ListenState::Detect,
                mode: None,
                text: Some("Hi XiaoZhi".into())
            }
        );
        assert!(matches!(
            parse(r#"{"session_id":"xxx","type":"listen","state":"stop"}"#).unwrap(),
            DeviceMsg::Listen {
                state: ListenState::Stop,
                ..
            }
        ));
    }

    #[test]
    fn parses_abort_and_unknown() {
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"abort","reason":"wake_word_detected"}"#).unwrap(),
            DeviceMsg::Abort {
                reason: Some("wake_word_detected".into())
            }
        );
        assert_eq!(
            parse(r#"{"session_id":"xxx","type":"mcp","payload":{}}"#).unwrap(),
            DeviceMsg::Other
        );
    }

    #[test]
    fn builds_server_messages() {
        let hello: Value = serde_json::from_str(&server_hello("s1")).unwrap();
        assert_eq!(hello["type"], "hello");
        assert_eq!(hello["transport"], "websocket");
        assert_eq!(hello["session_id"], "s1");
        assert_eq!(hello["audio_params"]["sample_rate"], 24000);
        assert_eq!(hello["audio_params"]["frame_duration"], 60);

        let s: Value = serde_json::from_str(&stt("s1", "сәлем")).unwrap();
        assert_eq!(
            (s["type"].as_str(), s["text"].as_str()),
            (Some("stt"), Some("сәлем"))
        );

        let start: Value = serde_json::from_str(&tts_start("s1")).unwrap();
        assert_eq!(
            (start["type"].as_str(), start["state"].as_str()),
            (Some("tts"), Some("start"))
        );
        let sentence: Value = serde_json::from_str(&tts_sentence("s1", "Иә.")).unwrap();
        assert_eq!(
            (sentence["state"].as_str(), sentence["text"].as_str()),
            (Some("sentence_start"), Some("Иә."))
        );
        let stop: Value = serde_json::from_str(&tts_stop("s1")).unwrap();
        assert_eq!(stop["state"], "stop");
    }
}
