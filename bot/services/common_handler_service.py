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

    @staticmethod
    async def _sync_client_tg_id_if_possible(
        *,
        panel_service: Any,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        telegram_user_id: int,
    ) -> None:
        if not client_uuid:
            return
        if inbound_id <= 0:
            return
        try:
            await panel_service.set_client_tg_id(
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_uuid=client_uuid,
                tg_id=str(telegram_user_id),
            )
        except Exception:
            pass

    async def bind_and_sync_service_for_user(
        self,
        *,
        panel_service: Any,
        telegram_user_id: int,
        panel_id: int,
        client_email: str,
        service_name: str | None,
        inbound_id: int | None = None,
    ) -> Any:
        result = await panel_service.bind_service_to_user(
            panel_id=panel_id,
            telegram_user_id=telegram_user_id,
            client_email=client_email,
            service_name=service_name,
            inbound_id=inbound_id,
        )

        # Try to sync TG ID to panel by finding client first
        try:
            target_inbound, target_client = await panel_service._find_client_on_panel(
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_email=client_email,
            )
            if target_inbound and target_client:
                actual_inbound_id = int(target_inbound.get("id") or 0)
                client_uuid = str(target_client.get("uuid") or target_client.get("id") or "").strip()
                if actual_inbound_id > 0 and client_uuid:
                    await self._sync_client_tg_id_if_possible(
                        panel_service=panel_service,
                        panel_id=panel_id,
                        inbound_id=actual_inbound_id,
                        client_uuid=client_uuid,
                        telegram_user_id=telegram_user_id,
                    )
        except Exception:
            pass
        return result

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
            client_uuid_actual = str(match.get("uuid") or match.get("id") or match.get("client_id") or "").strip()
            existing = await self.db.get_user_services_by_panel_email(panel_id, email)

            # Check if service already exists for this user
            user_already_has_service = any(int(row.get("telegram_user_id") or 0) == telegram_user_id for row in existing)

            # Always sync TG ID to the panel
            await self._sync_client_tg_id_if_possible(
                panel_service=panel_service,
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_uuid=client_uuid_actual,
                telegram_user_id=telegram_user_id,
            )

            if user_already_has_service:
                return StatusMissingServiceResult(
                    status="exists",
                    panel_id=panel_id,
                    inbound_id=inbound_id if inbound_id > 0 else None,
                    client_email=email,
                )

            # Add service to this user
            try:
                await panel_service.bind_service_to_user(
                    panel_id=panel_id,
                    telegram_user_id=telegram_user_id,
                    client_email=email,
                    service_name=None,
                    inbound_id=inbound_id if inbound_id > 0 else None,
                )
            except Exception:
                continue
            return StatusMissingServiceResult(
                status="added",
                panel_id=panel_id,
                inbound_id=inbound_id if inbound_id > 0 else None,
                client_email=email,
            )

        return StatusMissingServiceResult(status="not_found")
