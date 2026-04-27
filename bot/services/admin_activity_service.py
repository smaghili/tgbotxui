from __future__ import annotations

from bot.config import Settings
from bot.db import Database
from bot.utils import now_jalali_datetime

from .usage_service import UsageService


class AdminActivityService:
    def __init__(self, *, db: Database, usage_service: UsageService | None = None) -> None:
        self.db = db
        self.usage_service = usage_service

    async def record(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        text: str,
    ) -> str:
        stamped_text = f"{text}\nزمان: {now_jalali_datetime(settings.timezone)}"
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="admin_activity",
            target_type="admin_activity",
            target_id=str(actor_user_id),
            success=True,
            details=stamped_text,
        )
        if self.usage_service is not None and await self.usage_service.is_active_delegated_admin_user(actor_user_id):
            await self.usage_service.notify_admin_activity(actor_user_id=actor_user_id, text=stamped_text)
        return stamped_text
