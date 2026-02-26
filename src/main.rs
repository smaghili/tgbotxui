mod bot;
mod config;
mod crypto;
mod db;
mod metrics;
mod rate_limit;
mod service;
mod xui;

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use axum::serve;
use config::Config;
use db::Db;
use rate_limit::SlidingWindowRateLimiter;
use service::ServiceLayer;
use teloxide::Bot;
use tokio::net::TcpListener;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    let config = Arc::new(Config::from_env()?);
    init_logging(&config.log_level);

    let db = Arc::new(Db::connect(&config.database_url).await?);
    db.migrate().await?;

    let crypto = Arc::new(crypto::Crypto::new(&config.encryption_key_b64)?);
    let xui = Arc::new(xui::XuiClient::new(config.request_timeout_seconds)?);
    let services = Arc::new(ServiceLayer {
        db: db.clone(),
        crypto,
        xui,
        timezone: config.timezone.clone(),
    });
    services.update_cardinality_metrics().await?;

    if config.metrics_enabled {
        let host = config.metrics_host.clone();
        let port = config.metrics_port;
        tokio::spawn(async move {
            if let Err(err) = run_metrics_server(host, port).await {
                tracing::error!(error = %err, "metrics server failed");
            }
        });
    }

    {
        let services = services.clone();
        let interval = config.sync_interval_seconds;
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(Duration::from_secs(interval));
            loop {
                ticker.tick().await;
                services.refresh_all_services().await;
            }
        });
    }

    let bot = Bot::new(config.bot_token.clone());
    let ctx = Arc::new(bot::BotContext {
        config: config.clone(),
        services,
        limiter: Arc::new(SlidingWindowRateLimiter::default()),
    });
    tracing::info!("bot is running");
    bot::run_bot(bot, ctx).await;
    Ok(())
}

fn init_logging(level: &str) {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(level));
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .json()
        .with_target(true)
        .init();
}

async fn run_metrics_server(host: String, port: u16) -> Result<()> {
    let app = metrics::router();
    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    let listener = TcpListener::bind(addr).await?;
    tracing::info!(%addr, "metrics server started");
    serve(listener, app).await?;
    Ok(())
}
