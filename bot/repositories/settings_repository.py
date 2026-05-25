from __future__ import annotations

import json
from typing import Any

from bot.db import Database


class SettingsRepository:
    ROOT_DEFAULT_ENDUSER_SERVICE_ALERTS_DISABLED_KEY = "root_default_enduser_service_alerts_disabled_json"

    def __init__(self, *, db: Database) -> None:
        self.db = db

    async def get_app_setting(self, key: str, default: str | None = None) -> str | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            "SELECT value FROM app_settings WHERE key=? LIMIT 1;",
            (key,),
        )
        row = await cur.fetchone()
        return str(row["value"]) if row else default

    async def set_app_setting(self, key: str, value: str) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (key, value),
        )
        await self.db.conn.commit()

    async def get_user_notification_disabled_kinds(self, telegram_user_id: int) -> set[str]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT disabled_json
            FROM user_bot_notification_prefs
            WHERE telegram_user_id=?
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return set()
        raw = row["disabled_json"]
        if raw is None or raw == "":
            return set()
        try:
            data = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError):
            return set()
        if not isinstance(data, list):
            return set()
        return {str(x) for x in data if isinstance(x, str) and x.strip()}

    async def set_user_notification_disabled_kinds(self, telegram_user_id: int, disabled: set[str]) -> None:
        assert self.db.conn is not None
        payload = json.dumps(sorted(disabled), ensure_ascii=False)
        await self.db.conn.execute(
            """
            INSERT INTO user_bot_notification_prefs (telegram_user_id, disabled_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                disabled_json=excluded.disabled_json,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, payload),
        )
        await self.db.conn.commit()

    async def get_root_default_enduser_service_alert_disabled_kinds(self) -> set[str]:
        raw = await self.get_app_setting(self.ROOT_DEFAULT_ENDUSER_SERVICE_ALERTS_DISABLED_KEY, "[]")
        if raw is None or raw == "":
            return set()
        try:
            data = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError):
            return set()
        if not isinstance(data, list):
            return set()
        return {str(x) for x in data if isinstance(x, str) and x.strip()}

    async def set_root_default_enduser_service_alert_disabled_kinds(self, disabled: set[str]) -> None:
        payload = json.dumps(sorted(disabled), ensure_ascii=False)
        await self.set_app_setting(self.ROOT_DEFAULT_ENDUSER_SERVICE_ALERTS_DISABLED_KEY, payload)
