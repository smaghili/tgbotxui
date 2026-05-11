from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import main_keyboard
from bot.services.container import ServiceContainer
from bot.states import AddPanelStates, AdminSettingsStates, InboundsListStates

from .admin_shared import (
    answer_with_admin_menu,
    answer_with_cancel,
    inbounds_panel_select_keyboard,
    panel_delete_confirm_keyboard,
    panels_glass_keyboard,
    panels_list_text,
    refresh_panels_message,
    reject_if_not_any_admin,
    show_inbounds_for_panel,
    show_inbounds_overview_for_panel,
    two_factor_keyboard,
)

router = Router(name="admin_panels")


def _chunk_text_by_lines(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    lines = text.split("\n")
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for line in lines:
        if len(line) > max_len:
            if buf:
                chunks.append("\n".join(buf))
                buf = []
                cur = 0
            for j in range(0, len(line), max_len):
                chunks.append(line[j : j + max_len])
            continue
        add = len(line) + (1 if buf else 0)
        if cur + add > max_len and buf:
            chunks.append("\n".join(buf))
            buf = [line]
            cur = len(line)
        else:
            buf.append(line)
            cur += add
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def _panel_access_admins_keyboard(panel_id: int, admins: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for admin in admins:
        user_id = int(admin["telegram_user_id"])
        title = str(admin.get("title") or admin.get("full_name") or admin.get("username") or user_id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=title[:42],
                    callback_data=f"panel_access_grant:{panel_id}:{user_id}",
                )
            ]
        )
    if not rows:
        rows.append([InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _reject_if_not_full_admin(message: Message, settings: Settings, services: ServiceContainer) -> bool:
    if await services.access_service.can_manage_panels(user_id=message.from_user.id, settings=settings):
        return False
    await message.answer(t("no_admin_access", None))
    return True


async def _reject_callback_if_not_full_admin(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> bool:
    if await services.access_service.can_manage_panels(user_id=callback.from_user.id, settings=settings):
        return False
    await callback.answer(t("no_admin_access", None), show_alert=True)
    return True


async def _reject_callback_if_not_root_admin(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> bool:
    if services.access_service.is_root_admin(callback.from_user.id, settings):
        return False
    await callback.answer(t("no_admin_access", None), show_alert=True)
    return True


@router.message(F.text.in_(button_variants("btn_manage")))
async def handle_management(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    await answer_with_admin_menu(message, t("menu_management", None), settings=settings, services=services)


@router.message(F.text.in_(button_variants("btn_back")))
async def handle_back(message: Message, settings: Settings, services: ServiceContainer) -> None:
    await message.answer(
        t("menu_main", None),
        reply_markup=main_keyboard(await services.access_service.is_any_admin(message.from_user.id, settings)),
    )


@router.message(F.text.in_(button_variants("btn_cleanup_settings")))
async def start_cleanup_settings(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    current = await services.db.get_app_setting(
        "depleted_client_delete_after_hours",
        str(settings.depleted_client_delete_after_hours),
    )
    await state.set_state(AdminSettingsStates.waiting_depleted_cleanup_hours)
    await answer_with_cancel(message, t("admin_cleanup_hours_prompt", None, hours=current))


@router.message(AdminSettingsStates.waiting_depleted_cleanup_hours)
async def save_cleanup_hours(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    try:
        hours = int((message.text or "").strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("admin_invalid_positive_number", None))
        return
    await services.db.set_app_setting("depleted_client_delete_after_hours", str(hours))
    await state.clear()
    await answer_with_admin_menu(
        message,
        t("admin_cleanup_hours_saved", None, hours=hours),
        settings=settings,
        services=services,
    )


@router.message(F.text.in_(button_variants("btn_add_panel")))
async def start_add_panel(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    await state.set_state(AddPanelStates.waiting_name)
    await answer_with_cancel(message, t("panel_add_enter_name", None))


@router.message(AddPanelStates.waiting_name)
async def add_panel_get_name(message: Message, state: FSMContext) -> None:
    panel_name = (message.text or "").strip()
    if not panel_name:
        await message.answer(t("panel_add_name_empty", None))
        return
    await state.update_data(panel_name=panel_name)
    await state.set_state(AddPanelStates.waiting_login_url)
    await answer_with_cancel(message, t("panel_add_enter_login", None))


@router.message(AddPanelStates.waiting_login_url)
async def add_panel_get_url(message: Message, state: FSMContext) -> None:
    await state.update_data(login_url=(message.text or "").strip())
    await state.set_state(AddPanelStates.waiting_username)
    await answer_with_cancel(message, t("panel_add_enter_user", None))


@router.message(AddPanelStates.waiting_username)
async def add_panel_get_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=(message.text or "").strip())
    await state.set_state(AddPanelStates.waiting_password)
    await answer_with_cancel(message, t("panel_add_enter_pass", None))


@router.message(AddPanelStates.waiting_password)
async def add_panel_get_password(message: Message, state: FSMContext) -> None:
    await state.update_data(password=(message.text or "").strip())
    await state.set_state(AddPanelStates.waiting_two_factor_choice)
    await message.answer(t("panel_add_twofa_q", None), reply_markup=two_factor_keyboard())


async def _finalize_add_panel(
    *,
    origin_message: Message,
    actor_user_id: int,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
    two_factor: str | None,
) -> None:
    payload = await state.get_data()
    await state.clear()
    await origin_message.answer(t("panel_add_testing", None))
    result = await services.admin_panel_service.add_panel(
        actor_user_id=actor_user_id,
        name=payload["panel_name"],
        login_url=payload["login_url"],
        username=payload["username"],
        password=payload["password"],
        two_factor_code=two_factor,
    )
    if result.status == "invalid_credentials":
        await answer_with_admin_menu(origin_message, t("panel_add_invalid_credentials", None), settings=settings, services=services)
        return
    if result.status == "rate_limited":
        await answer_with_admin_menu(origin_message, t("panel_add_rate_limit", None), settings=settings, services=services)
        return
    if result.status == "validation_error":
        await answer_with_admin_menu(
            origin_message,
            t("panel_add_validation", None, error=result.error),
            settings=settings,
            services=services,
        )
        return
    if result.status == "xui_error":
        await answer_with_admin_menu(
            origin_message,
            t("panel_add_xui_error", None, error=result.error),
            settings=settings,
            services=services,
        )
        return
    if result.status == "unexpected_error":
        await answer_with_admin_menu(
            origin_message,
            t("panel_add_unexpected", None, error=result.error),
            settings=settings,
            services=services,
        )
        return
    await answer_with_admin_menu(origin_message, t("panel_add_ok", None), settings=settings, services=services)


@router.callback_query(AddPanelStates.waiting_two_factor_choice, F.data == "twofa_no")
async def add_panel_two_factor_no(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _finalize_add_panel(
        origin_message=callback.message,
        actor_user_id=callback.from_user.id,
        state=state,
        settings=settings,
        services=services,
        two_factor=None,
    )


@router.callback_query(AddPanelStates.waiting_two_factor_choice, F.data == "twofa_yes")
async def add_panel_two_factor_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AddPanelStates.waiting_two_factor_code)
    if callback.message is not None:
        await answer_with_cancel(callback.message, t("panel_add_enter_twofa", None))


@router.message(AddPanelStates.waiting_two_factor_code)
async def add_panel_get_two_factor_code(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.answer(t("panel_add_twofa_empty", None))
        return
    await _finalize_add_panel(
        origin_message=message,
        actor_user_id=message.from_user.id,
        state=state,
        settings=settings,
        services=services,
        two_factor=code,
    )


@router.message(F.text.in_(button_variants("btn_list_panels")))
async def list_panels(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    panels = await services.access_service.list_accessible_panels(
        user_id=message.from_user.id,
        settings=settings,
    )
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await message.answer(panels_list_text(), reply_markup=panels_glass_keyboard(panels, lang))


@router.callback_query(F.data.startswith("panel_outbounds_list:"))
async def panel_outbounds_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if not panel:
        await callback.answer(t("admin_panel_not_found", lang), show_alert=True)
        return
    try:
        tags = await services.panel_service.list_outbound_tags(panel_id)
    except Exception as exc:
        await callback.message.answer(t("panel_outbounds_fetch_error", lang, error=exc))
        await callback.answer()
        return
    if not tags:
        await callback.message.answer(
            t("panel_outbounds_header", lang, name=panel["name"], count=0)
            + "\n"
            + t("panel_outbounds_empty", lang),
        )
        await callback.answer()
        return
    body_lines = [f"{i}. {tag}" for i, tag in enumerate(tags, start=1)]
    text = t("panel_outbounds_header", lang, name=panel["name"], count=len(tags)) + "\n".join(body_lines)
    for part in _chunk_text_by_lines(text):
        await callback.message.answer(part)
    await callback.answer()


@router.callback_query(F.data.startswith("panel_default_toggle:"))
async def panel_default_toggle(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_root_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", None), show_alert=True)
        return
    changed, now_default = await services.admin_panel_service.toggle_default_panel(
        actor_user_id=callback.from_user.id,
        panel_id=panel_id,
    )
    if not changed:
        await callback.answer(t("admin_panel_not_found", None), show_alert=True)
        return
    await refresh_panels_message(callback, services, settings)
    await callback.answer(t("panel_default_set", None) if now_default else t("panel_default_unset", None))


@router.callback_query(F.data.startswith("panel_access_ask:"))
async def panel_access_ask(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.answer(t("admin_panel_not_found", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    admins = await services.db.list_delegated_admins(
        manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
    )
    await callback.message.edit_text(
        t("panel_access_select_admin", lang, name=panel["name"]),
        reply_markup=_panel_access_admins_keyboard(panel_id, admins, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_access_grant:"))
async def panel_access_grant(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, panel_raw, user_raw = callback.data.split(":", 2)
        panel_id = int(panel_raw)
        target_user_id = int(user_raw)
    except (ValueError, IndexError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    try:
        await services.admin_provisioning_service.grant_delegated_admin_panel_access(
            actor_user_id=callback.from_user.id,
            telegram_user_id=target_user_id,
            panel_id=panel_id,
        )
    except ValueError:
        await callback.answer(t("admin_delegated_not_found", lang), show_alert=True)
        return
    await refresh_panels_message(callback, services, settings)
    await callback.answer(t("panel_access_granted", lang))


@router.callback_query(F.data.startswith("panel_delete_ask:"))
async def panel_delete_ask(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", None), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if not panel:
        await callback.answer(t("panel_already_deleted", None), show_alert=True)
        return
    if not await services.access_service.can_delete_panel(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    ok = "✅" if panel["last_login_ok"] else "❌"
    star = "⭐ " if panel.get("is_default") else ""
    await callback.message.edit_text(
        t("panel_delete_confirm", None, name=f"{star}{panel['name']}", status=ok),
        reply_markup=panel_delete_confirm_keyboard(panel_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_delete_yes:"))
async def panel_delete_yes(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", None), show_alert=True)
        return
    if not await services.access_service.can_delete_panel(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    deleted = await services.admin_panel_service.delete_panel(actor_user_id=callback.from_user.id, panel_id=panel_id)
    if deleted:
        await refresh_panels_message(callback, services, settings)
        await callback.answer(t("panel_deleted", None))
    else:
        await callback.answer(t("panel_already_deleted", None), show_alert=True)


@router.callback_query(F.data == "panel_delete_no")
async def panel_delete_no(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    await refresh_panels_message(callback, services, settings)
    await callback.answer()


@router.message(F.text.in_(button_variants("btn_list_inbounds")))
async def start_inbounds_list(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        panel_id = None
    if panel_id is not None:
        await show_inbounds_for_panel(message, services, settings, panel_id)
        return
    panels = await services.panel_service.list_panels()
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    await state.set_state(InboundsListStates.waiting_panel_select)
    await message.answer(
        t("inbounds_select_panel", None),
        reply_markup=inbounds_panel_select_keyboard(panels),
    )


@router.message(F.text.in_(button_variants("btn_inbounds_overview")))
async def start_inbounds_overview(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        panel_id = None
    if panel_id is not None:
        await show_inbounds_overview_for_panel(message, services, settings, panel_id)
        return
    panels = await services.panel_service.list_panels()
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    await state.set_state(InboundsListStates.waiting_overview_panel_select)
    await message.answer(
        t("inbounds_select_panel", None),
        reply_markup=inbounds_panel_select_keyboard(panels),
    )


@router.callback_query(InboundsListStates.waiting_panel_select, F.data.startswith("inbounds_panel_pick:"))
async def inbounds_pick_panel(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        requested_panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", None), show_alert=True)
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(requested_panel_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await show_inbounds_for_panel(callback.message, services, settings, panel_id)


@router.callback_query(InboundsListStates.waiting_overview_panel_select, F.data.startswith("inbounds_panel_pick:"))
async def inbounds_overview_pick_panel(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        requested_panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", None), show_alert=True)
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(requested_panel_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await show_inbounds_overview_for_panel(callback.message, services, settings, panel_id)


@router.message(InboundsListStates.waiting_panel_select)
async def inbounds_waiting_panel_select_hint(message: Message) -> None:
    await message.answer(t("bind_choose_panel_inline", None))
