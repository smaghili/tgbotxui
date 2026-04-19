from __future__ import annotations

import pytest

from bot.services.usage_service import UsageService


class DummyBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class FakeDB:
    def __init__(self) -> None:
        self.lang_by_user: dict[int, str] = {}
        self.bound_rows: list[dict] = []
        self.delegated_admins: dict[int, dict] = {}

    async def get_user_language(self, telegram_user_id: int) -> str:
        return self.lang_by_user.get(telegram_user_id, "fa")

    async def get_delegated_admin_by_user_id(self, telegram_user_id: int) -> dict | None:
        return self.delegated_admins.get(telegram_user_id)

    async def get_user_services_by_panel_email(self, panel_id: int, client_email: str) -> list[dict]:
        return [
            row
            for row in self.bound_rows
            if int(row["panel_id"]) == panel_id and str(row["client_email"]).lower() == client_email.lower()
        ]


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
