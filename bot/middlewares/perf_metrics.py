from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.metrics import HANDLER_LATENCY_SECONDS


class PerformanceMetricsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        kind = "other"
        name = "unknown"
        if isinstance(event, Message):
            kind = "message"
            name = (event.text or event.caption or "unknown").strip().split()[0][:64] or "unknown"
        elif isinstance(event, CallbackQuery):
            kind = "callback"
            name = (event.data or "unknown").strip().split(":", 1)[0][:64] or "unknown"

        started = time.perf_counter()
        try:
            return await handler(event, data)
        finally:
            HANDLER_LATENCY_SECONDS.labels(kind=kind, name=name).observe(time.perf_counter() - started)
