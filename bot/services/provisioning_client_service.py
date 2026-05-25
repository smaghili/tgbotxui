from __future__ import annotations

import time
from typing import Any

from bot.config import Settings
from bot.i18n import t
from bot.services.provisioning_models import ManagedClientRef
from bot.utils import bytes_to_gb, format_gb, gb_to_bytes, to_local_date


class ProvisioningClientService:
    """Client mutation orchestration extracted from AdminProvisioningService."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    async def add_client_total_gb_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        add_gb: float,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ref = await self.owner._managed_ref_from_panel_client(panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
        return await self.owner._add_client_total_gb_for_ref(
            actor_user_id=actor_user_id,
            settings=settings,
            ref=ref,
            add_gb=add_gb,
            operation_name="add_client_total_gb",
            refund_reason_prefix="refund:add_client_total_gb_failed",
        )

    async def extend_client_expiry_days_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        add_days: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ref = await self.owner._managed_ref_from_panel_client(panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
        return await self.owner._extend_client_expiry_for_ref(
            actor_user_id=actor_user_id,
            settings=settings,
            ref=ref,
            add_days=add_days,
            operation_name="extend_client_expiry_days",
            refund_reason_prefix="refund:extend_client_expiry_days_failed",
        )

    async def delete_client_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> dict[str, Any]:
        ref = await self.owner._managed_ref_from_panel_client(panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
        return await self.owner._delete_client_for_ref(actor_user_id=actor_user_id, settings=settings, ref=ref)

    async def set_client_total_gb_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        total_gb: float | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        owner = self.owner
        ref = await owner._managed_ref_from_panel_client(panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
        before = await owner.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        if total_gb is None and not owner.access_service.is_root_admin(actor_user_id, settings):
            raise ValueError("delegated_unlimited_not_allowed")
        if total_gb is not None and owner.financial_service is not None:
            await owner.financial_service.validate_target_limits(actor_user_id=actor_user_id, settings=settings, total_gb=total_gb)
        charge_tx = None
        if owner.financial_service is not None:
            before_allocated_gb = max(0.0, bytes_to_gb(int(before.get("total") or 0)))
            charge_tx = await owner.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation="set_client_total_gb",
                panel_id=ref.panel_id,
                traffic_gb=0 if total_gb is None else max(0, total_gb - before_allocated_gb),
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await owner.panel_service.set_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, total_gb)
            after = await owner.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            await owner._refund_charge_bundle(actor_user_id=actor_user_id, charge_tx=charge_tx, reason=f"refund:set_client_total_gb_failed:{ref.client_uuid}")
            raise
        await owner.db.add_audit_log(actor_user_id=actor_user_id, action="set_client_total_gb", target_type="client", target_id=ref.client_uuid, success=True, details=f"total_gb={'unlimited' if total_gb is None else total_gb}")
        lang = await owner.db.get_user_language(actor_user_id)
        await owner._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_total_gb",
            user=str(after.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[t("admin_activity_detail_traffic_change", lang, before=format_gb(int(before.get("total") or 0), lang), after=t("admin_unlimited", lang) if total_gb is None else format_gb(int(after.get("total") or 0), lang))],
        )
        if owner.usage_service is not None:
            added_bytes = max(0, int(after.get("total") or 0) - int(before.get("total") or 0))
            if added_bytes > 0:
                await owner.usage_service.notify_user_traffic_increased(panel_id=ref.panel_id, client_email=str(after.get("email") or ref.client_email or ""), added_bytes=added_bytes, new_total_bytes=int(after.get("total") or 0))
        return before, after

    async def set_client_expiry_days_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        days: int | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        owner = self.owner
        ref = await owner._managed_ref_from_panel_client(panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
        before = await owner.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        if days is None and not owner.access_service.is_root_admin(actor_user_id, settings):
            raise ValueError("delegated_unlimited_not_allowed")
        if days is not None and owner.financial_service is not None:
            await owner.financial_service.validate_target_limits(actor_user_id=actor_user_id, settings=settings, total_days=days)
        charge_tx = None
        if owner.financial_service is not None:
            before_expiry = int(before.get("expiry") or 0)
            now_ts = int(time.time())
            before_days = 0 if before_expiry <= now_ts else max(1, (before_expiry - now_ts + 86399) // 86400)
            charge_tx = await owner.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation="set_client_expiry_days",
                panel_id=ref.panel_id,
                expiry_days=0 if days is None else max(0, days - before_days),
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await owner.panel_service.set_client_expiry_days(ref.panel_id, ref.inbound_id, ref.client_uuid, days)
            after = await owner.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            await owner._refund_charge_bundle(actor_user_id=actor_user_id, charge_tx=charge_tx, reason=f"refund:set_client_expiry_days_failed:{ref.client_uuid}")
            raise
        await owner.db.add_audit_log(actor_user_id=actor_user_id, action="set_client_expiry_days", target_type="client", target_id=ref.client_uuid, success=True, details=f"days={'unlimited' if days is None else days}")
        lang = await owner.db.get_user_language(actor_user_id)
        await owner._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_expiry_days",
            user=str(after.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[t("admin_activity_detail_expiry_change", lang, before=to_local_date(before.get("expiry"), settings.timezone, lang), after=t("admin_unlimited", lang) if days is None else to_local_date(after.get("expiry"), settings.timezone, lang))],
        )
        return before, after

    async def create_client_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_email: str,
        total_gb: float,
        expiry_days: int,
        tg_id: str = "",
    ) -> dict[str, Any]:
        return await self.owner._create_client_for_actor_impl(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
            total_gb=total_gb,
            expiry_days=expiry_days,
            tg_id=tg_id,
        )
