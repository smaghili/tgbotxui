from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.i18n import set_current_lang
from bot.services.container import ServiceContainer


class LanguageContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        services = data.get("services")
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user is not None:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user is not None:
            user_id = event.from_user.id

        if isinstance(services, ServiceContainer) and user_id is not None:
            lang = await services.db.get_user_language(user_id)
            set_current_lang(lang)
        else:
            set_current_lang("fa")
        return await handler(event, data)
