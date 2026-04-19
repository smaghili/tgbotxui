from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.config import Settings
from bot.i18n import button_variants, get_current_lang


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[int, Deque[float]] = defaultdict(deque)

    def allow(self, user_id: int, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        bucket = self._buckets[user_id]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


class AdminRateLimitMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, limiter: SlidingWindowLimiter | None = None) -> None:
        self.settings = settings
        self.limiter = limiter or SlidingWindowLimiter()
        self.admin_prefixes = {
            *button_variants("btn_manage"),
            *button_variants("btn_add_panel"),
            *button_variants("btn_list_panels"),
            *button_variants("btn_online_users"),
            *button_variants("btn_search_user"),
            *button_variants("btn_disabled_users"),
            *button_variants("btn_last_online_users"),
            *button_variants("btn_create_user"),
            *button_variants("btn_edit_config"),
            *button_variants("btn_manage_admins"),
            "/bind",
            "/sync_all",
        }

    def _is_admin_action(self, text: str) -> bool:
        value = (text or "").strip()
        return any(value.startswith(p) for p in self.admin_prefixes)

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        user_id = event.from_user.id
        if user_id not in self.settings.admin_ids:
            return await handler(event, data)

        if not self._is_admin_action(event.text or ""):
            return await handler(event, data)

        if not self.limiter.allow(
            user_id,
            limit=self.settings.admin_rate_limit_count,
            window_seconds=self.settings.admin_rate_limit_window_seconds,
        ):
            lang = get_current_lang()
            await event.answer(
                "Too many admin requests. Please try again later."
                if lang == "fa"
                else "Too many admin requests. Please try again later."
            )
            return None
        return await handler(event, data)

