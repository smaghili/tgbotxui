import json
import unittest
from types import SimpleNamespace

from bot.handlers.admin_finance import _finance_delegated_keyboard
from bot.handlers.admin_finance_helpers import consumed_basis_payable_remainder
from bot.services.admin_provisioning_service import AdminProvisioningService
from bot.services.financial_service import FinancialService


class AdminFinanceCreditTests(unittest.IsolatedAsyncioTestCase):
    def test_delegated_finance_keyboard_uses_credit_button(self) -> None:
        markup = _finance_delegated_keyboard("fa")

        self.assertEqual(len(markup.inline_keyboard), 3)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "fin:credit:me")

    def test_consumed_basis_payable_remainder(self) -> None:
        self.assertEqual(
            consumed_basis_payable_remainder(debt_amount=215_603_767, wallet_balance=181_713_660),
            33_890_107,
        )
        self.assertEqual(consumed_basis_payable_remainder(debt_amount=50, wallet_balance=100), 0)

    async def test_scope_financial_summary_aggregates_subtree_consumed_usage(self) -> None:
        class FakeDB:
            async def get_delegated_admin_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
                self.last_manager = manager_user_id
                self.last_include_self = include_self
                return [manager_user_id, 2002]

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 7, "name": "main"}]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [
                    {
                        "id": 11,
                        "settings": json.dumps(
                            {
                                "clients": [
                                    {"id": "u-main", "totalGB": 5 * (1024**3), "comment": "2001"},
                                    {"id": "u-child", "totalGB": 3 * (1024**3), "comment": "2002"},
                                    {"id": "u-root", "totalGB": 9 * (1024**3), "comment": ""},
                                ]
                            }
                        ),
                        "clientStats": [
                            {"id": "u-main", "up": 2 * (1024**3), "down": 0},
                            {"id": "u-child", "up": 1 * (1024**3) + 512, "down": 0},
                            {"id": "u-root", "up": 9 * (1024**3), "down": 0},
                        ],
                    }
                ]

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

            async def get_scope_sales_totals(self, telegram_user_ids: list[int], **kwargs) -> dict:
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
        self.assertAlmostEqual(summary["consumed_gb"], 3.000000476837158)
        self.assertEqual(summary["sale_amount"], 880_000)
        self.assertEqual(summary["debt_amount"], 660_000)
        self.assertEqual(summary["total_transactions"], 4)

    async def test_scope_financial_summary_uses_traffic_segments(self) -> None:
        gb = 1024 ** 3

        class FakeDB:
            async def get_delegated_admin_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
                return [manager_user_id]

            async def list_moaf_client_traffic_segments_for_panel(self, panel_id: int) -> dict:
                return {
                    (11, "u-moaf"): [
                        {
                            "owner_user_id": 2001,
                            "actor_user_id": 2001,
                            "start_bytes": 0,
                            "end_bytes": 2 * gb,
                            "is_billable": True,
                        },
                        {
                            "owner_user_id": 2001,
                            "actor_user_id": 55,
                            "start_bytes": 2 * gb,
                            "end_bytes": 7 * gb,
                            "is_billable": False,
                        },
                        {
                            "owner_user_id": 2001,
                            "actor_user_id": 55,
                            "start_bytes": 7 * gb,
                            "end_bytes": 9 * gb,
                            "is_billable": True,
                        },
                    ]
                }

        class FakePanelService:
            def __init__(self) -> None:
                self.used_bytes = 2 * gb

            async def list_panels(self) -> list[dict]:
                return [{"id": 7, "name": "main"}]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [
                    {
                        "id": 11,
                        "settings": json.dumps(
                            {
                                "clients": [
                                    {"id": "u-moaf", "totalGB": 9 * gb, "comment": "55"},
                                ]
                            }
                        ),
                        "clientStats": [
                            {"id": "u-moaf", "up": self.used_bytes, "down": 0},
                        ],
                    }
                ]

        class FakeAccessService:
            async def get_admin_context(self, user_id: int, settings) -> SimpleNamespace:
                return SimpleNamespace(is_root_admin=False, delegated_scope="full")

        class FakeFinancialService:
            async def get_wallet(self, telegram_user_id: int) -> dict:
                return {"balance": 0, "currency": "تومان"}

            async def get_pricing(self, telegram_user_id: int) -> dict:
                return {
                    "price_per_gb": 300,
                    "price_per_day": 0,
                    "currency": "تومان",
                    "charge_basis": "consumed",
                }

            async def get_scope_sales_totals(self, telegram_user_ids: list[int], **kwargs) -> dict:
                return {"total_sales": 1200, "total_transactions": 1}

        panel_service = FakePanelService()
        service = AdminProvisioningService(
            db=FakeDB(),  # type: ignore[arg-type]
            panel_service=panel_service,  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
            financial_service=FakeFinancialService(),  # type: ignore[arg-type]
        )

        summary = await service.get_admin_scope_financial_summary(
            actor_user_id=2001,
            settings=SimpleNamespace(admin_ids=[]),
        )

        self.assertEqual(summary["clients_count"], 1)
        self.assertEqual(summary["allocated_gb"], 4)
        self.assertEqual(summary["consumed_gb"], 2)
        self.assertEqual(summary["remaining_gb"], 2)
        self.assertEqual(summary["debt_amount"], 600)

        panel_service.used_bytes = 6 * gb
        summary = await service.get_admin_scope_financial_summary(
            actor_user_id=2001,
            settings=SimpleNamespace(admin_ids=[]),
        )

        self.assertEqual(summary["consumed_gb"], 2)
        self.assertEqual(summary["remaining_gb"], 2)
        self.assertEqual(summary["debt_amount"], 600)

        panel_service.used_bytes = 8 * gb
        summary = await service.get_admin_scope_financial_summary(
            actor_user_id=2001,
            settings=SimpleNamespace(admin_ids=[]),
        )

        self.assertEqual(summary["consumed_gb"], 3)
        self.assertEqual(summary["remaining_gb"], 1)
        self.assertEqual(summary["debt_amount"], 900)

    async def test_scope_financial_summary_excludes_finance_excluded_inbounds(self) -> None:
        gb = 1024 ** 3

        class FakeDB:
            async def get_delegated_admin_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
                return [manager_user_id]

            async def list_delegate_finance_excluded_inbounds(self, delegate_user_id: int) -> set[tuple[int, int]]:
                return {(7, 11)}

            async def list_moaf_client_exemptions_for_panel(self, panel_id: int) -> dict:
                return {}

            async def list_moaf_client_traffic_segments_for_panel(self, panel_id: int) -> dict:
                return {}

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 7, "name": "main"}]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [
                    {
                        "id": 11,
                        "settings": json.dumps(
                            {
                                "clients": [
                                    {"id": "excluded", "totalGB": 8 * gb, "comment": "2001"},
                                    {"id": "included", "totalGB": 4 * gb, "comment": "2001"},
                                ]
                            }
                        ),
                        "clientStats": [
                            {"id": "excluded", "up": 6 * gb, "down": 0},
                            {"id": "included", "up": 2 * gb, "down": 0},
                        ],
                    },
                    {
                        "id": 12,
                        "settings": json.dumps(
                            {
                                "clients": [
                                    {"id": "other", "totalGB": 4 * gb, "comment": "2001"},
                                ]
                            }
                        ),
                        "clientStats": [
                            {"id": "other", "up": 2 * gb, "down": 0},
                        ],
                    },
                ]

        class FakeAccessService:
            async def get_admin_context(self, user_id: int, settings) -> SimpleNamespace:
                return SimpleNamespace(is_root_admin=False, delegated_scope="full")

        class FakeFinancialService:
            async def get_wallet(self, telegram_user_id: int) -> dict:
                return {"balance": 0, "currency": "تومان"}

            async def get_pricing(self, telegram_user_id: int) -> dict:
                return {
                    "price_per_gb": 100_000,
                    "price_per_day": 0,
                    "currency": "تومان",
                    "charge_basis": "consumed",
                }

            async def get_scope_sales_totals(self, telegram_user_ids: list[int], **kwargs) -> dict:
                return {"total_sales": 0, "total_transactions": 0}

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

        self.assertEqual(summary["clients_count"], 1)
        self.assertEqual(summary["consumed_gb"], 2)
        self.assertEqual(summary["debt_amount"], 200_000)

    async def test_scope_sales_totals_excludes_inbound_pairs_when_requested(self) -> None:
        class FakeConn:
            async def execute(self, query: str, params: tuple[int, ...]):
                class Cur:
                    async def fetchall(self_nonlocal):
                        return [
                            {"telegram_user_id": 1, "amount": -100, "kind": "charge", "details": "panel=7;inbound=11;email=a"},
                            {"telegram_user_id": 1, "amount": -200, "kind": "charge", "details": "panel=7;inbound=12;email=b"},
                            {"telegram_user_id": 1, "amount": 50, "kind": "refund", "details": "panel=7;inbound=11;email=a"},
                        ]

                return Cur()

        class FakeDB:
            def __init__(self) -> None:
                self.conn = FakeConn()

        class FakeAccessService:
            pass

        fs = FinancialService(
            db=FakeDB(),  # type: ignore[arg-type]
            access_service=FakeAccessService(),  # type: ignore[arg-type]
        )

        totals = await fs.get_scope_sales_totals([1], excluded_inbound_pairs={(7, 11)})
        self.assertEqual(totals["total_sales"], 200)
        self.assertEqual(totals["total_refunds"], 0)
        self.assertEqual(totals["total_transactions"], 1)

    async def test_scope_financial_summary_ignores_invalid_old_detach_snapshots(self) -> None:
        gb = 1024 ** 3

        class FakeDB:
            async def get_delegated_admin_subtree_user_ids(self, *, manager_user_id: int, include_self: bool = True) -> list[int]:
                return [manager_user_id]

            async def list_moaf_client_traffic_segments_for_panel(self, panel_id: int) -> dict:
                return {
                    (11, "valid-child"): [
                        {
                            "owner_user_id": 2001,
                            "actor_user_id": 1,
                            "start_bytes": 0,
                            "end_bytes": 2 * gb,
                            "is_billable": True,
                            "source": "parent_detach_snapshot",
                        },
                    ],
                    (11, "root-created"): [
                        {
                            "owner_user_id": 2001,
                            "actor_user_id": 1,
                            "start_bytes": 0,
                            "end_bytes": 40 * gb,
                            "is_billable": True,
                            "source": "parent_detach_snapshot",
                        },
                    ],
                    (11, "moaf-created"): [
                        {
                            "owner_user_id": 2001,
                            "actor_user_id": 1,
                            "start_bytes": 0,
                            "end_bytes": 5 * gb,
                            "is_billable": True,
                            "source": "parent_detach_snapshot",
                        },
                    ],
                }

        class FakePanelService:
            async def list_panels(self) -> list[dict]:
                return [{"id": 7, "name": "main"}]

            async def list_inbounds(self, panel_id: int) -> list[dict]:
                return [
                    {
                        "id": 11,
                        "settings": json.dumps(
                            {
                                "clients": [
                                    {"id": "valid-child", "totalGB": 2 * gb, "comment": "55"},
                                    {"id": "root-created", "totalGB": 40 * gb, "comment": ""},
                                    {"id": "moaf-created", "totalGB": 5 * gb, "comment": "55:Moaf"},
                                ]
                            }
                        ),
                        "clientStats": [
                            {"id": "valid-child", "up": 1 * gb, "down": 0},
                            {"id": "root-created", "up": 4 * gb, "down": 0},
                            {"id": "moaf-created", "up": 3 * gb, "down": 0},
                        ],
                    }
                ]

        class FakeAccessService:
            async def get_admin_context(self, user_id: int, settings) -> SimpleNamespace:
                return SimpleNamespace(is_root_admin=False, delegated_scope="full")

        class FakeFinancialService:
            async def get_wallet(self, telegram_user_id: int) -> dict:
                return {"balance": 0, "currency": "تومان"}

            async def get_pricing(self, telegram_user_id: int) -> dict:
                return {
                    "price_per_gb": 220_000,
                    "price_per_day": 0,
                    "currency": "تومان",
                    "charge_basis": "consumed",
                }

            async def get_scope_sales_totals(self, telegram_user_ids: list[int], **kwargs) -> dict:
                return {"total_sales": 0, "total_transactions": 0}

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

        self.assertEqual(summary["allocated_gb"], 7)
        self.assertEqual(summary["consumed_gb"], 8)
        self.assertEqual(summary["remaining_gb"], 3)
        self.assertEqual(summary["remaining_amount"], 660_000)


if __name__ == "__main__":
    unittest.main()
