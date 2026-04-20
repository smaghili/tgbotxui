from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from bot.migration_runner import MigrationRunner


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def init_schema(self) -> int:
        assert self.conn is not None
        runner = MigrationRunner(self.conn, str(Path(__file__).resolve().parent / "migrations"))
        return await runner.migrate()

    async def upsert_user(
        self, telegram_user_id: int, full_name: str, username: str | None, is_admin: bool
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO users (telegram_user_id, full_name, username, is_admin, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                full_name=excluded.full_name,
                username=excluded.username,
                is_admin=excluded.is_admin,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, full_name, username, int(is_admin)),
        )
        await self.conn.commit()

    async def find_user_by_username(self, username: str) -> Dict[str, Any] | None:
        assert self.conn is not None
        normalized = username.strip().lstrip("@")
        if not normalized:
            return None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, full_name, username, is_admin
            FROM users
            WHERE LOWER(username)=LOWER(?)
            LIMIT 1;
            """,
            (normalized,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_user_language(self, telegram_user_id: int) -> str:
        assert self.conn is not None
        cur = await self.conn.execute(
            "SELECT language FROM users WHERE telegram_user_id=? LIMIT 1;",
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return "fa"
        value = str(row["language"] or "fa").strip().lower()
        return value if value in {"fa", "en"} else "fa"

    async def set_user_language(self, telegram_user_id: int, language: str) -> None:
        assert self.conn is not None
        lang = language.strip().lower()
        if lang not in {"fa", "en"}:
            lang = "fa"
        await self.conn.execute(
            """
            UPDATE users
            SET language=?, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (lang, telegram_user_id),
        )
        await self.conn.commit()

    async def get_app_setting(self, key: str, default: str | None = None) -> str | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            "SELECT value FROM app_settings WHERE key=? LIMIT 1;",
            (key,),
        )
        row = await cur.fetchone()
        return str(row["value"]) if row else default

    async def set_app_setting(self, key: str, value: str) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (key, value),
        )
        await self.conn.commit()

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, full_name, username, is_admin, language
            FROM users
            WHERE telegram_user_id=?
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_delegated_admin(
        self,
        *,
        telegram_user_id: int,
        title: str | None,
        created_by: int,
    ) -> int:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegated_admins (telegram_user_id, title, created_by, is_active, updated_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                title=excluded.title,
                is_active=1,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, title, created_by),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            """
            SELECT id
            FROM delegated_admins
            WHERE telegram_user_id=?
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return int(row["id"])

    async def get_delegated_admin_by_user_id(self, telegram_user_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, title, created_by, is_active, created_at, updated_at
            FROM delegated_admins
            WHERE telegram_user_id=? AND is_active=1
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def ensure_delegated_admin_profile(self, telegram_user_id: int) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegated_admin_profiles (
                telegram_user_id, updated_at
            ) VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                updated_at=delegated_admin_profiles.updated_at;
            """,
            (telegram_user_id,),
        )
        await self.conn.commit()

    async def get_delegated_admin_profile(self, telegram_user_id: int) -> Dict[str, Any]:
        assert self.conn is not None
        await self.ensure_delegated_admin_profile(telegram_user_id)
        cur = await self.conn.execute(
            """
            SELECT
                telegram_user_id,
                username_prefix,
                max_clients,
                min_traffic_gb,
                max_traffic_gb,
                min_expiry_days,
                max_expiry_days,
                charge_basis,
                is_active,
                expires_at,
                created_at,
                updated_at
            FROM delegated_admin_profiles
            WHERE telegram_user_id=?
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "telegram_user_id": telegram_user_id,
            "username_prefix": None,
            "max_clients": 0,
            "min_traffic_gb": 1,
            "max_traffic_gb": 0,
            "min_expiry_days": 1,
            "max_expiry_days": 0,
            "charge_basis": "allocated",
            "is_active": 1,
            "expires_at": None,
        }

    async def update_delegated_admin_profile(
        self,
        *,
        telegram_user_id: int,
        username_prefix: str | None = None,
        max_clients: int | None = None,
        min_traffic_gb: int | None = None,
        max_traffic_gb: int | None = None,
        min_expiry_days: int | None = None,
        max_expiry_days: int | None = None,
        charge_basis: str | None = None,
        is_active: int | None = None,
        expires_at: int | None = None,
    ) -> Dict[str, Any]:
        assert self.conn is not None
        await self.ensure_delegated_admin_profile(telegram_user_id)
        current = await self.get_delegated_admin_profile(telegram_user_id)
        payload = {
            "username_prefix": current.get("username_prefix") if username_prefix is None else username_prefix,
            "max_clients": int(current.get("max_clients") or 0) if max_clients is None else max_clients,
            "min_traffic_gb": int(current.get("min_traffic_gb") or 1) if min_traffic_gb is None else min_traffic_gb,
            "max_traffic_gb": int(current.get("max_traffic_gb") or 0) if max_traffic_gb is None else max_traffic_gb,
            "min_expiry_days": int(current.get("min_expiry_days") or 1) if min_expiry_days is None else min_expiry_days,
            "max_expiry_days": int(current.get("max_expiry_days") or 0) if max_expiry_days is None else max_expiry_days,
            "charge_basis": str(current.get("charge_basis") or "allocated") if charge_basis is None else charge_basis,
            "is_active": int(current.get("is_active") or 1) if is_active is None else is_active,
            "expires_at": current.get("expires_at") if expires_at is None else expires_at,
        }
        if payload["charge_basis"] not in {"allocated", "consumed"}:
            raise ValueError("invalid delegated charge basis.")
        if payload["max_clients"] < 0:
            raise ValueError("delegated max clients cannot be negative.")
        if payload["min_traffic_gb"] < 0 or payload["max_traffic_gb"] < 0:
            raise ValueError("delegated traffic limits cannot be negative.")
        if payload["min_expiry_days"] < 0 or payload["max_expiry_days"] < 0:
            raise ValueError("delegated expiry limits cannot be negative.")
        if payload["max_traffic_gb"] > 0 and payload["min_traffic_gb"] > payload["max_traffic_gb"]:
            raise ValueError("delegated min traffic cannot exceed max traffic.")
        if payload["max_expiry_days"] > 0 and payload["min_expiry_days"] > payload["max_expiry_days"]:
            raise ValueError("delegated min expiry cannot exceed max expiry.")
        await self.conn.execute(
            """
            UPDATE delegated_admin_profiles
            SET
                username_prefix=?,
                max_clients=?,
                min_traffic_gb=?,
                max_traffic_gb=?,
                min_expiry_days=?,
                max_expiry_days=?,
                charge_basis=?,
                is_active=?,
                expires_at=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (
                payload["username_prefix"],
                payload["max_clients"],
                payload["min_traffic_gb"],
                payload["max_traffic_gb"],
                payload["min_expiry_days"],
                payload["max_expiry_days"],
                payload["charge_basis"],
                payload["is_active"],
                payload["expires_at"],
                telegram_user_id,
            ),
        )
        await self.conn.commit()
        return await self.get_delegated_admin_profile(telegram_user_id)

    async def list_recent_wallet_transactions(
        self,
        *,
        telegram_user_id: int,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, actor_user_id, amount, balance_after, currency,
                   kind, operation, status, reference_transaction_id, details, metadata_json, created_at
            FROM wallet_transactions
            WHERE telegram_user_id=?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (telegram_user_id, max(1, int(limit))),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def list_recent_actor_audit_logs(
        self,
        *,
        actor_user_id: int,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, actor_user_id, action, target_type, target_id, success, details, created_at
            FROM audit_logs
            WHERE actor_user_id=?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (actor_user_id, max(1, int(limit))),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def add_delegated_admin_inbound_access(
        self,
        *,
        delegated_admin_id: int,
        panel_id: int,
        inbound_id: int,
    ) -> int:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegated_admin_inbounds (delegated_admin_id, panel_id, inbound_id, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(delegated_admin_id, panel_id, inbound_id) DO UPDATE SET
                updated_at=CURRENT_TIMESTAMP;
            """,
            (delegated_admin_id, panel_id, inbound_id),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            """
            SELECT id
            FROM delegated_admin_inbounds
            WHERE delegated_admin_id=? AND panel_id=? AND inbound_id=?
            LIMIT 1;
            """,
            (delegated_admin_id, panel_id, inbound_id),
        )
        row = await cur.fetchone()
        return int(row["id"])

    async def revoke_delegated_admin_access(self, access_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute(
            "DELETE FROM delegated_admin_inbounds WHERE id=?;",
            (access_id,),
        )
        await self.conn.commit()
        return (cur.rowcount or 0) > 0

    async def deactivate_delegated_admin(self, telegram_user_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            UPDATE delegated_admins
            SET is_active=0, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (telegram_user_id,),
        )
        await self.conn.execute(
            """
            UPDATE delegated_admin_profiles
            SET is_active=0, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (telegram_user_id,),
        )
        await self.conn.commit()
        return (cur.rowcount or 0) > 0

    async def list_delegated_admin_access_rows(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT
                dai.id AS access_id,
                da.id AS delegated_admin_id,
                da.telegram_user_id,
                da.title,
                da.is_active,
                da.created_by,
                dai.panel_id,
                p.name AS panel_name,
                dai.inbound_id,
                u.full_name,
                u.username
            FROM delegated_admin_inbounds AS dai
            JOIN delegated_admins AS da ON da.id = dai.delegated_admin_id
            JOIN panels AS p ON p.id = dai.panel_id
            LEFT JOIN users AS u ON u.telegram_user_id = da.telegram_user_id
            WHERE da.is_active=1
            ORDER BY da.telegram_user_id ASC, dai.panel_id ASC, dai.inbound_id ASC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def list_admin_access_rows_for_user(self, telegram_user_id: int) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT
                dai.id AS access_id,
                da.id AS delegated_admin_id,
                da.telegram_user_id,
                da.title,
                dai.panel_id,
                p.name AS panel_name,
                dai.inbound_id
            FROM delegated_admin_inbounds AS dai
            JOIN delegated_admins AS da ON da.id = dai.delegated_admin_id
            JOIN panels AS p ON p.id = dai.panel_id
            WHERE da.telegram_user_id=? AND da.is_active=1
            ORDER BY dai.panel_id ASC, dai.inbound_id ASC;
            """,
            (telegram_user_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def has_admin_access_to_inbound(
        self,
        *,
        telegram_user_id: int,
        panel_id: int,
        inbound_id: int,
    ) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT 1
            FROM delegated_admin_inbounds AS dai
            JOIN delegated_admins AS da ON da.id = dai.delegated_admin_id
            WHERE da.telegram_user_id=? AND da.is_active=1 AND dai.panel_id=? AND dai.inbound_id=?
            LIMIT 1;
            """,
            (telegram_user_id, panel_id, inbound_id),
        )
        row = await cur.fetchone()
        return row is not None

    async def get_delegated_admin_client_alert_state(
        self,
        *,
        delegated_admin_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> str | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT alert_state
            FROM delegated_admin_client_alerts
            WHERE delegated_admin_user_id=? AND panel_id=? AND inbound_id=? AND client_uuid=?
            LIMIT 1;
            """,
            (delegated_admin_user_id, panel_id, inbound_id, client_uuid),
        )
        row = await cur.fetchone()
        return str(row["alert_state"]) if row else None

    async def get_delegated_admin_client_alert_states(
        self,
        *,
        delegated_admin_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> tuple[str | None, str | None]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT traffic_alert_state, expiry_alert_state, alert_state
            FROM delegated_admin_client_alerts
            WHERE delegated_admin_user_id=? AND panel_id=? AND inbound_id=? AND client_uuid=?
            LIMIT 1;
            """,
            (delegated_admin_user_id, panel_id, inbound_id, client_uuid),
        )
        row = await cur.fetchone()
        if row is None:
            return None, None
        traffic = row["traffic_alert_state"] if "traffic_alert_state" in row.keys() else row["alert_state"]
        expiry = row["expiry_alert_state"] if "expiry_alert_state" in row.keys() else "normal"
        return str(traffic), str(expiry)

    async def upsert_delegated_admin_client_alert_state(
        self,
        *,
        delegated_admin_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        alert_state: str,
        mark_notified: bool,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegated_admin_client_alerts (
                delegated_admin_user_id, panel_id, inbound_id, client_uuid, alert_state, last_notified_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, CURRENT_TIMESTAMP)
            ON CONFLICT(delegated_admin_user_id, panel_id, inbound_id, client_uuid) DO UPDATE SET
                alert_state=excluded.alert_state,
                last_notified_at=CASE WHEN excluded.last_notified_at IS NOT NULL THEN excluded.last_notified_at ELSE delegated_admin_client_alerts.last_notified_at END,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                delegated_admin_user_id,
                panel_id,
                inbound_id,
                client_uuid,
                alert_state,
                int(mark_notified),
            ),
        )
        await self.conn.commit()

    async def upsert_delegated_admin_client_alert_states(
        self,
        *,
        delegated_admin_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        traffic_alert_state: str,
        expiry_alert_state: str,
        mark_notified: bool,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegated_admin_client_alerts (
                delegated_admin_user_id, panel_id, inbound_id, client_uuid,
                alert_state, traffic_alert_state, expiry_alert_state, last_notified_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, CURRENT_TIMESTAMP
            )
            ON CONFLICT(delegated_admin_user_id, panel_id, inbound_id, client_uuid) DO UPDATE SET
                alert_state=excluded.alert_state,
                traffic_alert_state=excluded.traffic_alert_state,
                expiry_alert_state=excluded.expiry_alert_state,
                last_notified_at=CASE WHEN excluded.last_notified_at IS NOT NULL THEN excluded.last_notified_at ELSE delegated_admin_client_alerts.last_notified_at END,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                delegated_admin_user_id,
                panel_id,
                inbound_id,
                client_uuid,
                traffic_alert_state,
                traffic_alert_state,
                expiry_alert_state,
                int(mark_notified),
            ),
        )
        await self.conn.commit()

    async def add_panel(
        self,
        *,
        name: str,
        base_url: str,
        web_base_path: str,
        login_path: str,
        username_enc: str,
        password_enc: str,
        two_factor_enc: str | None,
        created_by: int,
    ) -> int:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            INSERT INTO panels (
                name, base_url, web_base_path, login_path, username_enc, password_enc, two_factor_enc, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                name,
                base_url,
                web_base_path,
                login_path,
                username_enc,
                password_enc,
                two_factor_enc,
                created_by,
            ),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def get_panel(self, panel_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT * FROM panels WHERE id=?;", (panel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_panels(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, is_default, last_login_ok, last_error, updated_at
            FROM panels ORDER BY id DESC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_default_panel(self) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, is_default, last_login_ok, last_error, updated_at
            FROM panels
            WHERE is_default=1
            LIMIT 1;
            """
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_default_panel(self, panel_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT id FROM panels WHERE id=? LIMIT 1;", (panel_id,))
        row = await cur.fetchone()
        if row is None:
            return False
        await self.conn.execute("UPDATE panels SET is_default=0 WHERE is_default=1;")
        await self.conn.execute("UPDATE panels SET is_default=1 WHERE id=?;", (panel_id,))
        await self.conn.commit()
        return True

    async def clear_default_panel(self) -> None:
        assert self.conn is not None
        await self.conn.execute("UPDATE panels SET is_default=0 WHERE is_default=1;")
        await self.conn.commit()

    async def delete_panel(self, panel_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute("DELETE FROM panels WHERE id=?;", (panel_id,))
        await self.conn.commit()
        return (cur.rowcount or 0) > 0

    async def set_panel_login_status(self, panel_id: int, ok: bool, last_error: str | None) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE panels
            SET last_login_ok=?, last_error=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?;
            """,
            (int(ok), last_error, panel_id),
        )
        await self.conn.commit()

    async def save_panel_session(self, panel_id: int, cookies: Dict[str, str]) -> None:
        assert self.conn is not None
        raw = json.dumps(cookies, ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT INTO panel_sessions(panel_id, cookies_json)
            VALUES (?, ?)
            ON CONFLICT(panel_id) DO UPDATE SET
                cookies_json=excluded.cookies_json,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (panel_id, raw),
        )
        await self.conn.commit()

    async def get_panel_session(self, panel_id: int) -> Dict[str, str] | None:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT cookies_json FROM panel_sessions WHERE panel_id=?;", (panel_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return json.loads(row["cookies_json"])

    async def bind_user_service(
        self,
        *,
        telegram_user_id: int,
        panel_id: int,
        inbound_id: int | None,
        client_email: str,
        client_id: str | None,
        service_name: str,
        total_bytes: int,
        used_bytes: int,
        expire_at: int | None,
        status: str,
        last_synced_at: int,
    ) -> int:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO user_services (
                telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                total_bytes, used_bytes, expire_at, status, last_synced_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
            """,
            (
                telegram_user_id,
                panel_id,
                inbound_id,
                client_email,
                client_id,
                service_name,
                total_bytes,
                used_bytes,
                expire_at,
                status,
                last_synced_at,
            ),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            """
            SELECT id FROM user_services
            WHERE telegram_user_id=? AND panel_id=? AND client_email=?;
            """,
            (telegram_user_id, panel_id, client_email),
        )
        row = await cur.fetchone()
        return int(row["id"])

    async def get_user_services(self, telegram_user_id: int) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE telegram_user_id=? AND COALESCE(status, 'active') <> 'deleted'
            ORDER BY id ASC;
            """,
            (telegram_user_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_user_services_by_panel_email(self, panel_id: int, client_email: str) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE panel_id=? AND LOWER(client_email)=LOWER(?) AND COALESCE(status, 'active') <> 'deleted'
            ORDER BY id ASC;
            """,
            (panel_id, client_email),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_user_service_by_id(self, service_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE id=?
            LIMIT 1;
            """,
            (service_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all_user_services(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, panel_id, inbound_id, client_email, client_id, service_name,
                   total_bytes, used_bytes, expire_at, status, last_synced_at
            FROM user_services
            WHERE COALESCE(status, 'active') <> 'deleted'
            ORDER BY id ASC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def update_user_service_stats(
        self,
        *,
        service_id: int,
        total_bytes: int,
        used_bytes: int,
        expire_at: int | None,
        status: str,
        service_name: str,
        client_id: str | None,
        inbound_id: int | None,
        last_synced_at: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE user_services
            SET total_bytes=?, used_bytes=?, expire_at=?, status=?, service_name=?, client_id=?, inbound_id=?,
                last_synced_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?;
            """,
            (
                total_bytes,
                used_bytes,
                expire_at,
                status,
                service_name,
                client_id,
                inbound_id,
                last_synced_at,
                service_id,
            ),
        )
        await self.conn.commit()

    async def mark_user_service_deleted(
        self,
        *,
        service_id: int,
        status: str = "deleted",
        last_synced_at: int | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE user_services
            SET status=?, last_synced_at=COALESCE(?, last_synced_at), updated_at=CURRENT_TIMESTAMP
            WHERE id=?;
            """,
            (status, last_synced_at, service_id),
        )
        await self.conn.commit()

    async def mark_user_services_deleted_by_panel_email(
        self,
        *,
        panel_id: int,
        client_email: str,
        status: str = "deleted",
        last_synced_at: int | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE user_services
            SET status=?, last_synced_at=COALESCE(?, last_synced_at), updated_at=CURRENT_TIMESTAMP
            WHERE panel_id=? AND LOWER(client_email)=LOWER(?);
            """,
            (status, last_synced_at, panel_id, client_email),
        )
        await self.conn.commit()

    async def add_usage_snapshot(
        self,
        *,
        user_service_id: int,
        used_bytes: int,
        total_bytes: int,
        remaining_bytes: int | None,
        status: str,
        synced_at: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO usage_snapshots (
                user_service_id, used_bytes, total_bytes, remaining_bytes, status, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (user_service_id, used_bytes, total_bytes, remaining_bytes, status, synced_at),
        )
        await self.conn.commit()

    async def add_audit_log(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        success: bool = True,
        details: str | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO audit_logs(actor_user_id, action, target_type, target_id, success, details)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (actor_user_id, action, target_type, target_id, int(success), details),
        )
        await self.conn.commit()

    async def count_panels(self) -> int:
        assert self.conn is not None
        cur = await self.conn.execute("SELECT COUNT(*) AS cnt FROM panels;")
        row = await cur.fetchone()
        return int(row["cnt"])

    async def count_user_services(self) -> int:
        assert self.conn is not None
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_services WHERE COALESCE(status, 'active') <> 'deleted';"
        )
        row = await cur.fetchone()
        return int(row["cnt"])
