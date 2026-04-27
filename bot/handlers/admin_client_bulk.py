from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.states import ClientManageStates
from .admin_client_helpers import (
    bulk_clients_for_panel,
    delegated_profile_error_text,
    open_bulk_panel_menu,
    visible_bulk_panels,
)
from .admin_shared import (
    action_panel_select_keyboard,
    answer_with_admin_menu,
    answer_with_cancel,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
)

router = Router(name="admin_client_bulk")


@router.message(F.text.in_(button_variants("btn_bulk_operations")))
async def start_bulk_operations(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        panel_id = None
    if panel_id is not None:
        await open_bulk_panel_menu(
            message,
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        return
    panels = await visible_bulk_panels(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
    )
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    await message.answer(
        t("admin_bulk_pick_panel", None),
        reply_markup=action_panel_select_keyboard(panels, "bulk_panel_pick"),
    )


@router.callback_query(F.data.startswith("bulk_panel_pick:"))
async def bulk_panel_pick(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw = callback.data.split(":", 1)
        panel_id = int(panel_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await open_bulk_panel_menu(
        callback,
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )


@router.callback_query(F.data.startswith("pabt:"))
async def users_bulk_add_traffic_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw = callback.data.split(":", 1)
        panel_id = int(panel_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await state.update_data(bulk_panel_id=panel_id)
    await state.set_state(ClientManageStates.waiting_bulk_add_traffic_gb)
    await callback.message.edit_reply_markup(reply_markup=None)
    await answer_with_cancel(callback.message, t("admin_bulk_enter_traffic", None))
    await callback.answer()


@router.callback_query(F.data.startswith("pabd:"))
async def users_bulk_add_days_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw = callback.data.split(":", 1)
        panel_id = int(panel_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await state.update_data(bulk_panel_id=panel_id)
    await state.set_state(ClientManageStates.waiting_bulk_add_expiry_days)
    await callback.message.edit_reply_markup(reply_markup=None)
    await answer_with_cancel(callback.message, t("admin_bulk_enter_days", None))
    await callback.answer()


@router.message(ClientManageStates.waiting_bulk_add_traffic_gb)
async def bulk_add_traffic_gb(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    raw = (message.text or "").strip()
    try:
        gb = int(raw)
        if gb <= 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("admin_invalid_positive_number", None))
        return
    data = await state.get_data()
    await state.clear()
    panel_id = int(data["bulk_panel_id"])
    clients = await bulk_clients_for_panel(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    if not clients:
        await answer_with_admin_menu(message, t("admin_bulk_empty", None), settings=settings, services=services)
        return
    await answer_with_cancel(message, t("admin_bulk_started", None))
    success = 0
    failed = 0
    for client in clients:
        try:
            await services.admin_provisioning_service.add_client_total_gb_for_actor(
                actor_user_id=message.from_user.id,
                settings=settings,
                panel_id=panel_id,
                inbound_id=int(client["inbound_id"]),
                client_uuid=str(client["uuid"]),
                add_gb=gb,
            )
            success += 1
        except Exception as exc:
            delegated_error = delegated_profile_error_text(exc, None)
            if delegated_error is not None:
                failed += 1
                continue
            if "insufficient" in str(exc).lower():
                failed += 1
                continue
            failed += 1
    await answer_with_admin_menu(
        message,
        t("admin_bulk_done", None, success=success, failed=failed),
        settings=settings,
        services=services,
    )


@router.message(ClientManageStates.waiting_bulk_add_expiry_days)
async def bulk_add_expiry_days(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    raw = (message.text or "").strip()
    try:
        days = int(raw)
        if days <= 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("admin_invalid_positive_number", None))
        return
    data = await state.get_data()
    await state.clear()
    panel_id = int(data["bulk_panel_id"])
    clients = await bulk_clients_for_panel(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    if not clients:
        await answer_with_admin_menu(message, t("admin_bulk_empty", None), settings=settings, services=services)
        return
    await answer_with_cancel(message, t("admin_bulk_started", None))
    success = 0
    failed = 0
    for client in clients:
        try:
            await services.admin_provisioning_service.extend_client_expiry_days_for_actor(
                actor_user_id=message.from_user.id,
                settings=settings,
                panel_id=panel_id,
                inbound_id=int(client["inbound_id"]),
                client_uuid=str(client["uuid"]),
                add_days=days,
            )
            success += 1
        except Exception as exc:
            delegated_error = delegated_profile_error_text(exc, None)
            if delegated_error is not None:
                failed += 1
                continue
            if "insufficient" in str(exc).lower():
                failed += 1
                continue
            failed += 1
    await answer_with_admin_menu(
        message,
        t("admin_bulk_done", None, success=success, failed=failed),
        settings=settings,
        services=services,
    )
