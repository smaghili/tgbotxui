from __future__ import annotations

from bot.db import Database
from bot.repositories.delegated_admin_finance_repository import DelegatedAdminFinanceRepository
from bot.repositories.delegated_admin_repository import DelegatedAdminRepository
from bot.repositories.user_repository import UserRepository


class HandlerContextService:
    def __init__(self, *, db: Database) -> None:
        self.user_repo = UserRepository(db=db)
        self.delegated_repo = DelegatedAdminRepository(db=db)
        self.delegated_finance_repo = DelegatedAdminFinanceRepository(db=db)

    async def user_lang(self, user_id: int) -> str:
        return await self.user_repo.get_language(user_id)

    async def delegated_profile(self, user_id: int) -> dict:
        return await self.delegated_finance_repo.get_profile(user_id)

    async def delegated_admins(self) -> list[dict]:
        return await self.delegated_repo.list_delegated_admins()
