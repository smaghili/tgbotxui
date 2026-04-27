from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

from bot.config import Settings
from bot.db import Database
from bot.services.access_service import AccessService


class FinancialService:
    def __init__(
        self,
        *,
        db: Database,
        access_service: AccessService,
    ) -> None:
        self.db = db
        self.access_service = access_service

    async def _default_currency(self) -> str:
        return await self.db.get_app_setting("wallet_currency_label", "تومان") or "تومان"

    async def ensure_wallet(self, telegram_user_id: int, *, currency: str | None = None) -> None:
        assert self.db.conn is not None
        wallet_currency = currency or await self._default_currency()
        await self.db.conn.execute(
            """
            INSERT INTO user_wallets (telegram_user_id, balance, currency, updated_at)
            VALUES (?, 0, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                currency=COALESCE(user_wallets.currency, excluded.currency),
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, wallet_currency),
        )
        await self.db.conn.commit()

    async def get_wallet(self, telegram_user_id: int) -> dict[str, Any]:
        assert self.db.conn is not None
        await self.ensure_wallet(telegram_user_id)
        cur = await self.db.conn.execute(
            """
            SELECT telegram_user_id, balance, currency, created_at, updated_at
            FROM user_wallets
            WHERE telegram_user_id=?
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else {
            "telegram_user_id": telegram_user_id,
            "balance": 0,
            "currency": await self._default_currency(),
        }

    async def get_pricing(self, telegram_user_id: int) -> dict[str, Any]:
        assert self.db.conn is not None
        default_currency = await self._default_currency()
        profile = await self.db.get_delegated_admin_profile(telegram_user_id)
        cur = await self.db.conn.execute(
            """
            SELECT
                telegram_user_id,
                price_per_gb,
                price_per_day,
                currency,
                charge_basis,
                apply_price_to_past_reports,
                created_at,
                updated_at
            FROM user_pricing
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
            "price_per_gb": 0,
            "price_per_day": 0,
            "currency": default_currency,
            "charge_basis": str(profile.get("charge_basis") or "allocated"),
            "apply_price_to_past_reports": 1,
        }

    async def set_pricing(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        price_per_gb: int,
        price_per_day: int,
        currency: str | None = None,
        charge_basis: str = "allocated",
        apply_price_to_past_reports: bool | None = None,
    ) -> dict[str, Any]:
        assert self.db.conn is not None
        if price_per_gb < 0 or price_per_day < 0:
            raise ValueError("pricing values must be zero or positive.")
        pricing_currency = currency or await self._default_currency()
        current_pricing = await self.get_pricing(telegram_user_id)
        apply_to_past = (
            int(current_pricing.get("apply_price_to_past_reports") or 1)
            if apply_price_to_past_reports is None
            else int(bool(apply_price_to_past_reports))
        )
        await self.db.conn.execute(
            """
            INSERT INTO user_pricing (
                telegram_user_id,
                price_per_gb,
                price_per_day,
                currency,
                charge_basis,
                apply_price_to_past_reports,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                price_per_gb=excluded.price_per_gb,
                price_per_day=excluded.price_per_day,
                currency=excluded.currency,
                charge_basis=excluded.charge_basis,
                apply_price_to_past_reports=excluded.apply_price_to_past_reports,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                telegram_user_id,
                price_per_gb,
                price_per_day,
                pricing_currency,
                charge_basis,
                apply_to_past,
            ),
        )
        await self.db.conn.commit()
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="set_user_pricing",
            target_type="user_pricing",
            target_id=str(telegram_user_id),
            success=True,
            details=(
                f"gb={price_per_gb};day={price_per_day};currency={pricing_currency};"
                f"basis={charge_basis};apply_to_past={apply_to_past}"
            ),
        )
        return await self.get_pricing(telegram_user_id)

    async def get_scope_sales_totals(self, telegram_user_ids: list[int]) -> dict[str, int]:
        assert self.db.conn is not None
        if not telegram_user_ids:
            return {
                "total_sales": 0,
                "total_refunds": 0,
                "net_sales": 0,
                "total_transactions": 0,
            }
        placeholders = ",".join("?" for _ in telegram_user_ids)
        cur = await self.db.conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN kind='charge' THEN ABS(amount) ELSE 0 END), 0) AS total_sales,
                COALESCE(SUM(CASE WHEN kind='refund' THEN amount ELSE 0 END), 0) AS total_refunds,
                COALESCE(COUNT(*), 0) AS total_transactions
            FROM wallet_transactions
            WHERE telegram_user_id IN ({placeholders});
            """,
            tuple(telegram_user_ids),
        )
        row = await cur.fetchone()
        total_sales = int(row["total_sales"] or 0)
        total_refunds = int(row["total_refunds"] or 0)
        return {
            "total_sales": total_sales,
            "total_refunds": total_refunds,
            "net_sales": total_sales - total_refunds,
            "total_transactions": int(row["total_transactions"] or 0),
        }

    async def calculate_charge(
        self,
        telegram_user_id: int,
        *,
        traffic_gb: float = 0,
        expiry_days: int = 0,
    ) -> dict[str, Any]:
        pricing = await self.get_pricing(telegram_user_id)
        gb_price = int(pricing["price_per_gb"] or 0)
        day_price = int(pricing["price_per_day"] or 0)
        traffic_amount = max(Decimal("0"), Decimal(str(traffic_gb)))
        traffic_cost = int(traffic_amount * gb_price)
        expiry_cost = max(0, expiry_days) * day_price
        return {
            "traffic_gb": float(traffic_amount),
            "expiry_days": max(0, expiry_days),
            "price_per_gb": gb_price,
            "price_per_day": day_price,
            "currency": str(pricing.get("currency") or await self._default_currency()),
            "amount": traffic_cost + expiry_cost,
            "charge_basis": str(pricing.get("charge_basis") or "allocated"),
        }

    async def _apply_balance_change(
        self,
        *,
        telegram_user_id: int,
        actor_user_id: int | None,
        delta: int,
        kind: str,
        operation: str | None,
        details: str | None,
        metadata: dict[str, Any] | None = None,
        reference_transaction_id: int | None = None,
        allow_negative_balance: bool = False,
    ) -> dict[str, Any]:
        assert self.db.conn is not None
        await self.ensure_wallet(telegram_user_id)
        await self.db.conn.execute("BEGIN IMMEDIATE;")
        try:
            cur = await self.db.conn.execute(
                """
                SELECT balance, currency
                FROM user_wallets
                WHERE telegram_user_id=?
                LIMIT 1;
                """,
                (telegram_user_id,),
            )
            wallet = await cur.fetchone()
            if wallet is None:
                raise ValueError("wallet was not found.")
            current_balance = int(wallet["balance"] or 0)
            currency = str(wallet["currency"] or await self._default_currency())
            new_balance = current_balance + delta
            if new_balance < 0 and not allow_negative_balance:
                raise ValueError("insufficient wallet balance.")
            await self.db.conn.execute(
                """
                UPDATE user_wallets
                SET balance=?, updated_at=CURRENT_TIMESTAMP
                WHERE telegram_user_id=?;
                """,
                (new_balance, telegram_user_id),
            )
            cur = await self.db.conn.execute(
                """
                INSERT INTO wallet_transactions (
                    telegram_user_id, actor_user_id, amount, balance_after, currency,
                    kind, operation, status, reference_transaction_id, details, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?);
                """,
                (
                    telegram_user_id,
                    actor_user_id,
                    delta,
                    new_balance,
                    currency,
                    kind,
                    operation,
                    reference_transaction_id,
                    details,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            transaction_id = int(cur.lastrowid)
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise
        return {
            "id": transaction_id,
            "telegram_user_id": telegram_user_id,
            "amount": delta,
            "balance_after": new_balance,
            "currency": currency,
            "kind": kind,
            "operation": operation,
            "details": details,
        }

    async def set_wallet_balance(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        amount: int,
    ) -> dict[str, Any]:
        if amount < 0:
            raise ValueError("wallet balance cannot be negative.")
        wallet = await self.get_wallet(telegram_user_id)
        delta = amount - int(wallet["balance"] or 0)
        return await self._apply_balance_change(
            telegram_user_id=telegram_user_id,
            actor_user_id=actor_user_id,
            delta=delta,
            kind="manual_set",
            operation="wallet_set_balance",
            details=f"set_balance={amount}",
        )

    async def adjust_wallet_balance(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        delta: int,
        details: str | None = None,
    ) -> dict[str, Any]:
        if delta == 0:
            raise ValueError("wallet change amount cannot be zero.")
        return await self._apply_balance_change(
            telegram_user_id=telegram_user_id,
            actor_user_id=actor_user_id,
            delta=delta,
            kind="manual_adjust",
            operation="wallet_adjust_balance",
            details=details or f"delta={delta}",
        )

    async def ensure_delegated_actor_active(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> dict[str, Any] | None:
        if self.access_service.is_root_admin(actor_user_id, settings):
            return None
        profile = await self.db.get_delegated_admin_profile(actor_user_id)
        if int(profile.get("is_active") or 0) != 1:
            raise ValueError("delegated admin is inactive.")
        expires_at = int(profile.get("expires_at") or 0)
        if expires_at > 0 and expires_at <= int(time.time()):
            raise ValueError("delegated admin panel is expired.")
        return profile

    @staticmethod
    def _validate_traffic_range(profile: dict[str, Any], traffic_gb: float) -> None:
        min_traffic = max(0.0, float(profile.get("min_traffic_gb") or 0))
        max_traffic = max(0.0, float(profile.get("max_traffic_gb") or 0))
        if traffic_gb < min_traffic:
            raise ValueError("delegated traffic is below minimum.")
        if max_traffic > 0 and traffic_gb > max_traffic:
            raise ValueError("delegated traffic is above maximum.")

    @staticmethod
    def _validate_expiry_range(profile: dict[str, Any], expiry_days: int) -> None:
        min_days = max(0, int(profile.get("min_expiry_days") or 0))
        max_days = max(0, int(profile.get("max_expiry_days") or 0))
        if expiry_days < min_days:
            raise ValueError("delegated expiry is below minimum.")
        if max_days > 0 and expiry_days > max_days:
            raise ValueError("delegated expiry is above maximum.")

    async def validate_operation_limits(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        traffic_gb: float = 0,
        expiry_days: int = 0,
    ) -> dict[str, Any] | None:
        profile = await self.ensure_delegated_actor_active(actor_user_id=actor_user_id, settings=settings)
        if profile is None:
            return None
        if traffic_gb > 0:
            self._validate_traffic_range(profile, traffic_gb)
        if expiry_days > 0:
            self._validate_expiry_range(profile, expiry_days)
        return profile

    async def validate_target_limits(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        total_gb: float | None = None,
        total_days: int | None = None,
    ) -> dict[str, Any] | None:
        profile = await self.ensure_delegated_actor_active(actor_user_id=actor_user_id, settings=settings)
        if profile is None:
            return None
        if total_gb is not None:
            self._validate_traffic_range(profile, max(0, total_gb))
        if total_days is not None:
            self._validate_expiry_range(profile, max(0, total_days))
        return profile

    async def charge_operation(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        operation: str,
        traffic_gb: float = 0,
        expiry_days: int = 0,
        details: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        profile = await self.validate_operation_limits(
            actor_user_id=actor_user_id,
            settings=settings,
            traffic_gb=traffic_gb,
            expiry_days=expiry_days,
        )
        if profile is None:
            return None
        charge = await self.calculate_charge(
            actor_user_id,
            traffic_gb=traffic_gb,
            expiry_days=expiry_days,
        )
        # For consumed-basis delegates, billing is computed from real usage reports,
        # so operation-time wallet deductions must be skipped.
        if str(charge.get("charge_basis") or "allocated") == "consumed":
            return None
        amount = int(charge["amount"] or 0)
        if amount <= 0:
            return None
        allow_negative_wallet = int(profile.get("allow_negative_wallet") or 0) == 1
        return await self._apply_balance_change(
            telegram_user_id=actor_user_id,
            actor_user_id=actor_user_id,
            delta=-amount,
            kind="charge",
            operation=operation,
            details=details or f"traffic_gb={traffic_gb};expiry_days={expiry_days}",
            metadata={
                **(metadata or {}),
                "traffic_gb": max(0.0, float(traffic_gb)),
                "expiry_days": max(0, expiry_days),
                "price_per_gb": int(charge["price_per_gb"] or 0),
                "price_per_day": int(charge["price_per_day"] or 0),
            },
            allow_negative_balance=allow_negative_wallet,
        )

    async def refund_transaction(
        self,
        *,
        actor_user_id: int | None,
        transaction_id: int,
        reason: str,
    ) -> dict[str, Any]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT id, telegram_user_id, amount, operation
            FROM wallet_transactions
            WHERE id=?
            LIMIT 1;
            """,
            (transaction_id,),
        )
        original = await cur.fetchone()
        if original is None:
            raise ValueError("wallet transaction was not found.")
        original_amount = int(original["amount"] or 0)
        if original_amount >= 0:
            raise ValueError("only debit transactions can be refunded.")
        cur = await self.db.conn.execute(
            """
            SELECT id
            FROM wallet_transactions
            WHERE reference_transaction_id=? AND kind='refund'
            LIMIT 1;
            """,
            (transaction_id,),
        )
        refunded = await cur.fetchone()
        if refunded is not None:
            raise ValueError("wallet transaction was already refunded.")
        return await self._apply_balance_change(
            telegram_user_id=int(original["telegram_user_id"]),
            actor_user_id=actor_user_id,
            delta=abs(original_amount),
            kind="refund",
            operation=str(original["operation"] or "refund"),
            details=reason,
            reference_transaction_id=transaction_id,
        )

    async def get_sales_report(self, telegram_user_id: int) -> dict[str, Any]:
        assert self.db.conn is not None
        wallet = await self.get_wallet(telegram_user_id)
        pricing = await self.get_pricing(telegram_user_id)
        cur = await self.db.conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN kind='charge' THEN ABS(amount) ELSE 0 END), 0) AS total_sales,
                COALESCE(SUM(CASE WHEN kind='refund' THEN amount ELSE 0 END), 0) AS total_refunds,
                COALESCE(COUNT(*), 0) AS total_transactions
            FROM wallet_transactions
            WHERE telegram_user_id=?;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return {
            "wallet": wallet,
            "pricing": pricing,
            "total_sales": int(row["total_sales"] or 0),
            "total_refunds": int(row["total_refunds"] or 0),
            "total_transactions": int(row["total_transactions"] or 0),
        }

    async def get_overall_report(self) -> dict[str, Any]:
        assert self.db.conn is not None
        currency = await self._default_currency()
        cur = await self.db.conn.execute(
            """
            SELECT
                COALESCE(COUNT(*), 0) AS wallets_count,
                COALESCE(SUM(balance), 0) AS total_balance
            FROM user_wallets;
            """
        )
        wallets = await cur.fetchone()
        cur = await self.db.conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN kind='charge' THEN ABS(amount) ELSE 0 END), 0) AS total_sales,
                COALESCE(SUM(CASE WHEN kind='refund' THEN amount ELSE 0 END), 0) AS total_refunds,
                COALESCE(COUNT(CASE WHEN kind='charge' THEN 1 END), 0) AS sales_count,
                COALESCE(COUNT(*), 0) AS total_transactions
            FROM wallet_transactions;
            """
        )
        tx = await cur.fetchone()
        cur = await self.db.conn.execute(
            """
            SELECT COALESCE(COUNT(*), 0) AS pricing_profiles
            FROM user_pricing;
            """
        )
        pricing = await cur.fetchone()
        return {
            "currency": currency,
            "wallets_count": int(wallets["wallets_count"] or 0),
            "total_balance": int(wallets["total_balance"] or 0),
            "total_sales": int(tx["total_sales"] or 0),
            "total_refunds": int(tx["total_refunds"] or 0),
            "sales_count": int(tx["sales_count"] or 0),
            "total_transactions": int(tx["total_transactions"] or 0),
            "pricing_profiles": int(pricing["pricing_profiles"] or 0),
        }
