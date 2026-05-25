from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from bot.config import Settings
from bot.db import Database
from bot.services.access_service import AccessService
from bot.services.admin_panel_service import AdminPanelService
from bot.services.admin_provisioning_service import AdminProvisioningService
from bot.services.crypto import CryptoService
from bot.services.financial_service import FinancialService
from bot.services.panel_service import PanelService
from bot.services.usage_service import UsageService
from bot.services.xui_client import XUIClient


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    idx = (len(values) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return values[lo] * (1 - frac) + values[hi] * frac


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark usage sync latency")
    parser.add_argument("--rounds", type=int, default=3, help="Number of refresh rounds")
    args = parser.parse_args()

    settings = Settings.from_env()
    db = Database(settings.database_path)
    await db.connect()
    await db.init_schema()

    crypto = CryptoService(settings.encryption_key)
    xui = XUIClient(timeout_seconds=settings.request_timeout_seconds)
    panel_service = PanelService(
        db=db,
        crypto=crypto,
        xui=xui,
        sub_url_strip_port_rules=settings.sub_url_strip_port_rules,
        sub_url_base_overrides=settings.sub_url_base_overrides,
    )
    admin_panel_service = AdminPanelService(db=db, panel_service=panel_service)
    access_service = AccessService(db=db)
    financial_service = FinancialService(db=db, access_service=access_service)
    usage_service = UsageService(
        db=db,
        panel_service=panel_service,
        timezone=settings.timezone,
        root_admin_ids=settings.admin_ids,
        depleted_delete_after_hours=settings.depleted_client_delete_after_hours,
    )
    _ = AdminProvisioningService(
        db=db,
        panel_service=panel_service,
        access_service=access_service,
        financial_service=financial_service,
        usage_service=usage_service,
    )

    durations: list[float] = []
    try:
        for i in range(args.rounds):
            started = time.perf_counter()
            await usage_service.refresh_all_services()
            elapsed = time.perf_counter() - started
            durations.append(elapsed)
            print(f"round {i + 1}: {elapsed:.3f}s")

        print("---")
        print(f"rounds={len(durations)}")
        print(f"min={min(durations):.3f}s")
        print(f"avg={statistics.mean(durations):.3f}s")
        print(f"p50={pct(durations, 0.50):.3f}s")
        print(f"p95={pct(durations, 0.95):.3f}s")
        print(f"max={max(durations):.3f}s")
    finally:
        await xui.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
