from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.states import ClientManageStates
from bot.utils import parse_gb_amount
from .admin_client_helpers import (
    delegated_profile_error_text as _delegated_profile_error_text,
    ensure_client_scope as _ensure_client_scope,
    scoped_client_from_callback as _scoped_client_from_callback,
)
from .admin_shared import (
    answer_with_admin_menu,
    back_to_detail_keyboard,
    callback_error_alert,
    client_expiry_menu_keyboard,
    client_iplimit_menu_keyboard,
    client_ips_log_keyboard,
    client_traffic_menu_keyboard,
    normalize_tg_id,
    parse_client_callback_with_value,
    reject_callback_if_not_any_admin,
    render_client_detail,
    set_client_action_context,
)

router = Router(name="admin_client_actions")


@router.callback_query(F.data.startswith("tm:"))
async def client_traffic_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="tm",
        require_message=True,
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
    total_gb: float | None = None if value_raw == "unlimited" else parse_gb_amount(value_raw)
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
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="tc",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_custom_traffic_gb)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_traffic_gb", None))
    await callback.answer()


@router.callback_query(F.data.startswith("em:"))
async def client_expiry_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="em",
        require_message=True,
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="ec",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_custom_expiry_days)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_days", None))
    await callback.answer()


@router.callback_query(F.data.startswith("im:"))
async def client_iplimit_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="im",
        require_message=True,
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="ic",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_custom_ip_limit)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_ip_limit", None))
    await callback.answer()


@router.callback_query(F.data.startswith("ti:"))
async def client_tgid_input(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="ti",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
    await set_client_action_context(state, panel_id=panel_id, inbound_id=inbound_id, client_uuid=client_uuid)
    await state.set_state(ClientManageStates.waiting_tg_id)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_tg", None))
    await callback.answer()


@router.callback_query(F.data.startswith("te:"))
async def client_toggle_enable(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="te",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="il",
        require_message=True,
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
    client_ref = await _scoped_client_from_callback(
        callback,
        settings=settings,
        services=services,
        prefix="ix",
    )
    if client_ref is None:
        return
    panel_id, inbound_id, client_uuid = client_ref
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
        gb = parse_gb_amount(raw)
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
