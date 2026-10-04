use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use std::collections::HashMap;
use std::convert::Infallible;
use std::time::Duration;

use axum::Router;
use axum::extract::ws::rejection::WebSocketUpgradeRejection;
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
    /// (device_id, token) of the browser emulator. Deliberately absent from `cfg.devices`, so
    /// `/ota` and Bearer auth never see it; only the loopback `?token=` branch of `/ws` does.
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
    addr.ip().to_canonical().is_loopback()
}

/// Rejects DNS-rebinding: a page on a foreign origin resolved to 127.0.0.1 still sends its own Host.
fn is_local_host(host: &str) -> bool {
    let name = match host.strip_prefix('[') {
        Some(rest) => rest.split_once(']').map_or(rest, |(name, _)| name),
        None => host.split(':').next().unwrap_or(host),
    };
    name.eq_ignore_ascii_case("localhost") || name == "127.0.0.1" || name == "::1"
}

async fn local_only(
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    req: Request,
    next: Next,
) -> Response {
    let host_ok = header(req.headers(), "Host").is_some_and(is_local_host);
    if is_loopback(&addr) && host_ok {
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
    BroadcastStream::new(rx).filter_map(|item| async move {
        match item {
            Ok(ev) => serde_json::to_string(&ev).ok().map(DashItem::Event),
            Err(BroadcastStreamRecvError::Lagged(_)) => Some(DashItem::Resync),
        }
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
    upgrade: Result<WebSocketUpgrade, WebSocketUpgradeRejection>,
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
    let upgrade = match upgrade {
        Ok(upgrade) => upgrade,
        Err(rejection) => return rejection.into_response(),
    };
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
        assert!(is_loopback(&"[::ffff:127.0.0.1]:5000".parse().unwrap()));
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

    mod guards {
        use std::path::PathBuf;

        use axum::body::Body;
        use axum::extract::connect_info::MockConnectInfo;
        use axum::http::Request;
        use tower::ServiceExt;

        use super::*;

        const EMU_TOKEN: &str = "emu-secret";
        const LAN: &str = "192.168.1.50:5555";
        const LOCAL: &str = "127.0.0.1:5555";

        fn app(peer: &str) -> Router {
            let cfg = Config {
                bind: "127.0.0.1:0".parse().unwrap(),
                public_ws_url: "ws://127.0.0.1:0/ws".into(),
                brain_addr: "http://127.0.0.1:1".into(),
                link_token: "t".into(),
                devices: HashMap::from([("box".to_string(), "box-token".to_string())]),
                silero_model: PathBuf::from("models/silero_vad.onnx"),
                tz_offset_min: 300,
                emulator_device: Some("web-emulator".into()),
            };
            let state = AppState {
                cfg: Arc::new(cfg),
                link: LinkHandle::spawn("http://127.0.0.1:1".into(), "t".into()),
                hub: MetricsHub::new(),
                emulator: Some(("web-emulator".into(), EMU_TOKEN.into())),
            };
            router(state).layer(MockConnectInfo(peer.parse::<SocketAddr>().unwrap()))
        }

        async fn status(peer: &str, req: Request<Body>) -> StatusCode {
            app(peer).oneshot(req).await.unwrap().status()
        }

        fn get_req(path: &str, host: &str) -> Request<Body> {
            Request::get(path)
                .header("Host", host)
                .body(Body::empty())
                .unwrap()
        }

        fn ws_req(uri: &str) -> axum::http::request::Builder {
            Request::get(uri)
                .header("Host", "127.0.0.1:8000")
                .header("Connection", "upgrade")
                .header("Upgrade", "websocket")
                .header("Sec-WebSocket-Version", "13")
                .header("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZQ==")
        }

        #[tokio::test]
        async fn dashboard_routes_forbidden_from_lan() {
            for path in ["/", "/app.js", "/api/state", "/api/events", "/api/emulator"] {
                assert_eq!(
                    status(LAN, get_req(path, "127.0.0.1:8000")).await,
                    StatusCode::FORBIDDEN,
                    "{path}"
                );
            }
        }

        #[tokio::test]
        async fn emulator_info_allowed_from_loopback() {
            for host in [
                "127.0.0.1:8000",
                "localhost:8000",
                "[::1]:8000",
                "localhost",
            ] {
                assert_eq!(
                    status(LOCAL, get_req("/api/emulator", host)).await,
                    StatusCode::OK,
                    "{host}"
                );
            }
        }

        #[tokio::test]
        async fn foreign_or_missing_host_forbidden_from_loopback() {
            assert_eq!(
                status(LOCAL, get_req("/api/emulator", "evil.example")).await,
                StatusCode::FORBIDDEN
            );
            assert_eq!(
                status(LOCAL, get_req("/", "evil.example:8000")).await,
                StatusCode::FORBIDDEN
            );
            let no_host = Request::get("/api/state").body(Body::empty()).unwrap();
            assert_eq!(status(LOCAL, no_host).await, StatusCode::FORBIDDEN);
        }

        #[tokio::test]
        async fn emulator_query_token_rejected_from_lan() {
            let req = ws_req(&format!("/ws?token={EMU_TOKEN}"))
                .body(Body::empty())
                .unwrap();
            assert_eq!(status(LAN, req).await, StatusCode::UNAUTHORIZED);
        }

        #[tokio::test]
        async fn emulator_token_never_valid_as_bearer() {
            for peer in [LAN, LOCAL] {
                let req = ws_req("/ws")
                    .header("Authorization", format!("Bearer {EMU_TOKEN}"))
                    .body(Body::empty())
                    .unwrap();
                assert_eq!(status(peer, req).await, StatusCode::UNAUTHORIZED, "{peer}");
            }
        }

        #[tokio::test]
        async fn ota_does_not_know_emulator() {
            let req = Request::post("/ota")
                .header("Host", "192.168.1.10:8000")
                .header("Device-Id", "web-emulator")
                .body(Body::empty())
                .unwrap();
            assert_eq!(status(LAN, req).await, StatusCode::FORBIDDEN);
        }
    }
}
