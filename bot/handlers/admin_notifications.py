from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.notification_kinds import (
    NOTIFICATION_KIND_LABEL_KEY,
    ORDERED_NOTIFICATION_KINDS,
    ROOT_DEFAULT_ENDUSER_SERVICE_ALERT_KINDS,
    visible_notification_kinds,
)
from bot.services.container import ServiceContainer

from .admin_shared import reject_if_not_any_admin, reject_callback_if_not_any_admin

router = Router(name="admin_notifications")


def _trim_btn(text: str, max_len: int = 58) -> str:
    return text if len(text) <= max_len else text[: max_len - 2] + "…"


def _notification_prefs_keyboard(
    *,
    visible_kinds: tuple[str, ...],
    disabled: set[str],
    lang: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, kind in enumerate(visible_kinds):
        label_key = NOTIFICATION_KIND_LABEL_KEY.get(kind, kind)
        label = t(label_key, lang)
        prefix = "⬜ " if kind in disabled else "✅ "
        rows.append(
            [InlineKeyboardButton(text=_trim_btn(f"{prefix}{label}"), callback_data=f"nt:t:{idx}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _root_enduser_service_alerts_keyboard(*, disabled: set[str], lang: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, kind in enumerate(ROOT_DEFAULT_ENDUSER_SERVICE_ALERT_KINDS):
        label_key = NOTIFICATION_KIND_LABEL_KEY.get(kind, kind)
        label = t(label_key, lang)
        prefix = "⬜ " if kind in disabled else "✅ "
        rows.append(
            [InlineKeyboardButton(text=_trim_btn(f"{prefix}{label}"), callback_data=f"nt:ru:{idx}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _notification_actor_context(
    *,
    telegram_user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> tuple[bool, bool, tuple[str, ...]]:
    ctx = await services.access_service.get_admin_context(telegram_user_id, settings)
    visible = visible_notification_kinds(
        is_root_admin=ctx.is_root_admin,
        is_delegated_admin=ctx.is_delegated_admin,
    )
    return ctx.is_root_admin, ctx.is_delegated_admin, visible


@router.message(F.text.in_(button_variants("btn_bot_notifications")))
async def open_bot_notification_settings(
    message: Message, settings: Settings, services: ServiceContainer
) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    disabled = await services.db.get_user_notification_disabled_kinds(message.from_user.id)
    is_root, _, visible = await _notification_actor_context(
        telegram_user_id=message.from_user.id,
        settings=settings,
        services=services,
    )
    body = t("notif_menu_title", lang)
    if len(visible) < len(ORDERED_NOTIFICATION_KINDS):
        body = f"{body}\n\n{t('notif_menu_role_filtered', lang)}"
    await message.answer(
        body,
        reply_markup=_notification_prefs_keyboard(visible_kinds=visible, disabled=disabled, lang=lang),
    )
    if is_root:
        root_disabled = await services.db.get_root_default_enduser_service_alert_disabled_kinds()
        await message.answer(
            f"{t('notif_root_enduser_service_defaults_title', lang)}\n\n{t('notif_root_enduser_service_defaults_hint', lang)}",
            reply_markup=_root_enduser_service_alerts_keyboard(disabled=root_disabled, lang=lang),
        )


@router.callback_query(F.data.startswith("nt:t:"))
async def toggle_bot_notification_kind(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None or callback.from_user is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        idx = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    _, _, visible = await _notification_actor_context(
        telegram_user_id=callback.from_user.id,
        settings=settings,
        services=services,
    )
    if idx < 0 or idx >= len(visible):
        await callback.answer(t("notif_toggle_denied", lang), show_alert=True)
        return
    kind = visible[idx]
    disabled = await services.db.get_user_notification_disabled_kinds(callback.from_user.id)
    if kind in disabled:
        disabled.discard(kind)
    else:
        disabled.add(kind)
    await services.db.set_user_notification_disabled_kinds(callback.from_user.id, disabled)
    await callback.message.edit_reply_markup(
        reply_markup=_notification_prefs_keyboard(visible_kinds=visible, disabled=disabled, lang=lang),
    )
    await callback.answer(t("notif_saved", lang))


@router.callback_query(F.data.startswith("nt:ru:"))
async def toggle_root_enduser_service_alert_default(
    callback: CallbackQuery, settings: Settings, services: ServiceContainer
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None or callback.from_user is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    ctx = await services.access_service.get_admin_context(callback.from_user.id, settings)
    if not ctx.is_root_admin:
        await callback.answer(t("notif_toggle_denied", lang), show_alert=True)
        return
    try:
        idx = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if idx < 0 or idx >= len(ROOT_DEFAULT_ENDUSER_SERVICE_ALERT_KINDS):
        await callback.answer(t("notif_toggle_denied", lang), show_alert=True)
        return
    kind = ROOT_DEFAULT_ENDUSER_SERVICE_ALERT_KINDS[idx]
    disabled = await services.db.get_root_default_enduser_service_alert_disabled_kinds()
    if kind in disabled:
        disabled.discard(kind)
    else:
        disabled.add(kind)
    await services.db.set_root_default_enduser_service_alert_disabled_kinds(disabled)
    await callback.message.edit_reply_markup(
        reply_markup=_root_enduser_service_alerts_keyboard(disabled=disabled, lang=lang),
    )
    await callback.answer(t("notif_saved", lang))
