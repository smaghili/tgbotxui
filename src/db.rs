use anyhow::Result;
use serde::{Deserialize, Serialize};
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::{FromRow, Row, SqlitePool};

#[derive(Clone)]
pub struct Db {
    pub pool: SqlitePool,
}

#[derive(Debug, Clone, FromRow)]
pub struct PanelRow {
    pub id: i64,
    pub name: String,
    pub base_url: String,
    pub web_base_path: String,
    pub login_path: String,
    pub username_enc: String,
    pub password_enc: String,
    pub two_factor_enc: Option<String>,
    pub last_login_ok: i64,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, FromRow)]
pub struct UserServiceRow {
    pub id: i64,
    pub telegram_user_id: i64,
    pub panel_id: i64,
    pub inbound_id: Option<i64>,
    pub client_email: String,
    pub client_id: Option<String>,
    pub service_name: String,
    pub total_bytes: i64,
    pub used_bytes: i64,
    pub expire_at: Option<i64>,
    pub status: String,
    pub last_synced_at: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CookieJar {
    pub items: std::collections::HashMap<String, String>,
}

impl Db {
    pub async fn connect(database_url: &str) -> Result<Self> {
        let pool = SqlitePoolOptions::new()
            .max_connections(5)
            .connect(database_url)
            .await?;
        Ok(Self { pool })
    }

    pub async fn migrate(&self) -> Result<()> {
        sqlx::migrate!("./migrations").run(&self.pool).await?;
        Ok(())
    }

    pub async fn upsert_user(&self, telegram_user_id: i64, full_name: &str, username: Option<&str>, is_admin: bool) -> Result<()> {
        sqlx::query(
            r#"
            INSERT INTO users (telegram_user_id, full_name, username, is_admin, updated_at)
            VALUES (?1, ?2, ?3, ?4, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                full_name=excluded.full_name,
                username=excluded.username,
                is_admin=excluded.is_admin,
                updated_at=CURRENT_TIMESTAMP;
            "#,
        )
        .bind(telegram_user_id)
        .bind(full_name)
        .bind(username)
        .bind(if is_admin { 1_i64 } else { 0_i64 })
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn add_panel(
        &self,
        name: &str,
        base_url: &str,
        web_base_path: &str,
        login_path: &str,
        username_enc: &str,
        password_enc: &str,
        two_factor_enc: Option<&str>,
        created_by: i64,
    ) -> Result<i64> {
        let res = sqlx::query(
            r#"
            INSERT INTO panels (
                name, base_url, web_base_path, login_path, username_enc, password_enc, two_factor_enc, created_by
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8);
            "#,
        )
        .bind(name)
        .bind(base_url)
        .bind(web_base_path)
        .bind(login_path)
        .bind(username_enc)
        .bind(password_enc)
        .bind(two_factor_enc)
        .bind(created_by)
        .execute(&self.pool)
        .await?;
        Ok(res.last_insert_rowid())
    }

    pub async fn get_panel(&self, panel_id: i64) -> Result<Option<PanelRow>> {
        let row = sqlx::query_as::<_, PanelRow>(
            r#"
            SELECT id, name, base_url, web_base_path, login_path, username_enc, password_enc, two_factor_enc, last_login_ok, last_error
            FROM panels WHERE id = ?1;
            "#,
        )
        .bind(panel_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(row)
    }

    pub async fn list_panels(&self) -> Result<Vec<PanelRow>> {
        let rows = sqlx::query_as::<_, PanelRow>(
            r#"
            SELECT id, name, base_url, web_base_path, login_path, username_enc, password_enc, two_factor_enc, last_login_ok, last_error
            FROM panels ORDER BY id DESC;
            "#,
        )
        .fetch_all(&self.pool)
        .await?;
        Ok(rows)
    }

    pub async fn set_panel_login_status(&self, panel_id: i64, ok: bool, last_error: Option<&str>) -> Result<()> {
        sqlx::query(
            r#"
            UPDATE panels
            SET last_login_ok = ?1, last_error = ?2, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?3;
            "#,
        )
        .bind(if ok { 1_i64 } else { 0_i64 })
        .bind(last_error)
        .bind(panel_id)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn save_panel_session(&self, panel_id: i64, jar: &CookieJar) -> Result<()> {
        let json = serde_json::to_string(jar)?;
        sqlx::query(
            r#"
            INSERT INTO panel_sessions (panel_id, cookies_json)
            VALUES (?1, ?2)
            ON CONFLICT(panel_id) DO UPDATE SET
                cookies_json = excluded.cookies_json,
                updated_at = CURRENT_TIMESTAMP;
            "#,
        )
        .bind(panel_id)
        .bind(json)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn get_panel_session(&self, panel_id: i64) -> Result<CookieJar> {
        let row = sqlx::query("SELECT cookies_json FROM panel_sessions WHERE panel_id = ?1;")
            .bind(panel_id)
            .fetch_optional(&self.pool)
            .await?;

        if let Some(row) = row {
            let raw: String = row.get("cookies_json");
            let jar = serde_json::from_str::<CookieJar>(&raw).unwrap_or_default();
            Ok(jar)
        } else {
            Ok(CookieJar::default())
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn bind_user_service(
        &self,
        telegram_user_id: i64,
        panel_id: i64,
        inbound_id: Option<i64>,
        client_email: &str,
        client_id: Option<&str>,
        service_name: &str,
        total_bytes: i64,
        used_bytes: i64,
        expire_at: Option<i64>,
        status: &str,
        last_synced_at: i64,
    ) -> Result<i64> {
        sqlx::query(
            r#"
            INSERT INTO user_services (
                telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                total_bytes, used_bytes, expire_at, status, last_synced_at, updated_at
            )
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id, panel_id, client_email) DO UPDATE SET
                inbound_id=excluded.inbound_id,
                client_id=excluded.client_id,
                service_name=excluded.service_name,
                total_bytes=excluded.total_bytes,
                used_bytes=excluded.used_bytes,
                expire_at=excluded.expire_at,
                status=excluded.status,
                last_synced_at=excluded.last_synced_at,
                updated_at=CURRENT_TIMESTAMP;
            "#,
        )
        .bind(telegram_user_id)
        .bind(panel_id)
        .bind(inbound_id)
        .bind(client_email)
        .bind(client_id)
        .bind(service_name)
        .bind(total_bytes)
        .bind(used_bytes)
        .bind(expire_at)
        .bind(status)
        .bind(last_synced_at)
        .execute(&self.pool)
        .await?;

        let id: i64 = sqlx::query_scalar(
            r#"
            SELECT id FROM user_services
            WHERE telegram_user_id=?1 AND panel_id=?2 AND client_email=?3;
            "#,
        )
        .bind(telegram_user_id)
        .bind(panel_id)
        .bind(client_email)
        .fetch_one(&self.pool)
        .await?;
        Ok(id)
    }

    pub async fn get_user_services(&self, telegram_user_id: i64) -> Result<Vec<UserServiceRow>> {
        let rows = sqlx::query_as::<_, UserServiceRow>(
            r#"
            SELECT
              id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
              total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE telegram_user_id = ?1
            ORDER BY id ASC;
            "#,
        )
        .bind(telegram_user_id)
        .fetch_all(&self.pool)
        .await?;
        Ok(rows)
    }

    pub async fn get_all_user_services(&self) -> Result<Vec<UserServiceRow>> {
        let rows = sqlx::query_as::<_, UserServiceRow>(
            r#"
            SELECT
              id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
              total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            ORDER BY id ASC;
            "#,
        )
        .fetch_all(&self.pool)
        .await?;
        Ok(rows)
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn update_user_service_stats(
        &self,
        service_id: i64,
        total_bytes: i64,
        used_bytes: i64,
        expire_at: Option<i64>,
        status: &str,
        service_name: &str,
        client_id: Option<&str>,
        inbound_id: Option<i64>,
        last_synced_at: i64,
    ) -> Result<()> {
        sqlx::query(
            r#"
            UPDATE user_services
            SET total_bytes=?1, used_bytes=?2, expire_at=?3, status=?4, service_name=?5,
                client_id=?6, inbound_id=?7, last_synced_at=?8, updated_at=CURRENT_TIMESTAMP
            WHERE id=?9;
            "#,
        )
        .bind(total_bytes)
        .bind(used_bytes)
        .bind(expire_at)
        .bind(status)
        .bind(service_name)
        .bind(client_id)
        .bind(inbound_id)
        .bind(last_synced_at)
        .bind(service_id)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn add_usage_snapshot(
        &self,
        user_service_id: i64,
        used_bytes: i64,
        total_bytes: i64,
        remaining_bytes: Option<i64>,
        status: &str,
        synced_at: i64,
    ) -> Result<()> {
        sqlx::query(
            r#"
            INSERT INTO usage_snapshots (user_service_id, used_bytes, total_bytes, remaining_bytes, status, synced_at)
            VALUES (?1, ?2, ?3, ?4, ?5, ?6);
            "#,
        )
        .bind(user_service_id)
        .bind(used_bytes)
        .bind(total_bytes)
        .bind(remaining_bytes)
        .bind(status)
        .bind(synced_at)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn add_audit_log(
        &self,
        actor_user_id: Option<i64>,
        action: &str,
        target_type: Option<&str>,
        target_id: Option<&str>,
        success: bool,
        details: Option<&str>,
    ) -> Result<()> {
        sqlx::query(
            r#"
            INSERT INTO audit_logs (actor_user_id, action, target_type, target_id, success, details)
            VALUES (?1, ?2, ?3, ?4, ?5, ?6);
            "#,
        )
        .bind(actor_user_id)
        .bind(action)
        .bind(target_type)
        .bind(target_id)
        .bind(if success { 1_i64 } else { 0_i64 })
        .bind(details)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn count_panels(&self) -> Result<i64> {
        Ok(sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM panels;")
            .fetch_one(&self.pool)
            .await?)
    }

    pub async fn count_user_services(&self) -> Result<i64> {
        Ok(sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM user_services;")
            .fetch_one(&self.pool)
            .await?)
    }
}
