from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from .admin_handler_helpers import delegated_profile_error_text
from .admin_shared import (
    action_panel_select_keyboard,
    answer_with_admin_menu,
    ensure_client_access,
    panel_bulk_actions_keyboard,
    parse_client_callback,
    parse_client_callback_with_value,
)


async def parse_panel_action_callback(
    callback: CallbackQuery,
    *,
    require_message: bool = False,
) -> int | None:
    if callback.data is None or (require_message and callback.message is None):
        await callback.answer()
        return None
    try:
        _, panel_raw = callback.data.split(":", 1)
        return int(panel_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return None


async def scoped_client_from_callback(
    callback: CallbackQuery,
    *,
    settings: Settings,
    services: ServiceContainer,
    prefix: str,
    require_message: bool = False,
) -> tuple[int, int, str] | None:
    if callback.data is None or (require_message and callback.message is None):
        await callback.answer()
        return None
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data, prefix)
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return None
    if not await ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return None
    return panel_id, inbound_id, client_uuid


async def scoped_client_value_from_callback(
    callback: CallbackQuery,
    *,
    settings: Settings,
    services: ServiceContainer,
    prefix: str,
) -> tuple[int, int, str, str] | None:
    if callback.data is None:
        await callback.answer()
        return None
    try:
        panel_id, inbound_id, client_uuid, value_raw = parse_client_callback_with_value(callback.data, prefix)
    except ValueError:
        await callback.answer(t("admin_invalid_data", None), show_alert=True)
        return None
    if not await ensure_client_scope(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return None
    return panel_id, inbound_id, client_uuid, value_raw


async def scoped_client_from_state(
    state,
    *,
    actor_user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_key: str = "client_manage_panel_id",
    inbound_key: str = "client_manage_inbound_id",
    uuid_key: str = "client_manage_uuid",
) -> tuple[int, int, str] | None:
    data = await state.get_data()
    try:
        panel_id = int(data[panel_key])
        inbound_id = int(data[inbound_key])
        client_uuid = str(data[uuid_key])
    except (KeyError, TypeError, ValueError):
        await state.clear()
        return None
    await state.clear()
    if not await ensure_client_scope(
        user_id=actor_user_id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        return None
    return panel_id, inbound_id, client_uuid


def is_handled_delegated_operation_error(exc: Exception) -> bool:
    return delegated_profile_error_text(exc, None) is not None


async def actor_scope(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> tuple[int | None, set[int] | None]:
    context = await services.access_service.get_admin_context(user_id, settings)
    if context.is_root_admin:
        return None, None
    if context.is_full_admin:
        allowed = await services.access_service.get_allowed_inbound_ids(
            user_id=user_id,
            settings=settings,
            panel_id=panel_id,
        )
        return None, allowed
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


async def ensure_client_scope(
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


def low_traffic_threshold_mb(settings: Settings) -> int:
    return max(1, int(settings.low_traffic_list_threshold_mb))


async def panel_inbound_names(
    services: ServiceContainer,
    *,
    panel_id: int,
    inbound_id: int,
) -> tuple[str, str]:
    try:
        return await services.panel_service.panel_inbound_names(panel_id, inbound_id)
    except Exception:
        return str(panel_id), f"inbound-{inbound_id}"


async def resolve_panel_or_prompt(
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
        _, allowed = await actor_scope(
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


async def bulk_clients_for_panel(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> list[dict]:
    owner_filter, allowed_inbound_ids = await actor_scope(
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
            clients.append({**client, "panel_id": panel_id, "inbound_id": inbound_id})
    return clients


async def visible_bulk_panels(
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


async def open_bulk_panel_menu(
    target: Message | CallbackQuery,
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> None:
    clients = await bulk_clients_for_panel(
        user_id=user_id,
        settings=settings,
        services=services,
        panel_id=panel_id,
    )
    if not clients:
        if isinstance(target, CallbackQuery):
            await target.answer(t("admin_bulk_empty", None), show_alert=True)
            return
        await answer_with_admin_menu(
            target,
            t("admin_bulk_empty", None),
            settings=settings,
            services=services,
        )
        return
    if isinstance(target, CallbackQuery):
        if target.message is not None:
            await target.message.edit_text(
                t("admin_bulk_menu_text", None),
                reply_markup=panel_bulk_actions_keyboard(panel_id),
            )
        await target.answer()
        return
    await target.answer(
        t("admin_bulk_menu_text", None),
        reply_markup=panel_bulk_actions_keyboard(panel_id),
    )
