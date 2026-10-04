use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tonic::Request;

use crate::metrics::MetricsHub;
use crate::pb;
use crate::pb::brain_client::BrainClient;
use crate::pb::brain_event::Kind;

type Routes = Arc<Mutex<HashMap<String, mpsc::Sender<pb::BrainEvent>>>>;

#[derive(Clone)]
pub struct LinkHandle {
    out: mpsc::Sender<pb::GatewayEvent>,
    routes: Routes,
    connected: Arc<AtomicBool>,
}

pub fn event_device_id(ev: &pb::BrainEvent) -> Option<&str> {
    Some(match ev.kind.as_ref()? {
        Kind::Transcript(e) => &e.device_id,
        Kind::Speech(e) => &e.device_id,
        Kind::Action(e) => &e.device_id,
        Kind::End(e) => &e.device_id,
        Kind::Push(e) => &e.device_id,
    })
}

pub fn event_turn_id(ev: &pb::BrainEvent) -> Option<&str> {
    Some(match ev.kind.as_ref()? {
        Kind::Transcript(e) => &e.turn_id,
        Kind::Speech(e) => &e.turn_id,
        Kind::Action(e) => &e.turn_id,
        Kind::End(e) => &e.turn_id,
        Kind::Push(_) => return None,
    })
}

impl LinkHandle {
    pub fn spawn(brain_addr: String, token: String) -> LinkHandle {
        Self::start(brain_addr, token, None)
    }

    pub fn with_metrics(brain_addr: String, token: String, hub: Arc<MetricsHub>) -> LinkHandle {
        Self::start(brain_addr, token, Some(hub))
    }

    fn start(brain_addr: String, token: String, metrics: Option<Arc<MetricsHub>>) -> LinkHandle {
        let (out, rx) = mpsc::channel(256);
        let handle = LinkHandle {
            out,
            routes: Arc::default(),
            connected: Arc::default(),
        };
        tokio::spawn(run(
            brain_addr,
            token,
            rx,
            handle.routes.clone(),
            handle.connected.clone(),
            metrics,
        ));
        handle
    }

    pub fn is_connected(&self) -> bool {
        self.connected.load(Ordering::Relaxed)
    }

    pub fn send(&self, ev: pb::GatewayEvent) -> bool {
        self.is_connected() && self.out.try_send(ev).is_ok()
    }

    pub fn register(&self, device_id: &str) -> mpsc::Receiver<pb::BrainEvent> {
        let (tx, rx) = mpsc::channel(64);
        self.routes
            .lock()
            .unwrap()
            .insert(device_id.to_string(), tx);
        rx
    }

    pub fn unregister(&self, device_id: &str) {
        let mut routes = self.routes.lock().unwrap();
        if routes.get(device_id).is_some_and(|tx| tx.is_closed()) {
            routes.remove(device_id);
        }
    }
}

async fn run(
    addr: String,
    token: String,
    mut outbox: mpsc::Receiver<pb::GatewayEvent>,
    routes: Routes,
    connected: Arc<AtomicBool>,
    metrics: Option<Arc<MetricsHub>>,
) {
    let mut backoff = Duration::from_secs(1);
    loop {
        match connect_once(
            &addr,
            &token,
            &mut outbox,
            &routes,
            &connected,
            metrics.as_deref(),
        )
        .await
        {
            Ok(()) => return,
            Err(err) => tracing::warn!(%err, ?backoff, "brain link down"),
        }
        if connected.swap(false, Ordering::Relaxed) {
            if let Some(m) = &metrics {
                m.link(false);
            }
            backoff = Duration::from_secs(1);
        }
        loop {
            match outbox.try_recv() {
                Ok(_) => {}
                Err(mpsc::error::TryRecvError::Empty) => break,
                Err(mpsc::error::TryRecvError::Disconnected) => return,
            }
        }
        tokio::time::sleep(backoff).await;
        backoff = (backoff * 2).min(Duration::from_secs(30));
    }
}

async fn connect_once(
    addr: &str,
    token: &str,
    outbox: &mut mpsc::Receiver<pb::GatewayEvent>,
    routes: &Routes,
    connected: &AtomicBool,
    metrics: Option<&MetricsHub>,
) -> anyhow::Result<()> {
    let channel = tonic::transport::Endpoint::from_shared(addr.to_string())?
        .connect_timeout(Duration::from_secs(5))
        .http2_keep_alive_interval(Duration::from_secs(10))
        .keep_alive_timeout(Duration::from_secs(5))
        .keep_alive_while_idle(true)
        .connect()
        .await?;
    let mut client = BrainClient::new(channel);
    let (tx, rx) = mpsc::channel(64);
    let mut req = Request::new(ReceiverStream::new(rx));
    req.metadata_mut()
        .insert("authorization", format!("Bearer {token}").parse()?);
    let mut inbound = client.link(req).await?.into_inner();
    connected.store(true, Ordering::Relaxed);
    if let Some(m) = metrics {
        m.link(true);
    }
    tracing::info!(addr, "brain link up");

    let mut pending: Option<pb::GatewayEvent> = None;
    loop {
        tokio::select! {
            permit = tx.reserve(), if pending.is_some() => {
                if let Some(ev) = pending.take() {
                    permit?.send(ev);
                }
            }
            out = outbox.recv(), if pending.is_none() => match out {
                Some(ev) => pending = Some(ev),
                None => return Ok(()),
            },
            msg = inbound.message() => match msg? {
                Some(ev) => route(routes, ev),
                None => anyhow::bail!("brain closed the link"),
            },
        }
    }
}

fn route(routes: &Routes, ev: pb::BrainEvent) {
    let Some(device_id) = event_device_id(&ev).map(str::to_string) else {
        return;
    };
    let sender = routes.lock().unwrap().get(&device_id).cloned();
    match sender {
        Some(tx) if tx.try_send(ev).is_ok() => {}
        _ => tracing::warn!(
            device_id,
            "dropped brain event: device not connected or slow"
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::pin::Pin;
    use tokio_stream::{Stream, StreamExt, wrappers::TcpListenerStream};
    use tonic::{Response, Status, Streaming};

    struct Echo;

    #[tonic::async_trait]
    impl pb::brain_server::Brain for Echo {
        type LinkStream =
            Pin<Box<dyn Stream<Item = Result<pb::BrainEvent, Status>> + Send + 'static>>;

        async fn link(
            &self,
            req: Request<Streaming<pb::GatewayEvent>>,
        ) -> Result<Response<Self::LinkStream>, Status> {
            assert_eq!(req.metadata().get("authorization").unwrap(), "Bearer t0k");
            let mut inbound = req.into_inner();
            let out = async_stream_like(move |tx| async move {
                while let Some(Ok(ev)) = inbound.next().await {
                    if let Some(pb::gateway_event::Kind::Utterance(u)) = ev.kind {
                        let _ = tx
                            .send(Ok(pb::BrainEvent {
                                kind: Some(Kind::Transcript(pb::Transcript {
                                    device_id: u.device_id,
                                    turn_id: u.turn_id,
                                    text: "ok".into(),
                                })),
                            }))
                            .await;
                    }
                }
            });
            Ok(Response::new(out))
        }
    }

    fn async_stream_like<F, Fut>(
        f: F,
    ) -> Pin<Box<dyn Stream<Item = Result<pb::BrainEvent, Status>> + Send>>
    where
        F: FnOnce(mpsc::Sender<Result<pb::BrainEvent, Status>>) -> Fut,
        Fut: std::future::Future<Output = ()> + Send + 'static,
    {
        let (tx, rx) = mpsc::channel(16);
        tokio::spawn(f(tx));
        Box::pin(ReceiverStream::new(rx))
    }

    fn utterance(device: &str, turn: &str) -> pb::GatewayEvent {
        pb::GatewayEvent {
            kind: Some(pb::gateway_event::Kind::Utterance(pb::Utterance {
                device_id: device.into(),
                turn_id: turn.into(),
                pcm_s16le: vec![],
                sample_rate: 16000,
            })),
        }
    }

    #[tokio::test]
    async fn routes_events_to_the_right_device() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(
            tonic::transport::Server::builder()
                .add_service(pb::brain_server::BrainServer::new(Echo))
                .serve_with_incoming(TcpListenerStream::new(listener)),
        );

        let link = LinkHandle::spawn(format!("http://{addr}"), "t0k".into());
        let mut a = link.register("box-a");
        let mut b = link.register("box-b");
        for _ in 0..50 {
            if link.is_connected() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        assert!(link.is_connected());

        assert!(link.send(utterance("box-b", "t2")));
        assert!(link.send(utterance("box-a", "t1")));

        let ev_a = tokio::time::timeout(Duration::from_secs(3), a.recv())
            .await
            .unwrap()
            .unwrap();
        let ev_b = tokio::time::timeout(Duration::from_secs(3), b.recv())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            (event_device_id(&ev_a), event_turn_id(&ev_a)),
            (Some("box-a"), Some("t1"))
        );
        assert_eq!(
            (event_device_id(&ev_b), event_turn_id(&ev_b)),
            (Some("box-b"), Some("t2"))
        );
    }

    #[tokio::test]
    async fn stale_unregister_keeps_newer_registration() {
        let (out, _rx) = mpsc::channel(1);
        let link = LinkHandle {
            out,
            routes: Arc::default(),
            connected: Arc::default(),
        };
        let rx1 = link.register("box-a");
        drop(rx1);
        let mut rx2 = link.register("box-a");
        link.unregister("box-a");
        route(
            &link.routes,
            pb::BrainEvent {
                kind: Some(Kind::Transcript(pb::Transcript {
                    device_id: "box-a".into(),
                    turn_id: "t1".into(),
                    text: "x".into(),
                })),
            },
        );
        assert!(rx2.try_recv().is_ok());

        drop(rx2);
        link.unregister("box-a");
        assert!(link.routes.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn send_fails_while_disconnected() {
        let link = LinkHandle::spawn("http://127.0.0.1:1".into(), "t0k".into());
        tokio::time::sleep(Duration::from_millis(200)).await;
        assert!(!link.is_connected());
        assert!(!link.send(utterance("box-a", "t1")));
    }
}
