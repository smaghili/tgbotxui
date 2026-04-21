from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import NOOP
from bot.config import Settings
from bot.i18n import button_variants, t
from bot.pagination import chunk_buttons, paginate_window
from bot.services.container import ServiceContainer
from bot.states import ProvisioningStates
from bot.utils import format_gb

from .admin_shared import (
    answer_with_admin_menu,
    answer_with_cancel,
    edit_config_actions_keyboard,
    format_client_detail,
    inline_button,
    normalize_tg_id,
    panel_select_keyboard,
    parse_client_callback,
    notify_delegated_admin_activity,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
    yes_no_inline_keyboard,
)
from .config_bundle import send_config_bundle_card, send_existing_config_bundle_for_email, send_rotation_preview_bundle_for_email

router = Router(name="admin_provisioning")
EDIT_SEARCH_RESULTS_PER_PAGE = 20


def _delegated_profile_error_text(exc: Exception, lang: str | None) -> str | None:
    text = str(exc).lower()
    mapping = [
        ("already exists on this inbound", "admin_duplicate_client_email"),
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


def _inbound_access_keyboard(rows: list, prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    for row in rows:
        buttons.append(
            [
                inline_button(f"{row.panel_name} | {row.inbound_name}", f"{prefix}:{row.panel_id}:{row.inbound_id}")
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _create_tg_id_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard("pcu:tg_choice:yes", "pcu:tg_choice:no", lang)


def _edit_actions_keyboard(
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    lang: str | None = None,
    *,
    back_callback: str | None = None,
    back_text: str | None = None,
) -> InlineKeyboardMarkup:
    return edit_config_actions_keyboard(
        panel_id,
        inbound_id,
        client_uuid,
        True,
        lang,
        back_callback=back_callback,
        back_text=back_text,
    )


def _truncate_button_text(text: str, max_len: int = 60) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _edit_panel_select_keyboard(panels: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, "pecsp")


def _edit_search_results_keyboard(
    panel_id: int,
    clients: list[dict],
    *,
    query: str,
    lang: str | None = None,
    page: int = 1,
) -> InlineKeyboardMarkup:
    page, total_pages, start, end = paginate_window(len(clients), page, EDIT_SEARCH_RESULTS_PER_PAGE)
    page_buttons: list[InlineKeyboardButton] = []
    for client in clients[start:end]:
        email = str(client.get("email") or "").strip()
        inbound_id = int(client.get("inbound_id") or 0)
        client_uuid = str(client.get("uuid") or "").strip()
        if not email or inbound_id <= 0 or not client_uuid:
            continue
        prefix = "🟢" if bool(client.get("enabled", True)) else "⚫"
        page_buttons.append(
            inline_button(
                _truncate_button_text(f"{prefix} {email}"),
                f"pecs:{panel_id}:{inbound_id}:{client_uuid}:{page}:{query}",
            )
        )
    rows = chunk_buttons(page_buttons, columns=2)
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(
                inline_button(t("admin_page_prev", lang), f"pecp:{panel_id}:{page - 1}:{query}")
            )
        nav_row.append(inline_button(f"{page}/{total_pages}", NOOP))
        if page < total_pages:
            nav_row.append(
                inline_button(t("admin_page_next", lang), f"pecp:{panel_id}:{page + 1}:{query}")
            )
        rows.append(nav_row)
    rows.append([inline_button(t("admin_refresh_list", lang), f"pecsr:{panel_id}:{query}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _delete_confirm_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard(
        f"pec:delete_yes:{panel_id}:{inbound_id}:{client_uuid}",
        f"pec:detail:{panel_id}:{inbound_id}:{client_uuid}",
        lang,
    )


async def _send_config_bundle(
    message: Message,
    *,
    config_name: str,
    total_gb: int,
    expiry_days: int,
    vless_uri: str,
    sub_url: str,
    lang: str | None,
) -> None:
    await send_config_bundle_card(
        message,
        config_name=config_name,
        total_label=format_gb(total_gb * (1024**3), lang or "fa"),
        expiry_label=f"{expiry_days} {t('unit_day', lang)}",
        vless_uri=vless_uri,
        sub_url=sub_url,
        lang=lang,
        filename="client_config_qr.png",
    )


async def _render_edit_detail(
    callback: CallbackQuery | Message,
    *,
    services: ServiceContainer,
    settings: Settings,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    lang: str | None,
    back_callback: str | None = None,
    back_text: str | None = None,
) -> None:
    detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
    text = format_client_detail(detail, settings.timezone, lang)
    markup = edit_config_actions_keyboard(
        panel_id,
        inbound_id,
        client_uuid,
        bool(detail.get("enabled")),
        lang,
        back_callback=back_callback,
        back_text=back_text,
    )
    if isinstance(callback, CallbackQuery):
        if callback.message is not None:
            await callback.message.edit_text(text, reply_markup=markup)
    else:
        await callback.answer(text, reply_markup=markup)


async def _ensure_inbound_access(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
    inbound_id: int,
    client_uuid: str | None = None,
) -> bool:
    if await services.access_service.can_access_inbound(
        user_id=user_id,
        settings=settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
    ):
        return True
    owner_filter = await services.access_service.owner_filter_for_user(user_id=user_id, settings=settings)
    if owner_filter is None or not client_uuid:
        return False
    detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
    return str(detail.get("comment") or "").strip() == str(owner_filter)


def _actor_display_name(message_or_callback: Message | CallbackQuery) -> str:
    user = message_or_callback.from_user if isinstance(message_or_callback, CallbackQuery) else message_or_callback.from_user
    if user is None:
        return "unknown"
    if user.full_name:
        return user.full_name
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def _resolved_client_email(before: dict, after: dict) -> str:
    return str(after.get("email") or before.get("email") or "")


def _activity_details_block(details: list[str]) -> str:
    if not details:
        return ""
    return "\n" + "\n".join(details)


def _build_admin_activity_notice(
    *,
    lang: str | None,
    actor: str,
    action_key: str,
    user: str,
    panel: str,
    inbound: str,
    details: list[str] | None = None,
) -> str:
    return t(
        "admin_activity_notify_template",
        lang,
        actor=actor,
        action=t(action_key, lang),
        user=user,
        panel=panel,
        inbound=inbound,
        details=_activity_details_block(details or []),
    )


async def _notify_admin_activity(
    source: Message | CallbackQuery,
    *,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
    action_key: str,
    user: str,
    panel: str,
    inbound: str,
    details: list[str] | None = None,
) -> None:
    await _notify_root_admins_if_delegated(
        source,
        settings=settings,
        services=services,
        text=_build_admin_activity_notice(
            lang=lang,
            actor=_actor_display_name(source),
            action_key=action_key,
            user=user,
            panel=panel,
            inbound=inbound,
            details=details,
        ),
    )


def _delegated_min_create_error(
    *,
    is_delegated_admin: bool,
    traffic_gb: int | None = None,
    expiry_days: int | None = None,
    settings: Settings,
) -> tuple[str, int] | None:
    if not is_delegated_admin:
        return None
    if traffic_gb is not None and traffic_gb < settings.delegated_admin_min_create_gb:
        return "admin_delegated_min_create_traffic", settings.delegated_admin_min_create_gb
    if expiry_days is not None and expiry_days < settings.delegated_admin_min_create_days:
        return "admin_delegated_min_create_days", settings.delegated_admin_min_create_days
    return None


async def _notify_root_admins_if_delegated(
    source: Message | CallbackQuery,
    *,
    settings: Settings,
    services: ServiceContainer,
    text: str,
) -> None:
    await notify_delegated_admin_activity(
        source,
        settings=settings,
        services=services,
        text=text,
    )


async def _panel_inbound_names(
    services: ServiceContainer,
    *,
    panel_id: int,
    inbound_id: int,
) -> tuple[str, str]:
    panel_name = str(panel_id)
    inbound_name = str(inbound_id)
    panel = await services.panel_service.get_panel(panel_id)
    if panel is not None:
        panel_name = str(panel.get("name") or panel_id)
    try:
        inbounds = await services.panel_service.list_inbounds(panel_id)
        inbound = next((item for item in inbounds if int(item.get("id") or 0) == inbound_id), None)
        if inbound is not None:
            remark = str(inbound.get("remark") or "").strip()
            inbound_name = remark or f"inbound-{inbound_id}"
    except Exception:
        pass
    return panel_name, inbound_name


async def _restore_admin_menu(
    target: Message | CallbackQuery,
    *,
    services: ServiceContainer,
    settings: Settings,
    lang: str | None,
) -> None:
    message = target.message if isinstance(target, CallbackQuery) else target
    if message is None:
        return
    await answer_with_admin_menu(
        message,
        t("menu_management", lang),
        settings=settings,
        services=services,
        lang=lang,
    )


async def _visible_panels_for_actor(
    *,
    actor_user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> list[dict]:
    if await services.access_service.is_delegated_admin(actor_user_id):
        rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
        )
        visible_panel_ids = {row.panel_id for row in rows}
        return [panel for panel in await services.panel_service.list_panels() if int(panel["id"]) in visible_panel_ids]
    return await services.panel_service.list_panels()


async def _visible_inbound_ids_for_actor(
    *,
    actor_user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
) -> set[int] | None:
    owner_filter = await services.access_service.owner_filter_for_user(user_id=actor_user_id, settings=settings)
    if owner_filter is None:
        return None
    rows = await services.admin_provisioning_service.list_visible_inbounds_for_actor(
        actor_user_id=actor_user_id,
        settings=settings,
    )
    return {row.inbound_id for row in rows if row.panel_id == panel_id}


async def _resolve_panel_for_edit_search(
    message: Message,
    state: FSMContext,
    *,
    actor_user_id: int,
    query: str,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> int | None:
    try:
        panel_id = await services.panel_service.resolve_panel_id(None)
        allowed = await _visible_inbound_ids_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            services=services,
            panel_id=panel_id,
        )
        if allowed is None or allowed:
            return panel_id
    except ValueError:
        pass
    panels = await _visible_panels_for_actor(actor_user_id=actor_user_id, settings=settings, services=services)
    if not panels:
        await answer_with_admin_menu(
            message,
            t("bind_no_panel", lang),
            settings=settings,
            services=services,
            lang=lang,
        )
        return None
    await state.update_data(edit_search_query=query)
    await state.set_state(ProvisioningStates.waiting_edit_search_panel)
    await message.answer(t("admin_edit_search_pick_panel", lang), reply_markup=_edit_panel_select_keyboard(panels, lang))
    return None


async def _show_edit_search_results(
    message: Message | CallbackQuery,
    *,
    actor_user_id: int,
    panel_id: int,
    query: str,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
    page: int = 1,
) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        target = message.message if isinstance(message, CallbackQuery) else message
        if target is not None:
            await target.answer(t("admin_panel_not_found", lang))
        return
    owner_filter = await services.access_service.owner_filter_for_user(user_id=actor_user_id, settings=settings)
    allowed_inbound_ids = await _visible_inbound_ids_for_actor(
        actor_user_id=actor_user_id,
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
    target_text = t("admin_edit_search_result_header", lang, query=query, panel=panel["name"], count=len(clients))
    markup = _edit_search_results_keyboard(panel_id, clients, query=query, lang=lang, page=page)
    if not clients:
        target_text = t("admin_search_empty", lang, query=query, panel=panel["name"])
        markup = None
    if isinstance(message, CallbackQuery):
        if message.message is not None:
            await message.message.edit_text(target_text, reply_markup=markup)
    else:
        await message.answer(target_text, reply_markup=markup)


async def _show_resolved_edit_target(
    target: Message | CallbackQuery,
    *,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
    back_callback: str | None = None,
    back_text: str | None = None,
) -> None:
    await _render_edit_detail(
        target,
        services=services,
        settings=settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        lang=lang,
        back_callback=back_callback,
        back_text=back_text,
    )

@router.message(F.text.in_(button_variants("btn_create_user")))
async def start_create_user(
    message: Message,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    rows = await services.admin_provisioning_service.list_accessible_inbounds_for_actor(
        actor_user_id=message.from_user.id,
        settings=settings,
    )
    if not rows:
        await message.answer(t("admin_create_user_no_access", lang))
        return
    if len(rows) == 1:
        selected = rows[0]
        await state.update_data(create_panel_id=selected.panel_id, create_inbound_id=selected.inbound_id)
        await state.set_state(ProvisioningStates.waiting_create_email)
        await answer_with_cancel(message, t("admin_create_enter_email", lang), lang=lang)
        return
    await message.answer(
        t("admin_create_user_pick_inbound", lang),
        reply_markup=_inbound_access_keyboard(rows, "pcu:pick"),
    )


@router.callback_query(F.data.startswith("pcu:pick:"))
async def pick_create_user_inbound(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, _, panel_raw, inbound_raw = callback.data.split(":", 3)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    await state.update_data(create_panel_id=panel_id, create_inbound_id=inbound_id)
    await state.set_state(ProvisioningStates.waiting_create_email)
    await answer_with_cancel(callback.message, t("admin_create_enter_email", lang), lang=lang)
    await callback.answer()


@router.message(ProvisioningStates.waiting_create_email)
async def create_user_email(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    email = (message.text or "").strip()
    if not email:
        await answer_with_cancel(message, t("bind_config_id_empty", lang), lang=lang)
        return
    await state.update_data(create_email=email)
    await state.set_state(ProvisioningStates.waiting_create_traffic_gb)
    await answer_with_cancel(message, t("admin_create_enter_traffic", lang), lang=lang)


@router.message(ProvisioningStates.waiting_create_traffic_gb)
async def create_user_traffic(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        gb = int((message.text or "").strip())
        if gb <= 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("admin_invalid_positive_number", lang), lang=lang)
        return
    delegated_limit_error = _delegated_min_create_error(
        is_delegated_admin=await services.access_service.is_delegated_admin(message.from_user.id),
        traffic_gb=gb,
        settings=settings,
    )
    if delegated_limit_error is not None:
        error_key, minimum = delegated_limit_error
        await answer_with_cancel(message, t(error_key, lang, minimum=minimum), lang=lang)
        return
    await state.update_data(create_total_gb=gb)
    await state.set_state(ProvisioningStates.waiting_create_expiry_days)
    await answer_with_cancel(message, t("admin_create_enter_days", lang), lang=lang)


@router.message(ProvisioningStates.waiting_create_expiry_days)
async def create_user_days(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        days = int((message.text or "").strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("admin_invalid_positive_number", lang), lang=lang)
        return
    delegated_limit_error = _delegated_min_create_error(
        is_delegated_admin=await services.access_service.is_delegated_admin(message.from_user.id),
        expiry_days=days,
        settings=settings,
    )
    if delegated_limit_error is not None:
        error_key, minimum = delegated_limit_error
        await answer_with_cancel(message, t(error_key, lang, minimum=minimum), lang=lang)
        return
    await state.update_data(create_expiry_days=days)
    await state.set_state(ProvisioningStates.waiting_create_tg_id_choice)
    await message.answer(
        f"{t('admin_create_set_tg_title', lang)}\n\n{t('admin_create_set_tg_text', lang)}",
        reply_markup=_create_tg_id_choice_keyboard(lang),
    )


@router.callback_query(ProvisioningStates.waiting_create_tg_id_choice, F.data == "pcu:tg_choice:no")
async def create_user_tg_choice_no(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await _finish_create_user(callback.message, state, settings, services, lang, actor_user_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(ProvisioningStates.waiting_create_tg_id_choice, F.data == "pcu:tg_choice:yes")
async def create_user_tg_choice_yes(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.set_state(ProvisioningStates.waiting_create_tg_id)
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await answer_with_cancel(callback.message, t("admin_create_enter_tg", lang), lang=lang)
    await callback.answer()


@router.message(ProvisioningStates.waiting_create_tg_id)
async def create_user_tg_value(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    normalized = normalize_tg_id((message.text or "").strip())
    if normalized is None:
        await answer_with_cancel(message, t("admin_tgid_invalid", lang), lang=lang)
        return
    await state.update_data(create_tg_id=normalized)
    await _finish_create_user(message, state, settings, services, lang, actor_user_id=message.from_user.id)


async def _finish_create_user(
    message: Message,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
    *,
    actor_user_id: int,
) -> None:
    data = await state.get_data()
    await state.clear()
    await answer_with_cancel(message, t("admin_create_preparing", lang), lang=lang)
    try:
        result = await services.admin_provisioning_service.create_client_for_actor(
            actor_user_id=actor_user_id,
            settings=settings,
            panel_id=int(data["create_panel_id"]),
            inbound_id=int(data["create_inbound_id"]),
            client_email=str(data["create_email"]),
            total_gb=int(data["create_total_gb"]),
            expiry_days=int(data["create_expiry_days"]),
            tg_id=str(data.get("create_tg_id") or ""),
        )
    except Exception as exc:
        delegated_error = _delegated_profile_error_text(exc, lang)
        if delegated_error is not None:
            await message.answer(delegated_error)
            await _restore_admin_menu(message, services=services, settings=settings, lang=lang)
            return
        await message.answer(t("admin_edit_config_error", lang, error=exc))
        await _restore_admin_menu(message, services=services, settings=settings, lang=lang)
        return
    await _send_config_bundle(
        message,
        config_name=result["email"],
        total_gb=int(data["create_total_gb"]),
        expiry_days=int(data["create_expiry_days"]),
        vless_uri=result["vless_uri"],
        sub_url=result["sub_url"],
        lang=lang,
    )
    await _restore_admin_menu(message, services=services, settings=settings, lang=lang)


@router.message(F.text.in_(button_variants("btn_edit_config")))
async def start_edit_config(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await state.set_state(ProvisioningStates.waiting_vless_config)
    await answer_with_cancel(message, t("admin_edit_config_prompt", lang), lang=lang)


@router.message(ProvisioningStates.waiting_vless_config)
async def resolve_vless_config(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    raw = (message.text or "").strip()
    if not raw:
        await answer_with_cancel(message, t("admin_edit_config_prompt", lang), lang=lang)
        return
    if not raw.lower().startswith("vless://"):
        if len(raw) < 2:
            await answer_with_cancel(message, t("admin_search_too_short", lang), lang=lang)
            return
        panel_id = await _resolve_panel_for_edit_search(
            message,
            state,
            actor_user_id=message.from_user.id,
            query=raw,
            settings=settings,
            services=services,
            lang=lang,
        )
        if panel_id is None:
            return
        await state.clear()
        try:
            await _show_edit_search_results(
                message,
                actor_user_id=message.from_user.id,
                panel_id=panel_id,
                query=raw,
                settings=settings,
                services=services,
                lang=lang,
            )
            await _restore_admin_menu(message, services=services, settings=settings, lang=lang)
        except Exception as exc:
            await answer_with_cancel(message, t("admin_edit_config_error", lang, error=exc), lang=lang)
        return
    try:
        ref = await services.admin_provisioning_service.resolve_client_from_vless_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            vless_uri=raw,
        )
    except Exception as exc:
        await answer_with_cancel(message, t("admin_edit_config_error", lang, error=exc), lang=lang)
        return
    await state.clear()
    await _show_resolved_edit_target(
        message,
        panel_id=ref.panel_id,
        inbound_id=ref.inbound_id,
        client_uuid=ref.client_uuid,
        settings=settings,
        services=services,
        lang=lang,
    )
    await answer_with_admin_menu(
        message,
        t("menu_management", lang),
        settings=settings,
        services=services,
        lang=lang,
    )


@router.callback_query(F.data.startswith("pecsp:"))
async def pick_panel_for_edit_search(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    data = await state.get_data()
    query = str(data.get("edit_search_query") or "").strip()
    if len(query) < 2:
        await state.clear()
        await callback.answer(t("admin_search_too_short", lang), show_alert=True)
        return
    await state.clear()
    try:
        await _show_edit_search_results(
            callback,
            actor_user_id=callback.from_user.id,
            panel_id=panel_id,
            query=query,
            settings=settings,
            services=services,
            lang=lang,
        )
        await _restore_admin_menu(callback, services=services, settings=settings, lang=lang)
    except Exception as exc:
        if callback.message is not None:
            await callback.message.edit_text(t("admin_edit_config_error", lang, error=exc))
    await callback.answer()


@router.callback_query(F.data.startswith("pecp:"))
async def paginate_edit_search_results(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw, page_raw, query = callback.data.split(":", 3)
        panel_id = int(panel_raw)
        page = int(page_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    try:
        await _show_edit_search_results(
            callback,
            actor_user_id=callback.from_user.id,
            panel_id=panel_id,
            query=query,
            settings=settings,
            services=services,
            lang=lang,
            page=page,
        )
    except Exception as exc:
        if callback.message is not None:
            await callback.message.edit_text(t("admin_edit_config_error", lang, error=exc))
    await callback.answer()


@router.callback_query(F.data.startswith("pecsr:"))
async def refresh_edit_search_results(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw, query = callback.data.split(":", 2)
        panel_id = int(panel_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    try:
        await _show_edit_search_results(
            callback,
            actor_user_id=callback.from_user.id,
            panel_id=panel_id,
            query=query,
            settings=settings,
            services=services,
            lang=lang,
            page=1,
        )
    except Exception as exc:
        if callback.message is not None:
            await callback.message.edit_text(t("admin_edit_config_error", lang, error=exc))
    await callback.answer(t("admin_refresh_done", lang))


@router.callback_query(F.data.startswith("pecs:"))
async def select_edit_search_result(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        _, panel_raw, inbound_raw, client_uuid, page_raw, query = callback.data.split(":", 5)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
        page = int(page_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    try:
        await _show_resolved_edit_target(
            callback,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            settings=settings,
            services=services,
            lang=lang,
            back_callback=f"pecp:{panel_id}:{page}:{query}",
            back_text=t("admin_back", lang),
        )
    except Exception as exc:
        await callback.answer(t("admin_edit_config_error", lang, error=exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("pec:toggle:"))
async def edit_config_toggle_enable(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    try:
        detail, enabled = await services.admin_provisioning_service.toggle_client_for_actor(
            actor_user_id=callback.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
        )
        client_email = str(detail.get("email") or "").strip()
        await _render_edit_detail(
            callback,
            services=services,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            lang=lang,
            back_callback=f"pecp:{panel_id}:1:{client_email}" if client_email else None,
            back_text=t("admin_back", lang),
        )
    except Exception as exc:
        await callback.answer(t("admin_edit_config_error", lang, error=exc), show_alert=True)
        return
    await callback.answer(t("admin_enable_on", lang) if enabled else t("admin_enable_off", lang))


@router.callback_query(F.data.startswith("pec:get_config:"))
async def edit_config_get_config(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await callback.answer(t("status_prepare_config", lang))
    try:
        detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
        client_email = str(detail.get("email") or "").strip()
        if not client_email:
            raise ValueError("client email was not found.")
        await send_existing_config_bundle_for_email(
            callback.message,
            services=services,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
            config_name=client_email,
            total_bytes=int(detail.get("total") or 0),
            expiry=detail.get("expiry"),
            lang=lang,
            filename="client_config_qr.png",
        )
    except Exception as exc:
        await callback.answer(t("admin_edit_config_error", lang, error=exc), show_alert=True)
        return


def _rotate_confirm_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard(
        f"pec:rotate_yes:{panel_id}:{inbound_id}:{client_uuid}",
        f"pec:detail:{panel_id}:{inbound_id}:{client_uuid}",
        lang,
    )


@router.callback_query(F.data.startswith("pec:rotate_ask:"))
async def edit_config_rotate_ask(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await callback.message.answer(
        t("admin_edit_rotate_confirm", lang),
        reply_markup=_rotate_confirm_keyboard(panel_id, inbound_id, client_uuid, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pec:rotate_yes:"))
async def edit_config_rotate_yes(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await callback.answer(t("status_rotating", lang))
    try:
        detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
        client_email = str(detail.get("email") or "").strip()
        if not client_email:
            raise ValueError("client email was not found.")
        prepared = await send_rotation_preview_bundle_for_email(
            callback.message,
            services=services,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_email=client_email,
            config_name=client_email,
            total_bytes=int(detail.get("total") or 0),
            expiry=detail.get("expiry"),
            lang=lang,
            filename="client_config_qr.png",
        )
        await asyncio.sleep(max(0, int(settings.config_rotate_apply_delay_seconds)))
        await services.panel_service.apply_prepared_client_rotation(
            panel_id=int(prepared["panel_id"]),
            inbound_id=int(prepared["inbound_id"]),
            old_uuid=str(prepared["old_uuid"]),
            new_uuid=str(prepared["new_uuid"]),
            new_sub_id=str(prepared["new_sub_id"]),
        )
        await _render_edit_detail(
            callback,
            services=services,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=str(prepared["new_uuid"]),
            lang=lang,
            back_callback=f"pecp:{panel_id}:1:{client_email}",
            back_text=t("admin_back", lang),
        )
    except Exception as exc:
        await callback.answer(t("admin_edit_config_error", lang, error=exc), show_alert=True)
        return
    panel_name, inbound_name = await _panel_inbound_names(services, panel_id=panel_id, inbound_id=inbound_id)
    await _notify_admin_activity(
        callback,
        settings=settings,
        services=services,
        lang=lang,
        action_key="admin_activity_action_rotate_client",
        user=client_email,
        panel=panel_name,
        inbound=inbound_name,
    )
    await callback.message.answer(t("admin_edit_rotate_done", lang))


@router.callback_query(F.data.startswith("pec:tg_input:"))
async def edit_config_set_tg_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await state.update_data(edit_panel_id=panel_id, edit_inbound_id=inbound_id, edit_client_uuid=client_uuid)
    await state.set_state(ProvisioningStates.waiting_edit_tg_id)
    await answer_with_cancel(callback.message, t("admin_enter_tg", lang), lang=lang)
    await callback.answer()


@router.message(ProvisioningStates.waiting_edit_tg_id)
async def edit_config_set_tg_value(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    raw = (message.text or "").strip()
    tg_id = normalize_tg_id(raw)
    if tg_id is None:
        await message.answer(t("admin_tgid_invalid", lang))
        return
    data = await state.get_data()
    await state.clear()
    panel_id = int(data["edit_panel_id"])
    inbound_id = int(data["edit_inbound_id"])
    client_uuid = str(data["edit_client_uuid"])
    if not await _ensure_inbound_access(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", lang))
        await _restore_admin_menu(message, services=services, settings=settings, lang=lang)
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
        await message.answer(t("admin_tgid_saved_bind_failed", lang, error=exc))
        await _restore_admin_menu(message, services=services, settings=settings, lang=lang)
        return
    await message.answer(
        t("admin_tg_done", lang),
        reply_markup=_edit_actions_keyboard(panel_id, inbound_id, client_uuid, lang),
    )
    await _restore_admin_menu(message, services=services, settings=settings, lang=lang)


@router.callback_query(F.data.startswith("pec:detail:"))
async def edit_config_show_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        panel_id, inbound_id, client_uuid = parse_client_callback(callback.data.replace("pec:detail", "cr", 1), "cr")
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await _render_edit_detail(
        callback,
        services=services,
        settings=settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pec:traffic_input:"))
async def edit_config_add_traffic_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await state.update_data(edit_panel_id=panel_id, edit_inbound_id=inbound_id, edit_client_uuid=client_uuid)
    await state.set_state(ProvisioningStates.waiting_edit_add_traffic_gb)
    await callback.message.answer(t("admin_edit_enter_add_traffic", lang))
    await callback.answer()


@router.message(ProvisioningStates.waiting_edit_add_traffic_gb)
async def edit_config_add_traffic_value(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        gb = int((message.text or "").strip())
        if gb <= 0:
            raise ValueError
    except ValueError:
        await message.answer(t("admin_invalid_positive_number", lang))
        return
    data = await state.get_data()
    await state.clear()
    panel_id = int(data["edit_panel_id"])
    inbound_id = int(data["edit_inbound_id"])
    client_uuid = str(data["edit_client_uuid"])
    if not await _ensure_inbound_access(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", lang))
        return
    try:
        await services.admin_provisioning_service.add_client_total_gb_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            add_gb=gb,
        )
    except ValueError as exc:
        delegated_error = _delegated_profile_error_text(exc, lang)
        if delegated_error is not None:
            await message.answer(delegated_error)
            return
        if "insufficient" in str(exc).lower():
            await message.answer(t("finance_insufficient_wallet", lang))
            return
        await message.answer(t("admin_edit_config_error", lang, error=exc))
        return
    except Exception as exc:
        await message.answer(t("admin_edit_config_error", lang, error=exc))
        return
    await message.answer(
        t("admin_edit_traffic_added", lang),
        reply_markup=_edit_actions_keyboard(panel_id, inbound_id, client_uuid, lang),
    )
    await _render_edit_detail(
        message,
        services=services,
        settings=settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
        lang=lang,
    )


@router.callback_query(F.data.startswith("pec:days_input:"))
async def edit_config_add_days_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await state.update_data(edit_panel_id=panel_id, edit_inbound_id=inbound_id, edit_client_uuid=client_uuid)
    await state.set_state(ProvisioningStates.waiting_edit_add_expiry_days)
    await callback.message.answer(t("admin_edit_enter_add_days", lang))
    await callback.answer()


@router.message(ProvisioningStates.waiting_edit_add_expiry_days)
async def edit_config_add_days_value(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        days = int((message.text or "").strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer(t("admin_invalid_positive_number", lang))
        return
    data = await state.get_data()
    await state.clear()
    panel_id = int(data["edit_panel_id"])
    inbound_id = int(data["edit_inbound_id"])
    client_uuid = str(data["edit_client_uuid"])
    if not await _ensure_inbound_access(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await message.answer(t("no_admin_access", lang))
        return
    try:
        await services.admin_provisioning_service.extend_client_expiry_days_for_actor(
            actor_user_id=message.from_user.id,
            settings=settings,
            panel_id=panel_id,
            inbound_id=inbound_id,
            client_uuid=client_uuid,
            add_days=days,
        )
    except ValueError as exc:
        delegated_error = _delegated_profile_error_text(exc, lang)
        if delegated_error is not None:
            await message.answer(delegated_error)
            return
        if "insufficient" in str(exc).lower():
            await message.answer(t("finance_insufficient_wallet", lang))
            return
        await message.answer(t("admin_edit_config_error", lang, error=exc))
        return
    except Exception as exc:
        await message.answer(t("admin_edit_config_error", lang, error=exc))
        return
    await message.answer(
        t("admin_edit_days_added", lang),
        reply_markup=_edit_actions_keyboard(panel_id, inbound_id, client_uuid, lang),
    )


@router.callback_query(F.data.startswith("pec:delete_ask:"))
async def edit_config_delete_ask(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=_delete_confirm_keyboard(panel_id, inbound_id, client_uuid, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("pec:delete_yes:"))
async def edit_config_delete_yes(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        _, _, panel_raw, inbound_raw, client_uuid = callback.data.split(":", 4)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _ensure_inbound_access(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await services.admin_provisioning_service.delete_client_for_actor(
        actor_user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
        client_uuid=client_uuid,
    )
    await callback.message.edit_text(t("admin_edit_deleted", lang))
    await callback.answer()
