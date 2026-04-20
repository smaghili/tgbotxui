from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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
    panels = await services.panel_service.list_panels()
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    await message.answer(panels_list_text(), reply_markup=panels_glass_keyboard(panels))


@router.callback_query(F.data.startswith("panel_default_toggle:"))
async def panel_default_toggle(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
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
    await refresh_panels_message(callback, services)
    await callback.answer(t("panel_default_set", None) if now_default else t("panel_default_unset", None))


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
    deleted = await services.admin_panel_service.delete_panel(actor_user_id=callback.from_user.id, panel_id=panel_id)
    if deleted:
        await refresh_panels_message(callback, services)
        await callback.answer(t("panel_deleted", None))
    else:
        await callback.answer(t("panel_already_deleted", None), show_alert=True)


@router.callback_query(F.data == "panel_delete_no")
async def panel_delete_no(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    await refresh_panels_message(callback, services)
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
