from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from .admin_shared import (
    action_panel_select_keyboard,
    answer_with_admin_menu,
    client_list_keyboard,
    ensure_client_access,
    inbound_display_name,
    panel_bulk_actions_keyboard,
    single_button_inline_keyboard,
    users_clients_keyboard,
)


def delegated_profile_error_text(exc: Exception, lang: str | None) -> str | None:
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


async def render_inbound_clients_view(
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
        owner_filter, allowed_inbound_ids = await actor_scope(
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
