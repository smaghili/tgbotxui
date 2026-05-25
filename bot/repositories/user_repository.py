from __future__ import annotations

from typing import Any

from bot.db import Database


class UserRepository:
    def __init__(self, *, db: Database) -> None:
        self.db = db

    async def get_identity(self, telegram_user_id: int) -> dict[str, Any] | None:
        return await self.db.get_user_by_telegram_id(telegram_user_id)

    async def find_by_username(self, username: str) -> dict[str, Any] | None:
        return await self.db.find_user_by_username(username)

    async def get_language(self, telegram_user_id: int) -> str:
        return await self.db.get_user_language(telegram_user_id)

    async def set_language(self, telegram_user_id: int, language: str) -> None:
        await self.db.set_user_language(telegram_user_id, language)

    async def get_delegated_admin(self, telegram_user_id: int) -> dict[str, Any] | None:
        return await self.db.get_delegated_admin_by_user_id(telegram_user_id)

    async def get_delegated_profile(self, telegram_user_id: int) -> dict[str, Any]:
        return await self.db.get_delegated_admin_profile(telegram_user_id)
