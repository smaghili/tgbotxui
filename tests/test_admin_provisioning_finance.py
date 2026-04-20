import unittest

from bot.services.admin_provisioning_service import AdminProvisioningService, ManagedClientRef


class AdminProvisioningFinanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_traffic_by_vless_charges_wallet(self) -> None:
        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, int, str, int]] = []

            async def add_client_total_gb(self, panel_id: int, inbound_id: int, client_uuid: str, add_gb: int) -> None:
                self.calls.append(("traffic", panel_id, inbound_id, client_uuid, add_gb))

        class FakeAccessService:
            pass

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []
                self.refund_calls: list[dict] = []

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
            settings=None,  # type: ignore[arg-type]
            vless_uri="vless://example",
            add_gb=7,
        )

        self.assertEqual(ref.client_uuid, "uuid-1")
        self.assertEqual(panel_service.calls, [("traffic", 10, 20, "uuid-1", 7)])
        self.assertEqual(len(financial_service.charge_calls), 1)
        self.assertEqual(financial_service.charge_calls[0]["traffic_gb"], 7)
        self.assertEqual(financial_service.charge_calls[0]["operation"], "add_client_traffic")
        self.assertEqual(financial_service.refund_calls, [])
        self.assertEqual(len(db.audit_logs), 1)

    async def test_add_days_by_vless_refunds_wallet_when_panel_update_fails(self) -> None:
        class FakeDB:
            def __init__(self) -> None:
                self.audit_logs: list[dict] = []

            async def add_audit_log(self, **kwargs) -> None:
                self.audit_logs.append(kwargs)

        class FakePanelService:
            async def extend_client_expiry_days(self, panel_id: int, inbound_id: int, client_uuid: str, add_days: int) -> None:
                raise RuntimeError("panel failed")

        class FakeAccessService:
            pass

        class FakeFinancialService:
            def __init__(self) -> None:
                self.charge_calls: list[dict] = []
                self.refund_calls: list[dict] = []

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
