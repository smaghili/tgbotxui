from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

from bot.config import Settings
from bot.db import Database
from bot.repositories.finance_repository import FinanceRepository
from bot.repositories.user_repository import UserRepository
from bot.services.access_service import AccessService
from bot.services.operation_guard_service import OperationGuardService
from bot.utils import parse_detail_pairs


def _parse_consumed_pricing_tiers_json(raw: Any) -> list[dict[str, int]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, int]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            upto = int(item.get("upto_bytes") or 0)
            price = int(item.get("price_per_gb") or 0)
        except (TypeError, ValueError):
            continue
        out.append({"upto_bytes": max(0, upto), "price_per_gb": max(0, price)})
    out.sort(key=lambda x: x["upto_bytes"])
    return out


def compute_consumed_basis_debt_amount(
    *,
    consumed_bytes: int,
    price_per_gb: int,
    tiers: list[dict[str, int]],
    gb_unit: int,
) -> int:
    consumed_bytes = max(0, int(consumed_bytes))
    price_per_gb = max(0, int(price_per_gb))
    gb_unit = int(gb_unit)
    if gb_unit <= 0:
        return 0
    if not tiers:
        return (consumed_bytes * price_per_gb) // gb_unit
    debt = 0
    prev = 0
    for tier in tiers:
        upto = int(tier.get("upto_bytes") or 0)
        p = int(tier.get("price_per_gb") or 0)
        if upto <= prev:
            continue
        hi = min(consumed_bytes, upto)
        if hi > prev:
            debt += (hi - prev) * p // gb_unit
        prev = upto
    if consumed_bytes > prev:
        debt += (consumed_bytes - prev) * price_per_gb // gb_unit
    return int(debt)


def _next_consumed_pricing_tiers_json(
    *,
    current: dict[str, Any],
    price_per_gb: int,
    charge_basis: str,
    apply_to_past: int,
    consumed_bytes_snapshot: int | None,
) -> str:
    old_basis = str(current.get("charge_basis") or "allocated")
    new_basis = str(charge_basis or "allocated")
    old_gb = int(current.get("price_per_gb") or 0)
    old_tiers = _parse_consumed_pricing_tiers_json(current.get("consumed_pricing_tiers_json"))

    if new_basis != "consumed":
        return json.dumps([], separators=(",", ":"))
    if old_basis != "consumed":
        return json.dumps([], separators=(",", ":"))
    if apply_to_past != 0:
        return json.dumps([], separators=(",", ":"))
    if old_gb == price_per_gb:
        return json.dumps(old_tiers, separators=(",", ":"))
    if consumed_bytes_snapshot is None:
        return json.dumps(old_tiers, separators=(",", ":"))
    snap = max(0, int(consumed_bytes_snapshot))
    extended = list(old_tiers)
    extended.append({"upto_bytes": snap, "price_per_gb": old_gb})
    extended.sort(key=lambda x: x["upto_bytes"])
    return json.dumps(extended, separators=(",", ":"))


def _parse_allocated_pricing_tiers_json(raw: Any) -> list[dict[str, int]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, int]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            traffic_gb = int(item.get("traffic_gb") or 0)
            amount = int(item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if traffic_gb <= 0 or amount < 0:
            continue
        out.append({"traffic_gb": traffic_gb, "amount": amount})
    out.sort(key=lambda x: x["traffic_gb"])
    dedup: dict[int, int] = {}
    for row in out:
        dedup[int(row["traffic_gb"])] = int(row["amount"])
    return [{"traffic_gb": key, "amount": dedup[key]} for key in sorted(dedup.keys())]


def _allocated_tier_amount_for_traffic(*, traffic_gb: float, tiers: list[dict[str, int]]) -> int | None:
    if traffic_gb <= 0:
        return None
    try:
        traffic_key = Decimal(str(traffic_gb))
    except Exception:
        return None
    if traffic_key != traffic_key.to_integral_value():
        return None
    target_gb = int(traffic_key)
    if target_gb <= 0:
        return None
    for tier in tiers:
        if int(tier.get("traffic_gb") or 0) == target_gb:
            return max(0, int(tier.get("amount") or 0))
    return None


class FinancialService:
    def __init__(
        self,
        *,
        db: Database,
        access_service: AccessService,
        operation_guard: OperationGuardService | None = None,
    ) -> None:
        self.db = db
        self.access_service = access_service
        self.operation_guard = operation_guard or OperationGuardService()
        self.finance_repo = FinanceRepository(db=db)
        self.user_repo = UserRepository(db=db)

    @staticmethod
    def _wallet_key(user_id: int) -> str:
        return f"wallet:{int(user_id)}"

    @staticmethod
    def _pricing_key(user_id: int) -> str:
        return f"pricing:{int(user_id)}"

    async def _default_currency(self) -> str:
        return await self.db.get_app_setting("wallet_currency_label", "تومان") or "تومان"

    async def ensure_wallet(self, telegram_user_id: int, *, currency: str | None = None) -> None:
        wallet_currency = currency or await self._default_currency()
        await self.finance_repo.ensure_wallet(telegram_user_id, currency=wallet_currency)

    async def get_wallet(self, telegram_user_id: int) -> dict[str, Any]:
        await self.ensure_wallet(telegram_user_id)
        row = await self.finance_repo.get_wallet(telegram_user_id)
        return dict(row) if row else {
            "telegram_user_id": telegram_user_id,
            "balance": 0,
            "currency": await self._default_currency(),
        }

    async def get_pricing(self, telegram_user_id: int) -> dict[str, Any]:
        default_currency = await self._default_currency()
        profile = await self.user_repo.get_delegated_profile(telegram_user_id)
        row = await self.finance_repo.get_pricing(telegram_user_id)
        if row:
            return dict(row)
        return {
            "telegram_user_id": telegram_user_id,
            "price_per_gb": 0,
            "price_per_day": 0,
            "currency": default_currency,
            "charge_basis": str(profile.get("charge_basis") or "allocated"),
            "apply_price_to_past_reports": 1,
            "allocated_pricing_tiers_json": "[]",
            "consumed_pricing_tiers_json": "[]",
        }

    def consumed_basis_debt_amount(self, *, consumed_bytes: int, pricing: dict[str, Any]) -> int:
        tiers = _parse_consumed_pricing_tiers_json(pricing.get("consumed_pricing_tiers_json"))
        return compute_consumed_basis_debt_amount(
            consumed_bytes=consumed_bytes,
            price_per_gb=int(pricing.get("price_per_gb") or 0),
            tiers=tiers,
            gb_unit=1024**3,
        )

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
        consumed_bytes_snapshot: int | None = None,
        allocated_pricing_tiers_json: str | None = None,
    ) -> dict[str, Any]:
        async def _apply() -> dict[str, Any]:
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
            tiers_json = _next_consumed_pricing_tiers_json(
                current=current_pricing,
                price_per_gb=price_per_gb,
                charge_basis=charge_basis,
                apply_to_past=apply_to_past,
                consumed_bytes_snapshot=consumed_bytes_snapshot,
            )
            allocated_tiers_json = allocated_pricing_tiers_json
            if allocated_tiers_json is None:
                allocated_tiers_json = str(current_pricing.get("allocated_pricing_tiers_json") or "[]")
            await self.finance_repo.upsert_pricing(
                telegram_user_id=telegram_user_id,
                price_per_gb=price_per_gb,
                price_per_day=price_per_day,
                currency=pricing_currency,
                charge_basis=charge_basis,
                apply_price_to_past_reports=apply_to_past,
                allocated_pricing_tiers_json=allocated_tiers_json,
                consumed_pricing_tiers_json=tiers_json,
            )
            await self.db.add_audit_log(
                actor_user_id=actor_user_id,
                action="set_user_pricing",
                target_type="user_pricing",
                target_id=str(telegram_user_id),
                success=True,
                details=(
                    f"gb={price_per_gb};day={price_per_day};currency={pricing_currency};"
                    f"basis={charge_basis};apply_to_past={apply_to_past};"
                    f"allocated_tiers={str(allocated_tiers_json)[:200]};consumed_tiers={tiers_json[:200]}"
                ),
            )
            return await self.get_pricing(telegram_user_id)

        return await self.operation_guard.run(self._pricing_key(telegram_user_id), _apply)

    async def get_scope_sales_totals(
        self,
        telegram_user_ids: list[int],
        *,
        excluded_inbound_pairs: set[tuple[int, int]] | None = None,
    ) -> dict[str, int]:
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
            SELECT telegram_user_id, amount, kind, details
            FROM wallet_transactions
            WHERE telegram_user_id IN ({placeholders});
            """,
            tuple(telegram_user_ids),
        )
        filtered_sales = 0
        filtered_refunds = 0
        filtered_total = 0
        for tx in await cur.fetchall():
            details = parse_detail_pairs(tx["details"])
            panel_raw = str(details.get("panel") or "").strip()
            inbound_raw = str(details.get("inbound") or "").strip()
            if excluded_inbound_pairs and panel_raw.isdigit() and inbound_raw.isdigit():
                if (int(panel_raw), int(inbound_raw)) in excluded_inbound_pairs:
                    continue
            filtered_total += 1
            amount = int(tx["amount"] or 0)
            if str(tx["kind"] or "") == "charge":
                filtered_sales += abs(amount)
            elif str(tx["kind"] or "") == "refund":
                filtered_refunds += amount
        total_sales = filtered_sales
        total_refunds = filtered_refunds
        total_transactions = filtered_total
        return {
            "total_sales": total_sales,
            "total_refunds": total_refunds,
            "net_sales": total_sales - total_refunds,
            "total_transactions": total_transactions,
        }

    async def calculate_charge(
        self,
        telegram_user_id: int,
        *,
        panel_id: int | None = None,
        traffic_gb: float = 0,
        expiry_days: int = 0,
    ) -> dict[str, Any]:
        pricing = await self.get_pricing(telegram_user_id)
        if panel_id is not None:
            panel_pricing = await self.db.get_delegate_panel_pricing(
                telegram_user_id=telegram_user_id,
                panel_id=int(panel_id),
            )
            if panel_pricing is not None:
                pricing = {
                    **pricing,
                    "price_per_gb": int(panel_pricing.get("price_per_gb") or 0),
                    "price_per_day": int(panel_pricing.get("price_per_day") or 0),
                    "allocated_pricing_tiers_json": str(panel_pricing.get("allocated_pricing_tiers_json") or "[]"),
                }
        gb_price = int(pricing["price_per_gb"] or 0)
        day_price = int(pricing["price_per_day"] or 0)
        traffic_amount = max(Decimal("0"), Decimal(str(traffic_gb)))
        traffic_cost = int(traffic_amount * gb_price)
        charge_basis = str(pricing.get("charge_basis") or "allocated")
        if charge_basis == "allocated":
            allocated_tiers = _parse_allocated_pricing_tiers_json(pricing.get("allocated_pricing_tiers_json"))
            tier_amount = _allocated_tier_amount_for_traffic(
                traffic_gb=float(traffic_amount),
                tiers=allocated_tiers,
            )
            if tier_amount is not None:
                traffic_cost = tier_amount
        expiry_cost = max(0, expiry_days) * day_price
        return {
            "traffic_gb": float(traffic_amount),
            "expiry_days": max(0, expiry_days),
            "price_per_gb": gb_price,
            "price_per_day": day_price,
            "currency": str(pricing.get("currency") or await self._default_currency()),
            "amount": traffic_cost + expiry_cost,
            "charge_basis": charge_basis,
        }

    async def _upstream_charge_targets(self, *, actor_user_id: int, settings: Settings) -> list[int]:
        if self.access_service.is_root_admin(actor_user_id, settings):
            return []
        delegated = await self.db.get_delegated_admin_by_user_id(actor_user_id)
        if delegated is None:
            return []
        seen: set[int] = {actor_user_id}
        targets: list[int] = []
        parent_user_id = int(delegated.get("parent_user_id") or 0)
        while parent_user_id > 0 and parent_user_id not in seen:
            seen.add(parent_user_id)
            targets.append(parent_user_id)
            parent_row = await self.db.get_delegated_admin_by_user_id(parent_user_id)
            if parent_row is None:
                break
            parent_user_id = int(parent_row.get("parent_user_id") or 0)
        root_ids = sorted(int(item) for item in getattr(settings, "admin_ids", set()) if int(item) != actor_user_id)
        if len(root_ids) == 1 and root_ids[0] not in seen:
            targets.append(root_ids[0])
        return targets

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
        return await self.finance_repo.apply_balance_change(
            telegram_user_id=telegram_user_id,
            actor_user_id=actor_user_id,
            delta=delta,
            kind=kind,
            operation=operation,
            details=details,
            metadata=metadata,
            reference_transaction_id=reference_transaction_id,
            allow_negative_balance=allow_negative_balance,
            default_currency=await self._default_currency(),
        )

    async def set_wallet_balance(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        amount: int,
    ) -> dict[str, Any]:
        async def _apply() -> dict[str, Any]:
            wallet = await self.get_wallet(telegram_user_id)
            delta = amount - int(wallet["balance"] or 0)
            return await self._apply_balance_change(
                telegram_user_id=telegram_user_id,
                actor_user_id=actor_user_id,
                delta=delta,
                kind="manual_set",
                operation="wallet_set_balance",
                details=f"set_balance={amount}",
                allow_negative_balance=True,
            )

        return await self.operation_guard.run(self._wallet_key(telegram_user_id), _apply)

    async def adjust_wallet_balance(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        delta: int,
        details: str | None = None,
        allow_negative_balance: bool = True,
        operation: str = "wallet_adjust_balance",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async def _apply() -> dict[str, Any]:
            if delta == 0:
                raise ValueError("wallet change amount cannot be zero.")
            return await self._apply_balance_change(
                telegram_user_id=telegram_user_id,
                actor_user_id=actor_user_id,
                delta=delta,
                kind="manual_adjust",
                operation=operation,
                details=details or f"delta={delta}",
                metadata=metadata,
                allow_negative_balance=allow_negative_balance,
            )

        return await self.operation_guard.run(self._wallet_key(telegram_user_id), _apply)

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
        panel_id: int | None = None,
        traffic_gb: float = 0,
        expiry_days: int = 0,
        details: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        async def _apply() -> dict[str, Any] | None:
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
                panel_id=panel_id,
                traffic_gb=traffic_gb,
                expiry_days=expiry_days,
            )
            if str(charge.get("charge_basis") or "allocated") == "consumed":
                return None
            amount = int(charge["amount"] or 0)
            if amount <= 0:
                return None
            allow_negative_wallet = int(profile.get("allow_negative_wallet") or 0) == 1
            actor_tx = await self._apply_balance_change(
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
            related_transaction_ids: list[int] = []
            try:
                for upstream_user_id in await self._upstream_charge_targets(actor_user_id=actor_user_id, settings=settings):
                    upstream_charge = await self.calculate_charge(
                        upstream_user_id,
                        panel_id=panel_id,
                        traffic_gb=traffic_gb,
                        expiry_days=expiry_days,
                    )
                    if str(upstream_charge.get("charge_basis") or "allocated") == "consumed":
                        continue
                    upstream_amount = int(upstream_charge.get("amount") or 0)
                    if upstream_amount <= 0:
                        continue
                    upstream_profile = await self.db.get_delegated_admin_profile(upstream_user_id)
                    allow_negative_upstream = (
                        True
                        if self.access_service.is_root_admin(upstream_user_id, settings)
                        else int(upstream_profile.get("allow_negative_wallet") or 0) == 1
                    )
                    upstream_tx = await self._apply_balance_change(
                        telegram_user_id=upstream_user_id,
                        actor_user_id=actor_user_id,
                        delta=-upstream_amount,
                        kind="charge",
                        operation=f"wholesale_{operation}",
                        details=(
                            f"source_actor={actor_user_id};traffic_gb={traffic_gb};"
                            f"expiry_days={expiry_days}"
                        ),
                        metadata={
                            "source_actor_user_id": actor_user_id,
                            "traffic_gb": max(0.0, float(traffic_gb)),
                            "expiry_days": max(0, expiry_days),
                            "price_per_gb": int(upstream_charge.get("price_per_gb") or 0),
                            "price_per_day": int(upstream_charge.get("price_per_day") or 0),
                        },
                        allow_negative_balance=allow_negative_upstream,
                    )
                    related_transaction_ids.append(int(upstream_tx["id"]))
            except Exception:
                await self.refund_transaction(
                    actor_user_id=actor_user_id,
                    transaction_id=int(actor_tx["id"]),
                    reason=f"refund:upstream_charge_failed:{operation}",
                )
                raise
            if related_transaction_ids:
                actor_tx["related_transaction_ids"] = related_transaction_ids
            return actor_tx

        lock_keys = [self._wallet_key(actor_user_id)]
        for upstream_user_id in await self._upstream_charge_targets(actor_user_id=actor_user_id, settings=settings):
            lock_keys.append(self._wallet_key(upstream_user_id))
        return await self.operation_guard.run_many(lock_keys, _apply)

    async def refund_transaction(
        self,
        *,
        actor_user_id: int | None,
        transaction_id: int,
        reason: str,
    ) -> dict[str, Any]:
        original = await self.finance_repo.get_transaction(transaction_id)
        if original is None:
            raise ValueError("wallet transaction was not found.")
        original_amount = int(original["amount"] or 0)
        if original_amount >= 0:
            raise ValueError("only debit transactions can be refunded.")
        if await self.finance_repo.has_refund(transaction_id):
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
        wallet = await self.get_wallet(telegram_user_id)
        pricing = await self.get_pricing(telegram_user_id)
        row = await self.finance_repo.get_sales_report(telegram_user_id)
        return {
            "wallet": wallet,
            "pricing": pricing,
            "total_sales": int(row["total_sales"] or 0),
            "total_refunds": int(row["total_refunds"] or 0),
            "total_transactions": int(row["total_transactions"] or 0),
        }

    async def get_overall_report(self) -> dict[str, Any]:
        currency = await self._default_currency()
        wallets, tx, pricing = await self.finance_repo.get_overall_report()
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

    async def clear_wallet_ledger_for_user(self, *, telegram_user_id: int) -> None:
        await self.ensure_wallet(telegram_user_id)
        await self.db.clear_wallet_ledger_for_user(telegram_user_id)
