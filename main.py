from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Dispatcher
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.db import Database
from bot.handlers import admin, common
from bot.middlewares.language_context import LanguageContextMiddleware
from bot.middlewares.menu_state_reset import MenuStateResetMiddleware
from bot.metrics import create_metrics_app
from bot.middlewares.rate_limit import AdminRateLimitMiddleware
from bot.observability import configure_logging
from bot.services.access_service import AccessService
from bot.services.admin_panel_service import AdminPanelService
from bot.services.admin_provisioning_service import AdminProvisioningService
from bot.services.container import ServiceContainer
from bot.services.crypto import CryptoService
from bot.services.financial_service import FinancialService
from bot.services.panel_service import PanelService
from bot.services.telegram_runtime import create_bot_with_failover
from bot.services.usage_service import UsageService
from bot.services.xui_client import XUIClient

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    db = Database(settings.database_path)
    await db.connect()
    applied_migrations = await db.init_schema()
    if applied_migrations:
        logger.info("database migrations applied", extra={"count": applied_migrations})

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
    financial_service = FinancialService(
        db=db,
        access_service=access_service,
    )
    admin_provisioning_service = AdminProvisioningService(
        db=db,
        panel_service=panel_service,
        access_service=access_service,
        financial_service=financial_service,
    )
    usage_service = UsageService(
        db=db,
        panel_service=panel_service,
        timezone=settings.timezone,
        root_admin_ids=settings.admin_ids,
        depleted_delete_after_hours=settings.depleted_client_delete_after_hours,
    )
    services = ServiceContainer(
        db=db,
        panel_service=panel_service,
        admin_panel_service=admin_panel_service,
        access_service=access_service,
        admin_provisioning_service=admin_provisioning_service,
        financial_service=financial_service,
        usage_service=usage_service,
    )

    dp = Dispatcher()
    dp.message.middleware(LanguageContextMiddleware())
    dp.message.middleware(MenuStateResetMiddleware())
    dp.callback_query.middleware(LanguageContextMiddleware())
    dp.message.middleware(AdminRateLimitMiddleware(settings))
    dp.include_router(common.router)
    dp.include_router(admin.router)

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        usage_service.refresh_all_services,
        trigger="interval",
        seconds=settings.sync_interval_seconds,
        id="usage_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()

    metrics_runner: web.AppRunner | None = None
    if settings.metrics_enabled:
        metrics_app = create_metrics_app()
        metrics_runner = web.AppRunner(metrics_app)
        await metrics_runner.setup()
        site = web.TCPSite(metrics_runner, host=settings.metrics_host, port=settings.metrics_port)
        await site.start()
        logger.info("metrics server started")

    await usage_service.refresh_cardinality_metrics()
    logger.info("bot is running")
    bot = None
    proxy_index = 0
    try:
        while True:
            launch = await create_bot_with_failover(settings, start_index=proxy_index)
            bot = launch.bot
            usage_service.attach_bot(bot)
            proxy_index = (launch.proxy_index + 1) % max(len(settings.telegram_proxies), 1)
            try:
                await dp.start_polling(bot, settings=settings, services=services)
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("polling crashed; retrying with next telegram proxy candidate")
                usage_service.attach_bot(None)
                with suppress(Exception):
                    await bot.session.close()
                bot = None
                await asyncio.sleep(3)
    finally:
        if metrics_runner is not None:
            with suppress(Exception):
                await metrics_runner.cleanup()
        with suppress(Exception):
            scheduler.shutdown(wait=False)
        if bot is not None:
            with suppress(Exception):
                await bot.session.close()
        usage_service.attach_bot(None)
        with suppress(Exception):
            await db.close()


if __name__ == "__main__":
    settings = Settings.from_env()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    asyncio.run(run(settings))
