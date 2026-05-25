from __future__ import annotations

from typing import Any

from bot.db import Database


class DelegatedAdminRepository:
    def __init__(self, *, db: Database) -> None:
        self.db = db

    async def get_by_user_id(self, telegram_user_id: int) -> dict[str, Any] | None:
        return await self.db.get_delegated_admin_by_user_id(telegram_user_id)

    async def list_panel_access_rows(self, telegram_user_id: int) -> list[dict[str, Any]]:
        loader = getattr(self.db, "list_delegated_admin_panel_access_rows", None)
        if loader is None:
            return []
        return await loader(telegram_user_id)

    async def list_access_rows(self, manager_user_id: int | None = None) -> list[dict[str, Any]]:
        return await self.db.list_delegated_admin_access_rows(manager_user_id=manager_user_id)

    async def list_delegated_admins(self, manager_user_id: int | None = None) -> list[dict[str, Any]]:
        return await self.db.list_delegated_admins(manager_user_id=manager_user_id)

    async def list_admin_access_rows_for_user(self, telegram_user_id: int) -> list[dict[str, Any]]:
        return await self.db.list_admin_access_rows_for_user(telegram_user_id)

    async def upsert_delegated_admin(
        self,
        *,
        telegram_user_id: int,
        title: str | None,
        created_by: int,
        parent_user_id: int | None,
        admin_scope: str,
    ) -> int:
        return await self.db.upsert_delegated_admin(
            telegram_user_id=telegram_user_id,
            title=title,
            created_by=created_by,
            parent_user_id=parent_user_id,
            admin_scope=admin_scope,
        )

    async def add_panel_access(self, *, delegated_admin_id: int, panel_id: int) -> int:
        return await self.db.add_delegated_admin_panel_access(
            delegated_admin_id=delegated_admin_id,
            panel_id=panel_id,
        )

    async def add_inbound_access(self, *, delegated_admin_id: int, panel_id: int, inbound_id: int) -> int:
        return await self.db.add_delegated_admin_inbound_access(
            delegated_admin_id=delegated_admin_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )

    async def ensure_profile(self, telegram_user_id: int) -> None:
        await self.db.ensure_delegated_admin_profile(telegram_user_id)

    async def set_parent(self, *, telegram_user_id: int, parent_user_id: int | None, actor_user_id: int) -> bool:
        return await self.db.set_delegated_admin_parent(
            telegram_user_id=telegram_user_id,
            parent_user_id=parent_user_id,
            actor_user_id=actor_user_id,
        )

    async def get_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
        return await self.db.get_delegated_admin_subtree_user_ids(
            manager_user_id=manager_user_id,
            include_self=include_self,
        )

    async def list_full_admins(self) -> list[dict[str, Any]]:
        return await self.db.list_full_delegated_admins()

    async def revoke_access(self, access_id: int) -> bool:
        return await self.db.revoke_delegated_admin_access(access_id)

    async def set_scope(self, *, telegram_user_id: int, admin_scope: str) -> bool:
        return await self.db.set_delegated_admin_scope(telegram_user_id=telegram_user_id, admin_scope=admin_scope)

    async def get_last_parent_event(self, telegram_user_id: int) -> dict[str, Any] | None:
        return await self.db.get_last_delegated_admin_parent_event(telegram_user_id)

    async def deactivate(self, telegram_user_id: int) -> bool:
        return await self.db.deactivate_delegated_admin(telegram_user_id)
