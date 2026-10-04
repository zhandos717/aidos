use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use axum::Router;
use axum::extract::{State, WebSocketUpgrade};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Json, Response};
use axum::routing::{get, post};
use serde_json::json;

use crate::config::Config;
use crate::device::run_device;
use crate::link::LinkHandle;
use crate::metrics::MetricsHub;

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub link: LinkHandle,
    pub hub: Arc<MetricsHub>,
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/ota", post(ota).get(ota))
        .route("/ota/", post(ota).get(ota))
        .route("/ws", get(ws))
        .route("/api/state", get(api_state))
        .with_state(state)
}

pub async fn serve(listener: tokio::net::TcpListener, state: AppState) -> std::io::Result<()> {
    axum::serve(
        listener,
        router(state).into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
}

async fn api_state(State(st): State<AppState>) -> Response {
    Json(st.hub.snapshot()).into_response()
}

fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

async fn ota(State(st): State<AppState>, headers: HeaderMap) -> Response {
    let Some(device_id) = header(&headers, "Device-Id") else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    let Some(token) = st.cfg.devices.get(device_id) else {
        tracing::warn!(device_id, "ota: unknown device");
        return StatusCode::FORBIDDEN.into_response();
    };
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64;
    Json(json!({
        "websocket": {"url": st.cfg.public_ws_url, "token": token},
        "server_time": {"timestamp": now_ms, "timezone_offset": st.cfg.tz_offset_min},
        "firmware": {"version": "0.0.0", "url": ""}
    }))
    .into_response()
}

async fn ws(State(st): State<AppState>, headers: HeaderMap, upgrade: WebSocketUpgrade) -> Response {
    let token = header(&headers, "Authorization").and_then(|v| v.strip_prefix("Bearer "));
    let device = token.and_then(|t| {
        st.cfg
            .devices
            .iter()
            .find(|(_, v)| v.as_str() == t)
            .map(|(k, _)| k.clone())
    });
    let Some(device_id) = device else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    if header(&headers, "Device-Id").is_some_and(|claimed| claimed != device_id) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let model = st.cfg.silero_model.clone();
    upgrade.on_upgrade(move |socket| run_device(socket, device_id, st.link, model, st.hub))
}
