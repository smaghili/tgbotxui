from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.callbacks import NOOP, parse_inbound_page, parse_online_page
from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.states import ClientManageStates
from .admin_shared import (
    action_panel_select_keyboard,
    ensure_client_access,
    answer_with_admin_menu,
    answer_with_cancel,
    back_to_detail_keyboard,
    callback_error_alert,
    client_actions_keyboard,
    client_confirm_reset_keyboard,
    client_expiry_menu_keyboard,
    client_iplimit_menu_keyboard,
    client_ips_log_keyboard,
    client_traffic_menu_keyboard,
    inbound_display_name,
    online_clients_keyboard,
    online_panel_select_keyboard,
    online_filtered_clients_keyboard,
    parse_client_callback,
    parse_client_callback_with_value,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
    render_client_detail,
    set_client_action_context,
    show_online_clients_for_panel_callback,
    show_online_clients_for_panel_message,
    show_users_inbounds_for_panel_callback,
    show_users_inbounds_for_panel_message,
    single_button_inline_keyboard,
    panel_bulk_actions_keyboard,
    normalize_tg_id,
    users_clients_keyboard,
    users_panel_select_keyboard,
)

router = Router(name="admin_clients")


def _delegated_profile_error_text(exc: Exception, lang: str | None) -> str | None:
    text = str(exc).lower()
    mapping = [
        ("max clients reached", "admin_delegated_limit_error_max_clients"),
        ("traffic is below", "admin_delegated_limit_error_traffic_min"),
        ("traffic is above", "admin_delegated_limit_error_traffic_max"),
        ("expiry is below", "admin_delegated_limit_error_days_min"),
        ("expiry is above", "admin_delegated_limit_error_days_max"),
        ("inactive", "admin_delegated_inactive"),
        ("expired", "admin_delegated_expired"),
    ]
    for needle, key in mapping:
        if needle in text:
            return t(key, lang)
    return None
async def _actor_scope(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> tuple[int | None, set[int] | None]:
    owner_filter = await services.access_service.owner_filter_for_user(user_id=user_id, settings=settings)
    if owner_filter is None:
        return owner_filter, None
    visible_rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
        actor_user_id=user_id,
        settings=settings,
    )
    visible_inbound_ids = {
        row.inbound_id
        for row in visible_rows
        if row.panel_id == panel_id
    }
    return owner_filter, visible_inbound_ids


async def _ensure_client_scope(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
) -> bool:
    return await ensure_client_access(
        user_id=user_id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    )


async def _panel_inbound_names(
    services: ServiceContainer,
    *,
    panel_id: int,
    inbound_id: int,
) -> tuple[str, str]:
    try:
        return await services.panel_service.panel_inbound_names(panel_id, inbound_id)
    except Exception:
        return str(panel_id), f"inbound-{inbound_id}"


async def _resolve_panel_or_prompt(
    message: Message,
    services: ServiceContainer,
    *,
    settings: Settings,
    actor_user_id: int,
    action_text_key: str,
    action_prefix: str,
) -> int | None:
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
        _, allowed = await _actor_scope(
            user_id=actor_user_id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        if allowed is None or allowed:
            return panel_id
    except ValueError:
        pass
    if await services.access_service.is_delegated_admin(actor_user_id):
        access_rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        )
        visible_panel_ids = {row.panel_id for row in access_rows}
        panels = [
            panel
            for panel in await services.panel_service.list_panels()
            if int(panel["id"]) in visible_panel_ids
        ]
    else:
        panels = await services.panel_service.list_panels()
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return None
    await message.answer(t(action_text_key, None), reply_markup=action_panel_select_keyboard(panels, action_prefix))
    return None


async def _render_inbound_clients_view(
    message: Message,
    *,
    services: ServiceContainer,
    settings: Settings,
    actor_user_id: int,
    panel_id: int,
    inbound_id: int,
    page: int = 1,
) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.edit_text(t("admin_panel_not_found", None))
        return
    try:
        inbounds = await services.panel_service.list_inbounds(panel_id)
        owner_filter, allowed_inbound_ids = await _actor_scope(
            user_id=actor_user_id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        if allowed_inbound_ids is not None and inbound_id not in allowed_inbound_ids:
            await message.edit_text(t("no_admin_access", None))
            return
        clients = await services.panel_service.list_inbound_clients(
            panel_id,
            inbound_id,
            owner_admin_user_id=owner_filter,
        )
    except Exception as exc:
        await message.edit_text(f"{t('admin_error_fetch_inbounds', None)}:\n{exc}")
        return
    target = next((x for x in inbounds if int(x.get("id") or -1) == inbound_id), None)
    inbound_name = inbound_display_name(target or {"id": inbound_id, "remark": f"inbound-{inbound_id}"})
    if not clients:
        await message.edit_text(
            t("admin_inbound_clients_empty", None, panel=panel["name"], inbound=inbound_name),
            reply_markup=single_button_inline_keyboard(
                t("admin_back_to_inbounds", None),
                f"users_panel_pick:{panel_id}",
            ),
        )
        return
    await message.edit_text(
        t("admin_inbound_clients_header", None, panel=panel["name"], inbound=inbound_name, count=len(clients)),
        reply_markup=users_clients_keyboard(panel_id, inbound_id, clients, page=page),
    )


async def _bulk_clients_for_panel(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> list[dict]:
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=user_id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    inbounds = await services.panel_service.list_inbounds(panel_id)
    clients: list[dict] = []
    for inbound in inbounds:
        inbound_id = int(inbound.get("id") or 0)
        if inbound_id <= 0:
            continue
        if allowed_inbound_ids is not None and inbound_id not in allowed_inbound_ids:
            continue
        inbound_clients = await services.panel_service.list_inbound_clients(
            panel_id,
            inbound_id,
            owner_admin_user_id=owner_filter,
        )
        for client in inbound_clients:
            clients.append({**client, "inbound_id": inbound_id})
    return clients


async def _visible_bulk_panels(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> list[dict]:
    if await services.access_service.is_delegated_admin(user_id):
        access_rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
            actor_user_id=user_id,
            settings=settings,
        )
        visible_panel_ids = {row.panel_id for row in access_rows}
        return [panel for panel in await services.panel_service.list_panels() if int(panel["id"]) in visible_panel_ids]
    return await services.panel_service.list_panels()


async def _open_bulk_panel_menu(
    target: Message | CallbackQuery,
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> None:
    clients = await _bulk_clients_for_panel(
        user_id=user_id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    if isinstance(target, CallbackQuery):
        if not clients:
            await target.answer(t("admin_bulk_empty", None), show_alert=True)
            return
        if target.message is not None:
            await target.message.edit_text(
                t("admin_bulk_menu_text", None),
                reply_markup=panel_bulk_actions_keyboard(panel_id),
            )
        await target.answer()
        return
    if not clients:
        await answer_with_admin_menu(
            target,
            t("admin_bulk_empty", None),
            settings=settings,
            services=services,
        )
        return
    await target.answer(
        t("admin_bulk_menu_text", None),
        reply_markup=panel_bulk_actions_keyboard(panel_id),
    )


@router.message(F.text.in_(button_variants("btn_list_users")))
async def start_users_list(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        panel_id = None
    if panel_id is not None:
        _, allowed_inbound_ids = await _actor_scope(
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        await show_users_inbounds_for_panel_message(
            message,
            services,
            settings,
            panel_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        return
    if await services.access_service.is_delegated_admin(message.from_user.id):
        access_rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
        )
        visible_panel_ids = {row.panel_id for row in access_rows}
        panels = [panel for panel in await services.panel_service.list_panels() if int(panel["id"]) in visible_panel_ids]
    else:
        panels = await services.panel_service.list_panels()
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    await message.answer(
        t("admin_default_not_selected_list_users", None),
        reply_markup=users_panel_select_keyboard(panels),
    )


@router.message(F.text.in_(button_variants("btn_bulk_operations")))
async def start_bulk_operations(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        panel_id = None
    if panel_id is not None:
        await _open_bulk_panel_menu(
            message,
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        return
    panels = await _visible_bulk_panels(
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


@router.message(F.text.in_(button_variants("btn_online_users")))
async def start_online_users_list(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
    except ValueError:
        panel_id = None
    if panel_id is not None:
        owner_filter, allowed_inbound_ids = await _actor_scope(
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        await show_online_clients_for_panel_message(
            message,
            services,
            settings,
            panel_id,
            owner_admin_user_id=owner_filter,
            allowed_inbound_ids=allowed_inbound_ids,
        )
        return
    if await services.access_service.is_delegated_admin(message.from_user.id):
        access_rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
        )
        visible_panel_ids = {row.panel_id for row in access_rows}
        panels = [panel for panel in await services.panel_service.list_panels() if int(panel["id"]) in visible_panel_ids]
    else:
        panels = await services.panel_service.list_panels()
    if not panels:
        await answer_with_admin_menu(message, t("bind_no_panel", None), settings=settings, services=services)
        return
    await message.answer(
        t("admin_default_not_selected_online", None),
        reply_markup=online_panel_select_keyboard(panels),
    )


@router.callback_query(F.data == NOOP)
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(F.text.in_(button_variants("btn_search_user")))
async def start_search_user(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    panel_id = await _resolve_panel_or_prompt(
        message,
        services,
        settings=settings,
        actor_user_id=message.from_user.id,
        action_text_key="admin_default_not_selected_search",
        action_prefix="uols_panel_pick",
    )
    if panel_id is None:
        return
    await state.update_data(online_search_panel_id=panel_id)
    await state.set_state(ClientManageStates.waiting_online_search_query)
    await message.answer(t("admin_search_prompt", None))


@router.message(F.text.in_(button_variants("btn_disabled_users")))
async def start_disabled_users(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    panel_id = await _resolve_panel_or_prompt(
        message,
        services,
        settings=settings,
        actor_user_id=message.from_user.id,
        action_text_key="admin_default_not_selected_disabled",
        action_prefix="uod_panel_pick",
    )
    if panel_id is None:
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await answer_with_admin_menu(message, t("admin_panel_not_found", None), settings=settings, services=services)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    clients = await services.panel_service.list_disabled_clients(
        panel_id,
        owner_admin_user_id=owner_filter,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    if not clients:
        await message.answer(t("admin_disabled_empty", None, panel=panel["name"]))
        return
    await message.answer(
        t("admin_disabled_header", None, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(panel_id, clients, mode="ds", page=1),
    )


@router.message(F.text.in_(button_variants("btn_last_online_users")))
async def start_last_online_users(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    panel_id = await _resolve_panel_or_prompt(
        message,
        services,
        settings=settings,
        actor_user_id=message.from_user.id,
        action_text_key="admin_default_not_selected_last_online",
        action_prefix="uolt_panel_pick",
    )
    if panel_id is None:
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await answer_with_admin_menu(message, t("admin_panel_not_found", None), settings=settings, services=services)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    clients = await services.panel_service.list_clients_with_last_online(
        panel_id,
        owner_admin_user_id=owner_filter,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    if not clients:
        await message.answer(t("admin_last_online_empty", None, panel=panel["name"]))
        return
    await message.answer(
        t("admin_last_online_header", None, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(
            panel_id,
            clients,
            show_last_online=True,
            tz_name=settings.timezone,
            mode="lo",
            page=1,
        ),
    )


@router.callback_query(F.data.startswith("users_panel_pick:"))
async def users_pick_panel(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        requested_panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(requested_panel_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    _, allowed_inbound_ids = await _actor_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    await show_users_inbounds_for_panel_callback(
        callback,
        services,
        panel_id,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("online_panel_pick:"))
async def online_pick_panel(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        requested_panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    try:
        panel_id = await services.panel_service.resolve_panel_id(requested_panel_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    await show_online_clients_for_panel_callback(
        callback,
        services,
        panel_id,
        owner_admin_user_id=owner_filter,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uols_panel_pick:"))
async def pick_panel_for_search(
    callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await state.update_data(online_search_panel_id=panel_id)
    await state.set_state(ClientManageStates.waiting_online_search_query)
    await callback.message.edit_text(t("admin_search_prompt", None))
    await callback.answer()


@router.callback_query(F.data.startswith("uod_panel_pick:"))
async def pick_panel_for_disabled(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.answer(t("admin_panel_not_found", None), show_alert=True)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    clients = await services.panel_service.list_disabled_clients(
        panel_id,
        owner_admin_user_id=owner_filter,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    if not clients:
        await callback.message.edit_text(t("admin_disabled_empty", None, panel=panel["name"]))
        await callback.answer()
        return
    await callback.message.edit_text(
        t("admin_disabled_header", None, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(panel_id, clients, mode="ds", page=1),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uolt_panel_pick:"))
async def pick_panel_for_last_online(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.answer(t("admin_panel_not_found", None), show_alert=True)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    clients = await services.panel_service.list_clients_with_last_online(
        panel_id,
        owner_admin_user_id=owner_filter,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    if not clients:
        await callback.message.edit_text(t("admin_last_online_empty", None, panel=panel["name"]))
        await callback.answer()
        return
    await callback.message.edit_text(
        t("admin_last_online_header", None, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(
            panel_id,
            clients,
            show_last_online=True,
            tz_name=settings.timezone,
            mode="lo",
            page=1,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("users_inbound_pick:"))
async def users_pick_inbound(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw, inbound_raw = callback.data.split(":", 2)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await _render_inbound_clients_view(
        callback.message,
        services=services,
        settings=settings,
        actor_user_id=callback.from_user.id,
        panel_id=panel_id,
        inbound_id=inbound_id,
        page=1,
    )
    await callback.answer()


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
    await _open_bulk_panel_menu(
        callback,
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )


@router.callback_query(F.data.startswith("pabt:"))
async def users_bulk_add_traffic_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
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
async def users_bulk_add_days_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
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


@router.callback_query(F.data.startswith("uip:"))
async def users_inbound_paginate(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        parsed = parse_inbound_page(callback.data)
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await _render_inbound_clients_view(
        callback.message,
        services=services,
        settings=settings,
        actor_user_id=callback.from_user.id,
        panel_id=parsed.panel_id,
        inbound_id=parsed.inbound_id,
        page=parsed.page,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uolp:"))
async def online_refresh_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    await show_online_clients_for_panel_callback(
        callback,
        services,
        panel_id,
        owner_admin_user_id=owner_filter,
        allowed_inbound_ids=allowed_inbound_ids,
    )
    await callback.answer(t("admin_refresh_done", None))


@router.callback_query(F.data.startswith("uop:"))
async def online_paginate(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        parsed = parse_online_page(callback.data)
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return

    panel = await services.panel_service.get_panel(parsed.panel_id)
    if panel is None:
        await callback.answer(t("admin_panel_not_found", None), show_alert=True)
        return
    owner_filter, allowed_inbound_ids = await _actor_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=parsed.panel_id,
    )

    try:
        if parsed.mode == "on":
            clients = await services.panel_service.list_online_clients(
                parsed.panel_id,
                owner_admin_user_id=owner_filter,
                allowed_inbound_ids=allowed_inbound_ids,
            )
            text = t("admin_online_header", None, name=panel["name"], count=len(clients))
            markup = online_clients_keyboard(parsed.panel_id, clients, page=parsed.page)
        elif parsed.mode == "ds":
            clients = await services.panel_service.list_disabled_clients(
                parsed.panel_id,
                owner_admin_user_id=owner_filter,
                allowed_inbound_ids=allowed_inbound_ids,
            )
            text = t("admin_disabled_header", None, panel=panel["name"], count=len(clients))
            markup = online_filtered_clients_keyboard(parsed.panel_id, clients, mode="ds", page=parsed.page)
        elif parsed.mode == "lo":
            clients = await services.panel_service.list_clients_with_last_online(
                parsed.panel_id,
                owner_admin_user_id=owner_filter,
                allowed_inbound_ids=allowed_inbound_ids,
            )
            text = t("admin_last_online_header", None, panel=panel["name"], count=len(clients))
            markup = online_filtered_clients_keyboard(
                parsed.panel_id,
                clients,
                show_last_online=True,
                tz_name=settings.timezone,
                mode="lo",
                page=parsed.page,
            )
        elif parsed.mode == "sr":
            search_query = (parsed.query or "").strip()
            clients = await services.panel_service.search_clients_by_email(
                parsed.panel_id,
                search_query,
                owner_admin_user_id=owner_filter,
                allowed_inbound_ids=allowed_inbound_ids,
            )
            text = t("admin_search_result_header", None, query=search_query, panel=panel["name"], count=len(clients))
            markup = online_filtered_clients_keyboard(
                parsed.panel_id,
                clients,
                mode="sr",
                page=parsed.page,
                query=search_query,
            )
        else:
            await callback.answer(t("admin_invalid_data", None), show_alert=True)
            return
    except Exception as exc:
        await callback.message.edit_text(f"{t('admin_error_fetch_online', None)}:\n{exc}")
        await callback.answer()
        return

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("uols:"))
async def online_search_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    await state.update_data(online_search_panel_id=panel_id)
    await state.set_state(ClientManageStates.waiting_online_search_query)
    await callback.message.answer(t("admin_search_prompt", None))
    await callback.answer()


@router.message(ClientManageStates.waiting_online_search_query)
async def online_search_execute(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    query = (message.text or "").strip()
    data = await state.get_data()
    panel_id_raw = data.get("online_search_panel_id")
    if panel_id_raw is None:
        await state.clear()
        await answer_with_admin_menu(message, t("admin_invalid_data", None), settings=settings, services=services)
        return
    panel_id = int(panel_id_raw)
    if len(query) < 2:
        await message.answer(t("admin_search_too_short", None))
        return
    await state.clear()
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await answer_with_admin_menu(message, t("admin_panel_not_found", None), settings=settings, services=services)
        return
    try:
        owner_filter, allowed_inbound_ids = await _actor_scope(
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        clients = await services.panel_service.search_clients_by_email(
            panel_id,
            query,
            owner_admin_user_id=owner_filter,
            allowed_inbound_ids=allowed_inbound_ids,
        )
    except Exception as exc:
        await answer_with_admin_menu(
            message,
            f"{t('admin_error_fetch_online', None)}:\n{exc}",
            settings=settings,
            services=services,
        )
        return
    if not clients:
        await message.answer(t("admin_search_empty", None, query=query, panel=panel["name"]))
        return
    await message.answer(
        t("admin_search_result_header", None, query=query, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(panel_id, clients, mode="sr", page=1, query=query),
    )


@router.callback_query(F.data.startswith("uod:"))
async def online_show_disabled(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.answer(t("admin_panel_not_found", None), show_alert=True)
        return
    try:
        owner_filter, allowed_inbound_ids = await _actor_scope(
            user_id=callback.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        clients = await services.panel_service.list_disabled_clients(
            panel_id,
            owner_admin_user_id=owner_filter,
            allowed_inbound_ids=allowed_inbound_ids,
        )
    except Exception as exc:
        await callback.message.edit_text(f"{t('admin_error_fetch_online', None)}:\n{exc}")
        await callback.answer()
        return
    if not clients:
        await callback.message.edit_text(t("admin_disabled_empty", None, panel=panel["name"]))
        await callback.answer()
        return
    await callback.message.edit_text(
        t("admin_disabled_header", None, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(panel_id, clients, mode="ds", page=1),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uolt:"))
async def online_show_last_online(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.answer(t("admin_panel_not_found", None), show_alert=True)
        return
    try:
        owner_filter, allowed_inbound_ids = await _actor_scope(
            user_id=callback.from_user.id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        clients = await services.panel_service.list_clients_with_last_online(
            panel_id,
            owner_admin_user_id=owner_filter,
            allowed_inbound_ids=allowed_inbound_ids,
        )
    except Exception as exc:
        await callback.message.edit_text(f"{t('admin_error_fetch_online', None)}:\n{exc}")
        await callback.answer()
        return
    if not clients:
        await callback.message.edit_text(t("admin_last_online_empty", None, panel=panel["name"]))
        await callback.answer()
        return
    await callback.message.edit_text(
        t("admin_last_online_header", None, panel=panel["name"], count=len(clients)),
        reply_markup=online_filtered_clients_keyboard(
            panel_id,
            clients,
            show_last_online=True,
            tz_name=settings.timezone,
            mode="lo",
            page=1,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uol:"))
async def online_open_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "uol")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await render_client_detail(
        callback,
        services,
        settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        back_callback=f"uolp:{panel_id}",
        back_text=t("admin_back_to_online_list", None),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uo:"))
async def client_open_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "uo")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer()


@router.callback_query(F.data.startswith("cr:"))
async def client_refresh(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "cr")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_refresh_done", None))


@router.callback_query(F.data.startswith("ra:"))
async def client_reset_confirm(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "ra")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=client_confirm_reset_keyboard(panel_id, inbound_id, client_uuid))
    await callback.answer()


@router.callback_query(F.data.startswith("ry:"))
async def client_reset_yes(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "ry")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    try:
        await services.admin_provisioning_service.reset_client_traffic_for_actor(
            actor_user_id=callback.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
    except Exception as exc:
        await callback_error_alert(callback, exc)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_reset_done", None))


@router.callback_query(F.data.startswith("tm:"))
async def client_traffic_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "tm")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=client_traffic_menu_keyboard(panel_id, inbound_id, client_uuid))
    await callback.answer()


@router.callback_query(F.data.startswith("ts:"))
async def client_traffic_set(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid, value_raw = parse_client_callback_with_value(callback.data, "ts")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    total_gb: int | None = None if value_raw == "unlimited" else int(value_raw)
    try:
        await services.admin_provisioning_service.set_client_total_gb_for_actor(
            actor_user_id=callback.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            total_gb=total_gb,
        )
    except Exception as exc:
        delegated_error = _delegated_profile_error_text(exc, None)
        if delegated_error is not None:
            await callback.answer(delegated_error, show_alert=True)
            return
        if str(exc) == "delegated_unlimited_not_allowed":
            await callback.answer(t("finance_unlimited_not_allowed", None), show_alert=True)
            return
        if "insufficient" in str(exc).lower():
            await callback.answer(t("finance_insufficient_wallet", None), show_alert=True)
            return
        await callback_error_alert(callback, exc)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_traffic_limit_applied", None))


@router.callback_query(F.data.startswith("tc:"))
async def client_traffic_custom(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "tc")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_custom_traffic_gb)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_traffic_gb", None))
    await callback.answer()


@router.callback_query(F.data.startswith("em:"))
async def client_expiry_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "em")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=client_expiry_menu_keyboard(panel_id, inbound_id, client_uuid))
    await callback.answer()


@router.callback_query(F.data.startswith("es:"))
async def client_expiry_set(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid, value_raw = parse_client_callback_with_value(callback.data, "es")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    days: int | None = None if value_raw == "unlimited" else int(value_raw)
    try:
        await services.admin_provisioning_service.set_client_expiry_days_for_actor(
            actor_user_id=callback.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            days=days,
        )
    except Exception as exc:
        delegated_error = _delegated_profile_error_text(exc, None)
        if delegated_error is not None:
            await callback.answer(delegated_error, show_alert=True)
            return
        if str(exc) == "delegated_unlimited_not_allowed":
            await callback.answer(t("finance_unlimited_not_allowed", None), show_alert=True)
            return
        if "insufficient" in str(exc).lower():
            await callback.answer(t("finance_insufficient_wallet", None), show_alert=True)
            return
        await callback_error_alert(callback, exc)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_expiry_updated", None))


@router.callback_query(F.data.startswith("ec:"))
async def client_expiry_custom(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "ec")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_custom_expiry_days)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_days", None))
    await callback.answer()


@router.callback_query(F.data.startswith("im:"))
async def client_iplimit_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "im")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=client_iplimit_menu_keyboard(panel_id, inbound_id, client_uuid))
    await callback.answer()


@router.callback_query(F.data.startswith("is:"))
async def iplimit_set_callback(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid, value_raw = parse_client_callback_with_value(callback.data, "is")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    limit_ip: int | None = None if value_raw == "unlimited" else int(value_raw)
    try:
        await services.admin_provisioning_service.set_client_limit_ip_for_actor(
            actor_user_id=callback.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            limit_ip=limit_ip,
        )
    except Exception as exc:
        await callback_error_alert(callback, exc)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_ip_limit_updated", None))


@router.callback_query(F.data.startswith("ic:"))
async def client_iplimit_custom(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "ic")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_custom_ip_limit)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_ip_limit", None))
    await callback.answer()


@router.callback_query(F.data.startswith("ti:"))
async def client_tgid_input(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "ti")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_tg_id)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_tg", None))
    await callback.answer()


@router.callback_query(F.data.startswith("te:"))
async def client_toggle_enable(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "te")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    try:
        _detail, enabled = await services.admin_provisioning_service.toggle_client_for_actor(
            actor_user_id=callback.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
    except Exception as exc:
        await callback_error_alert(callback, exc)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_enable_on", None) if enabled else t("admin_enable_off", None))


@router.callback_query(F.data.startswith("il:"))
async def client_ips_log(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "il")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    try:
        detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
        ips = await services.panel_service.get_client_ips(panel_id, str(detail.get("email") or ""))
    except Exception as exc:
        await callback_error_alert(callback, exc)
        return
    await callback.message.edit_text(
        t("admin_ip_log_for", None, email=detail.get("email"), ips=ips),
        reply_markup=client_ips_log_keyboard(panel_id, inbound_id, client_uuid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ix:"))
async def client_ips_clear(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, "ix")
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return
    if not await _ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    try:
        detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
        await services.panel_service.clear_client_ips(panel_id, str(detail.get("email") or ""))
    except Exception as exc:
        await callback_error_alert(callback, exc)
        return
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_ip_log_cleared", None))


@router.message(ClientManageStates.waiting_custom_traffic_gb)
async def client_custom_traffic_gb(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    raw = (message.text or "").strip()
    try:
        gb = int(raw)
        if gb < 0:
            raise ValueError
    except ValueError:
        await message.answer(t("admin_invalid_gb", None))
        return
    data = await state.get_data()
    panel_id = int(data["client_manage_panel_id"])
    inbound_id = int(data["client_manage_inbound_id"])
    client_uuid = str(data["client_manage_uuid"])
    await state.clear()
    if not await _ensure_client_scope(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", None))
        return
    try:
        await services.admin_provisioning_service.set_client_total_gb_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            total_gb=gb,
        )
    except Exception as exc:
        delegated_error = _delegated_profile_error_text(exc, None)
        if delegated_error is not None:
            await answer_with_admin_menu(
                message,
                delegated_error,
                settings=settings,
                services=services,
            )
            return
        if "insufficient" in str(exc).lower():
            await answer_with_admin_menu(
                message,
                t("finance_insufficient_wallet", None),
                settings=settings,
                services=services,
            )
            return
        await answer_with_admin_menu(
            message,
            f"{t('admin_update_traffic_error', None)}:\n{exc}",
            settings=settings,
            services=services,
        )
        return
    await message.answer(
        t("admin_done", None),
        reply_markup=back_to_detail_keyboard(panel_id, inbound_id, client_uuid),
    )


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
    clients = await _bulk_clients_for_panel(
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
            delegated_error = _delegated_profile_error_text(exc, None)
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
    clients = await _bulk_clients_for_panel(
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
            delegated_error = _delegated_profile_error_text(exc, None)
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


@router.message(ClientManageStates.waiting_custom_expiry_days)
async def client_custom_expiry_days(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    raw = (message.text or "").strip()
    try:
        days = int(raw)
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer(t("admin_invalid_days", None))
        return
    data = await state.get_data()
    panel_id = int(data["client_manage_panel_id"])
    inbound_id = int(data["client_manage_inbound_id"])
    client_uuid = str(data["client_manage_uuid"])
    await state.clear()
    if not await _ensure_client_scope(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", None))
        return
    try:
        await services.admin_provisioning_service.set_client_expiry_days_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            days=days,
        )
    except Exception as exc:
        delegated_error = _delegated_profile_error_text(exc, None)
        if delegated_error is not None:
            await answer_with_admin_menu(
                message,
                delegated_error,
                settings=settings,
                services=services,
            )
            return
        if "insufficient" in str(exc).lower():
            await answer_with_admin_menu(
                message,
                t("finance_insufficient_wallet", None),
                settings=settings,
                services=services,
            )
            return
        await answer_with_admin_menu(
            message,
            f"{t('admin_update_expiry_error', None)}:\n{exc}",
            settings=settings,
            services=services,
        )
        return
    await message.answer(
        t("admin_done", None),
        reply_markup=back_to_detail_keyboard(panel_id, inbound_id, client_uuid),
    )


@router.message(ClientManageStates.waiting_custom_ip_limit)
async def client_custom_ip_limit(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    raw = (message.text or "").strip()
    try:
        limit = int(raw)
        if limit < 0:
            raise ValueError
    except ValueError:
        await message.answer(t("admin_invalid_ip", None))
        return
    data = await state.get_data()
    panel_id = int(data["client_manage_panel_id"])
    inbound_id = int(data["client_manage_inbound_id"])
    client_uuid = str(data["client_manage_uuid"])
    await state.clear()
    if not await _ensure_client_scope(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", None))
        return
    try:
        await services.admin_provisioning_service.set_client_limit_ip_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            limit_ip=limit,
        )
    except Exception as exc:
        await answer_with_admin_menu(
            message,
            f"{t('admin_update_ip_error', None)}:\n{exc}",
            settings=settings,
            services=services,
        )
        return
    await message.answer(
        t("admin_done", None),
        reply_markup=back_to_detail_keyboard(panel_id, inbound_id, client_uuid),
    )


@router.message(ClientManageStates.waiting_tg_id)
async def client_set_tg_id(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    raw = (message.text or "").strip()
    tg_id = normalize_tg_id(raw)
    if tg_id is None:
        await message.answer(t("admin_tgid_invalid", None))
        return
    data = await state.get_data()
    panel_id = int(data["client_manage_panel_id"])
    inbound_id = int(data["client_manage_inbound_id"])
    client_uuid = str(data["client_manage_uuid"])
    await state.clear()
    if not await _ensure_client_scope(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", None))
        return
    try:
        await services.admin_provisioning_service.set_client_tg_id_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            tg_id=tg_id,
        )
    except Exception as exc:
        await answer_with_admin_menu(
            message,
            f"{t('admin_update_tg_error', None)}:\n{exc}",
            settings=settings,
            services=services,
        )
        return
    await message.answer(
        t("admin_tg_done", None),
        reply_markup=back_to_detail_keyboard(panel_id, inbound_id, client_uuid),
    )
