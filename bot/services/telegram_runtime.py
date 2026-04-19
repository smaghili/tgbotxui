from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotLaunch:
    bot: Bot
    proxy: str | None
    proxy_index: int


async def create_bot_with_failover(
    settings: Settings,
    *,
    start_index: int = 0,
) -> BotLaunch:
    candidates: list[str | None] = list(settings.telegram_proxies) or [None]
    for offset in range(len(candidates)):
        idx = (start_index + offset) % len(candidates)
        proxy = candidates[idx]
        session = AiohttpSession(proxy=proxy) if proxy else None
        bot = Bot(
            token=settings.bot_token,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await bot.get_me()
            if proxy:
                logger.info("telegram bot connected using proxy", extra={"proxy": proxy, "proxy_index": idx})
            else:
                logger.info("telegram bot connected without proxy")
            return BotLaunch(bot=bot, proxy=proxy, proxy_index=idx)
        except Exception:
            logger.exception("failed to connect telegram bot using candidate", extra={"proxy": proxy, "proxy_index": idx})
            await bot.session.close()
    raise RuntimeError("failed to connect to Telegram with configured proxy candidates.")
