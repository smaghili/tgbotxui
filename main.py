from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.db import Database
from bot.handlers import admin, common
from bot.middlewares.language_context import LanguageContextMiddleware
from bot.metrics import create_metrics_app
from bot.middlewares.rate_limit import AdminRateLimitMiddleware
from bot.observability import configure_logging
from bot.services.admin_panel_service import AdminPanelService
from bot.services.container import ServiceContainer
from bot.services.crypto import CryptoService
from bot.services.panel_service import PanelService
from bot.services.usage_service import UsageService
from bot.services.xui_client import XUIClient

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    db = Database(settings.database_path)
    await db.connect()
    await db.init_schema()

    crypto = CryptoService(settings.encryption_key)
    xui = XUIClient(timeout_seconds=settings.request_timeout_seconds)
    panel_service = PanelService(db=db, crypto=crypto, xui=xui)
    admin_panel_service = AdminPanelService(db=db, panel_service=panel_service)
    usage_service = UsageService(db=db, panel_service=panel_service, timezone=settings.timezone)
    services = ServiceContainer(
        db=db,
        panel_service=panel_service,
        admin_panel_service=admin_panel_service,
        usage_service=usage_service,
    )

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(LanguageContextMiddleware())
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
    try:
        await dp.start_polling(bot, settings=settings, services=services)
    finally:
        if metrics_runner is not None:
            with suppress(Exception):
                await metrics_runner.cleanup()
        with suppress(Exception):
            scheduler.shutdown(wait=False)
        with suppress(Exception):
            await bot.session.close()
        with suppress(Exception):
            await db.close()


if __name__ == "__main__":
    settings = Settings.from_env()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    asyncio.run(run(settings))
