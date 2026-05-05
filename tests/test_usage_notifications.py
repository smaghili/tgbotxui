from __future__ import annotations

import pytest

from bot.services.usage_service import UsageService


class DummyBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.fail_chat_ids: set[int] = set()

    async def send_message(self, chat_id: int, text: str) -> None:
        if chat_id in self.fail_chat_ids:
            raise RuntimeError(f"failed:{chat_id}")
        self.messages.append((chat_id, text))


class FakeDB:
    def __init__(self) -> None:
        self.lang_by_user: dict[int, str] = {}
        self.bound_rows: list[dict] = []
        self.panels: dict[int, dict] = {}
        self.panel_access: set[tuple[int, int]] = set()
        self.delegated_admins: dict[int, dict] = {}
        self.client_owners: dict[tuple[int, int, str], int] = {}
        self.client_alert_states: dict[tuple[int, int, int, str], tuple[str | None, str | None]] = {}
        self.audit_logs: list[dict] = []
        self.pending_notifications: list[dict] = []
        self.next_notification_id = 1

    async def get_user_language(self, telegram_user_id: int) -> str:
        return self.lang_by_user.get(telegram_user_id, "fa")

    async def get_delegated_admin_by_user_id(self, telegram_user_id: int) -> dict | None:
        return self.delegated_admins.get(telegram_user_id)

    async def get_delegated_admin_profile(self, telegram_user_id: int) -> dict:
        return {"is_active": 1, "expires_at": 0}

    async def get_panel(self, panel_id: int) -> dict | None:
        return self.panels.get(panel_id)

    async def has_admin_access_to_panel(self, *, telegram_user_id: int, panel_id: int) -> bool:
        return (telegram_user_id, panel_id) in self.panel_access

    async def get_client_owner(self, *, panel_id: int, inbound_id: int, client_uuid: str) -> int | None:
        return self.client_owners.get((panel_id, inbound_id, client_uuid))

    async def get_delegated_admin_client_alert_states(
        self,
        *,
        delegated_admin_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
    ) -> tuple[str | None, str | None]:
        return self.client_alert_states.get((delegated_admin_user_id, panel_id, inbound_id, client_uuid), (None, None))

    async def upsert_delegated_admin_client_alert_states(
        self,
        *,
        delegated_admin_user_id: int,
        panel_id: int,
        inbound_id: int,
        client_uuid: str,
        traffic_alert_state: str,
        expiry_alert_state: str,
        mark_notified: bool,
    ) -> None:
        self.client_alert_states[(delegated_admin_user_id, panel_id, inbound_id, client_uuid)] = (
            traffic_alert_state,
            expiry_alert_state,
        )

    async def get_user_services_by_panel_email(self, panel_id: int, client_email: str) -> list[dict]:
        return [
            row
            for row in self.bound_rows
            if int(row["panel_id"]) == panel_id and str(row["client_email"]).lower() == client_email.lower()
        ]

    async def get_user_notification_disabled_kinds(self, telegram_user_id: int) -> set[str]:
        return set()

    async def enqueue_admin_activity_notification(
        self,
        *,
        actor_user_id: int | None,
        chat_id: int,
        text: str,
        next_attempt_at: int = 0,
        last_error: str | None = None,
        notification_kind: str | None = None,
    ) -> int:
        row = {
            "id": self.next_notification_id,
            "actor_user_id": actor_user_id,
            "chat_id": chat_id,
            "text": text,
            "attempts": 0,
            "last_error": last_error,
            "next_attempt_at": next_attempt_at,
            "sent_at": None,
            "notification_kind": notification_kind,
        }
        self.next_notification_id += 1
        self.pending_notifications.append(row)
        return int(row["id"])

    async def add_audit_log(self, **kwargs) -> None:
        self.audit_logs.append(kwargs)

    async def list_due_admin_activity_notifications(self, *, now_ts: int, limit: int = 100) -> list[dict]:
        rows = [
            row for row in self.pending_notifications
            if row["sent_at"] is None and int(row["next_attempt_at"]) <= now_ts
        ]
        return rows[:limit]

    async def mark_admin_activity_notification_sent(self, *, notification_id: int, sent_at: int) -> None:
        for row in self.pending_notifications:
            if int(row["id"]) == notification_id:
                row["sent_at"] = sent_at
                row["attempts"] = int(row["attempts"]) + 1
                row["last_error"] = None
                return

    async def mark_admin_activity_notification_failed(
        self,
        *,
        notification_id: int,
        last_error: str,
        next_attempt_at: int,
    ) -> None:
        for row in self.pending_notifications:
            if int(row["id"]) == notification_id:
                row["attempts"] = int(row["attempts"]) + 1
                row["last_error"] = last_error
                row["next_attempt_at"] = next_attempt_at
                return


class FakePanelService:
    def __init__(self, detail: dict | None = None) -> None:
        self.detail = detail or {}

    async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
        return self.detail


@pytest.mark.asyncio
async def test_threshold_crossing_sends_200mb_and_100mb_messages() -> None:
    db = FakeDB()
    db.lang_by_user[42] = "fa"
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    previous = {
        "telegram_user_id": 42,
        "service_name": "test-service",
        "client_email": "user@example.com",
        "total_bytes": 500 * 1024 * 1024,
        "used_bytes": 150 * 1024 * 1024,
        "status": "active",
    }
    current = {
        **previous,
        "total_bytes": 500 * 1024 * 1024,
        "used_bytes": 420 * 1024 * 1024,
        "status": "active",
    }

    await service._notify_service_state_changes(previous, current)

    assert [chat_id for chat_id, _ in bot.messages] == [42, 42]
    assert "200" in bot.messages[0][1]
    assert "100" in bot.messages[1][1]


@pytest.mark.asyncio
async def test_100mb_threshold_notifies_direct_owner_from_mapping() -> None:
    db = FakeDB()
    db.lang_by_user[42] = "fa"
    db.client_owners[(3, 8, "uuid-1")] = 999
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    previous = {
        "telegram_user_id": 42,
        "panel_id": 3,
        "inbound_id": 8,
        "client_id": "uuid-1",
        "service_name": "test-service",
        "client_email": "user@example.com",
        "total_bytes": 500 * 1024 * 1024,
        "used_bytes": 350 * 1024 * 1024,
        "status": "active",
    }
    current = {
        **previous,
        "used_bytes": 420 * 1024 * 1024,
    }

    await service._notify_service_state_changes(previous, current)

    assert [chat_id for chat_id, _ in bot.messages] == [42, 999]
    assert "user@example.com" in bot.messages[1][1]


@pytest.mark.asyncio
async def test_depleted_service_notifies_user_and_direct_delegated_admin() -> None:
    db = FakeDB()
    db.lang_by_user[77] = "fa"
    db.delegated_admins[555] = {"telegram_user_id": 555}
    panel_service = FakePanelService(detail={"comment": "555"})
    service = UsageService(db=db, panel_service=panel_service, timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    previous = {
        "telegram_user_id": 77,
        "panel_id": 3,
        "inbound_id": 8,
        "client_id": "uuid-1",
        "client_email": "user@example.com",
        "service_name": "starter",
        "total_bytes": 2 * 1024 * 1024 * 1024,
        "used_bytes": 1 * 1024 * 1024 * 1024,
        "status": "active",
    }
    current = {
        **previous,
        "used_bytes": 2 * 1024 * 1024 * 1024,
        "status": "depleted",
    }

    await service._notify_service_state_changes(previous, current)

    recipients = [chat_id for chat_id, _ in bot.messages]
    assert recipients == [77, 555]


@pytest.mark.asyncio
async def test_expired_service_notifies_user_and_root_admin_when_no_delegated_owner() -> None:
    db = FakeDB()
    db.lang_by_user[91] = "fa"
    panel_service = FakePanelService(detail={"comment": ""})
    service = UsageService(db=db, panel_service=panel_service, timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    previous = {
        "telegram_user_id": 91,
        "panel_id": 2,
        "inbound_id": 6,
        "client_id": "uuid-2",
        "client_email": "exp@example.com",
        "service_name": "exp-service",
        "total_bytes": 2 * 1024 * 1024 * 1024,
        "used_bytes": 1 * 1024 * 1024 * 1024,
        "status": "active",
    }
    current = {
        **previous,
        "status": "expired",
    }

    await service._notify_service_state_changes(previous, current)

    recipients = [chat_id for chat_id, _ in bot.messages]
    assert recipients == [91, 999]


@pytest.mark.asyncio
async def test_admin_traffic_increase_notifies_bound_user() -> None:
    db = FakeDB()
    db.lang_by_user[88] = "fa"
    db.bound_rows = [
        {
            "telegram_user_id": 88,
            "panel_id": 4,
            "client_email": "user@example.com",
            "service_name": "vip",
        }
    ]
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    await service.notify_user_traffic_increased(
        panel_id=4,
        client_email="user@example.com",
        added_bytes=2 * 1024 * 1024 * 1024,
        new_total_bytes=10 * 1024 * 1024 * 1024,
    )

    assert [chat_id for chat_id, _ in bot.messages] == [88]
    assert "اضافه شد" in bot.messages[0][1]


@pytest.mark.asyncio
async def test_admin_notifications_are_deduplicated_per_user() -> None:
    db = FakeDB()
    db.lang_by_user[88] = "fa"
    db.bound_rows = [
        {
            "telegram_user_id": 88,
            "panel_id": 4,
            "client_email": "user@example.com",
            "service_name": "vip-a",
        },
        {
            "telegram_user_id": 88,
            "panel_id": 4,
            "client_email": "user@example.com",
            "service_name": "vip-b",
        },
    ]
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    await service.notify_user_expiry_extended(
        panel_id=4,
        client_email="user@example.com",
        added_days=3,
        new_expiry=1_800_000_000,
    )

    assert [chat_id for chat_id, _ in bot.messages] == [88]


@pytest.mark.asyncio
async def test_failed_admin_activity_is_queued_for_retry() -> None:
    db = FakeDB()
    db.delegated_admins[555] = {"telegram_user_id": 555, "parent_user_id": 0}
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    bot.fail_chat_ids = {999}
    service.attach_bot(bot)  # type: ignore[arg-type]

    await service.notify_admin_activity(actor_user_id=555, text="admin event")

    assert bot.messages == []
    assert len(db.pending_notifications) == 1
    assert int(db.pending_notifications[0]["chat_id"]) == 999


@pytest.mark.asyncio
async def test_admin_activity_skips_parent_without_panel_access() -> None:
    db = FakeDB()
    db.panels[4] = {"id": 4, "is_default": 0, "created_by": 777}
    db.delegated_admins[555] = {"telegram_user_id": 555, "parent_user_id": 111}
    db.delegated_admins[111] = {"telegram_user_id": 111, "parent_user_id": 0}
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]

    await service.notify_admin_activity(actor_user_id=555, text="admin event", panel_id=4)

    assert [chat_id for chat_id, _ in bot.messages] == [999]


@pytest.mark.asyncio
async def test_pending_admin_activity_notifications_are_flushed() -> None:
    db = FakeDB()
    service = UsageService(db=db, panel_service=FakePanelService(), timezone="Asia/Tehran", root_admin_ids={999})  # type: ignore[arg-type]
    bot = DummyBot()
    service.attach_bot(bot)  # type: ignore[arg-type]
    notification_id = await db.enqueue_admin_activity_notification(
        actor_user_id=555,
        chat_id=999,
        text="queued event",
        next_attempt_at=0,
    )

    await service.flush_pending_admin_activity_notifications()

    assert (999, "queued event") in bot.messages
    row = next(item for item in db.pending_notifications if int(item["id"]) == notification_id)
    assert row["sent_at"] is not None
