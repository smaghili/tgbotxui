from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
import uuid as uuid_lib

from bot.config import Settings
from bot.db import Database
from bot.i18n import t
from bot.services.access_service import AccessService
from bot.services.financial_service import FinancialService
from bot.services.panel_service import PanelService
from bot.utils import build_admin_activity_notice, bytes_to_gb, display_name_from_parts, format_gb, now_jalali_datetime, to_local_date

if TYPE_CHECKING:
    from bot.services.usage_service import UsageService

logger = logging.getLogger(__name__)


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
        financial_service: FinancialService | None = None,
        usage_service: "UsageService | None" = None,
    ) -> None:
        self.db = db
        self.panel_service = panel_service
        self.access_service = access_service
        self.financial_service = financial_service
        self.usage_service = usage_service

    async def _actor_display_name(self, actor_user_id: int) -> str:
        user = await self.db.get_user_by_telegram_id(actor_user_id)
        if user is not None:
            return display_name_from_parts(
                full_name=str(user.get("full_name") or "").strip(),
                username=str(user.get("username") or "").strip(),
                fallback=actor_user_id,
            )
        delegated = await self.db.get_delegated_admin_by_user_id(actor_user_id)
        if delegated is not None:
            title = str(delegated.get("title") or "").strip()
            if title:
                return title
        return str(actor_user_id)

    async def _panel_inbound_names(self, *, panel_id: int, inbound_id: int) -> tuple[str, str]:
        try:
            return await self.panel_service.panel_inbound_names(panel_id, inbound_id)
        except Exception:
            return str(panel_id), f"inbound-{inbound_id}"

    async def _record_admin_activity(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        text: str,
    ) -> None:
        stamped_text = f"{text}\nزمان: {now_jalali_datetime(settings.timezone)}"
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="admin_activity",
            target_type="admin_activity",
            target_id=str(actor_user_id),
            success=True,
            details=stamped_text,
        )
        if self.usage_service is None or not await self.usage_service.is_active_delegated_admin_user(actor_user_id):
            return
        await self.usage_service.notify_admin_activity(actor_user_id=actor_user_id, text=stamped_text)

    async def record_admin_activity(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        text: str,
    ) -> None:
        await self._record_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            text=text,
        )

    async def _record_templated_admin_activity(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        action_key: str,
        user: str,
        panel_id: int,
        inbound_id: int,
        details: list[str] | None = None,
    ) -> None:
        lang = await self.db.get_user_language(actor_user_id)
        actor = await self._actor_display_name(actor_user_id)
        panel_name, inbound_name = await self._panel_inbound_names(panel_id=panel_id, inbound_id=inbound_id)
        activity_text = build_admin_activity_notice(
            lang=lang,
            actor=actor,
            action_text=t(action_key, lang),
            user=user,
            panel=panel_name,
            inbound=inbound_name,
            details=details,
        )
        await self._record_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            text=activity_text,
        )

    async def _managed_ref_from_panel_client(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> ManagedClientRef:
        panel_name, inbound_name = await self._panel_inbound_names(panel_id=panel_id, inbound_id=inbound_id)
        detail = await self.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
        return ManagedClientRef(
            panel_id=panel_id,
            panel_name=panel_name,
            inbound_id=inbound_id,
            inbound_name=inbound_name,
            client_uuid=client_uuid,
            client_email=str(detail.get("email") or ""),
        )

    async def _add_client_total_gb_for_ref(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        ref: ManagedClientRef,
        add_gb: float,
        operation_name: str,
        refund_reason_prefix: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        before = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        charge_tx = None
        if self.financial_service is not None:
            await self.financial_service.validate_operation_limits(
                actor_user_id=actor_user_id,
                settings=settings,
                traffic_gb=add_gb,
            )
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation=operation_name,
                traffic_gb=add_gb,
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await self.panel_service.add_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, add_gb)
            after = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            if charge_tx is not None and self.financial_service is not None:
                await self.financial_service.refund_transaction(
                    actor_user_id=actor_user_id,
                    transaction_id=int(charge_tx["id"]),
                    reason=f"{refund_reason_prefix}:{ref.client_uuid}",
                )
            raise
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="add_client_traffic",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"gb={add_gb}",
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_add_traffic",
            user=str(after.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[t("admin_activity_detail_amount_gb", lang, value=add_gb)],
        )
        if self.usage_service is not None:
            added_bytes = max(0, int(after.get("total") or 0) - int(before.get("total") or 0))
            if added_bytes > 0:
                await self.usage_service.notify_user_traffic_increased(
                    panel_id=ref.panel_id,
                    client_email=str(after.get("email") or ref.client_email or ""),
                    added_bytes=added_bytes,
                    new_total_bytes=int(after.get("total") or 0),
                )
        return before, after

    async def _extend_client_expiry_for_ref(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        ref: ManagedClientRef,
        add_days: int,
        operation_name: str,
        refund_reason_prefix: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        before = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        charge_tx = None
        if self.financial_service is not None:
            await self.financial_service.validate_operation_limits(
                actor_user_id=actor_user_id,
                settings=settings,
                expiry_days=add_days,
            )
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation=operation_name,
                expiry_days=add_days,
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await self.panel_service.extend_client_expiry_days(ref.panel_id, ref.inbound_id, ref.client_uuid, add_days)
            after = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            if charge_tx is not None and self.financial_service is not None:
                await self.financial_service.refund_transaction(
                    actor_user_id=actor_user_id,
                    transaction_id=int(charge_tx["id"]),
                    reason=f"{refund_reason_prefix}:{ref.client_uuid}",
                )
            raise
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="extend_client_expiry",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"days={add_days}",
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_add_days",
            user=str(after.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[t("admin_activity_detail_amount_days", lang, value=add_days)],
        )
        if self.usage_service is not None:
            await self.usage_service.notify_user_expiry_extended(
                panel_id=ref.panel_id,
                client_email=str(after.get("email") or ref.client_email or ""),
                added_days=add_days,
                new_expiry=after.get("expiry"),
            )
        return before, after

    async def _delete_client_for_ref(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        ref: ManagedClientRef,
    ) -> dict[str, Any]:
        before = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        await self.panel_service.delete_client(ref.panel_id, ref.inbound_id, ref.client_uuid)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="delete_client",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
        )
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_delete_client",
            user=str(before.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
        )
        return before

    async def toggle_client_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> tuple[dict[str, Any], bool]:
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        enabled = await self.panel_service.toggle_client_enable(ref.panel_id, ref.inbound_id, ref.client_uuid)
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_toggle_client",
            user=str(detail.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[
                t(
                    "admin_activity_detail_new_status",
                    lang,
                    value=t("admin_activity_status_active", lang)
                    if enabled
                    else t("admin_activity_status_inactive", lang),
                )
            ],
        )
        return detail, enabled

    async def set_client_tg_id_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        tg_id: str,
    ) -> dict[str, Any]:
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        await self.panel_service.set_client_tg_id(ref.panel_id, ref.inbound_id, ref.client_uuid, tg_id)
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        if tg_id:
            client_email = str(detail.get("email") or ref.client_email or "").strip()
            if client_email:
                resolved_user_id = None
                resolved_username = None
                if tg_id.lstrip("-").isdigit():
                    resolved_user_id = int(tg_id)
                    user = await self.db.get_user_by_telegram_id(resolved_user_id)
                    if user is not None:
                        resolved_username = str(user.get("username") or "").strip() or None
                else:
                    user = await self.db.find_user_by_username(tg_id)
                    if user is not None:
                        resolved_user_id = int(user["telegram_user_id"])
                        resolved_username = str(user.get("username") or "").strip() or None
                if resolved_user_id is not None:
                    await self.panel_service.bind_service_to_user(
                        panel_id=ref.panel_id,
                        telegram_user_id=resolved_user_id,
                        client_email=client_email,
                        service_name=None,
                        inbound_id=ref.inbound_id,
                    )
                    await self.panel_service.bind_services_for_telegram_identity(
                        telegram_user_id=resolved_user_id,
                        username=resolved_username,
                    )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_tg_id",
            user=str(detail.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[t("admin_activity_detail_new_value", lang, value=tg_id or "-")],
        )
        return detail

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
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        return await self._add_client_total_gb_for_ref(
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
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        return await self._extend_client_expiry_for_ref(
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
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        return await self._delete_client_for_ref(
            actor_user_id=actor_user_id,
            settings=settings,
            ref=ref,
        )

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
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        before = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        if total_gb is None and not self.access_service.is_root_admin(actor_user_id, settings):
            raise ValueError("delegated_unlimited_not_allowed")
        if total_gb is not None and self.financial_service is not None:
            await self.financial_service.validate_target_limits(
                actor_user_id=actor_user_id,
                settings=settings,
                total_gb=total_gb,
            )
        charge_tx = None
        if self.financial_service is not None:
            before_allocated_gb = max(0.0, bytes_to_gb(int(before.get("total") or 0)))
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation="set_client_total_gb",
                traffic_gb=0 if total_gb is None else max(0, total_gb - before_allocated_gb),
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await self.panel_service.set_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, total_gb)
            after = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            if charge_tx is not None and self.financial_service is not None:
                await self.financial_service.refund_transaction(
                    actor_user_id=actor_user_id,
                    transaction_id=int(charge_tx["id"]),
                    reason=f"refund:set_client_total_gb_failed:{ref.client_uuid}",
                )
            raise
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="set_client_total_gb",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"total_gb={'unlimited' if total_gb is None else total_gb}",
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_total_gb",
            user=str(after.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[
                t(
                    "admin_activity_detail_traffic_change",
                    lang,
                    before=format_gb(int(before.get("total") or 0), lang),
                    after=t("admin_unlimited", lang) if total_gb is None else format_gb(int(after.get("total") or 0), lang),
                )
            ],
        )
        if self.usage_service is not None:
            added_bytes = max(0, int(after.get("total") or 0) - int(before.get("total") or 0))
            if added_bytes > 0:
                await self.usage_service.notify_user_traffic_increased(
                    panel_id=ref.panel_id,
                    client_email=str(after.get("email") or ref.client_email or ""),
                    added_bytes=added_bytes,
                    new_total_bytes=int(after.get("total") or 0),
                )
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
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        before = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        if days is None and not self.access_service.is_root_admin(actor_user_id, settings):
            raise ValueError("delegated_unlimited_not_allowed")
        if days is not None and self.financial_service is not None:
            await self.financial_service.validate_target_limits(
                actor_user_id=actor_user_id,
                settings=settings,
                total_days=days,
            )
        charge_tx = None
        if self.financial_service is not None:
            before_expiry = int(before.get("expiry") or 0)
            now_ts = int(time.time())
            before_days = 0 if before_expiry <= now_ts else max(1, (before_expiry - now_ts + 86399) // 86400)
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation="set_client_expiry_days",
                expiry_days=0 if days is None else max(0, days - before_days),
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await self.panel_service.set_client_expiry_days(ref.panel_id, ref.inbound_id, ref.client_uuid, days)
            after = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            if charge_tx is not None and self.financial_service is not None:
                await self.financial_service.refund_transaction(
                    actor_user_id=actor_user_id,
                    transaction_id=int(charge_tx["id"]),
                    reason=f"refund:set_client_expiry_days_failed:{ref.client_uuid}",
                )
            raise
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="set_client_expiry_days",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"days={'unlimited' if days is None else days}",
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_expiry_days",
            user=str(after.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[
                t(
                    "admin_activity_detail_expiry_change",
                    lang,
                    before=to_local_date(before.get("expiry"), settings.timezone, lang),
                    after=t("admin_unlimited", lang) if days is None else to_local_date(after.get("expiry"), settings.timezone, lang),
                )
            ],
        )
        if self.usage_service is not None:
            before_expiry = int(before.get("expiry") or 0)
            after_expiry = int(after.get("expiry") or 0)
            if after_expiry > before_expiry:
                added_days = max(1, (after_expiry - before_expiry + 86399) // 86400)
                await self.usage_service.notify_user_expiry_extended(
                    panel_id=ref.panel_id,
                    client_email=str(after.get("email") or ref.client_email or ""),
                    added_days=added_days,
                    new_expiry=after.get("expiry"),
                )
        return before, after

    async def reset_client_traffic_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> dict[str, Any]:
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        await self.panel_service.reset_client_traffic(ref.panel_id, ref.inbound_id, str(detail.get("email") or ""))
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="reset_client_traffic",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
        )
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_reset_traffic",
            user=str(detail.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
        )
        return detail

    async def set_client_limit_ip_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        limit_ip: int | None,
    ) -> dict[str, Any]:
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        await self.panel_service.set_client_limit_ip(ref.panel_id, ref.inbound_id, ref.client_uuid, limit_ip)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="set_client_limit_ip",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"limit_ip={'unlimited' if limit_ip is None else limit_ip}",
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_ip_limit",
            user=str(detail.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[
                t(
                    "admin_activity_detail_new_value",
                    lang,
                    value=t("admin_unlimited", lang) if limit_ip is None else limit_ip,
                )
            ],
        )
        return detail

    async def _apply_delegated_username_prefix(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        client_email: str,
    ) -> str:
        email = client_email.strip()
        if self.access_service.is_root_admin(actor_user_id, settings):
            return email
        profile = await self.db.get_delegated_admin_profile(actor_user_id)
        prefix = str(profile.get("username_prefix") or "").strip()
        if not prefix:
            return email
        return email if email.startswith(prefix) else f"{prefix}{email}"

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
        delegated_admin_id = await self.db.upsert_delegated_admin(
            telegram_user_id=telegram_user_id,
            title=title,
            created_by=actor_user_id,
            parent_user_id=None if self.access_service.is_root_admin(actor_user_id, settings) else actor_user_id,
            admin_scope=admin_scope,
        )
        access_id = await self.db.add_delegated_admin_inbound_access(
            delegated_admin_id=delegated_admin_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )
        await self.db.ensure_delegated_admin_profile(telegram_user_id)
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
        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_full_admin:
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
        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_full_admin:
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
        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_full_admin:
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

    async def list_delegated_admin_accesses(self, manager_user_id: int | None = None) -> list[dict[str, Any]]:
        rows = await self.db.list_delegated_admin_access_rows(manager_user_id=manager_user_id)
        inbound_maps: dict[int, dict[int, str]] = {}
        for row in rows:
            panel_id = int(row["panel_id"])
            if panel_id not in inbound_maps:
                inbound_maps[panel_id] = await self._inbound_name_map_for_panel(panel_id)
            row["inbound_name"] = inbound_maps[panel_id].get(int(row["inbound_id"]), f"inbound-{row['inbound_id']}")
        return rows

    async def count_owned_clients_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> int:
        if self.access_service.is_root_admin(actor_user_id, settings):
            return 0
        count = 0
        for panel in await self.panel_service.list_panels():
            panel_id = int(panel["id"])
            try:
                clients = await self.panel_service.list_clients(
                    panel_id,
                    owner_admin_user_id=actor_user_id,
                )
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
        delegated = await self.db.get_delegated_admin_by_user_id(telegram_user_id)
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
        access_rows = await self.db.list_admin_access_rows_for_user(telegram_user_id)
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

    async def financial_scope_user_ids(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[int]:
        context = await self.access_service.get_admin_context(actor_user_id, settings)
        if context.is_root_admin:
            return []
        if context.delegated_scope == "full":
            return await self.db.get_delegated_admin_subtree_user_ids(manager_user_id=actor_user_id, include_self=True)
        return [actor_user_id]

    async def get_admin_scope_financial_summary(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> dict[str, Any]:
        wallet = await self.financial_service.get_wallet(actor_user_id) if self.financial_service is not None else {
            "balance": 0,
            "currency": "تومان",
        }
        pricing = await self.financial_service.get_pricing(actor_user_id) if self.financial_service is not None else {
            "price_per_gb": 0,
            "price_per_day": 0,
            "currency": "تومان",
            "charge_basis": "allocated",
            "apply_price_to_past_reports": 1,
        }
        owner_ids = await self.financial_scope_user_ids(actor_user_id=actor_user_id, settings=settings)
        if not owner_ids:
            return {
                "wallet": wallet,
                "pricing": pricing,
                "clients_count": 0,
                "allocated_bytes": 0,
                "consumed_bytes": 0,
                "allocated_gb": 0,
                "consumed_gb": 0,
                "sale_amount": 0,
                "debt_amount": 0,
                "total_transactions": 0,
                "scope_user_ids": [],
            }
        owner_id_set = {str(owner_id) for owner_id in owner_ids}
        seen: set[tuple[int, int, str]] = set()
        clients_count = 0
        allocated_bytes = 0
        consumed_bytes = 0
        panel_total_consumed_bytes = 0
        root_created_consumed_bytes = 0
        root_admin_id_set = {str(admin_id) for admin_id in settings.admin_ids}
        for panel in await self.panel_service.list_panels():
            panel_id = int(panel["id"])
            try:
                inbounds = await self.panel_service.list_inbounds(panel_id)
            except Exception:
                continue
            for inbound in inbounds:
                inbound_id = int(inbound.get("id") or 0)
                if inbound_id <= 0:
                    continue
                panel_total_consumed_bytes += max(0, int(inbound.get("up") or 0)) + max(0, int(inbound.get("down") or 0))

                stats_by_uuid: dict[str, dict[str, int]] = {}
                for stat in inbound.get("clientStats") or []:
                    if not isinstance(stat, dict):
                        continue
                    stat_uuid = str(stat.get("uuid") or stat.get("id") or "").strip()
                    if not stat_uuid:
                        continue
                    stats_by_uuid[stat_uuid] = {
                        "used": max(0, int(stat.get("up") or 0)) + max(0, int(stat.get("down") or 0)),
                        "total": max(0, int(stat.get("total") or 0)),
                    }

                settings_raw = inbound.get("settings")
                settings_obj: dict[str, Any] = {}
                if isinstance(settings_raw, str) and settings_raw.strip():
                    try:
                        parsed = json.loads(settings_raw)
                        if isinstance(parsed, dict):
                            settings_obj = parsed
                    except Exception:
                        settings_obj = {}
                clients = settings_obj.get("clients") if isinstance(settings_obj.get("clients"), list) else []
                for client in clients:
                    if not isinstance(client, dict):
                        continue
                    client_uuid = str(client.get("id") or client.get("uuid") or "").strip()
                    if not client_uuid:
                        continue
                    comment = str(client.get("comment") or "").strip()
                    usage = stats_by_uuid.get(client_uuid, {"used": 0, "total": 0})

                    if comment == "" or comment in root_admin_id_set:
                        root_created_consumed_bytes += int(usage.get("used") or 0)

                    if comment not in owner_id_set:
                        continue
                    key = (panel_id, inbound_id, client_uuid)
                    if key in seen:
                        continue
                    seen.add(key)
                    clients_count += 1
                    allocated_bytes += max(0, int(client.get("totalGB") or 0))
                    consumed_bytes += int(usage.get("used") or 0)
        price_per_gb = int(pricing.get("price_per_gb") or 0)
        allocated_gb = allocated_bytes // (1024 ** 3)
        if allocated_bytes % (1024 ** 3):
            allocated_gb += 1
        gb_unit = 1024 ** 3
        charge_basis = str(pricing.get("charge_basis") or "allocated")
        if charge_basis == "consumed":
            consumed_bytes = max(0, panel_total_consumed_bytes - root_created_consumed_bytes)
        consumed_gb = float(consumed_bytes) / float(gb_unit) if consumed_bytes > 0 else 0.0
        scope_totals = (
            await self.financial_service.get_scope_sales_totals(owner_ids)
            if self.financial_service is not None
            else {
                "total_sales": 0,
                "total_transactions": 0,
            }
        )
        sale_amount = int(scope_totals.get("total_sales") or 0)
        if charge_basis == "consumed":
            debt_amount = (consumed_bytes * price_per_gb) // gb_unit
        else:
            debt_amount = allocated_gb * price_per_gb
        return {
            "wallet": wallet,
            "pricing": pricing,
            "clients_count": clients_count,
            "allocated_bytes": allocated_bytes,
            "consumed_bytes": consumed_bytes,
            "allocated_gb": allocated_gb,
            "consumed_gb": consumed_gb,
            "sale_amount": sale_amount,
            "debt_amount": debt_amount,
            "total_transactions": int(scope_totals.get("total_transactions") or 0),
            "scope_user_ids": owner_ids,
        }

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
        client_email = await self._apply_delegated_username_prefix(
            actor_user_id=actor_user_id,
            settings=settings,
            client_email=client_email,
        )
        allowed = await self.access_service.can_access_inbound(
            user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )
        if not allowed:
            raise ValueError("you do not have access to this inbound.")
        existing_clients = await self.panel_service.list_inbound_clients(panel_id, inbound_id)
        normalized_email = client_email.strip().lower()
        if any(str(item.get("email") or "").strip().lower() == normalized_email for item in existing_clients):
            raise ValueError("client email already exists on this inbound.")
        if not (await self.access_service.get_admin_context(actor_user_id, settings)).is_full_admin:
            profile = await self.db.get_delegated_admin_profile(actor_user_id)
            max_clients = int(profile.get("max_clients") or 0)
            if max_clients > 0:
                current_count = await self.count_owned_clients_for_actor(actor_user_id=actor_user_id, settings=settings)
                if current_count >= max_clients:
                    raise ValueError("delegated admin max clients reached.")

        charge_tx = None
        if self.financial_service is not None:
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation="create_client",
                traffic_gb=total_gb,
                expiry_days=expiry_days,
                details=f"panel={panel_id};inbound={inbound_id};email={client_email}",
            )
        try:
            created = await self.panel_service.create_client(
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_email=client_email,
                total_gb=total_gb,
                expiry_days=expiry_days,
                tg_id=tg_id,
                comment=str(actor_user_id),
            )
        except Exception:
            if charge_tx is not None and self.financial_service is not None:
                await self.financial_service.refund_transaction(
                    actor_user_id=actor_user_id,
                    transaction_id=int(charge_tx["id"]),
                    reason=f"refund:create_client_failed:{client_email}",
                )
            raise
        try:
            await self.db.upsert_client_owner(
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_uuid=str(created["uuid"]),
                owner_user_id=actor_user_id,
                client_email=client_email,
            )
        except Exception:
            logger.exception(
                "failed to persist client owner mapping",
                extra={"panel_id": panel_id, "inbound_id": inbound_id, "client_uuid": created.get("uuid")},
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
        lang = await self.db.get_user_language(actor_user_id)
        actor = await self._actor_display_name(actor_user_id)
        panel_name, inbound_name = await self._panel_inbound_names(panel_id=panel_id, inbound_id=inbound_id)
        activity_text = t(
            "admin_activity_notify_template",
            lang,
            actor=actor,
            action=t("admin_activity_action_create_client", lang),
            user=client_email,
            panel=panel_name,
            inbound=inbound_name,
            details="\n"
            + "\n".join(
                [
                    t("admin_activity_detail_amount_gb", lang, value=total_gb),
                    t("admin_activity_detail_amount_days", lang, value=expiry_days),
                ]
            ),
        )
        await self._record_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            text=activity_text,
        )
        return {
            **created,
            "vless_uri": vless_uri,
            "sub_url": sub_url,
            "wallet_charge_amount": int(charge_tx["amount"]) if charge_tx is not None else 0,
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

        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_full_admin:
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
        add_gb: float,
    ) -> ManagedClientRef:
        ref = await self.resolve_client_from_vless_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            vless_uri=vless_uri,
        )
        await self._add_client_total_gb_for_ref(
            actor_user_id=actor_user_id,
            settings=settings,
            ref=ref,
            add_gb=add_gb,
            operation_name="add_client_traffic",
            refund_reason_prefix="refund:add_client_traffic_failed",
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
        await self._extend_client_expiry_for_ref(
            actor_user_id=actor_user_id,
            settings=settings,
            ref=ref,
            add_days=add_days,
            operation_name="extend_client_expiry",
            refund_reason_prefix="refund:extend_client_expiry_failed",
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
        await self._delete_client_for_ref(
            actor_user_id=actor_user_id,
            settings=settings,
            ref=ref,
        )
        return ref
