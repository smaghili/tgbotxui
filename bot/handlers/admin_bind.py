from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import admin_keyboard
from bot.services.container import ServiceContainer
from bot.states import BindServiceStates

from .admin_shared import (
    bind_panel_select_keyboard,
    bind_usage_text,
    parse_bind_command_args,
    reject_callback_if_not_admin,
    reject_if_not_admin,
)

logger = logging.getLogger(__name__)
router = Router(name="admin_bind")

@router.message(F.text.in_(button_variants("btn_bind_service")))
async def start_bind(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_admin(message, settings):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        default_panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        default_panel_id = None
    if default_panel_id is not None:
        default_panel = await services.panel_service.get_panel(default_panel_id)
        if default_panel is None:
            await message.answer(t("bind_invalid_default_panel", lang))
            return
        await state.update_data(panel_id=default_panel_id)
        await state.set_state(BindServiceStates.waiting_telegram_user_id)
        await message.answer(t("bind_default_panel_selected", lang, name=default_panel["name"]))
        return
    panels = await services.panel_service.list_panels()
    if not panels:
        await message.answer(t("bind_no_panel", lang), reply_markup=admin_keyboard(lang))
        return
    await state.set_state(BindServiceStates.waiting_panel_select)
    await message.answer(t("bind_select_panel", lang), reply_markup=bind_panel_select_keyboard(panels))


@router.callback_query(BindServiceStates.waiting_panel_select, F.data.startswith("bind_panel_pick:"))
async def bind_pick_panel(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        requested_panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(requested_panel_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.answer(t("bind_panel_not_found", lang), show_alert=True)
        return
    await state.update_data(panel_id=panel_id)
    await state.set_state(BindServiceStates.waiting_telegram_user_id)
    await callback.message.edit_text(t("bind_panel_selected", lang, name=panel["name"]))
    await callback.answer()


@router.message(BindServiceStates.waiting_panel_select)
async def bind_waiting_panel_select_hint(message: Message, services: ServiceContainer) -> None:
    lang = await services.db.get_user_language(message.from_user.id)
    await message.answer(t("bind_choose_panel_inline", lang))


@router.message(BindServiceStates.waiting_telegram_user_id)
async def bind_get_user_id(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(t("bind_tg_id_number", lang))
        return
    await state.update_data(telegram_user_id=user_id)
    await state.set_state(BindServiceStates.waiting_client_email)
    await message.answer(t("bind_enter_config_id", lang))


@router.message(BindServiceStates.waiting_client_email)
async def bind_get_email(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    lang = await services.db.get_user_language(message.from_user.id)
    value = (message.text or "").strip()
    if not value:
        await message.answer(t("bind_config_id_empty", lang))
        return
    await state.update_data(client_email=value)
    await state.set_state(BindServiceStates.waiting_service_name)
    await message.answer(t("bind_enter_service_name", lang))


@router.message(BindServiceStates.waiting_service_name)
async def bind_finalize(message: Message, state: FSMContext, services: ServiceContainer) -> None:
    lang = await services.db.get_user_language(message.from_user.id)
    data = await state.get_data()
    await state.clear()
    service_name = (message.text or "").strip()
    if service_name in {"", "-"}:
        service_name = None
    await message.answer(t("bind_checking_service", lang))
    try:
        usage = await services.panel_service.bind_service_to_user(
            panel_id=data["panel_id"],
            telegram_user_id=data["telegram_user_id"],
            client_email=data["client_email"],
            service_name=service_name,
        )
    except Exception as exc:
        logger.exception("bind service failed")
        await message.answer(f"{t('bind_failed', lang)}:\n{exc}", reply_markup=admin_keyboard(lang))
        return
    await message.answer(
        t("bind_success", lang, service=usage["service_name"], status=usage["status"]),
        reply_markup=admin_keyboard(lang),
    )


@router.message(F.text.in_(button_variants("btn_sync_usage")))
@router.message(Command("sync_all"))
async def sync_all(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_admin(message, settings):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await message.answer(t("sync_start", lang))
    await services.usage_service.refresh_all_services()
    await message.answer(t("sync_done", lang), reply_markup=admin_keyboard(lang))


@router.message(Command("bind"))
async def bind_by_command(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_admin(message, settings):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    args = (message.text or "").strip().split()[1:]
    try:
        explicit_panel_id, telegram_user_id, client_email, service_name = parse_bind_command_args(args)
    except ValueError as exc:
        key = str(exc)
        if key == "usage":
            await message.answer(bind_usage_text())
            return
        if key == "ids_must_be_int":
            await message.answer(t("bind_ids_numeric", lang) + bind_usage_text())
            return
        if key == "client_email_empty":
            await message.answer("client_email cannot be empty.")
            return
        await message.answer(bind_usage_text())
        return

    try:
        panel_id = await services.panel_service.resolve_panel_id(explicit_panel_id)
    except ValueError as exc:
        await message.answer(f"{exc}\n{t('bind_need_default_panel', lang)}")
        return
    try:
        usage = await services.panel_service.bind_service_to_user(
            panel_id=panel_id,
            telegram_user_id=telegram_user_id,
            client_email=client_email,
            service_name=service_name,
        )
    except Exception as exc:
        await message.answer(f"Error in bind:\n{exc}", reply_markup=admin_keyboard(lang))
        return
    await message.answer(
        f"Bind success:\nService: {usage['service_name']}\nStatus: {usage['status']}",
        reply_markup=admin_keyboard(lang),
    )
