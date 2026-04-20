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

    @property
    def is_admin(self) -> bool:
        return self.is_root_admin or self.is_delegated_admin

    @property
    def mode(self) -> str:
        return "full" if self.is_root_admin else "limited"


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
        is_delegated = False if is_root else await self.is_delegated_admin(user_id)
        return AdminContext(
            user_id=user_id,
            is_root_admin=is_root,
            is_delegated_admin=is_delegated,
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
        if self.is_root_admin(user_id, settings):
            return True
        return await self.db.has_admin_access_to_inbound(
            telegram_user_id=user_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )

    async def get_allowed_inbound_ids(
        self,
        *,
        user_id: int,
        settings: Settings,
        panel_id: int,
    ) -> set[int] | None:
        if self.is_root_admin(user_id, settings):
            return None
        rows = await self.db.list_admin_access_rows_for_user(user_id)
        allowed = {
            int(row["inbound_id"])
            for row in rows
            if int(row["panel_id"]) == panel_id
        }
        return allowed

    async def owner_filter_for_user(self, *, user_id: int, settings: Settings) -> int | None:
        if self.is_root_admin(user_id, settings):
            return None
        if await self.is_delegated_admin(user_id):
            return user_id
        return None
