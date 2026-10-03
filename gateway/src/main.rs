fn main() -> anyhow::Result<()> {
    let cfg = aidos_gateway::config::Config::from_env()?;
    println!("aidos-gateway config: bind={} brain={} devices={}", cfg.bind, cfg.brain_addr, cfg.devices.len());
    Ok(())
}
