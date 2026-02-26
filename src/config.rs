use std::collections::HashSet;
use std::env;

use anyhow::{anyhow, Result};

#[derive(Clone, Debug)]
pub struct Config {
    pub bot_token: String,
    pub admin_ids: HashSet<i64>,
    pub database_url: String,
    pub encryption_key_b64: String,
    pub request_timeout_seconds: u64,
    pub sync_interval_seconds: u64,
    pub timezone: String,
    pub log_level: String,
    pub metrics_enabled: bool,
    pub metrics_host: String,
    pub metrics_port: u16,
    pub admin_rate_limit_count: usize,
    pub admin_rate_limit_window_seconds: u64,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenvy::dotenv().ok();

        let bot_token = env::var("BOT_TOKEN").map_err(|_| anyhow!("BOT_TOKEN is required"))?;
        let encryption_key_b64 =
            env::var("ENCRYPTION_KEY").map_err(|_| anyhow!("ENCRYPTION_KEY is required"))?;
        let admin_ids = parse_admin_ids(&env::var("ADMIN_IDS").unwrap_or_default());
        if admin_ids.is_empty() {
            return Err(anyhow!("ADMIN_IDS must include at least one numeric Telegram user id"));
        }

        Ok(Self {
            bot_token,
            admin_ids,
            database_url: env::var("DATABASE_URL").unwrap_or_else(|_| "sqlite:data/bot.db".to_string()),
            encryption_key_b64,
            request_timeout_seconds: env::var("REQUEST_TIMEOUT_SECONDS")
                .unwrap_or_else(|_| "20".to_string())
                .parse()?,
            sync_interval_seconds: env::var("SYNC_INTERVAL_SECONDS")
                .unwrap_or_else(|_| "180".to_string())
                .parse()?,
            timezone: env::var("TIMEZONE").unwrap_or_else(|_| "Asia/Tehran".to_string()),
            log_level: env::var("LOG_LEVEL").unwrap_or_else(|_| "info".to_string()),
            metrics_enabled: parse_bool(&env::var("METRICS_ENABLED").unwrap_or_else(|_| "true".to_string())),
            metrics_host: env::var("METRICS_HOST").unwrap_or_else(|_| "127.0.0.1".to_string()),
            metrics_port: env::var("METRICS_PORT")
                .unwrap_or_else(|_| "9090".to_string())
                .parse()?,
            admin_rate_limit_count: env::var("ADMIN_RATE_LIMIT_COUNT")
                .unwrap_or_else(|_| "10".to_string())
                .parse()?,
            admin_rate_limit_window_seconds: env::var("ADMIN_RATE_LIMIT_WINDOW_SECONDS")
                .unwrap_or_else(|_| "60".to_string())
                .parse()?,
        })
    }

    pub fn is_admin(&self, user_id: i64) -> bool {
        self.admin_ids.contains(&user_id)
    }
}

fn parse_admin_ids(raw: &str) -> HashSet<i64> {
    raw.split(',')
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .filter_map(|s| s.parse::<i64>().ok())
        .collect()
}

fn parse_bool(raw: &str) -> bool {
    matches!(
        raw.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on" | "y"
    )
}
