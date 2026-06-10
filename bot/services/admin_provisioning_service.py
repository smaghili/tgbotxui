from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
import uuid as uuid_lib

from bot.config import Settings
from bot.db import Database
from bot.i18n import t
from bot.repositories.delegated_admin_repository import DelegatedAdminRepository
from bot.services.access_service import AccessService
from bot.services.delegated_access_service import DelegatedAccessService
from bot.services.financial_service import FinancialService
from bot.services.operation_guard_service import OperationGuardService
from bot.services.panel_service import PanelService
from bot.services.client_group_service import ClientGroupService
from bot.services.provisioning_client_service import ProvisioningClientService
from bot.services.provisioning_financial_summary_service import ProvisioningFinancialSummaryService
from bot.services.provisioning_models import InboundAccess, ManagedClientRef
from bot.utils import build_admin_activity_notice, bytes_to_gb, display_name_from_parts, format_gb, gb_to_bytes, now_jalali_datetime, to_local_date

if TYPE_CHECKING:
    from bot.services.usage_service import UsageService

logger = logging.getLogger(__name__)


def _owner_id_from_comment(comment: str) -> int | None:
    owner_raw = comment.strip().split(":", 1)[0].strip()
    return int(owner_raw) if owner_raw.isdigit() else None


def _delegate_finance_comment_tag(comment: str) -> str | None:
    raw = comment.strip()
    if ":" not in raw:
        return None
    tail = raw.split(":", 1)[1].strip()
    if tail.lower() == "moafresume":
        return "moafresume"
    if tail.lower() == "moaf":
        return "moaf"
    return None


class AdminProvisioningService:
    def __init__(
        self,
        *,
        db: Database,
        panel_service: PanelService,
        access_service: AccessService,
        financial_service: FinancialService | None = None,
        operation_guard: OperationGuardService | None = None,
        usage_service: "UsageService | None" = None,
    ) -> None:
        self.db = db
        self.panel_service = panel_service
        self.access_service = access_service
        self.financial_service = financial_service
        self.operation_guard = operation_guard
        self.usage_service = usage_service
        self.client_ops = ProvisioningClientService(self)
        self.client_group_service = ClientGroupService(db=db, panel_service=panel_service)
        self.delegated_repo = DelegatedAdminRepository(db=db)
        self.delegated_access = DelegatedAccessService(
            db=db,
            repo=self.delegated_repo,
            panel_service=panel_service,
            access_service=access_service,
            financial_service=financial_service,
        )
        self.financial_summary = ProvisioningFinancialSummaryService(
            db=db,
            panel_service=panel_service,
            access_service=access_service,
            financial_service=financial_service,
        )

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

    async def _log_delegated_create_failure(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_email: str,
        total_gb: float,
        expiry_days: int,
        exc: Exception,
    ) -> None:
        if self.access_service.is_root_admin(actor_user_id, settings):
            return
        delegated = await self.db.get_delegated_admin_by_user_id(actor_user_id)
        profile = await self.db.get_delegated_admin_profile(actor_user_id)
        wallet = await self.financial_service.get_wallet(actor_user_id) if self.financial_service is not None else None
        parent_user_id = int((delegated or {}).get("parent_user_id") or 0) or None
        parent_profile = await self.db.get_delegated_admin_profile(parent_user_id) if parent_user_id is not None else None
        parent_wallet = (
            await self.financial_service.get_wallet(parent_user_id)
            if self.financial_service is not None and parent_user_id is not None
            else None
        )
        logger.warning(
            "delegated create client failed",
            extra={
                "actor_user_id": actor_user_id,
                "panel_id": panel_id,
                "inbound_id": inbound_id,
                "client_email": client_email,
                "total_gb": total_gb,
                "expiry_days": expiry_days,
                "error": str(exc),
                "delegate_allow_negative_wallet": int(profile.get("allow_negative_wallet") or 0),
                "delegate_wallet_balance": int((wallet or {}).get("balance") or 0),
                "delegate_parent_user_id": parent_user_id or 0,
                "parent_allow_negative_wallet": int((parent_profile or {}).get("allow_negative_wallet") or 0),
                "parent_wallet_balance": int((parent_wallet or {}).get("balance") or 0),
            },
        )

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
        panel_id: int | None = None,
        notification_kind: str | None = None,
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
        if notification_kind is None:
            return
        await self.usage_service.notify_admin_activity(
            actor_user_id=actor_user_id,
            text=stamped_text,
            panel_id=panel_id,
            notification_kind=notification_kind,
        )

    async def record_admin_activity(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        text: str,
        panel_id: int | None = None,
        notification_kind: str | None = None,
    ) -> None:
        await self._record_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            text=text,
            panel_id=panel_id,
            notification_kind=notification_kind,
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
            panel_id=panel_id,
            notification_kind=action_key,
        )

    async def _initial_expiry_days_for_client(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_email: str,
    ) -> int | None:
        """Return initial expiry days from the earliest create_client charge metadata."""
        if self.db.conn is None:
            return None
        cur = await self.db.conn.execute(
            """
            SELECT metadata_json
            FROM wallet_transactions
            WHERE operation='create_client'
              AND details LIKE ?
            ORDER BY id ASC;
            """,
            (f"%panel={int(panel_id)};inbound={int(inbound_id)};email={client_email}%",),
        )
        rows = await cur.fetchall()
        for row in rows:
            try:
                raw = str(row["metadata_json"] or "").strip()
                if not raw:
                    continue
                meta = json.loads(raw)
                days = int(meta.get("expiry_days") or 0)
                if days > 0:
                    return days
            except Exception:
                continue
        return None

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

    async def _current_parent_user_id(self, actor_user_id: int) -> int | None:
        delegated = await self.db.get_delegated_admin_by_user_id(actor_user_id)
        if delegated is None:
            return None
        parent_user_id = int(delegated.get("parent_user_id") or 0)
        return parent_user_id if parent_user_id > 0 else None

    async def _last_parent_user_id(self, actor_user_id: int) -> int | None:
        loader = getattr(self.db, "get_last_delegated_admin_parent_event", None)
        if loader is None:
            return None
        event = await loader(actor_user_id)
        if event is None:
            return None
        old_parent_user_id = int(event.get("old_parent_user_id") or 0)
        new_parent_user_id = int(event.get("new_parent_user_id") or 0)
        return old_parent_user_id or new_parent_user_id or None

    async def _write_hierarchy_segment(
        self,
        *,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        owner_user_id: int,
        actor_user_id: int,
        start_bytes: int,
        end_bytes: int,
        is_billable: bool,
        source: str,
        client_email: str,
    ) -> None:
        segment_writer = getattr(self.db, "add_moaf_client_traffic_segment", None)
        if segment_writer is None or end_bytes <= start_bytes:
            return
        await segment_writer(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            owner_user_id=owner_user_id,
            actor_user_id=actor_user_id,
            start_bytes=start_bytes,
            end_bytes=end_bytes,
            is_billable=is_billable,
            source=source,
            client_email=client_email,
        )

    async def _update_client_comments_for_new_parent(
        self,
        *,
        child_user_id: int,
        new_parent_user_id: int | None,
    ) -> None:
        """Update all clients' comments to reflect new parent ID"""
        for panel in await self.panel_service.list_panels():
            panel_id = int(panel["id"])
            try:
                clients = await self.panel_service.list_clients(panel_id, owner_admin_user_id=child_user_id)
            except Exception:
                continue
            for client in clients:
                inbound_id = int(client.get("inbound_id") or 0)
                client_uuid = str(client.get("uuid") or "").strip()
                if inbound_id <= 0 or not client_uuid:
                    continue
                try:
                    detail = await self.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
                except Exception:
                    continue
                comment = str(detail.get("comment") or "").strip()
                if _owner_id_from_comment(comment) != child_user_id:
                    continue

                # Update comment with new parent ID
                finance_tag = _delegate_finance_comment_tag(comment)
                if new_parent_user_id is None:
                    # No parent - comment format: "child_id"
                    new_comment = str(child_user_id)
                else:
                    # Has parent - comment format: "parent_id" or "parent_id:tag"
                    new_comment = str(new_parent_user_id)
                    if finance_tag:
                        new_comment = f"{new_parent_user_id}:{finance_tag}"

                if new_comment != comment:
                    try:
                        await self.panel_service.update_client_comment(
                            panel_id=panel_id,
                            inbound_id=inbound_id,
                            client_uuid=client_uuid,
                            comment=new_comment,
                        )
                    except Exception:
                        pass

    async def _snapshot_existing_clients_for_parent(
        self,
        *,
        actor_user_id: int,
        child_user_id: int,
        parent_user_id: int,
        source: str,
    ) -> None:
        segment_loader = getattr(self.db, "get_moaf_client_traffic_segments", None)
        for panel in await self.panel_service.list_panels():
            panel_id = int(panel["id"])
            try:
                clients = await self.panel_service.list_clients(panel_id, owner_admin_user_id=child_user_id)
            except Exception:
                continue
            for client in clients:
                inbound_id = int(client.get("inbound_id") or 0)
                client_uuid = str(client.get("uuid") or "").strip()
                if inbound_id <= 0 or not client_uuid:
                    continue
                if segment_loader is not None:
                    existing_segments = await segment_loader(
                        panel_id=panel_id,
                        inbound_id=inbound_id,
                        client_uuid=client_uuid,
                    )
                    if existing_segments:
                        continue
                try:
                    detail = await self.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
                except Exception:
                    continue
                total_bytes = max(0, int(detail.get("total") or 0))
                comment = str(detail.get("comment") or "").strip()
                if _owner_id_from_comment(comment) != child_user_id:
                    continue
                if total_bytes <= 0:
                    continue
                await self._write_hierarchy_segment(
                    panel_id=panel_id,
                    inbound_id=inbound_id,
                    client_uuid=client_uuid,
                    owner_user_id=parent_user_id,
                    actor_user_id=child_user_id,
                    start_bytes=0,
                    end_bytes=total_bytes,
                    is_billable=True,
                    source=source,
                    client_email=str(detail.get("email") or client.get("email") or ""),
                )

    async def _refund_charge_bundle(self, *, actor_user_id: int, charge_tx: dict[str, Any] | None, reason: str) -> None:
        if charge_tx is None or self.financial_service is None:
            return
        refund_fn = getattr(self.financial_service, "refund_transaction", None)
        if refund_fn is None:
            return
        tx_ids: list[int] = [int(charge_tx["id"])]
        related = charge_tx.get("related_transaction_ids")
        if isinstance(related, list):
            for item in related:
                try:
                    tx_ids.append(int(item))
                except Exception:
                    continue
        for transaction_id in tx_ids:
            await refund_fn(
                actor_user_id=actor_user_id,
                transaction_id=transaction_id,
                reason=reason,
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
        comment_before = str(before.get("comment") or "").strip()
        fin_tag_before = _delegate_finance_comment_tag(comment_before)
        is_moaf_actor = actor_user_id in getattr(settings, "moaf_admin_ids", set())
        moaf_min_bytes = max(0, int(getattr(settings, "moaf_min_traffic_bytes", 0) or 0))
        current_total_bytes = max(0, int(before.get("total") or 0))
        moaf_remaining_bytes = max(0, moaf_min_bytes - current_total_bytes) if is_moaf_actor else 0
        moaf_gift_applies = is_moaf_actor and current_total_bytes < moaf_min_bytes
        billed_add_gb = 0.0 if moaf_gift_applies else add_gb
        charge_tx = None
        if self.financial_service is not None and billed_add_gb > 0:
            await self.financial_service.validate_operation_limits(
                actor_user_id=actor_user_id,
                settings=settings,
                traffic_gb=billed_add_gb,
            )
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation=operation_name,
                panel_id=ref.panel_id,
                traffic_gb=billed_add_gb,
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            existing_segments: list[dict[str, Any]] = []
            segment_loader = getattr(self.db, "get_moaf_client_traffic_segments", None)
            if segment_loader is not None:
                existing_segments = await segment_loader(
                    panel_id=ref.panel_id,
                    inbound_id=ref.inbound_id,
                    client_uuid=ref.client_uuid,
                )
            current_parent_user_id = await self._current_parent_user_id(actor_user_id)
            last_parent_user_id = await self._last_parent_user_id(actor_user_id)
            should_record_segment = (
                bool(existing_segments)
                or current_parent_user_id is not None
                or last_parent_user_id is not None
            )
            owner_user_id_for_segments: int | None = None
            if should_record_segment:
                owner_user_id_for_segments = (
                    int(existing_segments[0].get("owner_user_id") or 0)
                    if existing_segments
                    else None
                )
                owner_user_id_for_segments = owner_user_id_for_segments or await self.db.get_client_owner(
                    panel_id=ref.panel_id,
                    inbound_id=ref.inbound_id,
                    client_uuid=ref.client_uuid,
                )
                owner_user_id_for_segments = owner_user_id_for_segments or _owner_id_from_comment(
                    str(before.get("comment") or "")
                )
            updated_comment = None
            moaf_owner_user_id = owner_user_id_for_segments
            if moaf_gift_applies:
                updated_comment = f"{actor_user_id}:Moaf"
            try:
                if updated_comment is None:
                    await self.panel_service.add_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, add_gb)
                else:
                    await self.panel_service.add_client_total_gb(
                        ref.panel_id,
                        ref.inbound_id,
                        ref.client_uuid,
                        add_gb,
                        comment=updated_comment,
                    )
            except TypeError:
                await self.panel_service.add_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, add_gb)
            after = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
            before_total_bytes = max(0, int(before.get("total") or 0))
            after_total_bytes = max(0, int(after.get("total") or 0))
            segment_writer = getattr(self.db, "add_moaf_client_traffic_segment", None)
            if segment_writer is not None and should_record_segment and owner_user_id_for_segments is not None:
                if not existing_segments and before_total_bytes > 0:
                    initial_owner_user_id = current_parent_user_id or owner_user_id_for_segments
                    initial_is_billable = True
                    initial_source = "initial"
                    if fin_tag_before == "moaf" and current_parent_user_id is not None:
                        initial_is_billable = False
                        initial_source = "initial_moaf"
                    elif (
                        moaf_gift_applies
                        and current_parent_user_id is not None
                        and current_parent_user_id == owner_user_id_for_segments
                    ):
                        initial_is_billable = False
                        initial_source = "initial_moaf"
                    await segment_writer(
                        panel_id=ref.panel_id,
                        inbound_id=ref.inbound_id,
                        client_uuid=ref.client_uuid,
                        owner_user_id=initial_owner_user_id,
                        actor_user_id=initial_owner_user_id,
                        start_bytes=0,
                        end_bytes=before_total_bytes,
                        is_billable=initial_is_billable,
                        source=initial_source,
                        client_email=str(after.get("email") or ref.client_email or ""),
                    )
                if current_parent_user_id is not None and not moaf_gift_applies:
                    await segment_writer(
                        panel_id=ref.panel_id,
                        inbound_id=ref.inbound_id,
                        client_uuid=ref.client_uuid,
                        owner_user_id=current_parent_user_id,
                        actor_user_id=actor_user_id,
                        start_bytes=before_total_bytes,
                        end_bytes=after_total_bytes,
                        is_billable=True,
                        source="add_traffic",
                        client_email=str(after.get("email") or ref.client_email or ""),
                    )
            if moaf_gift_applies:
                exemption_writer = getattr(self.db, "upsert_moaf_client_exemption", None)
                if exemption_writer is not None and moaf_owner_user_id is not None:
                    await exemption_writer(
                        panel_id=ref.panel_id,
                        inbound_id=ref.inbound_id,
                        client_uuid=ref.client_uuid,
                        owner_user_id=moaf_owner_user_id,
                        moaf_user_id=actor_user_id,
                        exempt_after_bytes=before_total_bytes,
                    )
                if segment_writer is not None and moaf_owner_user_id is not None:
                    gifted_end_bytes = after_total_bytes
                    if gifted_end_bytes > before_total_bytes:
                        await segment_writer(
                            panel_id=ref.panel_id,
                            inbound_id=ref.inbound_id,
                            client_uuid=ref.client_uuid,
                            owner_user_id=moaf_owner_user_id,
                            actor_user_id=actor_user_id,
                            start_bytes=before_total_bytes,
                            end_bytes=gifted_end_bytes,
                            is_billable=False,
                            source="moaf",
                            client_email=str(after.get("email") or ref.client_email or ""),
                        )
                if self.usage_service is not None:
                    notifier = getattr(self.usage_service, "notify_root_admin_activity", None)
                    if notifier is not None:
                        await notifier(
                            actor_user_id=actor_user_id,
                            text=f"**خرید ویژه**\nافزایش حجم کاربر: {ref.client_email or '-'}",
                            panel_id=ref.panel_id,
                        )
        except Exception:
            await self._refund_charge_bundle(
                actor_user_id=actor_user_id,
                charge_tx=charge_tx,
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
        if not moaf_gift_applies:
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
                panel_id=ref.panel_id,
                expiry_days=add_days,
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};client_uuid={ref.client_uuid}",
            )
        try:
            await self.panel_service.extend_client_expiry_days(ref.panel_id, ref.inbound_id, ref.client_uuid, add_days)
            after = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            await self._refund_charge_bundle(
                actor_user_id=actor_user_id,
                charge_tx=charge_tx,
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

    async def set_client_owner_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        owner_user_id: int,
    ) -> dict[str, Any]:
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        if owner_user_id not in settings.admin_ids and not await self.access_service.is_delegated_admin(owner_user_id):
            raise ValueError("selected owner is not an active admin.")
        client_email = str(detail.get("email") or ref.client_email or "").strip()
        await self.db.upsert_client_owner(
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            client_uuid=ref.client_uuid,
            owner_user_id=owner_user_id,
            client_email=client_email or None,
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_set_tg_id",
            user=str(detail.get("email") or ref.client_email or "-"),
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[t("admin_activity_detail_new_value", lang, value=f"owner={owner_user_id}")],
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
        return await self.client_ops.add_client_total_gb_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            add_gb=add_gb,
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
        return await self.client_ops.extend_client_expiry_days_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            add_days=add_days,
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
        return await self.client_ops.delete_client_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
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
        return await self.client_ops.set_client_total_gb_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            total_gb=total_gb,
        )

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
        return await self.client_ops.set_client_expiry_days_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            days=days,
        )

    async def reset_client_traffic_for_actor(
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
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        email = str(detail.get("email") or "").strip()
        if not email:
            raise ValueError("client email missing.")
        charge_tx = None
        if self.financial_service is not None:
            charge_tx = await self.financial_service.charge_operation(
                actor_user_id=actor_user_id,
                settings=settings,
                operation="reset_client_traffic",
                panel_id=ref.panel_id,
                traffic_gb=0 if total_gb is None else total_gb,
                details=f"panel={ref.panel_id};inbound={ref.inbound_id};email={email}",
            )
        try:
            await self.panel_service.reset_client_traffic(ref.panel_id, ref.inbound_id, email)
            await self.panel_service.set_client_total_gb(ref.panel_id, ref.inbound_id, ref.client_uuid, total_gb)
            initial_days = await self._initial_expiry_days_for_client(
                panel_id=ref.panel_id,
                inbound_id=ref.inbound_id,
                client_email=email,
            )
            if initial_days is not None:
                await self.panel_service.set_client_expiry_days(
                    ref.panel_id, ref.inbound_id, ref.client_uuid, initial_days
                )
            updated = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        except Exception:
            await self._refund_charge_bundle(
                actor_user_id=actor_user_id,
                charge_tx=charge_tx,
                reason=f"refund:reset_client_traffic_failed:{ref.client_uuid}",
            )
            raise
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="reset_client_traffic",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"total_gb={'unlimited' if total_gb is None else total_gb}",
        )
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_reset_traffic",
            user=email or ref.client_email or "-",
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[
                t(
                    "admin_activity_detail_amount_gb",
                    await self.db.get_user_language(actor_user_id),
                    value="∞" if total_gb is None else total_gb,
                )
            ],
        )
        if self.usage_service is not None:
            await self.usage_service.notify_user_traffic_reset(
                panel_id=ref.panel_id,
                client_email=email,
                new_total_bytes=0 if total_gb is None else gb_to_bytes(total_gb),
            )
        return detail, updated

    async def set_client_outbound_tag_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        outbound_tag: str,
    ) -> dict[str, Any]:
        ref = await self._managed_ref_from_panel_client(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        detail = await self.panel_service.get_client_detail(ref.panel_id, ref.inbound_id, ref.client_uuid)
        email = str(detail.get("email") or "").strip()
        if not email:
            raise ValueError("client email missing.")
        if not await self.panel_service.actor_may_use_outbound_tag(
            ref.panel_id,
            actor_user_id,
            outbound_tag.strip(),
            settings,
            self.access_service,
        ):
            raise ValueError("outbound not allowed for this admin.")
        display_map = await self.db.get_panel_outbound_display_map(ref.panel_id)
        display_tag = display_map.get(outbound_tag.strip(), outbound_tag.strip())
        await self.panel_service.set_client_outbound_tag(
            ref.panel_id, ref.inbound_id, email, outbound_tag.strip()
        )
        await self.panel_service.reload_xray_config(ref.panel_id)
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="set_client_outbound",
            target_type="client",
            target_id=ref.client_uuid,
            success=True,
            details=f"outbound={outbound_tag}",
        )
        lang = await self.db.get_user_language(actor_user_id)
        await self._record_templated_admin_activity(
            actor_user_id=actor_user_id,
            settings=settings,
            action_key="admin_activity_action_change_location",
            user=email,
            panel_id=ref.panel_id,
            inbound_id=ref.inbound_id,
            details=[
                t(
                    "admin_activity_detail_outbound_tag",
                    lang,
                    tag=display_tag,
                )
            ],
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
        return await self.delegated_access.resolve_admin_target(value)

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
        return await self.delegated_access.grant_delegated_admin_access(
            actor_user_id=actor_user_id,
            settings=settings,
            telegram_user_id=telegram_user_id,
            title=title,
            panel_id=panel_id,
            inbound_id=inbound_id,
            admin_scope=admin_scope,
        )

    async def grant_delegated_admin_panel_access(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        panel_id: int,
    ) -> int:
        return await self.delegated_access.grant_delegated_admin_panel_access(
            actor_user_id=actor_user_id,
            telegram_user_id=telegram_user_id,
            panel_id=panel_id,
        )

    async def list_panel_inbound_access_state(
        self,
        *,
        panel_id: int,
        telegram_user_id: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], set[int]]:
        return await self.delegated_access.list_panel_inbound_access_state(
            panel_id=panel_id,
            telegram_user_id=telegram_user_id,
        )

    async def sync_delegated_admin_panel_inbound_access(
        self,
        *,
        actor_user_id: int,
        panel_id: int,
        telegram_user_id: int,
        inbound_ids: set[int],
    ) -> None:
        await self.delegated_access.sync_delegated_admin_panel_inbound_access(
            actor_user_id=actor_user_id,
            panel_id=panel_id,
            telegram_user_id=telegram_user_id,
            inbound_ids=inbound_ids,
        )

    async def change_delegated_admin_parent(
        self,
        *,
        actor_user_id: int,
        child_user_id: int,
        new_parent_user_id: int | None,
    ) -> None:
        delegated = await self.db.get_delegated_admin_by_user_id(child_user_id)
        if delegated is None:
            raise ValueError("delegated admin was not found.")
        if new_parent_user_id == child_user_id:
            raise ValueError("delegated admin cannot be parent of itself.")
        old_parent_user_id = int(delegated.get("parent_user_id") or 0) or None
        if old_parent_user_id == new_parent_user_id:
            return

        # Update all clients' comments to reflect new parent ID
        await self._update_client_comments_for_new_parent(
            child_user_id=child_user_id,
            new_parent_user_id=new_parent_user_id,
        )

        if old_parent_user_id is not None:
            await self._snapshot_existing_clients_for_parent(
                actor_user_id=actor_user_id,
                child_user_id=child_user_id,
                parent_user_id=old_parent_user_id,
                source="parent_detach_snapshot",
            )
        if new_parent_user_id is not None:
            parent = await self.db.get_delegated_admin_by_user_id(new_parent_user_id)
            if parent is None:
                raise ValueError("parent delegated admin was not found.")
            subtree = await self.db.get_delegated_admin_subtree_user_ids(manager_user_id=child_user_id, include_self=True)
            if new_parent_user_id in subtree:
                raise ValueError("delegated admin parent cycle is not allowed.")
        changed = await self.db.set_delegated_admin_parent(
            telegram_user_id=child_user_id,
            parent_user_id=new_parent_user_id,
            actor_user_id=actor_user_id,
        )
        if not changed:
            raise ValueError("delegated admin was not found.")
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action="change_delegated_admin_parent",
            target_type="delegated_admin",
            target_id=str(child_user_id),
            success=True,
            details=f"old_parent={old_parent_user_id or 0};new_parent={new_parent_user_id or 0}",
        )

    async def toggle_delegated_admin_primary_parent(
        self,
        *,
        actor_user_id: int,
        child_user_id: int,
    ) -> int | None:
        delegated = await self.db.get_delegated_admin_by_user_id(child_user_id)
        if delegated is None:
            raise ValueError("delegated admin was not found.")
        current_parent_user_id = int(delegated.get("parent_user_id") or 0) or None
        if current_parent_user_id is not None:
            await self.change_delegated_admin_parent(
                actor_user_id=actor_user_id,
                child_user_id=child_user_id,
                new_parent_user_id=None,
            )
            return None
        full_admins = [
            row
            for row in await self.db.list_full_delegated_admins()
            if int(row.get("telegram_user_id") or 0) != child_user_id
        ]
        if not full_admins:
            raise ValueError("full delegated admin was not found.")
        if len(full_admins) > 1:
            raise ValueError("more than one full delegated admin exists.")
        parent_user_id = int(full_admins[0]["telegram_user_id"])
        await self.change_delegated_admin_parent(
            actor_user_id=actor_user_id,
            child_user_id=child_user_id,
            new_parent_user_id=parent_user_id,
        )
        return parent_user_id

    async def revoke_delegated_admin_access(self, *, actor_user_id: int, access_id: int) -> bool:
        return await self.delegated_access.revoke_delegated_admin_access(
            actor_user_id=actor_user_id,
            access_id=access_id,
        )

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
        return await self.delegated_access.list_all_inbounds()

    async def list_grantable_inbounds_for_delegated_admin(self, telegram_user_id: int) -> list[InboundAccess]:
        return await self.delegated_access.list_grantable_inbounds_for_delegated_admin(telegram_user_id)

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

    async def list_accessible_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        return await self.delegated_access.list_accessible_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        )

    async def list_owned_client_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        return await self.delegated_access.list_owned_client_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        )

    async def list_visible_inbounds_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[InboundAccess]:
        return await self.delegated_access.list_visible_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        )

    async def list_delegated_admin_accesses(self, manager_user_id: int | None = None) -> list[dict[str, Any]]:
        return await self.delegated_access.list_delegated_admin_accesses(manager_user_id=manager_user_id)

    async def count_owned_clients_for_actor(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> int:
        return await self.delegated_access.count_owned_clients_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        )

    async def get_delegated_admin_overview(
        self,
        *,
        telegram_user_id: int,
        settings: Settings,
    ) -> dict[str, Any]:
        return await self.delegated_access.get_delegated_admin_overview(
            telegram_user_id=telegram_user_id,
            settings=settings,
        )

    async def financial_scope_user_ids(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> list[int]:
        return await self.financial_summary.financial_scope_user_ids(
            actor_user_id=actor_user_id,
            settings=settings,
        )

    async def get_admin_scope_financial_summary(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> dict[str, Any]:
        return await self.financial_summary.get_admin_scope_financial_summary(
            actor_user_id=actor_user_id,
            settings=settings,
        )

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
        group_name: str | None = None,
    ) -> dict[str, Any]:
        return await self.client_ops.create_client_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
            total_gb=total_gb,
            expiry_days=expiry_days,
            tg_id=tg_id,
            group_name=group_name,
        )

    async def _create_client_for_actor_impl(
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
        group_name: str | None = None,
    ) -> dict[str, Any]:
        async def _create() -> dict[str, Any]:
            resolved_inbound_ids: list[int] = []
            if group_name:
                resolved_inbound_ids = await self.client_group_service.resolve_group_inbound_ids(
                    panel_id=panel_id,
                    group_name=group_name,
                )
                if not resolved_inbound_ids:
                    raise ValueError("no inbound is assigned to the selected group.")
            target_inbound_ids = sorted({int(x) for x in (resolved_inbound_ids or [inbound_id]) if int(x) > 0})
            if not target_inbound_ids:
                raise ValueError("no inbound is available for client creation.")
            target_inbound_id = target_inbound_ids[0]
            normalized_email = await self._apply_delegated_username_prefix(
                actor_user_id=actor_user_id,
                settings=settings,
                client_email=client_email,
            )
            for candidate_inbound_id in target_inbound_ids:
                allowed = await self.access_service.can_access_inbound(
                    user_id=actor_user_id,
                    settings=settings,
                    panel_id=panel_id,
                    inbound_id=candidate_inbound_id,
                )
                if not allowed:
                    raise ValueError("you do not have access to one or more selected inbounds.")
            context = await self.access_service.get_admin_context(actor_user_id, settings)
            if not context.is_full_admin:
                profile = await self.db.get_delegated_admin_profile(actor_user_id)
                max_clients = int(profile.get("max_clients") or 0)
                if max_clients > 0:
                    current_count = await self.count_owned_clients_for_actor(actor_user_id=actor_user_id, settings=settings)
                    if current_count >= max_clients:
                        raise ValueError("delegated admin max clients reached.")

            charge_tx = None
            if self.financial_service is not None:
                try:
                    charge_tx = await self.financial_service.charge_operation(
                        actor_user_id=actor_user_id,
                        settings=settings,
                        operation="create_client",
                        panel_id=panel_id,
                        traffic_gb=total_gb,
                        expiry_days=expiry_days,
                        details=f"panel={panel_id};inbound={target_inbound_id};email={normalized_email}",
                    )
                except Exception as exc:
                    await self._log_delegated_create_failure(
                        actor_user_id=actor_user_id,
                        settings=settings,
                        panel_id=panel_id,
                        inbound_id=target_inbound_id,
                        client_email=normalized_email,
                        total_gb=total_gb,
                        expiry_days=expiry_days,
                        exc=exc,
                    )
                    raise
            try:
                # Determine comment: use parent ID if delegated admin, otherwise use actor ID
                delegated = await self.db.get_delegated_admin_by_user_id(actor_user_id)
                parent_user_id = int(delegated.get("parent_user_id") or 0) or None if delegated else None
                comment_owner_id = parent_user_id or actor_user_id

                created = await self.panel_service.create_client(
                    panel_id=panel_id,
                    inbound_id=target_inbound_id,
                    inbound_ids=target_inbound_ids,
                    client_email=normalized_email,
                    total_gb=total_gb,
                    expiry_days=expiry_days,
                    tg_id=tg_id,
                    comment=str(comment_owner_id),
                )
            except Exception:
                await self._refund_charge_bundle(
                    actor_user_id=actor_user_id,
                    charge_tx=charge_tx,
                    reason=f"refund:create_client_failed:{normalized_email}",
                )
                raise
            try:
                for candidate_inbound_id in target_inbound_ids:
                    await self.db.upsert_client_owner(
                        panel_id=panel_id,
                        inbound_id=candidate_inbound_id,
                        client_uuid=str(created["uuid"]),
                        owner_user_id=actor_user_id,
                        client_email=normalized_email,
                    )
            except Exception:
                logger.exception(
                    "failed to persist client owner mapping",
                    extra={"panel_id": panel_id, "inbound_id": inbound_id, "client_uuid": created.get("uuid")},
                )
            current_parent_user_id = await self._current_parent_user_id(actor_user_id)
            last_parent_user_id = await self._last_parent_user_id(actor_user_id)
            if last_parent_user_id is not None:
                created_uuid = str(created["uuid"])
                created_email = str(created.get("email") or normalized_email)
                total_bytes = gb_to_bytes(total_gb)
                if current_parent_user_id is not None:
                    for candidate_inbound_id in target_inbound_ids:
                        await self._write_hierarchy_segment(
                            panel_id=panel_id,
                            inbound_id=candidate_inbound_id,
                            client_uuid=created_uuid,
                            owner_user_id=current_parent_user_id,
                            actor_user_id=actor_user_id,
                            start_bytes=0,
                            end_bytes=total_bytes,
                            is_billable=True,
                            source="create_client",
                            client_email=created_email,
                        )
                if last_parent_user_id != current_parent_user_id:
                    for candidate_inbound_id in target_inbound_ids:
                        await self._write_hierarchy_segment(
                            panel_id=panel_id,
                            inbound_id=candidate_inbound_id,
                            client_uuid=created_uuid,
                            owner_user_id=last_parent_user_id,
                            actor_user_id=actor_user_id,
                            start_bytes=0,
                            end_bytes=total_bytes,
                            is_billable=False,
                            source="create_client_parent_change",
                            client_email=created_email,
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
                            for candidate_inbound_id in target_inbound_ids:
                                await self.panel_service.bind_service_to_user(
                                    panel_id=panel_id,
                                    telegram_user_id=resolved_user_id,
                                    client_email=normalized_email,
                                    service_name=None,
                                    inbound_id=candidate_inbound_id,
                                )
                    else:
                        user = await self.db.find_user_by_username(tg_id)
                        if user is not None:
                            resolved_user_id = int(user["telegram_user_id"])
                            resolved_username = str(user.get("username") or "").strip() or None
                            for candidate_inbound_id in target_inbound_ids:
                                await self.panel_service.bind_service_to_user(
                                    panel_id=panel_id,
                                    telegram_user_id=resolved_user_id,
                                    client_email=normalized_email,
                                    service_name=None,
                                    inbound_id=candidate_inbound_id,
                                )
                    if resolved_user_id is not None:
                        await self.panel_service.bind_services_for_telegram_identity(
                            telegram_user_id=resolved_user_id,
                            username=resolved_username,
                        )
                except Exception:
                    logger.exception(
                        "failed to bind created client to telegram identity",
                        extra={
                            "panel_id": panel_id,
                            "inbound_id": inbound_id,
                            "client_email": normalized_email,
                            "tg_id": tg_id,
                        },
                    )
            vless_uri = await self.panel_service.get_client_vless_uri_by_email(
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_email=normalized_email,
            )
            sub_url = await self.panel_service.get_client_subscription_url_by_email(
                panel_id=panel_id,
                inbound_id=inbound_id,
                client_email=normalized_email,
            )
            await self.db.add_audit_log(
                actor_user_id=actor_user_id,
                action="create_client",
                target_type="client",
                target_id=created["uuid"],
                success=True,
                details=f"panel={panel_id};inbound={inbound_id};email={normalized_email}",
            )
            lang = await self.db.get_user_language(actor_user_id)
            actor = await self._actor_display_name(actor_user_id)
            panel_name, inbound_name = await self._panel_inbound_names(panel_id=panel_id, inbound_id=inbound_id)
            activity_text = t(
                "admin_activity_notify_template",
                lang,
                actor=actor,
                action=t("admin_activity_action_create_client", lang),
                user=normalized_email,
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
                panel_id=panel_id,
                notification_kind="admin_activity_action_create_client",
            )
            return {
                **created,
                "vless_uri": vless_uri,
                "sub_url": sub_url,
                "wallet_charge_amount": int(charge_tx["amount"]) if charge_tx is not None else 0,
            }

        if self.operation_guard is None:
            return await _create()
        guard_keys = [
            f"inbound:{int(panel_id)}:{int(inbound_id)}:create_client",
            f"email:{int(panel_id)}:{int(inbound_id)}:{client_email.strip().lower()}",
        ]
        return await self.operation_guard.run_many(guard_keys, _create)

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

        if (await self.access_service.get_admin_context(actor_user_id, settings)).is_root_admin:
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
