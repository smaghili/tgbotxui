from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, Literal

from bot.db import Database
from bot.services.panel_service import PanelService
from bot.services.xui_client import XUIAuthError, XUIError, XUIRateLimitError, XUIValidationError

AddPanelStatus = Literal[
    "ok",
    "invalid_credentials",
    "rate_limited",
    "validation_error",
    "xui_error",
    "unexpected_error",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AddPanelResult:
    status: AddPanelStatus
    panel: Dict[str, Any] | None = None
    error: str | None = None


class AdminPanelService:
    def __init__(self, db: Database, panel_service: PanelService) -> None:
        self.db = db
        self.panel_service = panel_service

    async def add_panel(
        self,
        *,
        actor_user_id: int,
        name: str,
        login_url: str,
        username: str,
        password: str,
        two_factor_code: str | None,
    ) -> AddPanelResult:
        try:
            panel = await self.panel_service.add_panel(
                name=name,
                login_url=login_url,
                username=username,
                password=password,
                two_factor_code=two_factor_code,
                created_by=actor_user_id,
            )
        except XUIAuthError:
            await self.db.add_audit_log(
                actor_user_id=actor_user_id,
                action="add_panel",
                target_type="panel",
                success=False,
                details="invalid_credentials",
            )
            return AddPanelResult(status="invalid_credentials")
        except XUIRateLimitError:
            await self.db.add_audit_log(
                actor_user_id=actor_user_id,
                action="add_panel",
                target_type="panel",
                success=False,
                details="rate_limited",
            )
            return AddPanelResult(status="rate_limited")
        except XUIValidationError as exc:
            return AddPanelResult(status="validation_error", error=str(exc))
        except XUIError as exc:
            logger.exception("x-ui error on add panel")
            return AddPanelResult(status="xui_error", error=str(exc))
        except Exception as exc:
            logger.exception("unexpected error on add panel")
            return AddPanelResult(status="unexpected_error", error=str(exc))

        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="add_panel",
            target_type="panel",
            target_id=str(panel["id"]),
            success=True,
        )
        return AddPanelResult(status="ok", panel=panel)

    async def toggle_default_panel(self, *, actor_user_id: int, panel_id: int) -> tuple[bool, bool]:
        changed, now_default = await self.panel_service.toggle_default_panel(panel_id)
        if not changed:
            return False, False
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="set_default_panel" if now_default else "clear_default_panel",
            target_type="panel",
            target_id=str(panel_id),
            success=True,
        )
        return True, now_default

    async def delete_panel(self, *, actor_user_id: int, panel_id: int) -> bool:
        deleted = await self.panel_service.delete_panel(panel_id)
        if not deleted:
            return False
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="delete_panel",
            target_type="panel",
            target_id=str(panel_id),
            success=True,
        )
        return True
