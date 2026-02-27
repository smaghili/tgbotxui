from __future__ import annotations

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

XUI_REQUESTS = Counter("tgbot_xui_requests_total", "Total x-ui API requests", ["endpoint", "status"])
XUI_ERRORS = Counter("tgbot_xui_errors_total", "Total x-ui API errors", ["type"])
SYNC_RUNS = Counter("tgbot_sync_runs_total", "Total usage sync runs", ["result"])
USER_STATUS_REQUESTS = Counter(
    "tgbot_user_status_requests_total", "Total user status requests", ["result"]
)
PANEL_COUNT = Gauge("tgbot_panels_count", "Total registered panels")
USER_SERVICE_COUNT = Gauge("tgbot_user_services_count", "Total bound user services")


async def healthz(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def metrics(_: web.Request) -> web.Response:
    raw = generate_latest()
    return web.Response(body=raw, headers={"Content-Type": CONTENT_TYPE_LATEST})


def create_metrics_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/metrics", metrics)
    return app
