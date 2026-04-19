from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
import uuid as uuid_lib

from bot.config import Settings
from bot.db import Database
from bot.services.access_service import AccessService
from bot.services.panel_service import PanelService


@dataclass(slots=True, frozen=True)
class InboundAccess:
    panel_id: int
    panel_name: str
    inbound_id: int
    inbound_name: str
    access_id: int | None = None
    delegated_admin_user_id: int | None = None
    delegated_admin_title: str | None = None


@dataclass(slots=True, frozen=True)
class ManagedClientRef:
    panel_id: int
    panel_name: str
    inbound_id: int
    inbound_name: str
    client_uuid: str
    client_email: str


class AdminProvisioningService:
    def __init__(
        self,
        *,
        db: Database,
        panel_service: PanelService,
        access_service: AccessService,
    ) -> None:
        self.db = db
        self.panel_service = panel_service
        self.access_service = access_service

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
        telegram_user_id: int,
        title: str | None,
        panel_id: int,
        inbound_id: int,
    ) -> int:
        delegated_admin_id = await self.db.upsert_delegated_admin(
            telegram_user_id=telegram_user_id,
            title=title,
            created_by=actor_user_id,
        )
        access_id = await self.db.add_delegated_admin_inbound_access(
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
        return access_id

    async def revoke_delegated_admin_access(self, *, actor_user_id: int, access_id: int) -> bool:
        revoked = await self.db.revoke_delegated_admin_access(access_id)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="revoke_delegated_admin_access",
            target_type="delegated_admin_inbound",
            target_id=str(access_id),
            success=revoked,
        )
        return revoked

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

    @staticmethod
    def _inbound_display_name(inbound: dict[str, Any]) -> str:
        remark = str(inbound.get("remark") or "").strip()
        if remark:
            return remark
        port = inbound.get("port")
        if port:
            return f"inbound-{port}"
        inbound_id = inbound.get("id")
        return f"inbound-{inbound_id}"

    async def list_all_inbounds(self) -> list[InboundAccess]:
        panels = await self.panel_service.list_panels()
        rows: list[InboundAccess] = []
        for panel in panels:
            panel_id = int(panel["id"])
            try:
                inbounds = await self.panel_service.list_inbounds(panel_id)
            except Exception:
                continue
            for inbound in inbounds:
                inbound_id = int(inbound.get("id") or 0)
                if inbound_id <= 0:
                    continue
                rows.append(
                    InboundAccess(
                        panel_id=panel_id,
                        panel_name=str(panel["name"]),
                        inbound_id=inbound_id,
                        inbound_name=self._inbound_display_name(inbound),
                    )
                )
        return rows

    async def list_accessible_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        if self.access_service.is_root_admin(actor_user_id, settings):
            return await self.list_all_inbounds()

        access_rows = await self.db.list_admin_access_rows_for_user(actor_user_id)
        by_panel: dict[int, dict[int, str]] = {}
        rows: list[InboundAccess] = []
        for access in access_rows:
            panel_id = int(access["panel_id"])
            if panel_id not in by_panel:
                by_panel[panel_id] = await self._inbound_name_map_for_panel(panel_id)
            inbound_id = int(access["inbound_id"])
            inbound_name = by_panel[panel_id].get(inbound_id, f"inbound-{inbound_id}")
            rows.append(
                InboundAccess(
                    panel_id=panel_id,
                    panel_name=str(access["panel_name"]),
                    inbound_id=inbound_id,
                    inbound_name=inbound_name,
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
        if self.access_service.is_root_admin(actor_user_id, settings):
            return await self.list_all_inbounds()

        panel_rows = await self.panel_service.list_panels()
        panel_names = {int(panel["id"]): str(panel["name"]) for panel in panel_rows}
        inbound_maps: dict[int, dict[int, str]] = {}
        discovered: dict[tuple[int, int], InboundAccess] = {}

        for panel in panel_rows:
            panel_id = int(panel["id"])
            try:
                clients = await self.panel_service.list_clients(
                    panel_id,
                    owner_admin_user_id=actor_user_id,
                )
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
        if self.access_service.is_root_admin(actor_user_id, settings):
            return await self.list_all_inbounds()

        rows: dict[tuple[int, int], InboundAccess] = {}
        for access in await self.list_accessible_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        ):
            rows[(access.panel_id, access.inbound_id)] = access
        for owned in await self.list_owned_client_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        ):
            rows.setdefault((owned.panel_id, owned.inbound_id), owned)
        return sorted(rows.values(), key=lambda item: (item.panel_id, item.inbound_id))

    async def list_delegated_admin_accesses(self) -> list[dict[str, Any]]:
        rows = await self.db.list_delegated_admin_access_rows()
        inbound_maps: dict[int, dict[int, str]] = {}
        for row in rows:
            panel_id = int(row["panel_id"])
            if panel_id not in inbound_maps:
                inbound_maps[panel_id] = await self._inbound_name_map_for_panel(panel_id)
            row["inbound_name"] = inbound_maps[panel_id].get(int(row["inbound_id"]), f"inbound-{row['inbound_id']}")
        return rows

    async def create_client_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_email: str,
        total_gb: int,
        expiry_days: int,
        tg_id: str = "",
    ) -> dict[str, Any]:
        allowed = await self.access_service.can_access_inbound(
            user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )
        if not allowed:
            raise ValueError("you do not have access to this inbound.")

        created = await self.panel_service.create_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
            total_gb=total_gb,
            expiry_days=expiry_days,
            tg_id=tg_id,
            comment="" if self.access_service.is_root_admin(actor_user_id, settings) else str(actor_user_id),
        )
        if tg_id:
            try:
                resolved_user_id: int | None = None
                resolved_username: str | None = None
                if tg_id.lstrip("-").isdigit():
                    resolved_user_id = int(tg_id)
                    user = await self.db.get_user_by_telegram_id(resolved_user_id)
                    if user is not None:
                        resolved_username = str(user.get("username") or "").strip() or None
                    await self.panel_service.bind_service_to_user(
                        panel_id=panel_id,
                        telegram_user_id=resolved_user_id,
                        client_email=client_email,
                        service_name=None,
                        inbound_id=inbound_id,
                    )
                else:
                    user = await self.db.find_user_by_username(tg_id)
                    if user is not None:
                        resolved_user_id = int(user["telegram_user_id"])
                        resolved_username = str(user.get("username") or "").strip() or None
                        await self.panel_service.bind_service_to_user(
                            panel_id=panel_id,
                            telegram_user_id=resolved_user_id,
                            client_email=client_email,
                            service_name=None,
                            inbound_id=inbound_id,
                        )
                if resolved_user_id is not None:
                    await self.panel_service.bind_services_for_telegram_identity(
                        telegram_user_id=resolved_user_id,
                        username=resolved_username,
                    )
            except Exception:
                pass
        vless_uri = await self.panel_service.get_client_vless_uri_by_email(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
        )
        sub_url = await self.panel_service.get_client_subscription_url_by_email(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
        )
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="create_client",
            target_type="client",
            target_id=created["uuid"],
            success=True,
            details=f"panel={panel_id};inbound={inbound_id};email={client_email}",
        )
        return {
            **created,
            "vless_uri": vless_uri,
            "sub_url": sub_url,
        }

    @staticmethod
    def extract_uuid_from_vless_uri(vless_uri: str) -> str:
        raw = vless_uri.strip()
        if not raw:
            raise ValueError("config is empty.")
        parsed = urlparse(raw)
        if parsed.scheme.lower() != "vless":
            raise ValueError("config is not a VLESS URI.")
        if not parsed.username:
            raise ValueError("UUID was not found in config.")
        try:
            return str(uuid_lib.UUID(parsed.username))
        except ValueError as exc:
            raise ValueError("invalid UUID in config.") from exc

    async def resolve_client_from_vless_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        vless_uri: str,
    ) -> ManagedClientRef:
        client_uuid = self.extract_uuid_from_vless_uri(vless_uri)

        if self.access_service.is_root_admin(actor_user_id, settings):
            panels = await self.panel_service.list_panels()
            for panel in panels:
                panel_id = int(panel["id"])
                match = await self.panel_service.find_client_by_uuid(panel_id, client_uuid)
                if match is None:
                    continue
                all_inbounds = await self._inbound_name_map_for_panel(panel_id)
                return ManagedClientRef(
                    panel_id=panel_id,
                    panel_name=str(panel["name"]),
                    inbound_id=int(match["inbound_id"]),
                    inbound_name=all_inbounds.get(int(match["inbound_id"]), f"inbound-{match['inbound_id']}"),
                    client_uuid=client_uuid,
                    client_email=str(match.get("email") or ""),
                )
            raise ValueError("client was not found on any panel.")

        accesses = await self.list_visible_inbounds_for_actor(actor_user_id=actor_user_id, settings=settings)
        by_panel: dict[int, set[int]] = {}
        inbound_meta: dict[tuple[int, int], InboundAccess] = {}
        for access in accesses:
            by_panel.setdefault(access.panel_id, set()).add(access.inbound_id)
            inbound_meta[(access.panel_id, access.inbound_id)] = access
        for panel_id, inbound_ids in by_panel.items():
            owner_filter = await self.access_service.owner_filter_for_user(user_id=actor_user_id, settings=settings)
            match = await self.panel_service.find_client_by_uuid(
                panel_id,
                client_uuid,
                allowed_inbound_ids=inbound_ids,
                owner_admin_user_id=owner_filter,
            )
            if match is None:
                continue
            meta = inbound_meta[(panel_id, int(match["inbound_id"]))]
            return ManagedClientRef(
                panel_id=panel_id,
                panel_name=meta.panel_name,
                inbound_id=int(match["inbound_id"]),
                inbound_name=meta.inbound_name,
                client_uuid=client_uuid,
                client_email=str(match.get("email") or ""),
            )
        raise ValueError("client was not found inside your allowed inbounds.")

    async def add_traffic_by_vless_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        vless_uri: str,
        add_gb: int,
    ) -> ManagedClientRef:
        ref = await self.resolve_client_from_vless_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            vless_uri=vless_uri,
        )
        await self.panel_service.add_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, add_gb)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="add_client_traffic",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"gb={add_gb}",
        )
        return ref

    async def add_days_by_vless_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        vless_uri: str,
        add_days: int,
    ) -> ManagedClientRef:
        ref = await self.resolve_client_from_vless_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            vless_uri=vless_uri,
        )
        await self.panel_service.extend_client_expiry_days(ref.panel_id, ref.inbound_id, ref.client_uuid, add_days)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="extend_client_expiry",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"days={add_days}",
        )
        return ref

    async def delete_client_by_vless_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        vless_uri: str,
    ) -> ManagedClientRef:
        ref = await self.resolve_client_from_vless_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            vless_uri=vless_uri,
        )
        await self.panel_service.delete_client(ref.panel_id, ref.inbound_id, ref.client_uuid)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="delete_client",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
        )
        return ref
