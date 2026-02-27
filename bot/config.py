from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Set

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
            sync_interval_seconds=int(os.getenv("SYNC_INTERVAL_SECONDS", "180")),
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
        )
