from __future__ import annotations

from typing import Any


class DelegatedAdminFinanceRepository:
    def __init__(self, *, db: Any) -> None:
        self.db = db

    async def ensure_profile(self, telegram_user_id: int) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO delegated_admin_profiles (
                telegram_user_id, updated_at
            ) VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                updated_at=delegated_admin_profiles.updated_at;
            """,
            (telegram_user_id,),
        )
        await self.db.conn.commit()

    async def get_profile(self, telegram_user_id: int) -> dict[str, Any]:
        assert self.db.conn is not None
        await self.ensure_profile(telegram_user_id)
        cur = await self.db.conn.execute(
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

    async def update_profile(
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
    ) -> dict[str, Any]:
        assert self.db.conn is not None
        current = await self.get_profile(telegram_user_id)
        payload = {
            "username_prefix": current.get("username_prefix") if username_prefix is None else username_prefix,
            "max_clients": int(current.get("max_clients") or 0) if max_clients is None else max_clients,
            "min_traffic_gb": float(current.get("min_traffic_gb") or 0) if min_traffic_gb is None else float(min_traffic_gb),
            "max_traffic_gb": float(current.get("max_traffic_gb") or 0) if max_traffic_gb is None else float(max_traffic_gb),
            "min_expiry_days": int(current.get("min_expiry_days") or 1) if min_expiry_days is None else min_expiry_days,
            "max_expiry_days": int(current.get("max_expiry_days") or 0) if max_expiry_days is None else max_expiry_days,
            "charge_basis": str(current.get("charge_basis") or "allocated") if charge_basis is None else charge_basis,
            "allow_negative_wallet": int(current.get("allow_negative_wallet") or 0) if allow_negative_wallet is None else int(allow_negative_wallet),
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
        await self.db.conn.execute(
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
        await self.db.conn.commit()
        return await self.get_profile(telegram_user_id)

    async def list_recent_wallet_transactions(self, *, telegram_user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
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
        return [dict(row) for row in await cur.fetchall()]

    async def list_scope_wallet_transactions(
        self,
        telegram_user_ids: list[int],
        *,
        operation_names: list[str] | None = None,
        kind: str | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        assert self.db.conn is not None
        if not telegram_user_ids:
            return []
        clauses = [f"telegram_user_id IN ({','.join('?' for _ in telegram_user_ids)})"]
        params: list[Any] = list(telegram_user_ids)
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
        cur = await self.db.conn.execute(
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
        return [dict(row) for row in await cur.fetchall()]

    async def get_panel_pricing(self, *, telegram_user_id: int, panel_id: int) -> dict[str, Any] | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT telegram_user_id, panel_id, price_per_gb, price_per_day, allocated_pricing_tiers_json, username_prefix, max_clients, min_traffic_gb, max_traffic_gb, min_expiry_days, max_expiry_days, expires_at, created_at, updated_at
            FROM delegate_panel_pricing
            WHERE telegram_user_id=? AND panel_id=?
            LIMIT 1;
            """,
            (telegram_user_id, panel_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_panel_pricing(self, *, telegram_user_id: int) -> list[dict[str, Any]]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT dpp.telegram_user_id, dpp.panel_id, p.name AS panel_name, dpp.price_per_gb, dpp.price_per_day, dpp.allocated_pricing_tiers_json, dpp.username_prefix, dpp.max_clients, dpp.min_traffic_gb, dpp.max_traffic_gb, dpp.min_expiry_days, dpp.max_expiry_days, dpp.expires_at, dpp.created_at, dpp.updated_at
            FROM delegate_panel_pricing AS dpp
            LEFT JOIN panels AS p ON p.id = dpp.panel_id
            WHERE dpp.telegram_user_id=?
            ORDER BY dpp.panel_id ASC;
            """,
            (telegram_user_id,),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def set_panel_pricing(
        self,
        *,
        telegram_user_id: int,
        panel_id: int,
        price_per_gb: int,
        price_per_day: int,
        allocated_pricing_tiers_json: str = "[]",
        username_prefix: str | None = None,
        max_clients: int | None = None,
        min_traffic_gb: float | None = None,
        max_traffic_gb: float | None = None,
        min_expiry_days: int | None = None,
        max_expiry_days: int | None = None,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO delegate_panel_pricing (
                telegram_user_id, panel_id, price_per_gb, price_per_day, allocated_pricing_tiers_json, username_prefix, max_clients, min_traffic_gb, max_traffic_gb, min_expiry_days, max_expiry_days, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id, panel_id) DO UPDATE SET
                price_per_gb=excluded.price_per_gb,
                price_per_day=excluded.price_per_day,
                allocated_pricing_tiers_json=excluded.allocated_pricing_tiers_json,
                username_prefix=excluded.username_prefix,
                max_clients=excluded.max_clients,
                min_traffic_gb=excluded.min_traffic_gb,
                max_traffic_gb=excluded.max_traffic_gb,
                min_expiry_days=excluded.min_expiry_days,
                max_expiry_days=excluded.max_expiry_days,
                expires_at=excluded.expires_at,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                telegram_user_id,
                panel_id,
                price_per_gb,
                price_per_day,
                allocated_pricing_tiers_json,
                username_prefix,
                max_clients,
                min_traffic_gb,
                max_traffic_gb,
                min_expiry_days,
                max_expiry_days,
                expires_at,
            ),
        )
        await self.db.conn.commit()
        row = await self.get_panel_pricing(telegram_user_id=telegram_user_id, panel_id=panel_id)
        if row is None:
            raise ValueError("failed to save delegate panel pricing.")
        return row

    async def list_recent_actor_audit_logs(self, *, actor_user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT id, actor_user_id, action, target_type, target_id, success, details, created_at
            FROM audit_logs
            WHERE actor_user_id=?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (actor_user_id, max(1, int(limit))),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def list_scope_audit_logs(
        self,
        actor_user_ids: list[int],
        *,
        actions: list[str] | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        assert self.db.conn is not None
        if not actor_user_ids:
            return []
        clauses = [f"actor_user_id IN ({','.join('?' for _ in actor_user_ids)})"]
        params: list[Any] = list(actor_user_ids)
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
        cur = await self.db.conn.execute(
            f"""
            SELECT id, actor_user_id, action, target_type, target_id, success, details, created_at
            FROM audit_logs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
        )
        return [dict(row) for row in await cur.fetchall()]
