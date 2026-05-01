import unittest

from bot.services.admin_provisioning_service import AdminProvisioningService, ManagedClientRef
from bot.services.access_service import AdminContext


class AdminProvisioningFinanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_traffic_by_vless_charges_wallet(self) -> None:
        class Settings:
            moaf_admin_ids = set()
            moaf_min_traffic_bytes = 0
            timezone = "Asia/Tehran"

        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []
                self.exemptions: list[dict] = []
                self.segments: list[dict] = []
                self.segments: list[dict] = []
                self.exemptions: list[dict] = []

            async def get_user_language(self, user_id: int) -> str:
                return "fa"

            async def get_user_by_telegram_id(self, user_id: int) -> dict | None:
                return None

            async def get_delegated_admin_by_user_id(self, user_id: int) -> dict | None:
                return {"title": "delegate"}

            async def get_client_owner(self, **kwargs) -> int:
                return 999

            async def upsert_moaf_client_exemption(self, **kwargs) -> None:
                self.exemptions.append(kwargs)

            async def list_moaf_client_exemptions_for_panel(self, panel_id: int) -> dict:
                return {}

            async def get_moaf_client_traffic_segments(self, **kwargs) -> list[dict]:
                return self.segments

            async def add_moaf_client_traffic_segment(self, **kwargs) -> None:
                self.segments.append(kwargs)

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, int, str, int]] = []
                self.total = 2 * 1024 ** 3

            async def add_client_total_gb(self, panel_id: int, inbound_id: int, client_uuid: str, add_gb: int) -> None:
                self.calls.append(("traffic", panel_id, inbound_id, client_uuid, add_gb))
                self.total += add_gb * 1024 ** 3

            async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
                return {"email": "user@example.com", "total": self.total, "comment": "55"}

            async def panel_inbound_names(self, panel_id: int, inbound_id: int) -> tuple[str, str]:
                return "panel-a", "in-a"

        class FakeAccessService:
            pass

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []
                self.refund_calls: list[dict] = []
                self.validate_calls: list[dict] = []

            async def validate_operation_limits(self, **kwargs) -> None:
                self.validate_calls.append(kwargs)

            async def charge_operation(self, **kwargs):
                self.charge_calls.append(kwargs)
                return {"id": 321}

            async def refund_transaction(self, **kwargs):
                self.refund_calls.append(kwargs)

        db = FakeDB()
        panel_service = FakePanelService()
        financial_service = FakeFinancialService()
        service = AdminProvisioningService(
            db=db,  # type: ignore[arg-type]
            panel_service=panel_service,  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=financial_service,  # type: ignore[arg-type]
        )

        async def fake_resolve_client_from_vless_for_actor(**kwargs) -> ManagedClientRef:
            return ManagedClientRef(
                panel_id=10,
                panel_name="panel-a",
                inbound_id=20,
                inbound_name="in-a",
                client_uuid="uuid-1",
                client_email="user@example.com",
            )

        service.resolve_client_from_vless_for_actor = fake_resolve_client_from_vless_for_actor  # type: ignore[method-assign]

        ref = await service.add_traffic_by_vless_for_actor(
            actor_user_id=55,
            settings=Settings(),  # type: ignore[arg-type]
            vless_uri="vless://example",
            add_gb=7,
        )

        self.assertEqual(ref.client_uuid, "uuid-1")
        self.assertEqual(panel_service.calls, [("traffic", 10, 20, "uuid-1", 7)])
        self.assertEqual(len(financial_service.charge_calls), 1)
        self.assertEqual(financial_service.charge_calls[0]["traffic_gb"], 7)
        self.assertEqual(financial_service.charge_calls[0]["operation"], "add_client_traffic")
        self.assertEqual(financial_service.refund_calls, [])
        self.assertEqual(len(db.audit_logs), 2)

    async def test_moaf_add_traffic_by_vless_skips_wallet_and_updates_comment(self) -> None:
        class Settings:
            moaf_admin_ids = {55}
            moaf_min_traffic_bytes = 5 * 1024 ** 3
            timezone = "Asia/Tehran"

        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []
                self.exemptions: list[dict] = []
                self.segments: list[dict] = []

            async def get_user_language(self, user_id: int) -> str:
                return "fa"

            async def get_user_by_telegram_id(self, user_id: int) -> dict | None:
                return None

            async def get_delegated_admin_by_user_id(self, user_id: int) -> dict | None:
                return {"title": "delegate"}

            async def get_client_owner(self, **kwargs) -> int:
                return 999

            async def upsert_moaf_client_exemption(self, **kwargs) -> None:
                self.exemptions.append(kwargs)

            async def list_moaf_client_exemptions_for_panel(self, panel_id: int) -> dict:
                return {}

            async def get_moaf_client_traffic_segments(self, **kwargs) -> list[dict]:
                return self.segments

            async def add_moaf_client_traffic_segment(self, **kwargs) -> None:
                self.segments.append(kwargs)

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            def __init__(self) -> None:
                self.calls: list[dict] = []
                self.total = 2 * 1024 ** 3
                self.comment = "999"

            async def add_client_total_gb(
                self,
                panel_id: int,
                inbound_id: int,
                client_uuid: str,
                add_gb: int,
                *,
                comment: str | None = None,
            ) -> None:
                self.calls.append(
                    {
                        "panel_id": panel_id,
                        "inbound_id": inbound_id,
                        "client_uuid": client_uuid,
                        "add_gb": add_gb,
                        "comment": comment,
                    }
                )
                self.total += add_gb * 1024 ** 3
                self.comment = str(comment or self.comment)

            async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
                return {"email": "user@example.com", "total": self.total, "comment": self.comment}

            async def panel_inbound_names(self, panel_id: int, inbound_id: int) -> tuple[str, str]:
                return "panel-a", "in-a"

        class FakeAccessService:
            async def get_admin_context(self, user_id, settings) -> AdminContext:
                return AdminContext(
                    user_id=user_id,
                    is_root_admin=False,
                    is_delegated_admin=True,
                    delegated_scope="limited",
                )

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []
                self.validate_calls: list[dict] = []

            async def validate_operation_limits(self, **kwargs) -> None:
                self.validate_calls.append(kwargs)

            async def charge_operation(self, **kwargs):
                self.charge_calls.append(kwargs)
                return {"id": 321}

        class FakeUsageService:
            def __init__(self) -> None:
                self.root_messages: list[dict] = []
                self.traffic_messages: list[dict] = []

            async def is_active_delegated_admin_user(self, user_id: int) -> bool:
                return False

            async def notify_root_admin_activity(self, **kwargs) -> None:
                self.root_messages.append(kwargs)

            async def notify_user_traffic_increased(self, **kwargs) -> None:
                self.traffic_messages.append(kwargs)

        db = FakeDB()
        panel_service = FakePanelService()
        financial_service = FakeFinancialService()
        usage_service = FakeUsageService()
        service = AdminProvisioningService(
            db=db,  # type: ignore[arg-type]
            panel_service=panel_service,  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=financial_service,  # type: ignore[arg-type]
            usage_service=usage_service,  # type: ignore[arg-type]
        )

        async def fake_resolve_client_from_vless_for_actor(**kwargs) -> ManagedClientRef:
            return ManagedClientRef(
                panel_id=10,
                panel_name="panel-a",
                inbound_id=20,
                inbound_name="in-a",
                client_uuid="uuid-1",
                client_email="user@example.com",
            )

        service.resolve_client_from_vless_for_actor = fake_resolve_client_from_vless_for_actor  # type: ignore[method-assign]

        ref = await service.add_traffic_by_vless_for_actor(
            actor_user_id=55,
            settings=Settings(),  # type: ignore[arg-type]
            vless_uri="vless://example",
            add_gb=5,
        )

        self.assertEqual(ref.client_uuid, "uuid-1")
        self.assertEqual(financial_service.validate_calls, [])
        self.assertEqual(financial_service.charge_calls, [])
        self.assertEqual(panel_service.calls[0]["comment"], "55:Moaf")
        self.assertEqual(panel_service.comment, "55:Moaf")
        self.assertEqual(len(usage_service.root_messages), 1)
        self.assertTrue(str(usage_service.root_messages[0]["text"]).startswith("**خرید ویژه**"))
        self.assertIn("افزایش حجم کاربر", str(usage_service.root_messages[0]["text"]))
        self.assertEqual(db.exemptions[0]["owner_user_id"], 999)
        self.assertEqual(db.exemptions[0]["moaf_user_id"], 55)
        self.assertEqual(db.exemptions[0]["exempt_after_bytes"], 2 * 1024 ** 3)
        self.assertEqual(
            [(item["start_bytes"], item["end_bytes"], item["is_billable"]) for item in db.segments],
            [(0, 2 * 1024 ** 3, True), (2 * 1024 ** 3, 7 * 1024 ** 3, False)],
        )
        self.assertEqual(len(db.audit_logs), 1)

        await service.add_traffic_by_vless_for_actor(
            actor_user_id=55,
            settings=Settings(),  # type: ignore[arg-type]
            vless_uri="vless://example",
            add_gb=2,
        )

        self.assertEqual(len(financial_service.charge_calls), 1)
        self.assertEqual(financial_service.charge_calls[0]["traffic_gb"], 2)
        self.assertEqual(
            [(item["start_bytes"], item["end_bytes"], item["is_billable"]) for item in db.segments],
            [
                (0, 2 * 1024 ** 3, True),
                (2 * 1024 ** 3, 7 * 1024 ** 3, False),
                (7 * 1024 ** 3, 9 * 1024 ** 3, True),
            ],
        )

    async def test_small_add_after_initial_moaf_only_bills_new_segment(self) -> None:
        class Settings:
            moaf_admin_ids = {55}
            moaf_min_traffic_bytes = 5 * 1024 ** 3
            timezone = "Asia/Tehran"

        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []
                self.segments: list[dict] = []

            async def get_user_language(self, user_id: int) -> str:
                return "fa"

            async def get_user_by_telegram_id(self, user_id: int) -> dict | None:
                return None

            async def get_delegated_admin_by_user_id(self, user_id: int) -> dict | None:
                return {"title": "delegate"}

            async def get_client_owner(self, **kwargs) -> int:
                return 55

            async def list_moaf_client_exemptions_for_panel(self, panel_id: int) -> dict:
                return {}

            async def get_moaf_client_traffic_segments(self, **kwargs) -> list[dict]:
                return self.segments

            async def add_moaf_client_traffic_segment(self, **kwargs) -> None:
                self.segments.append(kwargs)

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            def __init__(self) -> None:
                self.total = 10 * 1024 ** 3
                self.comment = "55:Moaf"

            async def add_client_total_gb(
                self,
                panel_id: int,
                inbound_id: int,
                client_uuid: str,
                add_gb: int,
                *,
                comment: str | None = None,
            ) -> None:
                self.total += add_gb * 1024 ** 3
                self.comment = str(comment or self.comment)

            async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
                return {"email": "user@example.com", "total": self.total, "comment": self.comment}

            async def panel_inbound_names(self, panel_id: int, inbound_id: int) -> tuple[str, str]:
                return "panel-a", "in-a"

        class FakeAccessService:
            pass

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []
                self.validate_calls: list[dict] = []

            async def validate_operation_limits(self, **kwargs) -> None:
                self.validate_calls.append(kwargs)

            async def charge_operation(self, **kwargs):
                self.charge_calls.append(kwargs)
                return {"id": 321}

        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=FakePanelService(),  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=FakeFinancialService(),  # type: ignore[arg-type]
        )

        async def fake_resolve_client_from_vless_for_actor(**kwargs) -> ManagedClientRef:
            return ManagedClientRef(
                panel_id=10,
                panel_name="panel-a",
                inbound_id=20,
                inbound_name="in-a",
                client_uuid="uuid-1",
                client_email="user@example.com",
            )

        service.resolve_client_from_vless_for_actor = fake_resolve_client_from_vless_for_actor  # type: ignore[method-assign]

        await service.add_traffic_by_vless_for_actor(
            actor_user_id=55,
            settings=Settings(),  # type: ignore[arg-type]
            vless_uri="vless://example",
            add_gb=2,
        )

        self.assertEqual(service.financial_service.charge_calls[0]["traffic_gb"], 2)  # type: ignore[union-attr]
        self.assertEqual(
            [(item["start_bytes"], item["end_bytes"], item["is_billable"], item["source"]) for item in service.db.segments],  # type: ignore[attr-defined]
            [
                (0, 10 * 1024 ** 3, False, "initial_moaf"),
                (10 * 1024 ** 3, 12 * 1024 ** 3, True, "add_traffic"),
            ],
        )

    async def test_add_days_by_vless_refunds_wallet_when_panel_update_fails(self) -> None:
        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
                return {"email": "user@example.com", "total": 2 * 1024 ** 3, "expiry": 0}

            async def extend_client_expiry_days(self, panel_id: int, inbound_id: int, client_uuid: str, add_days: int) -> None:
                raise RuntimeError("panel failed")

        class FakeAccessService:
            pass

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []
                self.refund_calls: list[dict] = []

            async def validate_operation_limits(self, **kwargs) -> None:
                return None

            async def charge_operation(self, **kwargs):
                self.charge_calls.append(kwargs)
                return {"id": 654}

            async def refund_transaction(self, **kwargs):
                self.refund_calls.append(kwargs)

        db = FakeDB()
        financial_service = FakeFinancialService()
        service = AdminProvisioningService(
            db=db,  # type: ignore[arg-type]
            panel_service=FakePanelService(),  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=financial_service,  # type: ignore[arg-type]
        )

        async def fake_resolve_client_from_vless_for_actor(**kwargs) -> ManagedClientRef:
            return ManagedClientRef(
                panel_id=10,
                panel_name="panel-a",
                inbound_id=20,
                inbound_name="in-a",
                client_uuid="uuid-2",
                client_email="user@example.com",
            )

        service.resolve_client_from_vless_for_actor = fake_resolve_client_from_vless_for_actor  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "panel failed"):
            await service.add_days_by_vless_for_actor(
                actor_user_id=55,
                settings=None,  # type: ignore[arg-type]
                vless_uri="vless://example",
                add_days=14,
            )

        self.assertEqual(len(financial_service.charge_calls), 1)
        self.assertEqual(financial_service.charge_calls[0]["expiry_days"], 14)
        self.assertEqual(financial_service.charge_calls[0]["operation"], "extend_client_expiry")
        self.assertEqual(financial_service.refund_calls, [
            {
                "actor_user_id": 55,
                "transaction_id": 654,
                "reason": "refund:extend_client_expiry_failed:uuid-2",
            }
        ])
        self.assertEqual(db.audit_logs, [])


if __name__ == "__main__":
    unittest.main()
