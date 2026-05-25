from __future__ import annotations

from typing import Any

from bot.db import Database
from bot.repositories.audit_repository import AuditRepository
from bot.repositories.settings_repository import SettingsRepository
from bot.repositories.user_repository import UserRepository


class CommonHandlerService:
    def __init__(self, *, db: Database) -> None:
        self.db = db
        self.user_repo = UserRepository(db=db)
        self.settings_repo = SettingsRepository(db=db)
        self.audit_repo = AuditRepository(db=db)

    async def upsert_user(
        self,
        *,
        telegram_user_id: int,
        full_name: str,
        username: str | None,
        is_admin: bool,
    ) -> None:
        await self.db.upsert_user(
            telegram_user_id=telegram_user_id,
            full_name=full_name,
            username=username,
            is_admin=is_admin,
        )

    async def get_user_services(self, telegram_user_id: int) -> list[dict[str, Any]]:
        return await self.db.get_user_services(telegram_user_id)

    async def get_user_service_by_id(self, service_id: int) -> dict[str, Any] | None:
        return await self.db.get_user_service_by_id(service_id)

    async def get_app_setting(self, key: str, default: str | None = None) -> str | None:
        return await self.settings_repo.get(key, default)

    async def set_app_setting(self, key: str, value: str) -> None:
        await self.settings_repo.set(key, value)

    async def set_user_language(self, telegram_user_id: int, language: str) -> None:
        await self.user_repo.set_language(telegram_user_id, language)

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
        await self.audit_repo.add_log(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            success=success,
            details=details,
        )
