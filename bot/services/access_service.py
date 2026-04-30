from __future__ import annotations

from dataclasses import dataclass
import time

from bot.config import Settings
from bot.db import Database


@dataclass(slots=True, frozen=True)
class AdminContext:
    user_id: int
    is_root_admin: bool
    is_delegated_admin: bool
    delegated_scope: str = "limited"

    @property
    def is_admin(self) -> bool:
        return self.is_root_admin or self.is_delegated_admin

    @property
    def is_full_admin(self) -> bool:
        return self.is_root_admin or (self.is_delegated_admin and self.delegated_scope == "full")

    @property
    def mode(self) -> str:
        return "full" if self.is_full_admin else "limited"


class AccessService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def is_root_admin(self, user_id: int, settings: Settings) -> bool:
        return user_id in settings.admin_ids

    async def is_delegated_admin(self, user_id: int) -> bool:
        row = await self.db.get_delegated_admin_by_user_id(user_id)
        if row is None:
            return False
        profile = await self.db.get_delegated_admin_profile(user_id)
        if int(profile.get("is_active") or 0) != 1:
            return False
        expires_at = int(profile.get("expires_at") or 0)
        if expires_at > 0 and expires_at <= int(time.time()):
            return False
        return True

    async def get_admin_context(self, user_id: int, settings: Settings) -> AdminContext:
        is_root = self.is_root_admin(user_id, settings)
        delegated_scope = "limited"
        is_delegated = False
        if not is_root:
            row = await self.db.get_delegated_admin_by_user_id(user_id)
            is_delegated = row is not None and await self.is_delegated_admin(user_id)
            if row is not None:
                delegated_scope = str(row.get("admin_scope") or "limited")
        return AdminContext(
            user_id=user_id,
            is_root_admin=is_root,
            is_delegated_admin=is_delegated,
            delegated_scope=delegated_scope,
        )

    async def is_any_admin(self, user_id: int, settings: Settings) -> bool:
        context = await self.get_admin_context(user_id, settings)
        return context.is_admin

    async def can_access_inbound(
        self,
        *,
        user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
    ) -> bool:
        context = await self.get_admin_context(user_id, settings)
        if context.is_root_admin:
            return True
        if context.is_full_admin and await self.can_access_panel(
            user_id=user_id,
            settings=settings,
            panel_id=panel_id,
        ):
            panel = await self.db.get_panel(panel_id)
            if panel is not None and (int(panel.get("is_default") or 0) == 1 or int(panel.get("created_by") or 0) == user_id):
                return True
        return await self.db.has_admin_access_to_inbound(
            telegram_user_id=user_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )

    async def can_access_panel(
        self,
        *,
        user_id: int,
        settings: Settings,
        panel_id: int,
    ) -> bool:
        context = await self.get_admin_context(user_id, settings)
        if context.is_root_admin:
            return True
        panel = await self.db.get_panel(panel_id)
        if panel is None:
            return False
        if context.is_full_admin:
            if int(panel.get("is_default") or 0) == 1:
                return True
            if int(panel.get("created_by") or 0) == user_id:
                return True
        return await self.db.has_admin_access_to_panel(telegram_user_id=user_id, panel_id=panel_id)

    async def list_accessible_panels(self, *, user_id: int, settings: Settings) -> list[dict]:
        context = await self.get_admin_context(user_id, settings)
        panels = await self.db.list_panels()
        if context.is_root_admin:
            return panels
        explicit_panel_ids = {
            int(row["panel_id"])
            for row in await self.db.list_delegated_admin_panel_access_rows(user_id)
        }
        visible: list[dict] = []
        for panel in panels:
            panel_id = int(panel["id"])
            if int(panel.get("is_default") or 0) == 1:
                visible.append(panel)
                continue
            if context.is_full_admin and int(panel.get("created_by") or 0) == user_id:
                visible.append(panel)
                continue
            if panel_id in explicit_panel_ids:
                visible.append(panel)
        return visible

    async def can_delete_panel(
        self,
        *,
        user_id: int,
        settings: Settings,
        panel_id: int,
    ) -> bool:
        context = await self.get_admin_context(user_id, settings)
        if context.is_root_admin:
            return True
        if not context.is_full_admin:
            return False
        panel = await self.db.get_panel(panel_id)
        return panel is not None and int(panel.get("created_by") or 0) == user_id

    async def get_allowed_inbound_ids(
        self,
        *,
        user_id: int,
        settings: Settings,
        panel_id: int,
    ) -> set[int] | None:
        context = await self.get_admin_context(user_id, settings)
        if context.is_root_admin:
            return None
        if context.is_full_admin:
            panel = await self.db.get_panel(panel_id)
            if panel is not None and (int(panel.get("is_default") or 0) == 1 or int(panel.get("created_by") or 0) == user_id):
                return None
        rows = await self.db.list_admin_access_rows_for_user(user_id)
        allowed = {
            int(row["inbound_id"])
            for row in rows
            if int(row["panel_id"]) == panel_id
        }
        return allowed

    async def owner_filter_for_user(self, *, user_id: int, settings: Settings) -> int | None:
        context = await self.get_admin_context(user_id, settings)
        if context.is_full_admin:
            return None
        if context.is_delegated_admin:
            return user_id
        return None

    async def can_manage_panels(self, *, user_id: int, settings: Settings) -> bool:
        return (await self.get_admin_context(user_id, settings)).is_full_admin

    async def can_manage_admins(self, *, user_id: int, settings: Settings) -> bool:
        return (await self.get_admin_context(user_id, settings)).is_full_admin
