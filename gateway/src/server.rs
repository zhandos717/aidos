use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use std::collections::HashMap;
use std::convert::Infallible;
use std::time::Duration;

use axum::Router;
use axum::extract::{ConnectInfo, Query, Request, State, WebSocketUpgrade};
use axum::http::{HeaderMap, StatusCode, header::CONTENT_TYPE};
use axum::middleware::{self, Next};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Json, Response};
use axum::routing::{get, post};
use futures_util::{Stream, StreamExt};
use serde_json::json;
use tokio::sync::broadcast;
use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::wrappers::errors::BroadcastStreamRecvError;

use crate::config::Config;
use crate::device::run_device;
use crate::link::LinkHandle;
use crate::metrics::{DashEvent, MetricsHub};

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub link: LinkHandle,
    pub hub: Arc<MetricsHub>,
    /// (device_id, token) of the browser emulator; the token is also present in `cfg.devices`.
    pub emulator: Option<(String, String)>,
}

pub fn router(state: AppState) -> Router {
    let dashboard = Router::new()
        .route(
            "/",
            get(|| async {
                asset(
                    include_str!("../web/index.html"),
                    "text/html; charset=utf-8",
                )
            }),
        )
        .route(
            "/app.css",
            get(|| async { asset(include_str!("../web/app.css"), "text/css; charset=utf-8") }),
        )
        .route(
            "/app.js",
            get(|| async {
                asset(
                    include_str!("../web/app.js"),
                    "text/javascript; charset=utf-8",
                )
            }),
        )
        .route(
            "/emulator.js",
            get(|| async {
                asset(
                    include_str!("../web/emulator.js"),
                    "text/javascript; charset=utf-8",
                )
            }),
        )
        .route("/api/state", get(api_state))
        .route("/api/events", get(api_events))
        .route("/api/emulator", get(api_emulator))
        .layer(middleware::from_fn(local_only));
    Router::new()
        .route("/ota", post(ota).get(ota))
        .route("/ota/", post(ota).get(ota))
        .route("/ws", get(ws))
        .merge(dashboard)
        .with_state(state)
}

pub fn is_loopback(addr: &SocketAddr) -> bool {
    addr.ip().is_loopback()
}

async fn local_only(
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    req: Request,
    next: Next,
) -> Response {
    if is_loopback(&addr) {
        next.run(req).await
    } else {
        StatusCode::FORBIDDEN.into_response()
    }
}

fn asset(body: &'static str, content_type: &'static str) -> Response {
    ([(CONTENT_TYPE, content_type)], body).into_response()
}

#[derive(Debug, PartialEq)]
enum DashItem {
    Event(String),
    Resync,
}

fn dash_stream(rx: broadcast::Receiver<DashEvent>) -> impl Stream<Item = DashItem> {
    BroadcastStream::new(rx).map(|item| match item {
        Ok(ev) => DashItem::Event(serde_json::to_string(&ev).unwrap_or_default()),
        Err(BroadcastStreamRecvError::Lagged(_)) => DashItem::Resync,
    })
}

async fn api_events(
    State(st): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let stream = dash_stream(st.hub.subscribe()).map(|item| {
        Ok(match item {
            DashItem::Event(json) => Event::default().data(json),
            DashItem::Resync => Event::default().data(r#"{"type":"resync"}"#),
        })
    });
    Sse::new(stream).keep_alive(KeepAlive::new().interval(Duration::from_secs(15)))
}

async fn api_emulator(State(st): State<AppState>) -> Response {
    match &st.emulator {
        Some((device_id, token)) => {
            Json(json!({"device_id": device_id, "token": token, "ws_url": "/ws"})).into_response()
        }
        None => StatusCode::NOT_FOUND.into_response(),
    }
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

fn find_device(cfg: &Config, token: &str) -> Option<String> {
    cfg.devices
        .iter()
        .find(|(_, v)| v.as_str() == token)
        .map(|(k, _)| k.clone())
}

async fn ws(
    State(st): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    Query(q): Query<HashMap<String, String>>,
    headers: HeaderMap,
    upgrade: WebSocketUpgrade,
) -> Response {
    let header_token = header(&headers, "Authorization").and_then(|v| v.strip_prefix("Bearer "));
    let device = match (header_token, q.get("token")) {
        (Some(t), _) => find_device(&st.cfg, t),
        (None, Some(t)) if is_loopback(&peer) => st
            .emulator
            .as_ref()
            .filter(|(_, emu_token)| emu_token == t)
            .map(|(id, _)| id.clone()),
        _ => None,
    };
    let Some(device_id) = device else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    if header(&headers, "Device-Id").is_some_and(|claimed| claimed != device_id) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let model = st.cfg.silero_model.clone();
    upgrade.on_upgrade(move |socket| run_device(socket, device_id, st.link, model, st.hub))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_loopback_v4_and_v6() {
        assert!(is_loopback(&"127.0.0.1:5000".parse().unwrap()));
        assert!(is_loopback(&"[::1]:5000".parse().unwrap()));
        assert!(!is_loopback(&"192.168.1.20:5000".parse().unwrap()));
        assert!(!is_loopback(&"10.0.0.1:80".parse().unwrap()));
    }

    #[tokio::test]
    async fn sse_resync_on_lag() {
        let hub = crate::metrics::MetricsHub::new();
        let rx = hub.subscribe();
        for i in 0..300 {
            hub.device(&format!("d{i}"), true, "idle");
        }
        let mut stream = Box::pin(dash_stream(rx));
        let first = stream.next().await.unwrap();
        assert_eq!(first, DashItem::Resync);
    }
}
