use std::sync::Arc;

use anyhow::Context;

use aidos_gateway::config::Config;
use aidos_gateway::link::LinkHandle;
use aidos_gateway::server::{AppState, router};
use aidos_gateway::vad::SileroVad;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();
    let cfg = Config::from_env()?;
    SileroVad::load(&cfg.silero_model).with_context(|| {
        format!(
            "cannot load Silero VAD model from {}",
            cfg.silero_model.display()
        )
    })?;
    let link = LinkHandle::spawn(cfg.brain_addr.clone(), cfg.link_token.clone());
    let listener = tokio::net::TcpListener::bind(cfg.bind).await?;
    tracing::info!(bind = %cfg.bind, brain = cfg.brain_addr, devices = cfg.devices.len(), "aidos-gateway listening");
    axum::serve(
        listener,
        router(AppState {
            cfg: Arc::new(cfg),
            link,
        }),
    )
    .await?;
    Ok(())
}
