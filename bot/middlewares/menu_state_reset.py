from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from bot.i18n import button_variants


class MenuStateResetMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.menu_buttons = {
            *button_variants("btn_status"),
            *button_variants("btn_change_language"),
            *button_variants("btn_manage_finance"),
            *button_variants("btn_manage"),
            *button_variants("btn_back"),
            *button_variants("btn_add_panel"),
            *button_variants("btn_list_panels"),
            *button_variants("btn_list_inbounds"),
            *button_variants("btn_list_users"),
            *button_variants("btn_online_users"),
            *button_variants("btn_last_online_users"),
            *button_variants("btn_search_user"),
            *button_variants("btn_disabled_users"),
            *button_variants("btn_create_user"),
            *button_variants("btn_change_inbound_location"),
            *button_variants("btn_edit_config"),
            *button_variants("btn_inbounds_overview"),
            *button_variants("btn_low_traffic_users"),
            *button_variants("btn_bulk_operations"),
            *button_variants("btn_manage_admins"),
            *button_variants("btn_cleanup_settings"),
            *button_variants("btn_bot_notifications"),
            *button_variants("btn_bind_service"),
            *button_variants("btn_sync_usage"),
            *button_variants("finance_view_credit"),
            *button_variants("finance_delegates_list"),
            *button_variants("finance_today_sales"),
            *button_variants("finance_today_reports"),
            *button_variants("admin_delegated_details"),
            *button_variants("btn_cancel"),
            *button_variants("btn_cancel_operation"),
        }

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        text = getattr(event, "text", None)
        if isinstance(text, str) and text.strip() in self.menu_buttons:
            state = data.get("state")
            if state is not None and hasattr(state, "clear"):
                await state.clear()
        return await handler(event, data)
