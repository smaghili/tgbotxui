from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.notification_kinds import (
    NOTIFICATION_KIND_LABEL_KEY,
    ORDERED_NOTIFICATION_KINDS,
    ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS,
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
    lang: str | None,
    is_root: bool,
    personal_disabled: set[str],
    root_defaults_disabled: set[str],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, kind in enumerate(visible_kinds):
        label_key = NOTIFICATION_KIND_LABEL_KEY.get(kind, kind)
        label = t(label_key, lang)
        off = (
            kind in root_defaults_disabled
            if is_root and kind in ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS
            else kind in personal_disabled
        )
        prefix = "⬜ " if off else "✅ "
        rows.append(
            [InlineKeyboardButton(text=_trim_btn(f"{prefix}{label}"), callback_data=f"nt:t:{idx}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _merged_visible_notification_kinds(*, is_root: bool, base_visible: tuple[str, ...]) -> tuple[str, ...]:
    if not is_root:
        return base_visible
    return (*base_visible, *ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS)


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
    is_root, _, base_visible = await _notification_actor_context(
        telegram_user_id=message.from_user.id,
        settings=settings,
        services=services,
    )
    visible = _merged_visible_notification_kinds(is_root=is_root, base_visible=base_visible)
    root_defaults_disabled: set[str] = set()
    if is_root:
        root_defaults_disabled = await services.db.get_root_default_enduser_service_alert_disabled_kinds()
        body = f"{t('notif_menu_title', lang)}\n\n{t('notif_root_enduser_service_defaults_hint', lang)}"
    else:
        body = t("notif_menu_title", lang)
    if len(base_visible) < len(ORDERED_NOTIFICATION_KINDS):
        body = f"{body}\n\n{t('notif_menu_role_filtered', lang)}"
    await message.answer(
        body,
        reply_markup=_notification_prefs_keyboard(
            visible_kinds=visible,
            lang=lang,
            is_root=is_root,
            personal_disabled=disabled,
            root_defaults_disabled=root_defaults_disabled,
        ),
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
    is_root, _, base_visible = await _notification_actor_context(
        telegram_user_id=callback.from_user.id,
        settings=settings,
        services=services,
    )
    visible = _merged_visible_notification_kinds(is_root=is_root, base_visible=base_visible)
    if idx < 0 or idx >= len(visible):
        await callback.answer(t("notif_toggle_denied", lang), show_alert=True)
        return
    kind = visible[idx]
    personal_disabled = await services.db.get_user_notification_disabled_kinds(callback.from_user.id)
    root_defaults_disabled = await services.db.get_root_default_enduser_service_alert_disabled_kinds()
    if is_root and kind in ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS:
        if kind in root_defaults_disabled:
            root_defaults_disabled.discard(kind)
        else:
            root_defaults_disabled.add(kind)
        await services.db.set_root_default_enduser_service_alert_disabled_kinds(root_defaults_disabled)
    else:
        if kind in personal_disabled:
            personal_disabled.discard(kind)
        else:
            personal_disabled.add(kind)
        await services.db.set_user_notification_disabled_kinds(callback.from_user.id, personal_disabled)
    await callback.message.edit_reply_markup(
        reply_markup=_notification_prefs_keyboard(
            visible_kinds=visible,
            lang=lang,
            is_root=is_root,
            personal_disabled=personal_disabled,
            root_defaults_disabled=root_defaults_disabled,
        ),
    )
    await callback.answer(t("notif_saved", lang))
