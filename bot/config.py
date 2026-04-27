from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Set
from urllib.parse import urlparse, urlunparse

from cryptography.fernet import Fernet
from dotenv import load_dotenv


def _parse_admin_ids(raw: str) -> Set[int]:
    ids: set[int] = set()
    for chunk in raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError:
            continue
    return ids


def _parse_proxy_list(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for chunk in raw.replace("\r", "\n").replace(",", "\n").split("\n"):
        proxy = chunk.strip()
        if proxy:
            values.append(proxy)
    return tuple(values)


def _normalize_sub_url_base(raw_base: str) -> str:
    value = raw_base.strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/sub"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _parse_sub_url_strip_port_rules(raw: str) -> dict[str, str]:
    rules: dict[str, str] = {}
    for chunk in raw.replace("\r", "\n").replace(",", "\n").split("\n"):
        value = chunk.strip()
        if not value or ":" not in value:
            continue
        panel_key, host = value.split(":", 1)
        panel_key = panel_key.strip().lower()
        base_url = _normalize_sub_url_base(host)
        if not panel_key or not base_url:
            continue
        rules[panel_key] = base_url
    return rules


def _parse_sub_url_base_overrides(raw: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for chunk in raw.replace("\r", "\n").replace(",", "\n").split("\n"):
        value = chunk.strip()
        if not value:
            continue
        sep = "=" if "=" in value else "|"
        if sep not in value:
            continue
        panel_key, base_url = value.split(sep, 1)
        panel_key = panel_key.strip().lower()
        base_url = base_url.strip().rstrip("/")
        if not panel_key or not base_url:
            continue
        overrides[panel_key] = base_url
    return overrides


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_ids: Set[int]
    database_path: str
    encryption_key: str
    request_timeout_seconds: int
    sync_interval_seconds: int
    timezone: str
    log_level: str
    log_json: bool
    metrics_enabled: bool
    metrics_host: str
    metrics_port: int
    admin_rate_limit_count: int
    admin_rate_limit_window_seconds: int
    depleted_client_delete_after_hours: int
    config_rotate_apply_delay_seconds: int
    low_traffic_list_threshold_mb: int
    telegram_proxies: tuple[str, ...]
    sub_url_strip_port_rules: dict[str, str]
    sub_url_base_overrides: dict[str, str]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise ValueError("BOT_TOKEN is required.")

        encryption_key = os.getenv("ENCRYPTION_KEY", "").strip()
        if not encryption_key:
            raise ValueError("ENCRYPTION_KEY is required.")
        Fernet(encryption_key.encode("utf-8"))

        admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
        if not admin_ids:
            raise ValueError("ADMIN_IDS must include at least one numeric Telegram ID.")

        return cls(
            bot_token=bot_token,
            admin_ids=admin_ids,
            database_path=os.getenv("DATABASE_PATH", "data/bot.db").strip(),
            encryption_key=encryption_key,
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
            sync_interval_seconds=int(os.getenv("SYNC_INTERVAL_SECONDS", "120")),
            timezone=os.getenv("TIMEZONE", "Asia/Tehran").strip() or "Asia/Tehran",
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
            log_json=_env_bool("LOG_JSON", True),
            metrics_enabled=_env_bool("METRICS_ENABLED", True),
            metrics_host=os.getenv("METRICS_HOST", "127.0.0.1").strip() or "127.0.0.1",
            metrics_port=int(os.getenv("METRICS_PORT", "9090")),
            admin_rate_limit_count=int(os.getenv("ADMIN_RATE_LIMIT_COUNT", "10")),
            admin_rate_limit_window_seconds=int(
                os.getenv("ADMIN_RATE_LIMIT_WINDOW_SECONDS", "60")
            ),
            depleted_client_delete_after_hours=int(
                os.getenv("DEPLETED_CLIENT_DELETE_AFTER_HOURS", "48")
            ),
            config_rotate_apply_delay_seconds=int(
                os.getenv("CONFIG_ROTATE_APPLY_DELAY_SECONDS", "4")
            ),
            low_traffic_list_threshold_mb=int(
                os.getenv("LOW_TRAFFIC_LIST_THRESHOLD_MB", "500")
            ),
            telegram_proxies=_parse_proxy_list(os.getenv("TELEGRAM_PROXIES", "")),
            sub_url_strip_port_rules=_parse_sub_url_strip_port_rules(
                os.getenv("SUB_URL_STRIP_PORT_RULES", "")
            ),
            sub_url_base_overrides=_parse_sub_url_base_overrides(
                os.getenv("SUB_URL_BASE_OVERRIDES", "")
            ),
        )
