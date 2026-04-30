from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from .admin_client_helpers import scoped_client_from_callback as _scoped_client_from_callback
from .admin_shared import (
    callback_error_alert,
    client_confirm_reset_keyboard,
    reject_callback_if_not_any_admin,
    render_client_detail,
)

router = Router(name="admin_client_detail")


@router.callback_query(F.data.startswith("uol:"))
async def online_open_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="uol",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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


@router.callback_query(F.data.startswith("uodl:"))
async def disabled_open_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="uodl",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await render_client_detail(
        callback,
        services,
        settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        back_callback=f"uop:ds:{panel_id}:1",
        back_text=t("admin_back_to_disabled_list", None),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uolr:"))
async def low_traffic_open_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="uolr",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await render_client_detail(
        callback,
        services,
        settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        back_callback=f"uop:lr:{panel_id}:1",
        back_text=t("admin_back_to_low_traffic_list", None),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uo:"))
async def client_open_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="uo",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await render_client_detail(
        callback,
        services,
        settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        back_callback=f"users_inbound_pick:{panel_id}:{inbound_id}",
        back_text=t("admin_back_to_users_list", None),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cr:"))
async def client_refresh(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="cr",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await render_client_detail(callback, services, settings, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await callback.answer(t("admin_refresh_done", None))


@router.callback_query(F.data.startswith("ra:"))
async def client_reset_confirm(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="ra",
        require_message=True,
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await callback.message.edit_reply_markup(reply_markup=client_confirm_reset_keyboard(panel_id, inbound_id, client_uuid))
    await callback.answer()


@router.callback_query(F.data.startswith("ry:"))
async def client_reset_yes(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="ry",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
