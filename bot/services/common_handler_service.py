from __future__ import annotations

import re
from typing import Any

from bot.db import Database
from bot.repositories.audit_repository import AuditRepository
from bot.repositories.settings_repository import SettingsRepository
from bot.repositories.user_repository import UserRepository
from bot.services.provisioning_models import StatusMissingServiceResult


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
        return await self.settings_repo.get_app_setting(key, default)

    async def set_app_setting(self, key: str, value: str) -> None:
        await self.settings_repo.set_app_setting(key, value)

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

    @staticmethod
    def _extract_uuid_from_text(raw: str) -> str | None:
        text = (raw or "").strip()
        if not text:
            return None
        match = re.search(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
            text,
        )
        return match.group(0) if match else None

    async def bind_missing_status_service_by_link(
        self,
        *,
        panel_service: Any,
        telegram_user_id: int,
        link_or_config: str,
    ) -> StatusMissingServiceResult:
        client_uuid = self._extract_uuid_from_text(link_or_config)
        if not client_uuid:
            return StatusMissingServiceResult(status="invalid_link")

        for panel in await panel_service.list_panels():
            panel_id = int(panel["id"])
            try:
                match = await panel_service.find_client_by_uuid(panel_id, client_uuid)
            except Exception:
                continue
            if not match:
                continue
            email = str(match.get("email") or "").strip()
            if not email:
                continue
            inbound_id = int(match.get("inbound_id") or 0)
            existing = await self.db.get_user_services_by_panel_email(panel_id, email)
            if any(int(row.get("telegram_user_id") or 0) == telegram_user_id for row in existing):
                return StatusMissingServiceResult(
                    status="exists",
                    panel_id=panel_id,
                    inbound_id=inbound_id if inbound_id > 0 else None,
                    client_email=email,
                )
            await panel_service.bind_service_to_user(
                panel_id=panel_id,
                telegram_user_id=telegram_user_id,
                client_email=email,
                service_name=None,
                inbound_id=inbound_id if inbound_id > 0 else None,
            )
            return StatusMissingServiceResult(
                status="added",
                panel_id=panel_id,
                inbound_id=inbound_id if inbound_id > 0 else None,
                client_email=email,
            )

        return StatusMissingServiceResult(status="not_found")
