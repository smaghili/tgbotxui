from __future__ import annotations

import json
from typing import Any

from bot.db import Database


class FinancialStore:
    def __init__(self, *, db: Database) -> None:
        self.db = db

    async def ensure_wallet(self, telegram_user_id: int, *, currency: str) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO user_wallets (telegram_user_id, balance, currency, updated_at)
            VALUES (?, 0, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                currency=COALESCE(user_wallets.currency, excluded.currency),
                updated_at=CURRENT_TIMESTAMP;
            """,
            (telegram_user_id, currency),
        )
        await self.db.conn.commit()

    async def get_wallet_row(self, telegram_user_id: int) -> dict[str, Any] | None:
        assert self.db.conn is not None
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
        return dict(row) if row else None

    async def get_pricing_row(self, telegram_user_id: int) -> dict[str, Any] | None:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT
                telegram_user_id,
                price_per_gb,
                price_per_day,
                currency,
                charge_basis,
                apply_price_to_past_reports,
                consumed_pricing_tiers_json,
                created_at,
                updated_at
            FROM user_pricing
            WHERE telegram_user_id=?
            LIMIT 1;
            """,
            (telegram_user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_pricing(
        self,
        *,
        telegram_user_id: int,
        price_per_gb: int,
        price_per_day: int,
        currency: str,
        charge_basis: str,
        apply_price_to_past_reports: int,
        consumed_pricing_tiers_json: str = "[]",
    ) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            """
            INSERT INTO user_pricing (
                telegram_user_id,
                price_per_gb,
                price_per_day,
                currency,
                charge_basis,
                apply_price_to_past_reports,
                consumed_pricing_tiers_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                price_per_gb=excluded.price_per_gb,
                price_per_day=excluded.price_per_day,
                currency=excluded.currency,
                charge_basis=excluded.charge_basis,
                apply_price_to_past_reports=excluded.apply_price_to_past_reports,
                consumed_pricing_tiers_json=excluded.consumed_pricing_tiers_json,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                telegram_user_id,
                price_per_gb,
                price_per_day,
                currency,
                charge_basis,
                apply_price_to_past_reports,
                consumed_pricing_tiers_json,
            ),
        )
        await self.db.conn.commit()

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

    async def apply_balance_change(
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
        default_currency: str,
    ) -> dict[str, Any]:
        assert self.db.conn is not None
        await self.ensure_wallet(telegram_user_id, currency=default_currency)
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
            currency = str(wallet["currency"] or default_currency)
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

    async def get_transaction_row(self, transaction_id: int) -> dict[str, Any] | None:
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
        row = await cur.fetchone()
        return dict(row) if row else None

    async def has_refund_for(self, transaction_id: int) -> bool:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT id
            FROM wallet_transactions
            WHERE reference_transaction_id=? AND kind='refund'
            LIMIT 1;
            """,
            (transaction_id,),
        )
        return await cur.fetchone() is not None

    async def get_sales_report_row(self, telegram_user_id: int) -> dict[str, Any]:
        assert self.db.conn is not None
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
        return dict(row) if row else {"total_sales": 0, "total_refunds": 0, "total_transactions": 0}

    async def get_overall_report_rows(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        assert self.db.conn is not None
        cur = await self.db.conn.execute(
            """
            SELECT
                COALESCE(COUNT(*), 0) AS wallets_count,
                COALESCE(SUM(balance), 0) AS total_balance
            FROM user_wallets;
            """
        )
        wallets = dict(await cur.fetchone() or {})
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
        tx = dict(await cur.fetchone() or {})
        cur = await self.db.conn.execute(
            """
            SELECT COALESCE(COUNT(*), 0) AS pricing_profiles
            FROM user_pricing;
            """
        )
        pricing = dict(await cur.fetchone() or {})
        return wallets, tx, pricing
