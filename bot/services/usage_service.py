from __future__ import annotations

import logging
import time
from typing import List

from aiogram import Bot

from bot.db import Database
from bot.i18n import t
from bot.metrics import PANEL_COUNT, SYNC_RUNS, USER_SERVICE_COUNT, USER_STATUS_REQUESTS
from bot.notification_kinds import ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS
from bot.services.panel_service import PanelService
from bot.services.xui_client import XUIError
from bot.utils import format_bytes, format_gb, relative_remaining_time, status_emoji, to_local_date

logger = logging.getLogger(__name__)

# Outbound system notifications must go through this module (see scripts/audit_outbound_telegram.py).
# Handlers may still use message.answer for interactive UX; that is intentional and not part of prefs.


class UsageService:
    def __init__(
        self,
        db: Database,
        panel_service: PanelService,
        timezone: str,
        root_admin_ids: set[int] | None = None,
        depleted_delete_after_hours: int = 48,
    ) -> None:
        self.db = db
        self.panel_service = panel_service
        self.timezone = timezone
        self.root_admin_ids = set(root_admin_ids or set())
        self.depleted_delete_after_hours = depleted_delete_after_hours
        self.bot: Bot | None = None

    def attach_bot(self, bot: Bot | None) -> None:
        self.bot = bot

    async def is_bot_notification_enabled(self, chat_id: int, notification_kind: str | None) -> bool:
        if not notification_kind:
            return True
        disabled = await self.db.get_user_notification_disabled_kinds(chat_id)
        if notification_kind in disabled:
            return False
        if (
            notification_kind in ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS
            and chat_id not in self.root_admin_ids
        ):
            root_disabled = await self.db.get_root_default_enduser_service_alert_disabled_kinds()
            if notification_kind in root_disabled:
                return False
        return True

    async def _deliver_bot_notification(self, chat_id: int, text: str, *, notification_kind: str | None) -> str:
        if not await self.is_bot_notification_enabled(chat_id, notification_kind):
            return "skipped"
        if await self._send_chat_message(chat_id, text):
            return "sent"
        return "failed"

    @staticmethod
    def _remaining_bytes(total_bytes: int, used_bytes: int) -> int | None:
        if total_bytes <= 0:
            return None
        return max(total_bytes - used_bytes, 0)

    @staticmethod
    def _user_traffic_alert_state(*, total_bytes: int, used_bytes: int) -> str:
        remaining = UsageService._remaining_bytes(total_bytes, used_bytes)
        if remaining is None:
            return "normal"
        if remaining <= 0:
            return "depleted"
        if remaining <= 100 * 1024 * 1024:
            return "lt100"
        if remaining <= 200 * 1024 * 1024:
            return "lt200"
        return "normal"

    @staticmethod
    def _delegated_alert_state(*, total_bytes: int, used_bytes: int) -> str:
        if total_bytes <= 0:
            return "normal"
        remaining = max(total_bytes - used_bytes, 0)
        if remaining <= 0:
            return "depleted"
        if remaining <= 100 * 1024 * 1024:
            return "low"
        return "normal"

    @staticmethod
    def _delegated_expiry_alert_state(*, expire_at: int | None) -> str:
        if not expire_at:
            return "normal"
        remaining_seconds = int(expire_at) - int(time.time())
        if remaining_seconds <= 0:
            return "expired"
        if remaining_seconds <= 86400:
            return "low"
        return "normal"

    @staticmethod
    def _is_missing_client_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "inbound not found for email" in text or "client not found on this inbound" in text

    async def _send_chat_message(self, chat_id: int, text: str) -> bool:
        if self.bot is None:
            return False
        try:
            await self.bot.send_message(chat_id, text)
        except Exception:
            logger.exception("failed to send telegram message", extra={"chat_id": chat_id})
            return False
        return True

    async def _is_active_delegated_admin_user(self, user_id: int) -> bool:
        delegated = await self.db.get_delegated_admin_by_user_id(user_id)
        if delegated is None:
            return False
        profile = await self.db.get_delegated_admin_profile(user_id)
        if int(profile.get("is_active") or 0) != 1:
            return False
        expires_at = int(profile.get("expires_at") or 0)
        return not (expires_at > 0 and expires_at <= int(time.time()))

    async def is_active_delegated_admin_user(self, user_id: int) -> bool:
        return await self._is_active_delegated_admin_user(user_id)

    async def _active_delegated_admin_ids(self) -> list[int]:
        delegated_rows = await self.db.list_delegated_admin_access_rows(manager_user_id=None)
        delegated_ids = {
            int(row["telegram_user_id"])
            for row in delegated_rows
            if int(row.get("telegram_user_id") or 0) > 0
        }
        result: list[int] = []
        for delegated_user_id in sorted(delegated_ids):
            if await self._is_active_delegated_admin_user(delegated_user_id):
                result.append(delegated_user_id)
        return result

    async def _queue_admin_notification(
        self,
        *,
        actor_user_id: int | None,
        chat_id: int,
        text: str,
        last_error: str,
        notification_kind: str | None,
    ) -> int:
        return await self.db.enqueue_admin_activity_notification(
            actor_user_id=actor_user_id,
            chat_id=chat_id,
            text=text,
            next_attempt_at=int(time.time()) + 30,
            last_error=last_error,
            notification_kind=notification_kind,
        )

    async def _delegated_admin_can_receive_panel_activity(self, user_id: int, panel_id: int) -> bool:
        panel = await self.db.get_panel(panel_id)
        if panel is None:
            return False
        if int(panel.get("is_default") or 0) == 1:
            return True
        if int(panel.get("created_by") or 0) == user_id:
            return True
        return await self.db.has_admin_access_to_panel(telegram_user_id=user_id, panel_id=panel_id)

    async def _delegated_admin_can_receive_inbound_activity(
        self,
        user_id: int,
        panel_id: int | None,
        inbound_id: int | None,
    ) -> bool:
        if panel_id is None or panel_id <= 0:
            return False
        if not await self._is_active_delegated_admin_user(user_id):
            return False
        if inbound_id is None or inbound_id <= 0:
            return await self._delegated_admin_can_receive_panel_activity(user_id, panel_id)
        delegated = await self.db.get_delegated_admin_by_user_id(user_id)
        if delegated is None:
            return False
        scope = str(delegated.get("admin_scope") or "limited").strip().lower()
        if scope == "full":
            panel = await self.db.get_panel(panel_id)
            if panel is not None and (
                int(panel.get("is_default") or 0) == 1 or int(panel.get("created_by") or 0) == user_id
            ):
                return True
        return await self.db.has_admin_access_to_inbound(
            telegram_user_id=user_id,
            panel_id=panel_id,
            inbound_id=inbound_id,
        )

    async def _admin_activity_recipient_ids(self, actor_user_id: int, panel_id: int | None = None) -> list[int]:
        recipients = set(self.root_admin_ids)
        if not await self._is_active_delegated_admin_user(actor_user_id):
            return sorted(recipients)
        delegated = await self.db.get_delegated_admin_by_user_id(actor_user_id)
        if delegated is None:
            return sorted(recipients)
        parent_user_id = int(delegated.get("parent_user_id") or 0)
        seen_parents: set[int] = set()
        while parent_user_id > 0 and parent_user_id not in seen_parents:
            seen_parents.add(parent_user_id)
            if await self._is_active_delegated_admin_user(parent_user_id):
                recipients.add(parent_user_id)
            parent_row = await self.db.get_delegated_admin_by_user_id(parent_user_id)
            if parent_row is None:
                break
            parent_user_id = int(parent_row.get("parent_user_id") or 0)
        return sorted(recipients)

    async def _audit_admin_activity_delivery(
        self,
        *,
        actor_user_id: int | None,
        recipient_user_id: int,
        action: str,
        success: bool,
        details: str,
    ) -> None:
        if actor_user_id is None:
            return
        await self.db.add_audit_log(
            actor_user_id=actor_user_id,
            action=action,
            target_type="admin",
            target_id=str(recipient_user_id),
            success=success,
            details=details,
        )

    async def notify_admin_activity(
        self,
        *,
        actor_user_id: int,
        text: str,
        panel_id: int | None = None,
        notification_kind: str | None = None,
    ) -> None:
        for admin_id in await self._admin_activity_recipient_ids(actor_user_id, panel_id):
            outcome = await self._deliver_bot_notification(admin_id, text, notification_kind=notification_kind)
            if outcome == "skipped":
                continue
            if outcome == "sent":
                await self._audit_admin_activity_delivery(
                    actor_user_id=actor_user_id,
                    recipient_user_id=admin_id,
                    action="admin_activity_notification_sent",
                    success=True,
                    details="delivery=immediate",
                )
                continue
            notification_id = await self._queue_admin_notification(
                actor_user_id=actor_user_id,
                chat_id=admin_id,
                text=text,
                last_error="immediate_send_failed",
                notification_kind=notification_kind,
            )
            await self._audit_admin_activity_delivery(
                actor_user_id=actor_user_id,
                recipient_user_id=admin_id,
                action="admin_activity_notification_queued",
                success=False,
                details=f"delivery=immediate_failed;notification_id={notification_id}",
            )

    async def notify_root_admin_activity(
        self,
        *,
        actor_user_id: int,
        text: str,
        notification_kind: str | None = None,
    ) -> None:
        for admin_id in sorted(self.root_admin_ids):
            outcome = await self._deliver_bot_notification(admin_id, text, notification_kind=notification_kind)
            if outcome == "skipped":
                continue
            if outcome == "sent":
                await self._audit_admin_activity_delivery(
                    actor_user_id=actor_user_id,
                    recipient_user_id=admin_id,
                    action="root_admin_activity_notification_sent",
                    success=True,
                    details="delivery=immediate",
                )
                continue
            notification_id = await self._queue_admin_notification(
                actor_user_id=actor_user_id,
                chat_id=admin_id,
                text=text,
                last_error="immediate_send_failed",
                notification_kind=notification_kind,
            )
            await self._audit_admin_activity_delivery(
                actor_user_id=actor_user_id,
                recipient_user_id=admin_id,
                action="root_admin_activity_notification_queued",
                success=False,
                details=f"delivery=immediate_failed;notification_id={notification_id}",
            )

    async def _auto_cleanup_recipient_ids(self) -> list[int]:
        recipients = set(self.root_admin_ids)
        recipients.update(await self._active_delegated_admin_ids())
        return sorted(recipients)

    async def _notify_auto_cleanup_deleted_clients(self, *, deleted_clients: list[dict], hours: int) -> None:
        if not deleted_clients:
            return
        recipient_ids = await self._auto_cleanup_recipient_ids()
        if not recipient_ids:
            return
        for deleted_client in deleted_clients:
            panel_id_raw = deleted_client.get("panel_id")
            inbound_id_raw = deleted_client.get("inbound_id")
            panel_id = int(panel_id_raw) if panel_id_raw is not None else None
            inbound_id = int(inbound_id_raw) if inbound_id_raw is not None else None
            text = t(
                "admin_auto_cleanup_deleted_notification",
                "fa",
                email=str(deleted_client.get("email") or "-"),
                hours=hours,
                panel=str(deleted_client.get("panel_name") or deleted_client.get("panel_id") or "-"),
                inbound=str(deleted_client.get("inbound_name") or deleted_client.get("inbound_id") or "-"),
            )
            for admin_id in recipient_ids:
                if admin_id not in self.root_admin_ids:
                    if not await self._delegated_admin_can_receive_inbound_activity(
                        admin_id,
                        panel_id=panel_id,
                        inbound_id=inbound_id,
                    ):
                        continue
                outcome = await self._deliver_bot_notification(
                    admin_id, text, notification_kind="bot_notify_auto_cleanup_deleted"
                )
                if outcome in {"sent", "skipped"}:
                    continue
                await self._queue_admin_notification(
                    actor_user_id=None,
                    chat_id=admin_id,
                    text=text,
                    last_error="auto_cleanup_notification_send_failed",
                    notification_kind="bot_notify_auto_cleanup_deleted",
                )

    async def flush_pending_admin_activity_notifications(self, *, limit: int = 100) -> None:
        rows = await self.db.list_due_admin_activity_notifications(now_ts=int(time.time()), limit=limit)
        for row in rows:
            notification_id = int(row["id"])
            actor_user_id_raw = row.get("actor_user_id")
            actor_user_id = int(actor_user_id_raw) if actor_user_id_raw is not None else None
            chat_id = int(row["chat_id"])
            text = str(row.get("text") or "")
            attempts = int(row.get("attempts") or 0)
            kind_raw = row.get("notification_kind")
            kind = str(kind_raw).strip() if kind_raw is not None else ""
            if kind and not await self.is_bot_notification_enabled(chat_id, kind):
                await self.db.mark_admin_activity_notification_sent(
                    notification_id=notification_id,
                    sent_at=int(time.time()),
                )
                await self._audit_admin_activity_delivery(
                    actor_user_id=actor_user_id,
                    recipient_user_id=chat_id,
                    action="admin_activity_notification_skipped",
                    success=True,
                    details=f"delivery=disabled;notification_id={notification_id};kind={kind}",
                )
                continue
            if await self._send_chat_message(chat_id, text):
                await self.db.mark_admin_activity_notification_sent(
                    notification_id=notification_id,
                    sent_at=int(time.time()),
                )
                await self._audit_admin_activity_delivery(
                    actor_user_id=actor_user_id,
                    recipient_user_id=chat_id,
                    action="admin_activity_notification_sent",
                    success=True,
                    details=f"delivery=retry;notification_id={notification_id}",
                )
                continue
            backoff_seconds = min(1800, 30 * (2 ** min(attempts, 5)))
            await self.db.mark_admin_activity_notification_failed(
                notification_id=notification_id,
                last_error="retry_send_failed",
                next_attempt_at=int(time.time()) + backoff_seconds,
            )
            await self._audit_admin_activity_delivery(
                actor_user_id=actor_user_id,
                recipient_user_id=chat_id,
                action="admin_activity_notification_retry_failed",
                success=False,
                details=f"delivery=retry_failed;notification_id={notification_id};attempt={attempts + 1}",
            )

    async def _manager_chat_ids_for_service(
        self,
        *,
        panel_id: int,
        inbound_id: int | None,
        client_uuid: str | None,
    ) -> list[int]:
        if inbound_id and client_uuid:
            try:
                detail = await self.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
            except Exception:
                logger.exception(
                    "failed to resolve service owner for admin notification",
                    extra={"panel_id": panel_id, "inbound_id": inbound_id, "client_uuid": client_uuid},
                )
            else:
                comment = str(detail.get("comment") or "").strip()
                owner_raw = comment.split(":", 1)[0].strip()
                if owner_raw.isdigit():
                    delegated_id = int(owner_raw)
                    if await self._is_active_delegated_admin_user(delegated_id):
                        return [delegated_id]
        return sorted(self.root_admin_ids)

    async def _direct_owner_chat_ids_for_service(
        self,
        *,
        panel_id: int,
        inbound_id: int | None,
        client_uuid: str | None,
    ) -> list[int]:
        if not inbound_id or not client_uuid:
            return []
        owner_id = await self.db.get_client_owner(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        if owner_id is not None:
            if owner_id in self.root_admin_ids:
                return [owner_id]
            if await self._is_active_delegated_admin_user(owner_id):
                return [owner_id]
            return []
        try:
            detail = await self.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
        except Exception:
            logger.exception(
                "failed to resolve direct service owner for threshold notification",
                extra={"panel_id": panel_id, "inbound_id": inbound_id, "client_uuid": client_uuid},
            )
            return []
        comment = str(detail.get("comment") or "").strip()
        if not comment and len(self.root_admin_ids) == 1:
            return sorted(self.root_admin_ids)
        owner_raw = comment.split(":", 1)[0].strip()
        if not owner_raw.isdigit():
            return []
        owner_id = int(owner_raw)
        if owner_id in self.root_admin_ids:
            return [owner_id]
        if not await self._is_active_delegated_admin_user(owner_id):
            return []
        return [owner_id]

    async def _service_location_labels(self, panel_id: int, inbound_id: int | None) -> tuple[str, str]:
        try:
            return await self.panel_service.panel_inbound_names(panel_id, inbound_id)
        except Exception:
            return str(panel_id), "-" if inbound_id is None else f"inbound-{inbound_id}"

    async def _notify_user_about_threshold(
        self,
        *,
        service_row: dict,
        telegram_user_id: int,
        service_name: str,
        remaining_bytes: int,
        threshold_mb: int,
    ) -> None:
        lang = await self.db.get_user_language(telegram_user_id)
        text = t(
            "service_threshold_warning",
            lang,
            service_name=service_name,
            threshold_mb=threshold_mb,
            remaining=format_bytes(remaining_bytes, lang),
        )
        await self._deliver_bot_notification(telegram_user_id, text, notification_kind="bot_notify_user_service_threshold")
        await self._notify_direct_owner_about_threshold(
            service_row=service_row,
            service_name=service_name,
            remaining_bytes=remaining_bytes,
            threshold_mb=threshold_mb,
        )

    async def _notify_direct_owner_about_threshold(
        self,
        *,
        service_row: dict,
        service_name: str,
        remaining_bytes: int,
        threshold_mb: int,
    ) -> None:
        if threshold_mb != 100:
            return
        panel_id_raw = service_row.get("panel_id")
        if panel_id_raw is None:
            return
        panel_id = int(panel_id_raw)
        inbound_id = int(service_row["inbound_id"]) if service_row.get("inbound_id") else None
        client_uuid = str(service_row.get("client_id") or "").strip() or None
        manager_chat_ids = await self._direct_owner_chat_ids_for_service(
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        if not manager_chat_ids:
            return
        panel_label, inbound_label = await self._service_location_labels(panel_id, inbound_id)
        manager_text = t(
            "admin_service_threshold_warning",
            "fa",
            client_email=str(service_row.get("client_email") or "-"),
            threshold_mb=threshold_mb,
            service_name=service_name,
            panel=panel_label,
            inbound=inbound_label,
            remaining=format_bytes(remaining_bytes, "fa"),
        )
        for chat_id in manager_chat_ids:
            sent = await self._deliver_bot_notification(
                chat_id, manager_text, notification_kind="bot_notify_manager_service_threshold"
            ) == "sent"
            if sent and inbound_id is not None and client_uuid is not None:
                _, expiry_state = await self.db.get_delegated_admin_client_alert_states(
                    delegated_admin_user_id=chat_id,
                    panel_id=panel_id,
                    inbound_id=inbound_id,
                    client_uuid=client_uuid,
                )
                await self.db.upsert_delegated_admin_client_alert_states(
                    delegated_admin_user_id=chat_id,
                    panel_id=panel_id,
                    inbound_id=inbound_id,
                    client_uuid=client_uuid,
                    traffic_alert_state="low",
                    expiry_alert_state=expiry_state or "normal",
                    mark_notified=True,
                )

    async def _notify_service_depleted(
        self,
        *,
        service_row: dict,
        service_name: str,
    ) -> None:
        user_id = int(service_row["telegram_user_id"])
        lang = await self.db.get_user_language(user_id)
        if lang == "en":
            user_text = (
                "Service warning:\n"
                f"Your service {service_name} has run out of traffic."
            )
        else:
            user_text = (
                "هشدار سرویس:\n"
                f"سرویس {service_name} به پایان رسیده و حجم آن تمام شده است."
            )
        await self._deliver_bot_notification(user_id, user_text, notification_kind="bot_notify_user_service_depleted")

        panel_label, inbound_label = await self._service_location_labels(
            int(service_row["panel_id"]),
            int(service_row["inbound_id"]) if service_row.get("inbound_id") else None,
        )
        manager_text = (
            "هشدار اتمام سرویس:\n"
            f"کاربر: {service_row.get('client_email')}\n"
            f"سرویس: {service_name}\n"
            f"پنل: {panel_label}\n"
            f"اینباند: {inbound_label}\n"
            "وضعیت: حجم سرویس تمام شده است."
        )
        manager_chat_ids = await self._manager_chat_ids_for_service(
            panel_id=int(service_row["panel_id"]),
            inbound_id=int(service_row["inbound_id"]) if service_row.get("inbound_id") else None,
            client_uuid=str(service_row.get("client_id") or "").strip() or None,
        )
        for chat_id in manager_chat_ids:
            await self._deliver_bot_notification(
                chat_id, manager_text, notification_kind="bot_notify_manager_service_depleted"
            )

    async def _notify_service_expired(
        self,
        *,
        service_row: dict,
        service_name: str,
    ) -> None:
        user_id = int(service_row["telegram_user_id"])
        lang = await self.db.get_user_language(user_id)
        if lang == "en":
            user_text = (
                "Service warning:\n"
                f"Your service {service_name} has expired."
            )
        else:
            user_text = (
                "هشدار سرویس:\n"
                f"زمان سرویس {service_name} به پایان رسیده است."
            )
        await self._deliver_bot_notification(user_id, user_text, notification_kind="bot_notify_user_service_expired")

        panel_label, inbound_label = await self._service_location_labels(
            int(service_row["panel_id"]),
            int(service_row["inbound_id"]) if service_row.get("inbound_id") else None,
        )
        manager_text = (
            "هشدار اتمام سرویس:\n"
            f"کاربر: {service_row.get('client_email')}\n"
            f"سرویس: {service_name}\n"
            f"پنل: {panel_label}\n"
            f"اینباند: {inbound_label}\n"
            "وضعیت: تاریخ انقضای سرویس تمام شده است."
        )
        manager_chat_ids = await self._manager_chat_ids_for_service(
            panel_id=int(service_row["panel_id"]),
            inbound_id=int(service_row["inbound_id"]) if service_row.get("inbound_id") else None,
            client_uuid=str(service_row.get("client_id") or "").strip() or None,
        )
        for chat_id in manager_chat_ids:
            await self._deliver_bot_notification(
                chat_id, manager_text, notification_kind="bot_notify_manager_service_expired"
            )

    async def _notify_service_state_changes(self, previous: dict, current: dict) -> None:
        service_name = str(current.get("service_name") or previous.get("service_name") or previous.get("client_email") or "service")
        previous_total = int(previous.get("total_bytes") or 0)
        previous_used = int(previous.get("used_bytes") or 0)
        current_total = int(current.get("total_bytes") or 0)
        current_used = int(current.get("used_bytes") or 0)
        previous_remaining = self._remaining_bytes(previous_total, previous_used)
        current_remaining = self._remaining_bytes(current_total, current_used)
        previous_state = self._user_traffic_alert_state(total_bytes=previous_total, used_bytes=previous_used)
        current_state = self._user_traffic_alert_state(total_bytes=current_total, used_bytes=current_used)
        previous_status = str(previous.get("status") or "")
        current_status = str(current.get("status") or "")

        if current_status == "expired":
            if previous_status != "expired":
                await self._notify_service_expired(service_row=current, service_name=service_name)
            return

        if current_state == "depleted" or current_status == "depleted":
            if previous_state != "depleted" and previous_status != "depleted":
                await self._notify_service_depleted(service_row=current, service_name=service_name)
            return

        if previous_remaining is None or current_remaining is None:
            return

        if previous_remaining > 200 * 1024 * 1024 and current_remaining <= 200 * 1024 * 1024:
            await self._notify_user_about_threshold(
                service_row=current,
                telegram_user_id=int(current["telegram_user_id"]),
                service_name=service_name,
                remaining_bytes=current_remaining,
                threshold_mb=200,
            )
        if previous_remaining > 100 * 1024 * 1024 and current_remaining <= 100 * 1024 * 1024:
            await self._notify_user_about_threshold(
                service_row=current,
                telegram_user_id=int(current["telegram_user_id"]),
                service_name=service_name,
                remaining_bytes=current_remaining,
                threshold_mb=100,
            )

    async def _sync_service_row(self, service_row: dict) -> None:
        try:
            usage = await self.panel_service.fetch_client_usage(service_row["panel_id"], service_row["client_email"])
        except XUIError as exc:
            if self._is_missing_client_error(exc):
                await self.db.mark_user_service_deleted(
                    service_id=int(service_row["id"]),
                    status="deleted",
                    last_synced_at=int(time.time()),
                )
                await self.db.add_audit_log(
                    actor_user_id=None,
                    action="auto_mark_missing_service_deleted",
                    target_type="user_service",
                    target_id=str(service_row["id"]),
                    success=True,
                    details=(
                        f"panel={service_row['panel_id']};email={service_row['client_email']};"
                        f"client_id={service_row.get('client_id')};reason={exc}"
                    ),
                )
                logger.warning(
                    "marked missing service as deleted",
                    extra={
                        "service_id": service_row["id"],
                        "panel_id": service_row["panel_id"],
                        "client_email": service_row["client_email"],
                    },
                )
                return
            raise
        await self.db.update_user_service_stats(
            service_id=service_row["id"],
            total_bytes=usage["total_bytes"],
            used_bytes=usage["used_bytes"],
            expire_at=usage["expire_at"],
            status=usage["status"],
            service_name=service_row.get("service_name") or usage["service_name"],
            client_id=usage.get("client_id"),
            inbound_id=usage.get("inbound_id"),
            last_synced_at=usage["synced_at"],
        )
        await self.db.add_usage_snapshot(
            user_service_id=service_row["id"],
            used_bytes=usage["used_bytes"],
            total_bytes=usage["total_bytes"],
            remaining_bytes=usage["remaining_bytes"],
            status=usage["status"],
            synced_at=usage["synced_at"],
        )
        current_row = {
            **service_row,
            "service_name": service_row.get("service_name") or usage["service_name"],
            "client_id": usage.get("client_id"),
            "inbound_id": usage.get("inbound_id"),
            "total_bytes": usage["total_bytes"],
            "used_bytes": usage["used_bytes"],
            "expire_at": usage["expire_at"],
            "status": usage["status"],
            "last_synced_at": usage["synced_at"],
        }
        await self._notify_service_state_changes(service_row, current_row)

    async def notify_user_traffic_increased(
        self,
        *,
        panel_id: int,
        client_email: str,
        added_bytes: int,
        new_total_bytes: int,
    ) -> None:
        if added_bytes <= 0:
            return
        rows = await self.db.get_user_services_by_panel_email(panel_id, client_email)
        notified_user_ids: set[int] = set()
        for row in rows:
            user_id = int(row["telegram_user_id"])
            if user_id in notified_user_ids:
                continue
            notified_user_ids.add(user_id)
            lang = await self.db.get_user_language(user_id)
            service_name = str(row.get("service_name") or row.get("client_email") or client_email)
            if lang == "en":
                text = (
                    "Service update:\n"
                    f"{format_bytes(added_bytes, lang)} has been added to your service {service_name} by the admin.\n"
                    f"New total traffic: {format_gb(new_total_bytes, lang)}"
                )
            else:
                text = (
                    "اطلاع سرویس:\n"
                    f"{format_bytes(added_bytes, lang)} توسط ادمین به سرویس {service_name} اضافه شد.\n"
                    f"حجم جدید سرویس: {format_gb(new_total_bytes, lang)}"
                )
            await self._deliver_bot_notification(user_id, text, notification_kind="bot_notify_user_traffic_increased")

    async def notify_user_expiry_extended(
        self,
        *,
        panel_id: int,
        client_email: str,
        added_days: int,
        new_expiry: int | None,
    ) -> None:
        if added_days <= 0:
            return
        rows = await self.db.get_user_services_by_panel_email(panel_id, client_email)
        notified_user_ids: set[int] = set()
        for row in rows:
            user_id = int(row["telegram_user_id"])
            if user_id in notified_user_ids:
                continue
            notified_user_ids.add(user_id)
            lang = await self.db.get_user_language(user_id)
            service_name = str(row.get("service_name") or row.get("client_email") or client_email)
            if lang == "en":
                text = (
                    "Service update:\n"
                    f"{added_days} day(s) has been added to your service {service_name} by the admin.\n"
                    f"New expiry date: {to_local_date(new_expiry, self.timezone, lang)}"
                )
            else:
                text = (
                    "اطلاع سرویس:\n"
                    f"{added_days} روز توسط ادمین به سرویس {service_name} اضافه شد.\n"
                    f"تاریخ جدید انقضا: {to_local_date(new_expiry, self.timezone, lang)}"
                )
            await self._deliver_bot_notification(user_id, text, notification_kind="bot_notify_user_expiry_extended")

    async def _scan_delegated_admin_alerts(self) -> None:
        if self.bot is None:
            return
        access_rows = await self.db.list_delegated_admin_access_rows()
        if not access_rows:
            return
        inbound_names_cache: dict[tuple[int, int], str] = {}
        panel_names_cache: dict[int, str] = {}

        for access in access_rows:
            admin_user_id = int(access["telegram_user_id"])
            panel_id = int(access["panel_id"])
            inbound_id = int(access["inbound_id"])
            panel_name = str(access.get("panel_name") or panel_id)
            panel_names_cache[panel_id] = panel_name
            try:
                clients = await self.panel_service.list_inbound_clients(
                    panel_id,
                    inbound_id,
                    owner_admin_user_id=admin_user_id,
                )
            except Exception:
                logger.exception(
                    "failed to list delegated admin inbound clients",
                    extra={"telegram_user_id": admin_user_id, "panel_id": panel_id, "inbound_id": inbound_id},
                )
                continue

            if (panel_id, inbound_id) not in inbound_names_cache:
                try:
                    inbounds = await self.panel_service.list_inbounds(panel_id)
                    target = next((row for row in inbounds if int(row.get("id") or 0) == inbound_id), None)
                    inbound_names_cache[(panel_id, inbound_id)] = str(target.get("remark") or f"inbound-{inbound_id}") if target else f"inbound-{inbound_id}"
                except Exception:
                    inbound_names_cache[(panel_id, inbound_id)] = f"inbound-{inbound_id}"
            inbound_name = inbound_names_cache[(panel_id, inbound_id)]

            for client in clients:
                client_uuid = str(client.get("uuid") or "").strip()
                if not client_uuid:
                    continue
                try:
                    detail = await self.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
                except Exception:
                    logger.exception(
                        "failed to fetch delegated client detail",
                        extra={"telegram_user_id": admin_user_id, "panel_id": panel_id, "inbound_id": inbound_id, "client_uuid": client_uuid},
                    )
                    continue
                total_bytes = int(detail.get("total") or 0)
                used_bytes = int(detail.get("used") or 0)
                traffic_state = self._delegated_alert_state(total_bytes=total_bytes, used_bytes=used_bytes)
                expiry_state = self._delegated_expiry_alert_state(expire_at=detail.get("expiry"))
                old_traffic_state, old_expiry_state = await self.db.get_delegated_admin_client_alert_states(
                    delegated_admin_user_id=admin_user_id,
                    panel_id=panel_id,
                    inbound_id=inbound_id,
                    client_uuid=client_uuid,
                )
                should_notify_traffic = traffic_state in {"low", "depleted"} and traffic_state != old_traffic_state
                should_notify_expiry = expiry_state in {"low", "expired"} and expiry_state != old_expiry_state
                notified = False

                if should_notify_traffic:
                    remaining = max(total_bytes - used_bytes, 0)
                    if traffic_state == "depleted":
                        text = (
                            "هشدار سرویس:\n"
                            f"حجم کاربر {detail.get('email')} به پایان رسیده است.\n"
                            f"پنل: {panel_name}\n"
                            f"اینباند: {inbound_name}\n"
                            "حجم باقی‌مانده: 0"
                        )
                    else:
                        text = (
                            "هشدار سرویس:\n"
                            f"کاربر {detail.get('email')} کمتر از 100 مگابایت حجم دارد.\n"
                            f"پنل: {panel_name}\n"
                            f"اینباند: {inbound_name}\n"
                            f"حجم باقی‌مانده: {format_gb(remaining, 'fa')}"
                        )
                    traffic_kind = (
                        "bot_notify_delegated_panel_traffic_depleted"
                        if traffic_state == "depleted"
                        else "bot_notify_delegated_panel_traffic_low"
                    )
                    outcome = await self._deliver_bot_notification(admin_user_id, text, notification_kind=traffic_kind)
                    if outcome in {"sent", "skipped"}:
                        notified = True

                if should_notify_expiry:
                    if expiry_state == "expired":
                        text = (
                            "هشدار انقضا:\n"
                            f"زمان کاربر {detail.get('email')} به پایان رسیده است.\n"
                            f"پنل: {panel_name}\n"
                            f"اینباند: {inbound_name}\n"
                            f"تاریخ پایان: {to_local_date(detail.get('expiry'), self.timezone, 'fa')}"
                        )
                    else:
                        text = (
                            "هشدار انقضا:\n"
                            f"کمتر از 1 روز تا پایان کاربر {detail.get('email')} باقی مانده است.\n"
                            f"پنل: {panel_name}\n"
                            f"اینباند: {inbound_name}\n"
                            f"تاریخ پایان: {to_local_date(detail.get('expiry'), self.timezone, 'fa')}\n"
                            f"زمان باقی‌مانده: {relative_remaining_time(detail.get('expiry'), self.timezone, 'fa')}"
                        )
                    expiry_kind = (
                        "bot_notify_delegated_panel_expiry_expired"
                        if expiry_state == "expired"
                        else "bot_notify_delegated_panel_expiry_low"
                    )
                    outcome = await self._deliver_bot_notification(admin_user_id, text, notification_kind=expiry_kind)
                    if outcome in {"sent", "skipped"}:
                        notified = True

                await self.db.upsert_delegated_admin_client_alert_states(
                    delegated_admin_user_id=admin_user_id,
                    panel_id=panel_id,
                    inbound_id=inbound_id,
                    client_uuid=client_uuid,
                    traffic_alert_state=traffic_state,
                    expiry_alert_state=expiry_state,
                    mark_notified=notified,
                )

    async def refresh_user_services(self, telegram_user_id: int) -> None:
        services = await self.db.get_user_services(telegram_user_id)
        had_error = False
        for row in services:
            try:
                await self._sync_service_row(row)
            except Exception:
                had_error = True
                logger.exception("failed to sync service", extra={"service_id": row.get("id")})
        SYNC_RUNS.labels(result="error" if had_error else "ok").inc()

    async def refresh_all_services(self) -> None:
        services = await self.db.get_all_user_services()
        had_error = False
        for row in services:
            try:
                await self._sync_service_row(row)
            except Exception:
                had_error = True
                logger.exception("failed to sync service", extra={"service_id": row.get("id")})
        try:
            await self._scan_delegated_admin_alerts()
        except Exception:
            had_error = True
            logger.exception("failed to scan delegated admin alerts")
        try:
            await self.cleanup_depleted_clients()
        except Exception:
            had_error = True
            logger.exception("failed to cleanup depleted clients")
        try:
            await self.flush_pending_admin_activity_notifications()
        except Exception:
            had_error = True
            logger.exception("failed to flush admin activity notifications")
        SYNC_RUNS.labels(result="error" if had_error else "ok").inc()
        await self.refresh_cardinality_metrics()

    async def cleanup_depleted_clients(self) -> None:
        raw_hours = await self.db.get_app_setting(
            "depleted_client_delete_after_hours",
            str(self.depleted_delete_after_hours),
        )
        try:
            hours = int(raw_hours or self.depleted_delete_after_hours)
            if hours <= 0:
                raise ValueError
        except ValueError:
            hours = self.depleted_delete_after_hours
        result = await self.panel_service.cleanup_depleted_clients(hours)
        await self._notify_auto_cleanup_deleted_clients(
            deleted_clients=list(result.get("deleted_clients") or []),
            hours=hours,
        )
        logger.info("depleted client cleanup finished", extra={"hours": hours, **result})

    async def refresh_cardinality_metrics(self) -> None:
        PANEL_COUNT.set(await self.db.count_panels())
        USER_SERVICE_COUNT.set(await self.db.count_user_services())

    def _format_status_card(self, service: dict, lang: str) -> str:
        status_text = status_emoji(service.get("status", "unknown"), lang)
        name = service.get("service_name") or service.get("client_email")
        total = int(service.get("total_bytes", -1))
        used = int(service.get("used_bytes", 0))
        expire_at = service.get("expire_at")

        if total < 0:
            traffic_text = t("us_unlimited", lang)
            used_text = format_gb(used, lang)
            remain_text = t("us_unlimited", lang)
            percent_text = "-"
        else:
            remain = max(total - used, 0)
            percent = (remain / total * 100) if total > 0 else 0
            traffic_text = format_gb(total, lang)
            used_text = format_gb(used, lang)
            remain_text = format_gb(remain, lang)
            percent_text = f"{percent:.2f}%"

        return (
            f"{t('us_service_status', lang)}: {status_text}\n"
            f"{t('us_service_name', lang)}: {name}\n\n"
            f"{t('us_traffic', lang)}: {traffic_text}\n"
            f"{t('us_used', lang)}: {used_text}\n"
            f"{t('us_remaining', lang)}: {remain_text} ({percent_text})\n\n"
            f"{t('us_expiry_date', lang)}: {to_local_date(expire_at, self.timezone, lang)} "
            f"({relative_remaining_time(expire_at, self.timezone, lang)})"
        )

    async def get_user_status_messages(self, telegram_user_id: int, force_refresh: bool = False) -> List[str]:
        if force_refresh:
            await self.refresh_user_services(telegram_user_id)
        lang = await self.db.get_user_language(telegram_user_id)
        services = await self.db.get_user_services(telegram_user_id)
        USER_STATUS_REQUESTS.labels(result="empty" if not services else "ok").inc()
        return [self._format_status_card(service, lang) for service in services]
