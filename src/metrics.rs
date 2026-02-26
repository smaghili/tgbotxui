use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::{routing::get, Router};
use once_cell::sync::Lazy;
use prometheus::{
    opts, register_counter_vec, register_int_gauge, Encoder, CounterVec, IntGauge, TextEncoder,
};

pub static XUI_REQUESTS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        opts!("tgbot_xui_requests_total", "Total x-ui API requests"),
        &["endpoint", "status"]
    )
    .expect("xui requests metric")
});

pub static XUI_ERRORS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        opts!("tgbot_xui_errors_total", "Total x-ui API errors"),
        &["type"]
    )
    .expect("xui errors metric")
});

pub static SYNC_RUNS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        opts!("tgbot_sync_runs_total", "Total usage sync runs"),
        &["result"]
    )
    .expect("sync runs metric")
});

pub static USER_STATUS_REQUESTS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        opts!(
            "tgbot_user_status_requests_total",
            "Total user status requests by result"
        ),
        &["result"]
    )
    .expect("status metric")
});

pub static PANEL_COUNT: Lazy<IntGauge> =
    Lazy::new(|| register_int_gauge!("tgbot_panels_count", "Total registered panels").expect("panel gauge"));

pub static USER_SERVICE_COUNT: Lazy<IntGauge> = Lazy::new(|| {
    register_int_gauge!("tgbot_user_services_count", "Total bound user services")
        .expect("service gauge")
});

pub fn router() -> Router {
    Router::new()
        .route("/healthz", get(healthz))
        .route("/metrics", get(metrics))
}

async fn healthz() -> impl IntoResponse {
    (StatusCode::OK, "{\"status\":\"ok\"}")
}

async fn metrics() -> Response {
    let encoder = TextEncoder::new();
    let metric_families = prometheus::gather();
    let mut buffer = Vec::<u8>::new();
    if encoder.encode(&metric_families, &mut buffer).is_err() {
        return (StatusCode::INTERNAL_SERVER_ERROR, "metrics encode error").into_response();
    }
    (StatusCode::OK, String::from_utf8_lossy(&buffer).to_string()).into_response()
}
