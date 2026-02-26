use std::collections::HashMap;
use std::time::Duration;

use anyhow::{anyhow, Result};
use reqwest::header::{COOKIE, SET_COOKIE};
use reqwest::{Method, StatusCode};
use serde_json::Value;
use thiserror::Error;

use crate::metrics::{XUI_ERRORS, XUI_REQUESTS};

#[derive(Debug, Clone)]
pub struct PanelConnection {
    pub base_url: String,
    pub web_base_path: String,
    pub login_path: String,
    pub username: String,
    pub password: String,
    pub two_factor: Option<String>,
}

#[derive(Debug, Error)]
pub enum XuiError {
    #[error("authentication failed")]
    Auth,
    #[error("validation failed: {0}")]
    Validation(String),
    #[error("rate limited")]
    RateLimited,
    #[error("server error: {0}")]
    Server(String),
    #[error("request error: {0}")]
    Request(String),
}

#[derive(Clone)]
pub struct XuiClient {
    client: reqwest::Client,
    max_retries: u8,
}

impl XuiClient {
    pub fn new(timeout_seconds: u64) -> Result<Self> {
        let client = reqwest::ClientBuilder::new()
            .timeout(Duration::from_secs(timeout_seconds))
            .build()?;
        Ok(Self { client, max_retries: 2 })
    }

    pub async fn login(&self, conn: &PanelConnection) -> std::result::Result<HashMap<String, String>, XuiError> {
        let url = format!("{}{}", conn.base_url, conn.login_path);
        let mut payload = serde_json::json!({
            "username": conn.username,
            "password": conn.password,
        });
        if let Some(two) = &conn.two_factor {
            payload["twoFactorCode"] = Value::String(two.clone());
        }

        let response = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| XuiError::Request(e.to_string()))?;

        let status = response.status();
        if status == StatusCode::UNAUTHORIZED {
            XUI_REQUESTS.with_label_values(&["/login/", "401"]).inc();
            XUI_ERRORS.with_label_values(&["auth"]).inc();
            return Err(XuiError::Auth);
        }
        if matches!(status, StatusCode::BAD_REQUEST | StatusCode::UNPROCESSABLE_ENTITY | StatusCode::UNSUPPORTED_MEDIA_TYPE) {
            let response = self
                .client
                .post(&url)
                .form(&[
                    ("username", conn.username.as_str()),
                    ("password", conn.password.as_str()),
                    ("twoFactorCode", conn.two_factor.as_deref().unwrap_or("")),
                ])
                .send()
                .await
                .map_err(|e| XuiError::Request(e.to_string()))?;
            return self.handle_login_response(response).await;
        }
        self.handle_login_response(response).await
    }

    async fn handle_login_response(
        &self,
        response: reqwest::Response,
    ) -> std::result::Result<HashMap<String, String>, XuiError> {
        let status = response.status();
        let endpoint = "/login/";
        let text = response.text().await.unwrap_or_default();

        if status == StatusCode::TOO_MANY_REQUESTS {
            XUI_REQUESTS.with_label_values(&[endpoint, "429"]).inc();
            XUI_ERRORS.with_label_values(&["rate_limit"]).inc();
            return Err(XuiError::RateLimited);
        }
        if status.is_server_error() {
            XUI_REQUESTS.with_label_values(&[endpoint, "5xx"]).inc();
            XUI_ERRORS.with_label_values(&["server"]).inc();
            return Err(XuiError::Server(text.chars().take(300).collect()));
        }
        if status.is_client_error() {
            XUI_REQUESTS.with_label_values(&[endpoint, "4xx"]).inc();
            XUI_ERRORS.with_label_values(&["validation"]).inc();
            return Err(XuiError::Validation(text.chars().take(300).collect()));
        }

        let body: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
        if let Some(false) = body.get("success").and_then(|v| v.as_bool()) {
            XUI_REQUESTS.with_label_values(&[endpoint, "app_error"]).inc();
            XUI_ERRORS.with_label_values(&["app"]).inc();
            return Err(XuiError::Request(
                body.get("msg")
                    .and_then(|v| v.as_str())
                    .unwrap_or("3x-ui rejected login")
                    .to_string(),
            ));
        }

        let cookies = extract_set_cookies_raw(&response);
        if cookies.is_empty() {
            XUI_REQUESTS.with_label_values(&[endpoint, "no_cookie"]).inc();
            XUI_ERRORS.with_label_values(&["no_cookie"]).inc();
            return Err(XuiError::Request("no cookie returned".to_string()));
        }
        XUI_REQUESTS.with_label_values(&[endpoint, "ok"]).inc();
        Ok(cookies)
    }

    pub async fn get_client_traffics(
        &self,
        conn: &PanelConnection,
        cookies: &HashMap<String, String>,
        client_email: &str,
    ) -> std::result::Result<(Value, HashMap<String, String>), XuiError> {
        let endpoint = format!("/inbounds/getClientTraffics/{}", urlencoding::encode(client_email));
        self.request(conn, Method::GET, &endpoint, cookies, None).await
    }

    pub async fn request(
        &self,
        conn: &PanelConnection,
        method: Method,
        endpoint: &str,
        cookies: &HashMap<String, String>,
        payload: Option<Value>,
    ) -> std::result::Result<(Value, HashMap<String, String>), XuiError> {
        let api_path = format!(
            "{}/panel/api{}",
            normalize_base_path(&conn.web_base_path),
            if endpoint.starts_with('/') { endpoint.to_string() } else { format!("/{}", endpoint) }
        );
        let url = format!("{}{}", conn.base_url, api_path);
        let cookie_header = build_cookie_header(cookies);

        for attempt in 0..=self.max_retries {
            let mut req = self.client.request(method.clone(), &url);
            if !cookie_header.is_empty() {
                req = req.header(COOKIE, &cookie_header);
            }
            if let Some(ref p) = payload {
                req = req.json(p);
            }
            let response = req
                .send()
                .await
                .map_err(|e| XuiError::Request(e.to_string()))?;

            let status = response.status();
            if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
                XUI_REQUESTS.with_label_values(&[endpoint, "auth"]).inc();
                XUI_ERRORS.with_label_values(&["auth"]).inc();
                return Err(XuiError::Auth);
            }
            if status == StatusCode::TOO_MANY_REQUESTS {
                if attempt < self.max_retries {
                    tokio::time::sleep(Duration::from_millis(300 * (attempt as u64 + 1))).await;
                    continue;
                }
                XUI_REQUESTS.with_label_values(&[endpoint, "429"]).inc();
                XUI_ERRORS.with_label_values(&["rate_limit"]).inc();
                return Err(XuiError::RateLimited);
            }
            if status.is_server_error() {
                if attempt < self.max_retries {
                    tokio::time::sleep(Duration::from_millis(300 * (attempt as u64 + 1))).await;
                    continue;
                }
                let text = response.text().await.unwrap_or_default();
                XUI_REQUESTS.with_label_values(&[endpoint, "5xx"]).inc();
                XUI_ERRORS.with_label_values(&["server"]).inc();
                return Err(XuiError::Server(text.chars().take(300).collect()));
            }
            if matches!(status, StatusCode::BAD_REQUEST | StatusCode::UNPROCESSABLE_ENTITY | StatusCode::UNSUPPORTED_MEDIA_TYPE)
            {
                let text = response.text().await.unwrap_or_default();
                XUI_REQUESTS.with_label_values(&[endpoint, "validation"]).inc();
                XUI_ERRORS.with_label_values(&["validation"]).inc();
                return Err(XuiError::Validation(text.chars().take(300).collect()));
            }
            if status.is_client_error() {
                let text = response.text().await.unwrap_or_default();
                XUI_REQUESTS.with_label_values(&[endpoint, "4xx"]).inc();
                XUI_ERRORS.with_label_values(&["request"]).inc();
                return Err(XuiError::Request(text.chars().take(300).collect()));
            }

            let new_cookies = extract_set_cookies_raw(&response);
            let text = response.text().await.unwrap_or_default();
            let body: Value = serde_json::from_str(&text)
                .map_err(|e| XuiError::Request(format!("invalid json response: {e}")))?;
            if let Some(false) = body.get("success").and_then(|v| v.as_bool()) {
                return Err(XuiError::Request(
                    body.get("msg")
                        .and_then(|v| v.as_str())
                        .unwrap_or("3x-ui rejected request")
                        .to_string(),
                ));
            }
            XUI_REQUESTS.with_label_values(&[endpoint, "ok"]).inc();
            return Ok((body, new_cookies));
        }

        Err(XuiError::Request("request exhausted retries".to_string()))
    }
}

pub fn parse_login_url(raw_login_url: &str) -> Result<(String, String, String)> {
    let mut raw = raw_login_url.trim().to_string();
    if raw.is_empty() {
        return Err(anyhow!("login url is empty"));
    }
    if !raw.contains("://") {
        raw = format!("http://{raw}");
    }
    let parsed = url::Url::parse(&raw).map_err(|_| anyhow!("invalid login url"))?;
    let mut path = parsed.path().to_string();
    if path.is_empty() {
        path = "/login/".to_string();
    }
    if !path.ends_with('/') {
        path.push('/');
    }
    if !path.to_ascii_lowercase().ends_with("/login/") {
        return Err(anyhow!("login url must end with /login/"));
    }
    let mut web_base_path = path.trim_end_matches("/login/").to_string();
    if web_base_path == "/" {
        web_base_path.clear();
    }
    let base_url = format!("{}://{}", parsed.scheme(), parsed.host_str().unwrap_or_default());
    let base_url = if let Some(port) = parsed.port() {
        format!("{base_url}:{port}")
    } else {
        base_url
    };
    Ok((base_url, web_base_path, path))
}

fn normalize_base_path(path: &str) -> String {
    if path.trim().is_empty() {
        "".to_string()
    } else if path.starts_with('/') {
        path.trim_end_matches('/').to_string()
    } else {
        format!("/{}", path.trim_end_matches('/'))
    }
}

fn build_cookie_header(cookies: &HashMap<String, String>) -> String {
    cookies
        .iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("; ")
}

fn extract_set_cookies_raw(response: &reqwest::Response) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for value in response.headers().get_all(SET_COOKIE).iter() {
        if let Ok(raw) = value.to_str() {
            if let Some((first, _)) = raw.split_once(';') {
                if let Some((name, val)) = first.split_once('=') {
                    out.insert(name.trim().to_string(), val.trim().to_string());
                }
            }
        }
    }
    out
}
