import unittest
from types import SimpleNamespace

from bot.handlers.admin_finance import _finance_delegated_keyboard
from bot.services.admin_provisioning_service import AdminProvisioningService


class AdminFinanceCreditTests(unittest.IsolatedAsyncioTestCase):
    def test_delegated_finance_keyboard_uses_credit_button(self) -> None:
        markup = _finance_delegated_keyboard("fa")

        self.assertEqual(len(markup.inline_keyboard), 1)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "fin:credit:me")

    async def test_scope_financial_summary_aggregates_subtree_consumed_usage(self) -> None:
        class FakeDB:
            async def get_delegated_admin_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
                self.last_manager = manager_user_id
                self.last_include_self = include_self
                return [manager_user_id, 2002]

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 7, "name": "main"}]

            async def list_clients(self, panel_id: int, **kwargs) -> list[dict]:
                return [
                    {"inbound_id": 11, "uuid": "u-main", "comment": "2001"},
                    {"inbound_id": 12, "uuid": "u-child", "comment": "2002"},
                    {"inbound_id": 13, "uuid": "u-root", "comment": ""},
                ]

            async def get_client_detail(self, panel_id: int, inbound_id: int, client_uuid: str) -> dict:
                details = {
                    "u-main": {"total": 5 * (1024**3), "used": 2 * (1024**3)},
                    "u-child": {"total": 3 * (1024**3), "used": 1 * (1024**3) + 512},
                    "u-root": {"total": 9 * (1024**3), "used": 9 * (1024**3)},
                }
                return details[client_uuid]

        class FakeAccessService:
            async def get_admin_context(self, user_id: int, settings) -> SimpleNamespace:
                return SimpleNamespace(is_root_admin=False, delegated_scope="full")

        class FakeFinancialService:
            async def get_wallet(self, telegram_user_id: int) -> dict:
                return {"balance": 125_000, "currency": "تومان"}

            async def get_pricing(self, telegram_user_id: int) -> dict:
                return {
                    "price_per_gb": 220_000,
                    "price_per_day": 0,
                    "currency": "تومان",
                    "charge_basis": "consumed",
                }

            async def get_scope_sales_totals(self, telegram_user_ids: list[int]) -> dict:
                return {
                    "total_sales": 880_000,
                    "total_transactions": 4,
                }

        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=FakePanelService(),  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=FakeFinancialService(),  # type: ignore[arg-type]
        )

        summary = await service.get_admin_scope_financial_summary(
            actor_user_id=2001,
            settings=SimpleNamespace(admin_ids=[]),
        )

        self.assertEqual(summary["clients_count"], 2)
        self.assertEqual(summary["allocated_gb"], 8)
        self.assertEqual(summary["consumed_gb"], 4)
        self.assertEqual(summary["sale_amount"], 880_000)
        self.assertEqual(summary["debt_amount"], 880_000)
        self.assertEqual(summary["total_transactions"], 4)


if __name__ == "__main__":
    unittest.main()
