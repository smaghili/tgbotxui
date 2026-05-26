import unittest

from bot.services.common_handler_service import CommonHandlerService


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


if __name__ == "__main__":
    unittest.main()
