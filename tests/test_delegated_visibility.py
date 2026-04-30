import unittest

from bot.services.access_service import AccessService, AdminContext
from bot.services.admin_provisioning_service import AdminProvisioningService


class DelegatedVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_delegated_panel_list_hides_unpermitted_panels(self) -> None:
        class Settings:
            admin_ids = set()

        class FakeDB:
            async def get_delegated_admin_by_user_id(self, telegram_user_id: int) -> dict:
                return {"telegram_user_id": telegram_user_id, "admin_scope": "full"}

            async def get_delegated_admin_profile(self, telegram_user_id: int) -> dict:
                return {"is_active": 1, "expires_at": 0}

            async def list_panels(self) -> list[dict]:
                return [
                    {"id": 10, "name": "default", "is_default": 1, "created_by": 1},
                    {"id": 20, "name": "hidden", "is_default": 0, "created_by": 999},
                    {"id": 30, "name": "granted", "is_default": 0, "created_by": 999},
                    {"id": 40, "name": "owned", "is_default": 0, "created_by": 55},
                ]

            async def list_delegated_admin_panel_access_rows(self, telegram_user_id: int) -> list[dict]:
                return [{"panel_id": 30}]

        service = AccessService(FakeDB())  # type: ignore[arg-type]

        panels = await service.list_accessible_panels(user_id=55, settings=Settings())  # type: ignore[arg-type]

        self.assertEqual([int(panel["id"]) for panel in panels], [10, 30, 40])

    async def test_visible_inbounds_include_owned_clients_outside_explicit_access(self) -> None:
        class FakeAccessService:
            async def get_admin_context(self, user_id, settings) -> AdminContext:
                return AdminContext(
                    user_id=user_id,
                    is_root_admin=False,
                    is_delegated_admin=True,
                    delegated_scope="limited",
                )

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

    async def test_full_delegated_visibility_excludes_unrelated_panels(self) -> None:
        class FakeAccessService:
            async def get_admin_context(self, user_id, settings) -> AdminContext:
                return AdminContext(
                    user_id=user_id,
                    is_root_admin=False,
                    is_delegated_admin=True,
                    delegated_scope="full",
                )

        class FakeDB:
            async def list_admin_access_rows_for_user(self, telegram_user_id: int) -> list[dict]:
                return [
                    {
                        "access_id": 1,
                        "panel_id": 30,
                        "panel_name": "explicit-panel",
                        "inbound_id": 301,
                        "title": "delegated",
                    }
                ]

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [
                    {"id": 10, "name": "default-panel", "is_default": 1, "created_by": 1},
                    {"id": 20, "name": "private-panel", "is_default": 0, "created_by": 999},
                    {"id": 30, "name": "explicit-panel", "is_default": 0, "created_by": 999},
                    {"id": 40, "name": "owned-panel", "is_default": 0, "created_by": 55},
                ]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [
                    {"id": panel_id * 10 + 1, "remark": f"in-{panel_id}-a"},
                    {"id": panel_id * 10 + 2, "remark": f"in-{panel_id}-b"},
                ]

            async def list_clients(self, panel_id: int, **kwargs) -> list[dict]:
                return []

        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=FakePanelService(),  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
        )

        rows = await service.list_visible_inbounds_for_actor(actor_user_id=55, settings=None)  # type: ignore[arg-type]

        self.assertEqual(
            [(row.panel_id, row.inbound_id) for row in rows],
            [(10, 101), (10, 102), (30, 301), (40, 401), (40, 402)],
        )

    async def test_grantable_inbounds_are_limited_to_default_and_panel_access(self) -> None:
        class FakeDB:
            async def list_delegated_admin_panel_access_rows(self, telegram_user_id: int) -> list[dict]:
                return [{"panel_id": 30, "panel_name": "granted-panel"}]

        class FakePanelService:
            async def get_default_panel(self) -> dict:
                return {"id": 10, "name": "default-panel"}

            async def list_panels(self) -> list[dict]:
                return [
                    {"id": 10, "name": "default-panel", "is_default": 1},
                    {"id": 20, "name": "hidden-panel", "is_default": 0},
                    {"id": 30, "name": "granted-panel", "is_default": 0},
                ]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [{"id": panel_id * 10 + 1, "remark": f"in-{panel_id}"}]

        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=FakePanelService(),  # type: ignore[arg-type]
            access_service=None,  # type: ignore[arg-type]
        )

        rows = await service.list_grantable_inbounds_for_delegated_admin(telegram_user_id=55)

        self.assertEqual([(row.panel_id, row.inbound_id) for row in rows], [(10, 101), (30, 301)])

    async def test_moaf_create_skips_finance_and_marks_comment(self) -> None:
        class Settings:
            admin_ids = set()
            moaf_admin_ids = {55}
            moaf_traffic_bytes = {5 * 1024 ** 3}

        class FakeAccessService:
            def is_root_admin(self, user_id, settings) -> bool:
                return False

            async def can_access_inbound(self, **kwargs) -> bool:
                return True

            async def get_admin_context(self, user_id, settings) -> AdminContext:
                return AdminContext(
                    user_id=user_id,
                    is_root_admin=False,
                    is_delegated_admin=True,
                    delegated_scope="limited",
                )

        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []

            async def get_delegated_admin_profile(self, user_id: int) -> dict:
                return {"max_clients": 0}

            async def upsert_client_owner(self, **kwargs) -> None:
                return None

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            def __init__(self) -> None:
                self.comment = ""

            async def create_client(self, **kwargs) -> dict:
                self.comment = str(kwargs.get("comment") or "")
                return {"uuid": "uuid-1", "email": kwargs["client_email"]}

            async def get_client_vless_uri_by_email(self, **kwargs) -> str:
                return "vless://uuid@example.com:443"

            async def get_client_subscription_url_by_email(self, **kwargs) -> str:
                return ""

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []

            async def charge_operation(self, **kwargs) -> dict:
                self.charge_calls.append(kwargs)
                return {"id": 1, "amount": 1000}

        panel_service = FakePanelService()
        financial_service = FakeFinancialService()
        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=panel_service,  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=financial_service,  # type: ignore[arg-type]
        )

        result = await service.create_client_for_actor(
            actor_user_id=55,
            settings=Settings(),  # type: ignore[arg-type]
            panel_id=1,
            inbound_id=100,
            client_email="u1",
            total_gb=5,
            expiry_days=30,
        )

        self.assertEqual(panel_service.comment, "55:Moaf")
        self.assertEqual(financial_service.charge_calls, [])
        self.assertEqual(result["wallet_charge_amount"], 0)


if __name__ == "__main__":
    unittest.main()
