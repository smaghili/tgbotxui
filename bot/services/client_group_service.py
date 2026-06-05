from __future__ import annotations

from typing import Any

from bot.db import Database
from bot.services.panel_service import PanelService


class ClientGroupService:
    def __init__(self, *, db: Database, panel_service: PanelService) -> None:
        self.db = db
        self.panel_service = panel_service

    async def _require_group(self, *, panel_id: int, group_id: int) -> dict[str, Any]:
        group = await self.get_group(panel_id=panel_id, group_id=group_id)
        if group is None:
            raise ValueError("group not found.")
        return group

    async def _list_member_inbound_ids(self, *, group_id: int) -> list[int]:
        members = await self.db.list_client_inbound_group_members(group_id=group_id)
        return [int(row["inbound_id"]) for row in members if int(row.get("inbound_id") or 0) > 0]

    async def _inbound_lookup(self, *, panel_id: int) -> dict[int, str | None]:
        inbounds = await self.panel_service.list_inbounds(panel_id)
        return {
            int(inbound.get("id") or 0): str(inbound.get("remark") or "").strip() or None
            for inbound in inbounds
            if int(inbound.get("id") or 0) > 0
        }

    async def ensure_default_group(
        self,
        *,
        panel_id: int,
        group_name: str = "مشتریان",
        preferred_inbound_remark: str | None = None,
    ) -> dict[str, Any]:
        group = await self.db.get_client_inbound_group_by_name(panel_id=panel_id, name=group_name)
        if group is None:
            group_id = await self.db.create_client_inbound_group(panel_id=panel_id, name=group_name, is_default=True)
            group = await self.db.get_client_inbound_group(group_id)
        elif not bool(group.get("is_default")):
            await self.db.set_default_client_inbound_group(panel_id=panel_id, group_id=int(group["id"]))
            group = await self.db.get_client_inbound_group(int(group["id"]))
        if group is None:
            raise ValueError("failed to initialize default client inbound group.")

        if await self._list_member_inbound_ids(group_id=int(group["id"])) or not preferred_inbound_remark:
            return group

        inbounds = await self.panel_service.list_inbounds(panel_id)
        target = next(
            (
                inbound
                for inbound in inbounds
                if str(inbound.get("remark") or "").strip() == preferred_inbound_remark
            ),
            None,
        )
        if target is None:
            raise ValueError(f"default inbound '{preferred_inbound_remark}' was not found on panel.")
        inbound_id = int(target.get("id") or 0)
        if inbound_id <= 0:
            raise ValueError("default inbound has invalid id.")
        await self.db.add_client_inbound_group_member(
            group_id=int(group["id"]),
            inbound_id=inbound_id,
            inbound_remark=str(target.get("remark") or "").strip() or None,
        )
        return group

    async def resolve_group_inbound_ids(
        self,
        *,
        panel_id: int,
        group_name: str | None = None,
    ) -> list[int]:
        group = None
        if group_name:
            group = await self.db.get_client_inbound_group_by_name(panel_id=panel_id, name=group_name)
        if group is None:
            group = await self.db.get_default_client_inbound_group(panel_id=panel_id)
        if group is None:
            return []
        return await self._list_member_inbound_ids(group_id=int(group["id"]))

    async def list_groups(self, *, panel_id: int) -> list[dict[str, Any]]:
        return await self.db.list_client_inbound_groups(panel_id=panel_id)

    async def create_group(self, *, panel_id: int, name: str) -> dict[str, Any]:
        normalized = name.strip()
        if not normalized:
            raise ValueError("group name is empty.")
        existing = await self.db.get_client_inbound_group_by_name(panel_id=panel_id, name=normalized)
        if existing is not None:
            raise ValueError("group already exists.")
        group_id = await self.db.create_client_inbound_group(panel_id=panel_id, name=normalized, is_default=False)
        group = await self.db.get_client_inbound_group(group_id)
        if group is None:
            raise ValueError("failed to create group.")
        return group

    async def get_group(self, *, panel_id: int, group_id: int) -> dict[str, Any] | None:
        group = await self.db.get_client_inbound_group(group_id)
        if group is None or int(group.get("panel_id") or 0) != panel_id:
            return None
        return group

    async def get_group_members(self, *, panel_id: int, group_id: int) -> list[dict[str, Any]]:
        group = await self.get_group(panel_id=panel_id, group_id=group_id)
        if group is None:
            return []
        return await self.db.list_client_inbound_group_members(group_id=group_id)

    async def sync_group_inbounds(
        self,
        *,
        panel_id: int,
        group_id: int,
        inbound_ids: set[int],
    ) -> None:
        await self._require_group(panel_id=panel_id, group_id=group_id)
        inbound_lookup = await self._inbound_lookup(panel_id=panel_id)
        members = [
            {"inbound_id": inbound_id, "inbound_remark": inbound_lookup[inbound_id], "position": index}
            for index, inbound_id in enumerate(sorted(inbound_ids))
            if inbound_id in inbound_lookup
        ]
        await self.db.replace_client_inbound_group_members(group_id=group_id, members=members)
