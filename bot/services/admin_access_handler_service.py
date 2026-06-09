from __future__ import annotations

from typing import Any

from bot.db import Database
from bot.repositories.delegated_admin_finance_repository import DelegatedAdminFinanceRepository
from bot.repositories.delegated_admin_repository import DelegatedAdminRepository
from bot.services.handler_context_service import HandlerContextService


class AdminAccessHandlerService:
    def __init__(
        self,
        *,
        db: Database,
        delegated_admin_repository: DelegatedAdminRepository,
        handler_context_service: HandlerContextService,
    ) -> None:
        self.db = db
        self.delegated_admin_repository = delegated_admin_repository
        self.handler_context_service = handler_context_service
        self.delegated_finance_repository = DelegatedAdminFinanceRepository(db=db)

    async def user_lang(self, user_id: int) -> str:
        return await self.handler_context_service.user_lang(user_id)

    async def delegated_admin(self, user_id: int) -> dict[str, Any] | None:
        return await self.delegated_admin_repository.get_by_user_id(user_id)

    async def delegated_profile(self, user_id: int) -> dict[str, Any]:
        return await self.handler_context_service.delegated_profile(user_id)

    async def list_admin_access_rows_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return await self.delegated_admin_repository.list_admin_access_rows_for_user(user_id)

    async def get_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
        scope_loader = getattr(self.db, "get_delegated_admin_financial_scope_user_ids", None)
        if scope_loader is not None:
            return await scope_loader(manager_user_id=manager_user_id, include_self=include_self)
        return await self.delegated_admin_repository.get_subtree_user_ids(
            manager_user_id=manager_user_id,
            include_self=include_self,
        )

    async def get_last_parent_event(self, user_id: int) -> dict[str, Any] | None:
        return await self.delegated_admin_repository.get_last_parent_event(user_id)

    async def list_delegate_panel_pricing(self, *, user_id: int) -> list[dict[str, Any]]:
        return await self.delegated_finance_repository.list_panel_pricing(telegram_user_id=user_id)

    async def get_delegate_panel_pricing(self, *, user_id: int, panel_id: int) -> dict[str, Any] | None:
        return await self.delegated_finance_repository.get_panel_pricing(telegram_user_id=user_id, panel_id=panel_id)

    async def set_delegate_panel_pricing(
        self,
        *,
        user_id: int,
        panel_id: int,
        price_per_gb: int | None = None,
        price_per_day: int | None = None,
        reset_to_global: bool = False,
    ) -> None:
        await self.delegated_finance_repository.set_panel_pricing(
            telegram_user_id=user_id,
            panel_id=panel_id,
            price_per_gb=price_per_gb,
            price_per_day=price_per_day,
        )

    async def set_delegate_panel_pricing_payload(
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
    ) -> None:
        await self.delegated_finance_repository.set_panel_pricing(
            telegram_user_id=telegram_user_id,
            panel_id=panel_id,
            price_per_gb=price_per_gb,
            price_per_day=price_per_day,
            allocated_pricing_tiers_json=allocated_pricing_tiers_json,
            username_prefix=username_prefix,
            max_clients=max_clients,
            min_traffic_gb=min_traffic_gb,
            max_traffic_gb=max_traffic_gb,
            min_expiry_days=min_expiry_days,
            max_expiry_days=max_expiry_days,
            expires_at=expires_at,
        )

    async def update_delegated_profile(self, telegram_user_id: int, **changes: Any) -> None:
        await self.delegated_finance_repository.update_profile(telegram_user_id=telegram_user_id, **changes)

    async def set_delegated_scope(self, *, telegram_user_id: int, admin_scope: str) -> bool:
        return await self.delegated_admin_repository.set_scope(telegram_user_id=telegram_user_id, admin_scope=admin_scope)

    async def list_delegate_finance_excluded_inbounds(self, delegate_id: int) -> set[tuple[int, int]]:
        return await self.db.list_delegate_finance_excluded_inbounds(delegate_id)

    async def add_delegate_finance_excluded_inbound(self, *, delegate_id: int, panel_id: int, inbound_id: int) -> None:
        await self.db.add_delegate_finance_excluded_inbound(
            delegate_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )

    async def remove_delegate_finance_excluded_inbound(
        self,
        *,
        delegate_id: int,
        panel_id: int,
        inbound_id: int,
    ) -> None:
        await self.db.remove_delegate_finance_excluded_inbound(
            delegate_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )

    async def add_delegate_finance_exclude_client_remaining(self, *, delegate_id: int, panel_id: int, inbound_id: int, client_uuid: str) -> None:
        await self.db.add_delegate_finance_exclude_client_remaining(
            delegate_id=delegate_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )

    async def list_recent_wallet_transactions(self, *, user_id: int, limit: int) -> list[dict[str, Any]]:
        return await self.delegated_finance_repository.list_recent_wallet_transactions(telegram_user_id=user_id, limit=limit)

    async def list_recent_actor_audit_logs(self, *, actor_user_id: int, limit: int) -> list[dict[str, Any]]:
        return await self.delegated_finance_repository.list_recent_actor_audit_logs(actor_user_id=actor_user_id, limit=limit)

    async def deactivate_delegated_admin(self, user_id: int) -> None:
        await self.delegated_admin_repository.deactivate(user_id)

    async def merge_placeholder_user(self, *, real_user_id: int, username: str) -> None:
        """Merge placeholder user record (created by username) to real user ID when they run /start"""
        if not username:
            return
        username_normalized = username.lstrip("@").lower()
        placeholder_user_id = -(abs(hash(username_normalized)) % 2147483647)
        try:
            # Transfer any delegated admin records from placeholder to real user
            placeholder_admin = await self.delegated_admin_repository.get_by_user_id(placeholder_user_id)
            if placeholder_admin:
                # Update the placeholder admin record to use real user ID
                await self.db.merge_user_records(
                    old_user_id=placeholder_user_id,
                    new_user_id=real_user_id,
                )
        except Exception:
            pass
