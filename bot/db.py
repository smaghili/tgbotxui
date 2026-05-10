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

    async def get_user_notification_disabled_kinds(self, telegram_user_id: int) -> set[str]:
        assert self.conn is not None
        cur = await self.conn.execute(
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
        assert self.conn is not None
        payload = json.dumps(sorted(disabled), ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT INTO user_bot_notification_prefs (telegram_user_id, disabled_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                disabled_json=excluded.disabled_json,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, payload),
        )
        await self.conn.commit()

    ROOT_DEFAULT_ENDUSER_SERVICE_ALERTS_DISABLED_KEY = "root_default_enduser_service_alerts_disabled_json"

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
        parent_user_id: int | None = None,
        admin_scope: str = "limited",
    ) -> int:
        assert self.conn is not None
        scope = admin_scope if admin_scope in {"limited", "full"} else "limited"
        await self.conn.execute(
            """
            INSERT INTO delegated_admins (
                telegram_user_id, title, created_by, parent_user_id, admin_scope, is_active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                title=excluded.title,
                parent_user_id=COALESCE(excluded.parent_user_id, delegated_admins.parent_user_id),
                admin_scope=excluded.admin_scope,
                is_active=1,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, title, created_by, parent_user_id, scope),
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
            SELECT id, telegram_user_id, title, created_by, parent_user_id, admin_scope, is_active, created_at, updated_at
            FROM delegated_admins
            WHERE telegram_user_id=? AND is_active=1
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def count_active_delegated_children(self, parent_telegram_user_id: int) -> int:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM delegated_admins child
            LEFT JOIN delegated_admin_profiles p ON p.telegram_user_id = child.telegram_user_id
            WHERE child.parent_user_id = ?
              AND child.is_active = 1
              AND COALESCE(p.is_active, 1) = 1;
            """,
            (parent_telegram_user_id,),
        )
        row = await cur.fetchone()
        return int(row["c"] or 0)

    async def list_full_delegated_admins(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, title, created_by, parent_user_id, admin_scope, is_active, created_at, updated_at
            FROM delegated_admins
            WHERE is_active=1 AND admin_scope='full'
            ORDER BY telegram_user_id ASC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def set_delegated_admin_scope(self, *, telegram_user_id: int, admin_scope: str) -> bool:
        assert self.conn is not None
        scope = admin_scope if admin_scope in {"limited", "full"} else "limited"
        cur = await self.conn.execute(
            """
            UPDATE delegated_admins
            SET admin_scope=?, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (scope, telegram_user_id),
        )
        await self.conn.commit()
        return (cur.rowcount or 0) > 0

    async def set_delegated_admin_parent(
        self,
        *,
        telegram_user_id: int,
        parent_user_id: int | None,
        actor_user_id: int,
    ) -> bool:
        assert self.conn is not None
        current = await self.get_delegated_admin_by_user_id(telegram_user_id)
        if current is None:
            return False
        old_parent_user_id = int(current.get("parent_user_id") or 0) or None
        await self.conn.execute(
            """
            UPDATE delegated_admins
            SET parent_user_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (parent_user_id, telegram_user_id),
        )
        await self.conn.execute(
            """
            INSERT INTO delegated_admin_parent_events (
                telegram_user_id, old_parent_user_id, new_parent_user_id, actor_user_id
            ) VALUES (?, ?, ?, ?);
            """,
            (telegram_user_id, old_parent_user_id, parent_user_id, actor_user_id),
        )
        await self.conn.commit()
        return True

    async def get_last_delegated_admin_parent_event(self, telegram_user_id: int) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, telegram_user_id, old_parent_user_id, new_parent_user_id, actor_user_id, created_at
            FROM delegated_admin_parent_events
            WHERE telegram_user_id=?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_delegated_admin_subtree_user_ids(
        self,
        *,
        manager_user_id: int,
        include_self: bool = True,
    ) -> List[int]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            WITH RECURSIVE admin_tree(telegram_user_id) AS (
                SELECT telegram_user_id
                FROM delegated_admins
                WHERE telegram_user_id=? AND is_active=1
                UNION ALL
                SELECT da.telegram_user_id
                FROM delegated_admins AS da
                JOIN admin_tree AS at ON da.parent_user_id = at.telegram_user_id
                WHERE da.is_active=1
            )
            SELECT DISTINCT telegram_user_id
            FROM admin_tree;
            """,
            (manager_user_id,),
        )
        rows = await cur.fetchall()
        user_ids = [int(row["telegram_user_id"]) for row in rows]
        if not include_self:
            user_ids = [item for item in user_ids if item != manager_user_id]
        return user_ids

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
                allow_negative_wallet,
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
            "allow_negative_wallet": 0,
            "is_active": 1,
            "expires_at": None,
        }

    async def update_delegated_admin_profile(
        self,
        *,
        telegram_user_id: int,
        username_prefix: str | None = None,
        max_clients: int | None = None,
        min_traffic_gb: float | None = None,
        max_traffic_gb: float | None = None,
        min_expiry_days: int | None = None,
        max_expiry_days: int | None = None,
        charge_basis: str | None = None,
        allow_negative_wallet: int | None = None,
        is_active: int | None = None,
        expires_at: int | None = None,
    ) -> Dict[str, Any]:
        assert self.conn is not None
        await self.ensure_delegated_admin_profile(telegram_user_id)
        current = await self.get_delegated_admin_profile(telegram_user_id)
        payload = {
            "username_prefix": current.get("username_prefix") if username_prefix is None else username_prefix,
            "max_clients": int(current.get("max_clients") or 0) if max_clients is None else max_clients,
            "min_traffic_gb": float(current.get("min_traffic_gb") or 0) if min_traffic_gb is None else float(min_traffic_gb),
            "max_traffic_gb": float(current.get("max_traffic_gb") or 0) if max_traffic_gb is None else float(max_traffic_gb),
            "min_expiry_days": int(current.get("min_expiry_days") or 1) if min_expiry_days is None else min_expiry_days,
            "max_expiry_days": int(current.get("max_expiry_days") or 0) if max_expiry_days is None else max_expiry_days,
            "charge_basis": str(current.get("charge_basis") or "allocated") if charge_basis is None else charge_basis,
            "allow_negative_wallet": (
                int(current.get("allow_negative_wallet") or 0)
                if allow_negative_wallet is None else int(allow_negative_wallet)
            ),
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
        if payload["allow_negative_wallet"] not in {0, 1}:
            raise ValueError("delegated allow_negative_wallet must be 0 or 1.")
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
                allow_negative_wallet=?,
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
                payload["allow_negative_wallet"],
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

    async def list_scope_wallet_transactions(
        self,
        telegram_user_ids: List[int],
        *,
        operation_names: List[str] | None = None,
        kind: str | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        assert self.conn is not None
        if not telegram_user_ids:
            return []

        clauses = [f"telegram_user_id IN ({','.join('?' for _ in telegram_user_ids)})"]
        params: List[Any] = list(telegram_user_ids)

        if operation_names:
            clauses.append(f"operation IN ({','.join('?' for _ in operation_names)})")
            params.extend(operation_names)
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if created_at_from:
            clauses.append("created_at>=?")
            params.append(created_at_from)
        if created_at_to:
            clauses.append("created_at<?")
            params.append(created_at_to)

        params.append(max(1, int(limit)))
        cur = await self.conn.execute(
            f"""
            SELECT id, telegram_user_id, actor_user_id, amount, balance_after, currency,
                   kind, operation, status, reference_transaction_id, details, metadata_json, created_at
            FROM wallet_transactions
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
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

    async def list_scope_audit_logs(
        self,
        actor_user_ids: List[int],
        *,
        actions: List[str] | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        assert self.conn is not None
        if not actor_user_ids:
            return []

        clauses = [f"actor_user_id IN ({','.join('?' for _ in actor_user_ids)})"]
        params: List[Any] = list(actor_user_ids)

        if actions:
            clauses.append(f"action IN ({','.join('?' for _ in actions)})")
            params.extend(actions)
        if created_at_from:
            clauses.append("created_at>=?")
            params.append(created_at_from)
        if created_at_to:
            clauses.append("created_at<?")
            params.append(created_at_to)

        params.append(max(1, int(limit)))
        cur = await self.conn.execute(
            f"""
            SELECT id, actor_user_id, action, target_type, target_id, success, details, created_at
            FROM audit_logs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
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

    async def add_delegated_admin_panel_access(self, *, delegated_admin_id: int, panel_id: int) -> int:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegated_admin_panels (delegated_admin_id, panel_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(delegated_admin_id, panel_id) DO UPDATE SET
                updated_at=CURRENT_TIMESTAMP;
            """,
            (delegated_admin_id, panel_id),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            """
            SELECT id
            FROM delegated_admin_panels
            WHERE delegated_admin_id=? AND panel_id=?
            LIMIT 1;
            """,
            (delegated_admin_id, panel_id),
        )
        row = await cur.fetchone()
        return int(row["id"])

    async def list_delegated_admin_panel_access_rows(self, telegram_user_id: int) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT
                dap.id AS panel_access_id,
                da.id AS delegated_admin_id,
                da.telegram_user_id,
                da.title,
                dap.panel_id,
                p.name AS panel_name
            FROM delegated_admin_panels AS dap
            JOIN delegated_admins AS da ON da.id = dap.delegated_admin_id
            JOIN panels AS p ON p.id = dap.panel_id
            WHERE da.telegram_user_id=? AND da.is_active=1
            ORDER BY dap.panel_id ASC;
            """,
            (telegram_user_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def list_delegated_admins(self, manager_user_id: int | None = None) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT
                da.id AS delegated_admin_id,
                da.telegram_user_id,
                da.title,
                da.parent_user_id,
                da.admin_scope,
                da.is_active,
                da.created_by,
                u.full_name,
                u.username
            FROM delegated_admins AS da
            LEFT JOIN users AS u ON u.telegram_user_id = da.telegram_user_id
            WHERE da.is_active=1
            ORDER BY da.telegram_user_id ASC;
            """
        )
        rows = [dict(row) for row in await cur.fetchall()]
        if manager_user_id is None:
            return rows
        subtree_ids = set(await self.get_delegated_admin_subtree_user_ids(manager_user_id=manager_user_id))
        return [
            row
            for row in rows
            if int(row["telegram_user_id"]) in subtree_ids and int(row["telegram_user_id"]) != manager_user_id
        ]

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

    async def list_delegated_admin_access_rows(self, manager_user_id: int | None = None) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT
                dai.id AS access_id,
                da.id AS delegated_admin_id,
                da.telegram_user_id,
                da.title,
                da.parent_user_id,
                da.admin_scope,
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
        mapped = [dict(row) for row in rows]
        if manager_user_id is None:
            return mapped
        subtree_ids = set(await self.get_delegated_admin_subtree_user_ids(manager_user_id=manager_user_id))
        return [row for row in mapped if int(row["telegram_user_id"]) in subtree_ids and int(row["telegram_user_id"]) != manager_user_id]

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
            SELECT id, name, base_url, web_base_path, login_path, created_by, is_default, last_login_ok, last_error, updated_at
            FROM panels ORDER BY id DESC;
            """
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_default_panel(self) -> Dict[str, Any] | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, name, base_url, web_base_path, login_path, created_by, is_default, last_login_ok, last_error, updated_at
            FROM panels
            WHERE is_default=1
            LIMIT 1;
            """
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def has_admin_access_to_panel(self, *, telegram_user_id: int, panel_id: int) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT 1
            FROM delegated_admin_panels AS dap
            JOIN delegated_admins AS da ON da.id = dap.delegated_admin_id
            WHERE da.telegram_user_id=? AND da.is_active=1 AND dap.panel_id=?
            LIMIT 1;
            """,
            (telegram_user_id, panel_id),
        )
        row = await cur.fetchone()
        return row is not None

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

    async def upsert_client_owner(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        owner_user_id: int,
        client_email: str | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO client_owners (
                panel_id, inbound_id, client_uuid, owner_user_id, client_email, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(panel_id, inbound_id, client_uuid) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                client_email=excluded.client_email,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (panel_id, inbound_id, client_uuid, owner_user_id, client_email),
        )
        await self.conn.commit()

    async def get_client_owner(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> int | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT owner_user_id
            FROM client_owners
            WHERE panel_id=? AND inbound_id=? AND client_uuid=?
            LIMIT 1;
            """,
            (panel_id, inbound_id, client_uuid),
        )
        row = await cur.fetchone()
        return int(row["owner_user_id"]) if row else None

    async def list_client_owners_for_panel(self, panel_id: int) -> dict[tuple[int, str], int]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT inbound_id, client_uuid, owner_user_id
            FROM client_owners
            WHERE panel_id=?;
            """,
            (panel_id,),
        )
        rows = await cur.fetchall()
        return {
            (int(row["inbound_id"]), str(row["client_uuid"])):
            int(row["owner_user_id"])
            for row in rows
        }

    async def upsert_moaf_client_exemption(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        owner_user_id: int,
        moaf_user_id: int,
        exempt_after_bytes: int,
        client_email: str | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO moaf_client_exemptions (
                panel_id,
                inbound_id,
                client_uuid,
                owner_user_id,
                moaf_user_id,
                exempt_after_bytes,
                client_email,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(panel_id, inbound_id, client_uuid) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                moaf_user_id=excluded.moaf_user_id,
                exempt_after_bytes=MIN(moaf_client_exemptions.exempt_after_bytes, excluded.exempt_after_bytes),
                client_email=COALESCE(excluded.client_email, moaf_client_exemptions.client_email),
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                panel_id,
                inbound_id,
                client_uuid,
                owner_user_id,
                moaf_user_id,
                max(0, int(exempt_after_bytes)),
                client_email,
            ),
        )
        await self.conn.commit()

    async def list_moaf_client_exemptions_for_panel(self, panel_id: int) -> dict[tuple[int, str], dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT inbound_id, client_uuid, owner_user_id, moaf_user_id, exempt_after_bytes, client_email
            FROM moaf_client_exemptions
            WHERE panel_id=?;
            """,
            (panel_id,),
        )
        rows = await cur.fetchall()
        return {
            (int(row["inbound_id"]), str(row["client_uuid"])): {
                "owner_user_id": int(row["owner_user_id"]),
                "moaf_user_id": int(row["moaf_user_id"]),
                "exempt_after_bytes": max(0, int(row["exempt_after_bytes"] or 0)),
                "client_email": row["client_email"],
            }
            for row in rows
        }

    async def list_moaf_resume_delegate_caps_for_panel(self, panel_id: int) -> dict[tuple[int, str, int], int]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT inbound_id, client_uuid, delegate_user_id, cap_total_bytes
            FROM moaf_resume_delegate_caps
            WHERE panel_id=?;
            """,
            (panel_id,),
        )
        rows = await cur.fetchall()
        return {
            (int(row["inbound_id"]), str(row["client_uuid"]), int(row["delegate_user_id"])): max(
                0, int(row["cap_total_bytes"] or 0)
            )
            for row in rows
        }

    async def insert_moaf_resume_delegate_cap_if_missing(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        delegate_user_id: int,
        cap_total_bytes: int,
    ) -> None:
        assert self.conn is not None
        cap = max(0, int(cap_total_bytes))
        await self.conn.execute(
            """
            INSERT INTO moaf_resume_delegate_caps (
                panel_id, inbound_id, client_uuid, delegate_user_id, cap_total_bytes
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(panel_id, inbound_id, client_uuid, delegate_user_id) DO NOTHING;
            """,
            (panel_id, inbound_id, client_uuid, delegate_user_id, cap),
        )
        await self.conn.commit()

    async def get_moaf_resume_delegate_cap(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        delegate_user_id: int,
    ) -> int | None:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT cap_total_bytes
            FROM moaf_resume_delegate_caps
            WHERE panel_id=? AND inbound_id=? AND client_uuid=? AND delegate_user_id=?
            LIMIT 1;
            """,
            (panel_id, inbound_id, client_uuid, delegate_user_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return max(0, int(row["cap_total_bytes"] or 0))

    async def list_delegate_finance_excluded_inbounds(self, delegate_user_id: int) -> set[tuple[int, int]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT panel_id, inbound_id
            FROM delegate_finance_excluded_inbounds
            WHERE delegate_user_id=?;
            """,
            (delegate_user_id,),
        )
        rows = await cur.fetchall()
        return {(int(row["panel_id"]), int(row["inbound_id"])) for row in rows}

    async def add_delegate_finance_excluded_inbound(
        self,
        *,
        delegate_user_id: int,
        panel_id: int,
        inbound_id: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegate_finance_excluded_inbounds (delegate_user_id, panel_id, inbound_id)
            VALUES (?, ?, ?)
            ON CONFLICT(delegate_user_id, panel_id, inbound_id) DO NOTHING;
            """,
            (delegate_user_id, panel_id, inbound_id),
        )
        await self.conn.commit()

    async def remove_delegate_finance_excluded_inbound(
        self,
        *,
        delegate_user_id: int,
        panel_id: int,
        inbound_id: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            DELETE FROM delegate_finance_excluded_inbounds
            WHERE delegate_user_id=? AND panel_id=? AND inbound_id=?;
            """,
            (delegate_user_id, panel_id, inbound_id),
        )
        await self.conn.commit()

    async def list_delegate_finance_exclude_client_remaining(
        self, delegate_user_id: int
    ) -> set[tuple[int, int, str]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT panel_id, inbound_id, client_uuid
            FROM delegate_finance_exclude_client_remaining
            WHERE delegate_user_id=?;
            """,
            (delegate_user_id,),
        )
        rows = await cur.fetchall()
        return {(int(row["panel_id"]), int(row["inbound_id"]), str(row["client_uuid"])) for row in rows}

    async def add_delegate_finance_exclude_client_remaining(
        self,
        *,
        delegate_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO delegate_finance_exclude_client_remaining (
                delegate_user_id, panel_id, inbound_id, client_uuid
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(delegate_user_id, panel_id, inbound_id, client_uuid) DO NOTHING;
            """,
            (delegate_user_id, panel_id, inbound_id, client_uuid),
        )
        await self.conn.commit()

    async def remove_delegate_finance_exclude_client_remaining(
        self,
        *,
        delegate_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            DELETE FROM delegate_finance_exclude_client_remaining
            WHERE delegate_user_id=? AND panel_id=? AND inbound_id=? AND client_uuid=?;
            """,
            (delegate_user_id, panel_id, inbound_id, client_uuid),
        )
        await self.conn.commit()

    async def clear_wallet_ledger_for_user(self, telegram_user_id: int) -> None:
        assert self.conn is not None
        await self.conn.execute("DELETE FROM wallet_transactions WHERE telegram_user_id=?;", (telegram_user_id,))
        await self.conn.execute(
            """
            UPDATE user_wallets
            SET balance=0, updated_at=CURRENT_TIMESTAMP
            WHERE telegram_user_id=?;
            """,
            (telegram_user_id,),
        )
        await self.conn.commit()

    async def add_moaf_client_traffic_segment(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        owner_user_id: int,
        actor_user_id: int,
        start_bytes: int,
        end_bytes: int,
        is_billable: bool,
        source: str,
        client_email: str | None = None,
    ) -> None:
        assert self.conn is not None
        start = max(0, int(start_bytes))
        end = max(start, int(end_bytes))
        if end <= start:
            return
        await self.conn.execute(
            """
            INSERT INTO moaf_client_traffic_segments (
                panel_id,
                inbound_id,
                client_uuid,
                owner_user_id,
                actor_user_id,
                start_bytes,
                end_bytes,
                is_billable,
                source,
                client_email
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                panel_id,
                inbound_id,
                client_uuid,
                owner_user_id,
                actor_user_id,
                start,
                end,
                int(bool(is_billable)),
                source,
                client_email,
            ),
        )
        await self.conn.commit()

    async def get_moaf_client_traffic_segments(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> list[dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, owner_user_id, actor_user_id, start_bytes, end_bytes, is_billable, source, client_email, created_at
            FROM moaf_client_traffic_segments
            WHERE panel_id=? AND inbound_id=? AND client_uuid=?
            ORDER BY start_bytes ASC, id ASC;
            """,
            (panel_id, inbound_id, client_uuid),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def list_moaf_client_traffic_segments_for_panel(self, panel_id: int) -> dict[tuple[int, str], list[dict[str, Any]]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT inbound_id, client_uuid, owner_user_id, actor_user_id, start_bytes, end_bytes, is_billable, source, client_email
            FROM moaf_client_traffic_segments
            WHERE panel_id=?
            ORDER BY start_bytes ASC, id ASC;
            """,
            (panel_id,),
        )
        rows = await cur.fetchall()
        result: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (int(row["inbound_id"]), str(row["client_uuid"]))
            result.setdefault(key, []).append(
                {
                    "owner_user_id": int(row["owner_user_id"]),
                    "actor_user_id": int(row["actor_user_id"]),
                    "start_bytes": max(0, int(row["start_bytes"] or 0)),
                    "end_bytes": max(0, int(row["end_bytes"] or 0)),
                    "is_billable": bool(row["is_billable"]),
                    "source": str(row["source"] or ""),
                    "client_email": row["client_email"],
                }
            )
        return result

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

    async def enqueue_admin_activity_notification(
        self,
        *,
        actor_user_id: int | None,
        chat_id: int,
        text: str,
        next_attempt_at: int = 0,
        last_error: str | None = None,
        notification_kind: str | None = None,
    ) -> int:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            INSERT INTO admin_activity_notifications (
                actor_user_id, chat_id, text, attempts, last_error, next_attempt_at, notification_kind
            )
            VALUES (?, ?, ?, 0, ?, ?, ?);
            """,
            (actor_user_id, chat_id, text, last_error, int(next_attempt_at), notification_kind),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def list_due_admin_activity_notifications(
        self,
        *,
        now_ts: int,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            SELECT id, actor_user_id, chat_id, text, attempts, last_error, next_attempt_at, sent_at, created_at, notification_kind
            FROM admin_activity_notifications
            WHERE sent_at IS NULL AND next_attempt_at <= ?
            ORDER BY id ASC
            LIMIT ?;
            """,
            (int(now_ts), max(1, int(limit))),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def mark_admin_activity_notification_sent(
        self,
        *,
        notification_id: int,
        sent_at: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE admin_activity_notifications
            SET sent_at=?, attempts=attempts + 1, last_error=NULL
            WHERE id=?;
            """,
            (int(sent_at), notification_id),
        )
        await self.conn.commit()

    async def mark_admin_activity_notification_failed(
        self,
        *,
        notification_id: int,
        last_error: str,
        next_attempt_at: int,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            UPDATE admin_activity_notifications
            SET attempts=attempts + 1, last_error=?, next_attempt_at=?
            WHERE id=?;
            """,
            (last_error, int(next_attempt_at), notification_id),
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
