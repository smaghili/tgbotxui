import unittest

from bot.services.common_handler_service import CommonHandlerService
from bot.handlers.common import _filter_admin_owned_status_rows


class CommonHandlerServiceMissingStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_link_returns_invalid_link(self) -> None:
        class FakeDB:
            pass

        service = CommonHandlerService(db=FakeDB())  # type: ignore[arg-type]
        result = await service.bind_missing_status_service_by_link(
            panel_service=object(),
            telegram_user_id=1,
            link_or_config="not-a-link",
        )
        self.assertEqual(result.status, "invalid_link")

    async def test_not_found_returns_not_found(self) -> None:
        class FakeDB:
            async def get_user_services_by_panel_email(self, panel_id: int, email: str) -> list[dict]:
                return []

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 1}]

            async def find_client_by_uuid(self, panel_id: int, client_uuid: str) -> dict | None:
                return None

        service = CommonHandlerService(db=FakeDB())  # type: ignore[arg-type]
        result = await service.bind_missing_status_service_by_link(
            panel_service=FakePanelService(),
            telegram_user_id=1,
            link_or_config="vless://11111111-1111-4111-8111-111111111111@example.com:443",
        )
        self.assertEqual(result.status, "not_found")

    async def test_existing_returns_exists(self) -> None:
        class FakeDB:
            async def get_user_services_by_panel_email(self, panel_id: int, email: str) -> list[dict]:
                return [{"telegram_user_id": 7}]

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 5}]

            async def find_client_by_uuid(self, panel_id: int, client_uuid: str) -> dict | None:
                return {"email": "alice", "inbound_id": 2}

            async def bind_service_to_user(self, **kwargs) -> dict:
                raise AssertionError("bind should not be called when service already exists")

        service = CommonHandlerService(db=FakeDB())  # type: ignore[arg-type]
        result = await service.bind_missing_status_service_by_link(
            panel_service=FakePanelService(),
            telegram_user_id=7,
            link_or_config="11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(result.status, "exists")
        self.assertEqual(result.panel_id, 5)
        self.assertEqual(result.inbound_id, 2)

    async def test_found_binds_and_returns_added(self) -> None:
        class FakeDB:
            async def get_user_services_by_panel_email(self, panel_id: int, email: str) -> list[dict]:
                return []

        class FakePanelService:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def list_panels(self) -> list[dict]:
                return [{"id": 9}]

            async def find_client_by_uuid(self, panel_id: int, client_uuid: str) -> dict | None:
                return {"email": "bob", "inbound_id": 3}

            async def bind_service_to_user(self, **kwargs) -> dict:
                self.calls.append(kwargs)
                return {}

        panel = FakePanelService()
        service = CommonHandlerService(db=FakeDB())  # type: ignore[arg-type]
        result = await service.bind_missing_status_service_by_link(
            panel_service=panel,
            telegram_user_id=42,
            link_or_config="11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(result.status, "added")
        self.assertEqual(len(panel.calls), 1)
        self.assertEqual(panel.calls[0]["telegram_user_id"], 42)
        self.assertEqual(panel.calls[0]["panel_id"], 9)
        self.assertEqual(panel.calls[0]["client_email"], "bob")


class CommonStatusAdminVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_admin_owned_status_rows_uses_targeted_detail_lookup(self) -> None:
        class FakePanelService:
            def __init__(self) -> None:
                self.detail_calls: list[tuple[int, int, str]] = []

            async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
                self.detail_calls.append((panel_id, inbound_id, client_uuid))
                if client_uuid == "uuid-visible":
                    return {"tg_id": "12345"}
                return {"tg_id": "99999"}

            async def list_clients(self, panel_id: int) -> list[dict]:
                raise AssertionError("list_clients should not be used for admin status visibility")

        class FakeServices:
            def __init__(self) -> None:
                self.panel_service = FakePanelService()

        services = FakeServices()
        rows = [
            {"id": 1, "panel_id": 10, "inbound_id": 20, "client_id": "uuid-visible", "client_email": "a@example.com"},
            {"id": 2, "panel_id": 10, "inbound_id": 21, "client_id": "uuid-hidden", "client_email": "b@example.com"},
        ]

        visible = await _filter_admin_owned_status_rows(
            user_id=12345,
            username=None,
            service_rows=rows,
            services=services,  # type: ignore[arg-type]
        )

        self.assertEqual([row["id"] for row in visible], [1])
        self.assertEqual(
            services.panel_service.detail_calls,
            [(10, 20, "uuid-visible"), (10, 21, "uuid-hidden")],
        )


if __name__ == "__main__":
    unittest.main()
