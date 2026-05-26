from __future__ import annotations

from typing import Any

from bot.config import Settings
from bot.i18n import t
from bot.repositories.delegated_admin_repository import DelegatedAdminRepository
from bot.services.access_service import AccessService
from bot.services.financial_service import FinancialService
from bot.services.panel_service import PanelService
from bot.services.panel_access_errors import (
    PanelAccessDelegatedAdminNotFoundError,
    PanelAccessInboundNotFoundError,
    PanelAccessPanelNotFoundError,
)
from bot.services.provisioning_models import InboundAccess


class DelegatedAccessService:
    def __init__(
        self,
        *,
        db: Any,
        repo: DelegatedAdminRepository,
        panel_service: PanelService,
        access_service: AccessService,
        financial_service: FinancialService | None = None,
    ) -> None:
        self.db = db
        self.repo = repo
        self.panel_service = panel_service
        self.access_service = access_service
        self.financial_service = financial_service

    @staticmethod
    def _inbound_display_name(inbound: dict[str, Any]) -> str:
        remark = str(inbound.get("remark") or "").strip()
        if remark:
            return remark
        port = inbound.get("port")
        if port:
            return f"inbound-{port}"
        return f"inbound-{inbound.get('id')}"

    async def _inbound_name_map_for_panel(self, panel_id: int) -> dict[int, str]:
        try:
            inbounds = await self.panel_service.list_inbounds(panel_id)
        except Exception:
            return {}
        return {
            int(inbound.get("id") or 0): self._inbound_display_name(inbound)
            for inbound in inbounds
            if int(inbound.get("id") or 0) > 0
        }

    async def _list_panel_inbounds(
        self,
        *,
        panel: dict[str, Any],
        allowed_inbound_ids: set[int] | None = None,
        delegated_admin_user_id: int | None = None,
    ) -> list[InboundAccess]:
        panel_id = int(panel["id"])
        try:
            inbounds = await self.panel_service.list_inbounds(panel_id)
        except Exception:
            return []
        rows: list[InboundAccess] = []
        for inbound in inbounds:
            inbound_id = int(inbound.get("id") or 0)
            if inbound_id <= 0:
                continue
            if allowed_inbound_ids is not None and inbound_id not in allowed_inbound_ids:
                continue
            rows.append(
                InboundAccess(
                    panel_id=panel_id,
                    panel_name=str(panel["name"]),
                    inbound_id=inbound_id,
                    inbound_name=self._inbound_display_name(inbound),
                    delegated_admin_user_id=delegated_admin_user_id,
                )
            )
        return rows

    async def resolve_admin_target(self, value: str) -> tuple[int, str | None]:
        raw = value.strip()
        if not raw:
            raise ValueError("admin target is empty.")
        title: str | None = None
        if raw.lstrip("-").isdigit():
            user_id = int(raw)
            user = await self.db.get_user_by_telegram_id(user_id)
            if user is not None:
                title = str(user.get("full_name") or user.get("username") or "").strip() or None
            return user_id, title
        user = await self.db.find_user_by_username(raw)
        if user is None:
            raise ValueError("username was not found in bot database.")
        title = str(user.get("full_name") or user.get("username") or "").strip() or None
        return int(user["telegram_user_id"]), title

    async def grant_delegated_admin_access(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        telegram_user_id: int,
        title: str | None,
        panel_id: int,
        inbound_id: int,
        admin_scope: str = "limited",
    ) -> int:
        delegated_admin_id = await self.repo.upsert_delegated_admin(
            telegram_user_id=telegram_user_id,
            title=title,
            created_by=actor_user_id,
            parent_user_id=None if self.access_service.is_root_admin(actor_user_id, settings) else actor_user_id,
            admin_scope=admin_scope,
        )
        await self.repo.add_panel_access(delegated_admin_id=delegated_admin_id, panel_id=panel_id)
        access_id = await self.repo.add_inbound_access(
            delegated_admin_id=delegated_admin_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )
        await self.repo.ensure_profile(telegram_user_id)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="grant_delegated_admin_access",
            target_type="delegated_admin_inbound",
            target_id=str(access_id),
            success=True,
            details=f"user={telegram_user_id};panel={panel_id};inbound={inbound_id}",
        )
        return access_id

    async def grant_delegated_admin_panel_access(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        panel_id: int,
    ) -> int:
        delegated = await self.repo.get_by_user_id(telegram_user_id)
        if delegated is None:
            raise ValueError("delegated admin was not found.")
        access_id = await self.repo.add_panel_access(
            delegated_admin_id=int(delegated["id"]),
            panel_id=panel_id,
        )
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="grant_delegated_admin_panel_access",
            target_type="delegated_admin_panel",
            target_id=str(access_id),
            success=True,
            details=f"user={telegram_user_id};panel={panel_id}",
        )
        return access_id

    async def list_panel_inbound_access_state(
        self,
        *,
        panel_id: int,
        telegram_user_id: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], set[int]]:
        panel = await self.panel_service.get_panel(panel_id)
        if panel is None:
            raise PanelAccessPanelNotFoundError
        delegated = await self.repo.get_by_user_id(telegram_user_id)
        if delegated is None:
            raise PanelAccessDelegatedAdminNotFoundError
        inbounds = await self.panel_service.list_inbounds(panel_id)
        selected_ids = {
            int(row["inbound_id"])
            for row in await self.repo.list_admin_access_rows_for_user(telegram_user_id)
            if int(row["panel_id"]) == panel_id
        }
        return panel, inbounds, selected_ids

    async def sync_delegated_admin_panel_inbound_access(
        self,
        *,
        actor_user_id: int,
        panel_id: int,
        telegram_user_id: int,
        inbound_ids: set[int],
    ) -> None:
        delegated = await self.repo.get_by_user_id(telegram_user_id)
        if delegated is None:
            raise PanelAccessDelegatedAdminNotFoundError
        inbounds = await self.panel_service.list_inbounds(panel_id)
        available_ids = {int(inbound.get("id") or 0) for inbound in inbounds if int(inbound.get("id") or 0) > 0}
        normalized_ids = {int(inbound_id) for inbound_id in inbound_ids if int(inbound_id) > 0}
        if not normalized_ids.issubset(available_ids):
            raise PanelAccessInboundNotFoundError
        delegated_admin_id = int(delegated["id"])
        current_rows = [row for row in await self.repo.list_admin_access_rows_for_user(telegram_user_id) if int(row["panel_id"]) == panel_id]
        current_map = {int(row["inbound_id"]): int(row["access_id"]) for row in current_rows}
        await self.repo.add_panel_access(delegated_admin_id=delegated_admin_id, panel_id=panel_id)
        for inbound_id in normalized_ids - set(current_map):
            access_id = await self.repo.add_inbound_access(
                delegated_admin_id=delegated_admin_id,
                panel_id=panel_id,
                inbound_id=inbound_id,
            )
            await self.db.add_audit_log(
                actor_user_id=actor_user_id,
                action="grant_delegated_admin_access",
                target_type="delegated_admin_inbound",
                target_id=str(access_id),
                success=True,
                details=f"user={telegram_user_id};panel={panel_id};inbound={inbound_id}",
            )
        for inbound_id in set(current_map) - normalized_ids:
            access_id = current_map[inbound_id]
            revoked = await self.repo.revoke_access(access_id)
            await self.db.add_audit_log(
                actor_user_id=actor_user_id,
                action="revoke_delegated_admin_access",
                target_type="delegated_admin_inbound",
                target_id=str(access_id),
                success=revoked,
                details=f"user={telegram_user_id};panel={panel_id};inbound={inbound_id}",
            )

    async def revoke_delegated_admin_access(self, *, actor_user_id: int, access_id: int) -> bool:
        revoked = await self.repo.revoke_access(access_id)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="revoke_delegated_admin_access",
            target_type="delegated_admin_inbound",
            target_id=str(access_id),
            success=revoked,
        )
        return revoked

    async def list_all_inbounds(self) -> list[InboundAccess]:
        panels = await self.panel_service.list_panels()
        rows: list[InboundAccess] = []
        for panel in panels:
            rows.extend(await self._list_panel_inbounds(panel=panel))
        return rows

    async def list_grantable_inbounds_for_delegated_admin(self, telegram_user_id: int) -> list[InboundAccess]:
        default_panel = await self.panel_service.get_default_panel()
        allowed_panel_ids = {int(default_panel["id"])} if default_panel is not None else set()
        for row in await self.repo.list_panel_access_rows(telegram_user_id):
            allowed_panel_ids.add(int(row["panel_id"]))
        panels = [panel for panel in await self.panel_service.list_panels() if int(panel["id"]) in allowed_panel_ids]
        rows: list[InboundAccess] = []
        for panel in panels:
            rows.extend(await self._list_panel_inbounds(panel=panel))
        return sorted(rows, key=lambda item: (item.panel_id, item.inbound_id))

    async def list_accessible_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        context = await self.access_service.get_admin_context(actor_user_id, settings)
        if context.is_root_admin:
            return await self.list_all_inbounds()

        access_rows = await self.repo.list_admin_access_rows_for_user(actor_user_id)
        if context.is_full_admin:
            explicit_by_panel: dict[int, set[int]] = {}
            for access in access_rows:
                explicit_by_panel.setdefault(int(access["panel_id"]), set()).add(int(access["inbound_id"]))
            granted_panel_ids = {int(row["panel_id"]) for row in await self.repo.list_panel_access_rows(actor_user_id)}
            rows: dict[tuple[int, int], InboundAccess] = {}
            for panel in await self.panel_service.list_panels():
                panel_id = int(panel["id"])
                has_full_panel_access = (
                    int(panel.get("is_default") or 0) == 1
                    or int(panel.get("created_by") or 0) == actor_user_id
                    or panel_id in granted_panel_ids
                )
                if has_full_panel_access:
                    for inbound in await self._list_panel_inbounds(panel=panel, delegated_admin_user_id=actor_user_id):
                        rows[(inbound.panel_id, inbound.inbound_id)] = inbound
                    continue
                explicit_inbounds = explicit_by_panel.get(panel_id)
                if explicit_inbounds:
                    for inbound in await self._list_panel_inbounds(
                        panel=panel,
                        allowed_inbound_ids=explicit_inbounds,
                        delegated_admin_user_id=actor_user_id,
                    ):
                        rows[(inbound.panel_id, inbound.inbound_id)] = inbound
            return sorted(rows.values(), key=lambda item: (item.panel_id, item.inbound_id))

        by_panel: dict[int, dict[int, str]] = {}
        rows: list[InboundAccess] = []
        for access in access_rows:
            panel_id = int(access["panel_id"])
            if panel_id not in by_panel:
                by_panel[panel_id] = await self._inbound_name_map_for_panel(panel_id)
            inbound_id = int(access["inbound_id"])
            rows.append(
                InboundAccess(
                    panel_id=panel_id,
                    panel_name=str(access["panel_name"]),
                    inbound_id=inbound_id,
                    inbound_name=by_panel[panel_id].get(inbound_id, f"inbound-{inbound_id}"),
                    access_id=int(access["access_id"]),
                    delegated_admin_user_id=actor_user_id,
                    delegated_admin_title=str(access.get("title") or "").strip() or None,
                )
            )
        return rows

    async def list_owned_client_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_root_admin:
            return await self.list_all_inbounds()
        panel_rows = await self.panel_service.list_panels()
        panel_names = {int(panel["id"]): str(panel["name"]) for panel in panel_rows}
        inbound_maps: dict[int, dict[int, str]] = {}
        discovered: dict[tuple[int, int], InboundAccess] = {}
        for panel in panel_rows:
            panel_id = int(panel["id"])
            try:
                clients = await self.panel_service.list_clients(panel_id, owner_admin_user_id=actor_user_id)
            except Exception:
                continue
            if not clients:
                continue
            if panel_id not in inbound_maps:
                inbound_maps[panel_id] = await self._inbound_name_map_for_panel(panel_id)
            for client in clients:
                inbound_id = int(client.get("inbound_id") or 0)
                if inbound_id <= 0:
                    continue
                key = (panel_id, inbound_id)
                if key in discovered:
                    continue
                discovered[key] = InboundAccess(
                    panel_id=panel_id,
                    panel_name=panel_names.get(panel_id, str(panel_id)),
                    inbound_id=inbound_id,
                    inbound_name=inbound_maps[panel_id].get(inbound_id, f"inbound-{inbound_id}"),
                    delegated_admin_user_id=actor_user_id,
                )
        return list(discovered.values())

    async def list_visible_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_root_admin:
            return await self.list_all_inbounds()
        rows: dict[tuple[int, int], InboundAccess] = {}
        for access in await self.list_accessible_inbounds_for_actor(actor_user_id=actor_user_id, settings=settings):
            rows[(access.panel_id, access.inbound_id)] = access
        for owned in await self.list_owned_client_inbounds_for_actor(actor_user_id=actor_user_id, settings=settings):
            rows.setdefault((owned.panel_id, owned.inbound_id), owned)
        return sorted(rows.values(), key=lambda item: (item.panel_id, item.inbound_id))

    async def list_delegated_admin_accesses(self, manager_user_id: int | None = None) -> list[dict[str, Any]]:
        rows = await self.repo.list_access_rows(manager_user_id=manager_user_id)
        inbound_maps: dict[int, dict[int, str]] = {}
        for row in rows:
            panel_id = int(row["panel_id"])
            if panel_id not in inbound_maps:
                inbound_maps[panel_id] = await self._inbound_name_map_for_panel(panel_id)
            row["inbound_name"] = inbound_maps[panel_id].get(int(row["inbound_id"]), f"inbound-{row['inbound_id']}")
        return rows

    async def count_owned_clients_for_actor(self, *, actor_user_id: int, settings: Settings) -> int:
        if self.access_service.is_root_admin(actor_user_id, settings):
            return 0
        count = 0
        for panel in await self.panel_service.list_panels():
            panel_id = int(panel["id"])
            try:
                clients = await self.panel_service.list_clients(panel_id, owner_admin_user_id=actor_user_id)
            except Exception:
                continue
            count += len(clients)
        return count

    async def get_delegated_admin_overview(
        self,
        *,
        telegram_user_id: int,
        settings: Settings,
    ) -> dict[str, Any]:
        delegated = await self.repo.get_by_user_id(telegram_user_id)
        profile = await self.db.get_delegated_admin_profile(telegram_user_id)
        wallet = await self.financial_service.get_wallet(telegram_user_id) if self.financial_service is not None else {
            "balance": 0,
            "currency": "تومان",
        }
        pricing = await self.financial_service.get_pricing(telegram_user_id) if self.financial_service is not None else {
            "price_per_gb": 0,
            "price_per_day": 0,
            "currency": "تومان",
            "charge_basis": "allocated",
            "apply_price_to_past_reports": 1,
        }
        user = await self.db.get_user_by_telegram_id(telegram_user_id)
        access_rows = await self.repo.list_admin_access_rows_for_user(telegram_user_id)
        owned_count = await self.count_owned_clients_for_actor(actor_user_id=telegram_user_id, settings=settings)
        return {
            "delegated": delegated,
            "profile": profile,
            "wallet": wallet,
            "pricing": pricing,
            "user": user,
            "access_rows": access_rows,
            "owned_clients_count": owned_count,
        }
