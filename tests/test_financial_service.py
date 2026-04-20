from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.db import Database
from bot.services.access_service import AccessService
from bot.services.financial_service import FinancialService


def _db_path(name: str) -> Path:
    path = Path.cwd() / name
    if path.exists():
        path.unlink()
    return path


@pytest.mark.asyncio
async def test_charge_and_refund_wallet_transaction() -> None:
    db_path = _db_path(".test-finance.sqlite3")
    db = Database(str(db_path))
    await db.connect()
    await db.init_schema()
    await db.upsert_user(telegram_user_id=1001, full_name="Delegated", username="delegated", is_admin=False)

    access_service = AccessService(db)
    financial_service = FinancialService(db=db, access_service=access_service)

    await financial_service.set_wallet_balance(actor_user_id=1, telegram_user_id=1001, amount=500_000)
    await financial_service.set_pricing(
        actor_user_id=1,
        telegram_user_id=1001,
        price_per_gb=300_000,
        price_per_day=10_000,
    )

    tx = await financial_service.charge_operation(
        actor_user_id=1001,
        settings=SimpleNamespace(admin_ids=[]),
        operation="create_client",
        traffic_gb=1,
        expiry_days=2,
    )

    assert tx is not None
    assert int(tx["amount"]) == -320_000
    wallet = await financial_service.get_wallet(1001)
    assert int(wallet["balance"]) == 180_000

    await financial_service.refund_transaction(
        actor_user_id=1,
        transaction_id=int(tx["id"]),
        reason="refund:test",
    )
    wallet = await financial_service.get_wallet(1001)
    assert int(wallet["balance"]) == 500_000

    report = await financial_service.get_sales_report(1001)
    assert int(report["total_sales"]) == 320_000
    assert int(report["total_refunds"]) == 320_000

    await db.close()
    if db_path.exists():
        db_path.unlink()


@pytest.mark.asyncio
async def test_root_admin_is_not_charged() -> None:
    db_path = _db_path(".test-finance-root.sqlite3")
    db = Database(str(db_path))
    await db.connect()
    await db.init_schema()
    await db.upsert_user(telegram_user_id=1, full_name="Root", username="root", is_admin=True)

    access_service = AccessService(db)
    financial_service = FinancialService(db=db, access_service=access_service)

    tx = await financial_service.charge_operation(
        actor_user_id=1,
        settings=SimpleNamespace(admin_ids=[1]),
        operation="create_client",
        traffic_gb=10,
        expiry_days=30,
    )

    assert tx is None
    wallet = await financial_service.get_wallet(1)
    assert int(wallet["balance"]) == 0

    await db.close()
    if db_path.exists():
        db_path.unlink()
