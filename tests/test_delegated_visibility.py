import unittest

from bot.services.admin_provisioning_service import AdminProvisioningService


class DelegatedVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_inbounds_include_owned_clients_outside_explicit_access(self) -> None:
        class FakeAccessService:
            def is_root_admin(self, user_id, settings) -> bool:
                return False

        class FakeDB:
            async def list_admin_access_rows_for_user(self, telegram_user_id: int) -> list[dict]:
                return [
                    {
                        "access_id": 1,
                        "panel_id": 10,
                        "panel_name": "panel-a",
                        "inbound_id": 100,
                        "title": "delegated",
                    }
                ]

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 10, "name": "panel-a"}]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [
                    {"id": 100, "remark": "in-a"},
                    {"id": 200, "remark": "in-b"},
                ]

            async def list_clients(self, panel_id: int, **kwargs) -> list[dict]:
                owner_id = kwargs.get("owner_admin_user_id")
                if owner_id == 55:
                    return [{"inbound_id": 200, "uuid": "u1", "email": "user@example.com"}]
                return []

        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=FakePanelService(),  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
        )

        rows = await service.list_visible_inbounds_for_actor(actor_user_id=55, settings=None)  # type: ignore[arg-type]

        self.assertEqual([(row.panel_id, row.inbound_id) for row in rows], [(10, 100), (10, 200)])


if __name__ == "__main__":
    unittest.main()
