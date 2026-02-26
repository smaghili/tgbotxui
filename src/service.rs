use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Result};
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};

use crate::crypto::Crypto;
use crate::db::{CookieJar, Db, PanelRow, UserServiceRow};
use crate::metrics::{PANEL_COUNT, SYNC_RUNS, USER_SERVICE_COUNT, USER_STATUS_REQUESTS};
use crate::xui::{parse_login_url, PanelConnection, XuiClient, XuiError};

#[derive(Clone)]
pub struct ServiceLayer {
    pub db: Arc<Db>,
    pub crypto: Arc<Crypto>,
    pub xui: Arc<XuiClient>,
    pub timezone: String,
}

#[derive(Debug, Clone)]
pub struct UsageData {
    pub client_email: String,
    pub client_id: Option<String>,
    pub inbound_id: Option<i64>,
    pub service_name: String,
    pub total_bytes: i64,
    pub used_bytes: i64,
    pub remaining_bytes: Option<i64>,
    pub expire_at: Option<i64>,
    pub status: String,
    pub synced_at: i64,
}

impl ServiceLayer {
    pub async fn add_panel(
        &self,
        login_url: &str,
        username: &str,
        password: &str,
        two_factor: Option<&str>,
        created_by: i64,
    ) -> Result<i64> {
        let (base_url, web_base_path, login_path) = parse_login_url(login_url)?;
        let conn = PanelConnection {
            base_url: base_url.clone(),
            web_base_path: web_base_path.clone(),
            login_path: login_path.clone(),
            username: username.to_string(),
            password: password.to_string(),
            two_factor: two_factor.map(|v| v.to_string()),
        };
        let cookies = self.xui.login(&conn).await.map_err(anyhow_from_xui)?;

        let panel_name = format!("{}_{}", base_url.trim_start_matches("http://").trim_start_matches("https://"), username);
        let username_enc = self.crypto.encrypt(username)?;
        let password_enc = self.crypto.encrypt(password)?;
        let two_factor_enc = match two_factor {
            Some(v) if !v.is_empty() => Some(self.crypto.encrypt(v)?),
            _ => None,
        };

        let panel_id = self
            .db
            .add_panel(
                &panel_name,
                &base_url,
                &web_base_path,
                &login_path,
                &username_enc,
                &password_enc,
                two_factor_enc.as_deref(),
                created_by,
            )
            .await?;
        self.db
            .save_panel_session(panel_id, &CookieJar { items: cookies })
            .await?;
        self.db.set_panel_login_status(panel_id, true, None).await?;
        self.update_cardinality_metrics().await?;
        Ok(panel_id)
    }

    pub async fn list_panels(&self) -> Result<Vec<PanelRow>> {
        self.db.list_panels().await
    }

    pub async fn bind_service_to_user(
        &self,
        panel_id: i64,
        telegram_user_id: i64,
        client_email: &str,
        service_name: Option<&str>,
        inbound_id: Option<i64>,
    ) -> Result<UsageData> {
        let usage = self.fetch_client_usage(panel_id, client_email).await?;
        let sid = self
            .db
            .bind_user_service(
                telegram_user_id,
                panel_id,
                inbound_id.or(usage.inbound_id),
                &usage.client_email,
                usage.client_id.as_deref(),
                service_name.unwrap_or(&usage.service_name),
                usage.total_bytes,
                usage.used_bytes,
                usage.expire_at,
                &usage.status,
                usage.synced_at,
            )
            .await?;
        let mut out = usage;
        out.service_name = service_name.unwrap_or(&out.service_name).to_string();
        out.client_id = Some(sid.to_string());
        self.update_cardinality_metrics().await?;
        Ok(out)
    }

    pub async fn fetch_client_usage(&self, panel_id: i64, client_email: &str) -> Result<UsageData> {
        let panel = self
            .db
            .get_panel(panel_id)
            .await?
            .ok_or_else(|| anyhow!("panel not found"))?;
        let conn = self.panel_to_connection(&panel)?;
        let mut jar = self.db.get_panel_session(panel_id).await?;

        let response = self
            .xui
            .get_client_traffics(&conn, &jar.items, client_email)
            .await;
        let (body, new_cookies) = match response {
            Ok(v) => v,
            Err(XuiError::Auth) => {
                let new_login = self.xui.login(&conn).await.map_err(anyhow_from_xui)?;
                jar.items = new_login.clone();
                self.db
                    .save_panel_session(panel_id, &CookieJar { items: new_login.clone() })
                    .await?;
                self.xui
                    .get_client_traffics(&conn, &new_login, client_email)
                    .await
                    .map_err(anyhow_from_xui)?
            }
            Err(other) => {
                self.db
                    .set_panel_login_status(panel_id, false, Some(&other.to_string()))
                    .await?;
                return Err(anyhow_from_xui(other));
            }
        };

        if !new_cookies.is_empty() {
            let mut merged = jar.items.clone();
            for (k, v) in new_cookies {
                merged.insert(k, v);
            }
            self.db
                .save_panel_session(panel_id, &CookieJar { items: merged })
                .await?;
        }
        self.db.set_panel_login_status(panel_id, true, None).await?;
        Ok(normalize_usage(&body, client_email))
    }

    pub async fn sync_single_service(&self, row: &UserServiceRow) -> Result<()> {
        let usage = self.fetch_client_usage(row.panel_id, &row.client_email).await?;
        self.db
            .update_user_service_stats(
                row.id,
                usage.total_bytes,
                usage.used_bytes,
                usage.expire_at,
                &usage.status,
                &row.service_name,
                usage.client_id.as_deref(),
                usage.inbound_id,
                usage.synced_at,
            )
            .await?;
        self.db
            .add_usage_snapshot(
                row.id,
                usage.used_bytes,
                usage.total_bytes,
                usage.remaining_bytes,
                &usage.status,
                usage.synced_at,
            )
            .await?;
        Ok(())
    }

    pub async fn refresh_all_services(&self) {
        let rows = match self.db.get_all_user_services().await {
            Ok(v) => v,
            Err(err) => {
                tracing::error!(error = %err, "failed reading services for sync");
                SYNC_RUNS.with_label_values(&["error"]).inc();
                return;
            }
        };

        let mut has_error = false;
        for row in rows {
            if let Err(err) = self.sync_single_service(&row).await {
                has_error = true;
                let _ = self
                    .db
                    .add_audit_log(
                        None,
                        "sync_service",
                        Some("user_service"),
                        Some(&row.id.to_string()),
                        false,
                        Some(&err.to_string()),
                    )
                    .await;
                tracing::warn!(service_id = row.id, error = %err, "sync failed");
            }
        }
        SYNC_RUNS
            .with_label_values(&[if has_error { "error" } else { "ok" }])
            .inc();
        let _ = self.update_cardinality_metrics().await;
    }

    pub async fn get_user_status_cards(&self, telegram_user_id: i64, force_refresh: bool) -> Result<Vec<String>> {
        if force_refresh {
            let rows = self.db.get_user_services(telegram_user_id).await?;
            for row in rows {
                let _ = self.sync_single_service(&row).await;
            }
        }
        let rows = self.db.get_user_services(telegram_user_id).await?;
        USER_STATUS_REQUESTS
            .with_label_values(&[if rows.is_empty() { "empty" } else { "ok" }])
            .inc();
        Ok(rows.iter().map(format_status_card).collect())
    }

    pub async fn update_cardinality_metrics(&self) -> Result<()> {
        PANEL_COUNT.set(self.db.count_panels().await? as i64);
        USER_SERVICE_COUNT.set(self.db.count_user_services().await? as i64);
        Ok(())
    }

    fn panel_to_connection(&self, panel: &PanelRow) -> Result<PanelConnection> {
        Ok(PanelConnection {
            base_url: panel.base_url.clone(),
            web_base_path: panel.web_base_path.clone(),
            login_path: panel.login_path.clone(),
            username: self.crypto.decrypt(&panel.username_enc)?,
            password: self.crypto.decrypt(&panel.password_enc)?,
            two_factor: match &panel.two_factor_enc {
                Some(v) => Some(self.crypto.decrypt(v)?),
                None => None,
            },
        })
    }
}

fn anyhow_from_xui(err: XuiError) -> anyhow::Error {
    anyhow!(err.to_string())
}

fn now_ts() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}

fn normalize_usage(body: &Value, fallback_email: &str) -> UsageData {
    let item = pick_traffic_obj(body, fallback_email);
    let up = item.get("up").and_then(|v| v.as_i64()).unwrap_or(0);
    let down = item.get("down").and_then(|v| v.as_i64()).unwrap_or(0);
    let total = item.get("total").and_then(|v| v.as_i64()).unwrap_or(-1);
    let used = up + down;
    let expire_at = parse_expiry(item.get("expiryTime").or_else(|| item.get("expiry_time")));
    let enabled = item.get("enable").and_then(|v| v.as_bool()).unwrap_or(true);
    let now = now_ts();
    let status = if !enabled {
        "suspended".to_string()
    } else if expire_at.is_some() && expire_at.unwrap_or_default() <= now {
        "expired".to_string()
    } else if total >= 0 && used >= total {
        "depleted".to_string()
    } else {
        "active".to_string()
    };
    let remaining_bytes = if total < 0 { None } else { Some((total - used).max(0)) };

    UsageData {
        client_email: item
            .get("email")
            .and_then(|v| v.as_str())
            .unwrap_or(fallback_email)
            .to_string(),
        client_id: item
            .get("id")
            .or_else(|| item.get("clientId"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        inbound_id: item.get("inboundId").and_then(|v| v.as_i64()),
        service_name: item
            .get("email")
            .and_then(|v| v.as_str())
            .unwrap_or(fallback_email)
            .to_string(),
        total_bytes: total,
        used_bytes: used,
        remaining_bytes,
        expire_at,
        status,
        synced_at: now,
    }
}

fn pick_traffic_obj<'a>(body: &'a Value, fallback_email: &str) -> &'a Value {
    let obj = body.get("obj").unwrap_or(body);
    if let Some(arr) = obj.as_array() {
        for item in arr {
            if item
                .get("email")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .eq_ignore_ascii_case(fallback_email)
            {
                return item;
            }
        }
        return arr.first().unwrap_or(&Value::Null);
    }
    if obj.get("email").is_some() {
        obj
    } else if let Some(client) = obj.get("client") {
        client
    } else {
        obj
    }
}

fn parse_expiry(v: Option<&Value>) -> Option<i64> {
    let raw = v.and_then(|x| x.as_i64())?;
    if raw <= 0 {
        return None;
    }
    if raw > 10_000_000_000 {
        Some(raw / 1000)
    } else {
        Some(raw)
    }
}

fn format_status_card(row: &UserServiceRow) -> String {
    let status_text = match row.status.as_str() {
        "active" => "✅ فعال",
        "expired" => "⛔ منقضی",
        "depleted" => "🚫 اتمام حجم",
        "suspended" => "⚠️ تعلیق",
        _ => "❓ نامشخص",
    };
    let total = row.total_bytes;
    let used = row.used_bytes.max(0);
    let (traffic_text, used_text, remain_text, percent_text) = if total < 0 {
        (
            "نامحدود".to_string(),
            format_gb(used),
            "نامحدود".to_string(),
            "-".to_string(),
        )
    } else {
        let remain = (total - used).max(0);
        let percent = if total > 0 {
            (remain as f64 / total as f64) * 100.0
        } else {
            0.0
        };
        (
            format_gb(total),
            format_gb(used),
            format_gb(remain),
            format!("{percent:.2}%"),
        )
    };

    let expiry_txt = row
        .expire_at
        .map(format_expiry)
        .unwrap_or_else(|| "ندارد (نامشخص)".to_string());

    format!(
        "📊وضعیت سرویس : {status_text}\n\
         👤 نام سرویس : {service_name}\n\n\
         🔋 ترافیک : {traffic_text}\n\
         📥 حجم مصرفی : {used_text}\n\
         💢 حجم باقی مانده : {remain_text} ({percent_text})\n\n\
         📅 تاریخ اتمام : {expiry_txt}",
        service_name = row.service_name
    )
}

fn format_expiry(exp: i64) -> String {
    let now = Utc::now();
    let dt = Utc.timestamp_opt(exp, 0).single().unwrap_or(now);
    let rem = dt - now;
    let rem_txt = if rem <= Duration::seconds(0) {
        "منقضی شده".to_string()
    } else {
        let total_minutes = rem.num_minutes();
        let months = total_minutes / (30 * 24 * 60);
        let rem_after_month = total_minutes % (30 * 24 * 60);
        let days = rem_after_month / (24 * 60);
        let rem_after_day = rem_after_month % (24 * 60);
        let hours = rem_after_day / 60;
        let minutes = rem_after_day % 60;
        format!("{months} ماه {days} روز {hours} ساعت {minutes} دقیقه دیگر")
    };
    format!("{} ({rem_txt})", dt.format("%Y/%m/%d"))
}

fn format_gb(bytes: i64) -> String {
    let gb = bytes as f64 / (1024_f64.powi(3));
    format!("{gb:.2} گیگابایت")
}
