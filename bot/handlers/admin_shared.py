from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from bot.callbacks import NOOP, encode_inbound_page, encode_online_page
from bot.config import Settings
from bot.i18n import t
from bot.keyboards import admin_keyboard, cancel_only_keyboard
from bot.pagination import chunk_buttons, paginate_window
from bot.services.container import ServiceContainer
from bot.utils import (
    display_name_from_parts,
    format_bytes,
    inbound_display_name as format_inbound_display_name,
    now_jalali_datetime,
    parse_epoch,
    relative_remaining_time,
    to_jalali_datetime,
    to_persian_digits,
)

CLIENTS_PER_PAGE = 20


def _truncate_button_text(text: str, max_len: int = 60) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _panel_button_text(panel: dict) -> str:
    ok = "✅" if panel["last_login_ok"] else "❌"
    star = "⭐ " if panel.get("is_default") else ""
    return f"{star}{ok} {panel['name']}"


def inline_button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def single_button_inline_keyboard(text: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[inline_button(text, callback_data)]])


def _append_preset_rows(
    rows: list[list[InlineKeyboardButton]],
    *,
    items: list[tuple[str, str]],
    columns: int,
) -> None:
    current_row: list[InlineKeyboardButton] = []
    for text, callback_data in items:
        current_row.append(inline_button(text, callback_data))
        if len(current_row) == columns:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)


def _pagination_nav_row(
    *,
    page: int,
    total_pages: int,
    lang: str | None,
    callback_for_page,
) -> list[InlineKeyboardButton] | None:
    if total_pages <= 1:
        return None
    row: list[InlineKeyboardButton] = []
    if page > 1:
        row.append(inline_button(t("admin_page_prev", lang), callback_for_page(page - 1)))
    row.append(inline_button(f"{page}/{total_pages}", NOOP))
    if page < total_pages:
        row.append(inline_button(t("admin_page_next", lang), callback_for_page(page + 1)))
    return row


def is_root_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


async def reject_if_not_admin(message: Message, settings: Settings) -> bool:
    if is_root_admin(message.from_user.id, settings):
        return False
    await message.answer(t("no_admin_access", None))
    return True


async def reject_callback_if_not_admin(callback: CallbackQuery, settings: Settings) -> bool:
    if is_root_admin(callback.from_user.id, settings):
        return False
    await callback.answer(t("no_admin_access", None), show_alert=True)
    return True


async def reject_if_not_any_admin(
    message: Message,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    if await services.access_service.is_any_admin(message.from_user.id, settings):
        return False
    await message.answer(t("no_admin_access", None))
    return True


async def reject_callback_if_not_any_admin(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    if await services.access_service.is_any_admin(callback.from_user.id, settings):
        return False
    await callback.answer(t("no_admin_access", None), show_alert=True)
    return True


async def admin_keyboard_for_user(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None = None,
) -> ReplyKeyboardMarkup:
    # helper retained as a coroutine boundary for future role-sensitive keyboards
    context = await services.access_service.get_admin_context(user_id, settings)
    return admin_keyboard(context.mode, lang)


async def admin_reply_markup_for_message(
    message: Message,
    *,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None = None,
) -> ReplyKeyboardMarkup:
    return await admin_keyboard_for_user(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )


async def answer_with_admin_menu(
    message: Message,
    text: str,
    *,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None = None,
) -> None:
    await message.answer(
        text,
        reply_markup=await admin_reply_markup_for_message(
            message,
            settings=settings,
            services=services,
            lang=lang,
        ),
    )


async def answer_with_cancel(
    message: Message,
    text: str,
    *,
    lang: str | None = None,
) -> None:
    await message.answer(text, reply_markup=cancel_only_keyboard(lang))


def two_button_inline_keyboard(
    left_text: str,
    left_callback: str,
    right_text: str,
    right_callback: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button(left_text, left_callback),
                inline_button(right_text, right_callback),
            ]
        ]
    )


def yes_no_inline_keyboard(
    yes_callback: str,
    no_callback: str,
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    return two_button_inline_keyboard(
        t("btn_yes", lang),
        yes_callback,
        t("btn_no", lang),
        no_callback,
    )


def two_factor_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard("twofa_yes", "twofa_no", lang)


def normalize_tg_id(raw: str) -> str | None:
    tg_id = "" if raw == "-" else raw
    if tg_id and not (tg_id.lstrip("-").isdigit() or tg_id.startswith("@")):
        return None
    return tg_id


async def bind_services_for_tg_identity(
    *,
    services: ServiceContainer,
    panel_id: int,
    inbound_id: int,
    client_email: str,
    tg_id: str,
) -> None:
    resolved_user_id: int | None = None
    resolved_username: str | None = None
    if not tg_id:
        return
    if tg_id.lstrip("-").isdigit():
        resolved_user_id = int(tg_id)
        user = await services.db.get_user_by_telegram_id(resolved_user_id)
        if user is not None:
            resolved_username = str(user.get("username") or "").strip() or None
    else:
        user = await services.db.find_user_by_username(tg_id)
        if user is not None:
            resolved_user_id = int(user["telegram_user_id"])
            resolved_username = str(user.get("username") or "").strip() or None
    if resolved_user_id is None:
        return
    await services.panel_service.bind_service_to_user(
        panel_id=panel_id,
        telegram_user_id=resolved_user_id,
        client_email=client_email,
        service_name=None,
        inbound_id=inbound_id,
    )
    await services.panel_service.bind_services_for_telegram_identity(
        telegram_user_id=resolved_user_id,
        username=resolved_username,
    )


async def notify_delegated_admin_activity(
    source: Message | CallbackQuery,
    *,
    settings: Settings,
    services: ServiceContainer,
    text: str,
) -> None:
    await services.admin_provisioning_service.record_admin_activity(
        actor_user_id=source.from_user.id,
        settings=settings,
        text=text,
    )


def back_to_detail_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return single_button_inline_keyboard(
        t("admin_back_to_detail", lang),
        f"cr:{panel_id}:{inbound_id}:{client_uuid}",
    )


async def callback_error_alert(callback: CallbackQuery, exc: Exception, lang: str | None = None) -> None:
    await callback.answer(f"{t('error_prefix', lang)}: {exc}", show_alert=True)


def panels_list_text(lang: str | None = None) -> str:
    return t("admin_panels_list", lang)


def panel_select_keyboard(panels: list[dict], callback_prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for panel in panels:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_panel_button_text(panel),
                    callback_data=f"{callback_prefix}:{panel['id']}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panels_glass_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        rows.append(
            [
                inline_button(_panel_button_text(p), f"panel_default_toggle:{p['id']}"),
                inline_button("🔑", f"panel_access_ask:{p['id']}"),
                inline_button("🗑️", f"panel_delete_ask:{p['id']}"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_delete_confirm_keyboard(panel_id: int, lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard(f"panel_delete_yes:{panel_id}", "panel_delete_no", lang)


def bind_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, "bind_panel_pick")


def inbounds_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, "inbounds_panel_pick")


def users_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, "users_panel_pick")


def online_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, "online_panel_pick")


def inbound_display_name(inbound: dict) -> str:
    return format_inbound_display_name(inbound)


def users_inbounds_keyboard(panel_id: int, inbounds: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for inbound in inbounds:
        inbound_id = inbound.get("id")
        if inbound_id is None:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=inbound_display_name(inbound),
                    callback_data=f"users_inbound_pick:{panel_id}:{int(inbound_id)}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_clients_keyboard(
    panel_id: int,
    inbound_id: int,
    clients: list[dict],
    lang: str | None = None,
    *,
    page: int = 1,
) -> InlineKeyboardMarkup:
    page, total_pages, start, end = paginate_window(len(clients), page, CLIENTS_PER_PAGE)
    page_buttons: list[InlineKeyboardButton] = []
    for client in clients[start:end]:
        email = str(client.get("email") or "").strip()
        uuid = str(client.get("uuid") or "").strip()
        if not email or not uuid:
            continue
        page_buttons.append(inline_button(_truncate_button_text(email), f"uo:{panel_id}:{inbound_id}:{uuid}"))
    rows = chunk_buttons(page_buttons, columns=2)
    nav_row = _pagination_nav_row(
        page=page,
        total_pages=total_pages,
        lang=lang,
        callback_for_page=lambda target_page: encode_inbound_page(panel_id, inbound_id, target_page),
    )
    if nav_row is not None:
        rows.append(nav_row)
    rows.append([inline_button(t("admin_back_to_inbounds", lang), f"users_panel_pick:{panel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_bulk_actions_keyboard(panel_id: int, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button(t("admin_bulk_add_traffic", lang), f"pabt:{panel_id}")],
            [inline_button(t("admin_bulk_add_days", lang), f"pabd:{panel_id}")],
        ]
    )


def _build_pagination_callback(
    *,
    mode: str,
    panel_id: int,
    page: int,
    query: str | None = None,
) -> str:
    return encode_online_page(mode, panel_id, page, query)


def online_clients_keyboard(
    panel_id: int,
    clients: list[dict],
    lang: str | None = None,
    *,
    page: int = 1,
) -> InlineKeyboardMarkup:
    return client_list_keyboard(
        panel_id,
        clients,
        lang,
        mode="on",
        page=page,
    )


def action_panel_select_keyboard(panels: list[dict], action_prefix: str) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, action_prefix)


def client_list_keyboard(
    panel_id: int,
    clients: list[dict],
    lang: str | None = None,
    *,
    show_last_online: bool = False,
    tz_name: str = "UTC",
    mode: str = "on",
    page: int = 1,
    query: str | None = None,
) -> InlineKeyboardMarkup:
    page, total_pages, start, end = paginate_window(len(clients), page, CLIENTS_PER_PAGE)
    page_buttons: list[InlineKeyboardButton] = []
    for client in clients[start:end]:
        email = str(client.get("email") or "").strip()
        inbound_id = int(client.get("inbound_id") or 0)
        uuid = str(client.get("uuid") or "").strip()
        if not email or inbound_id <= 0 or not uuid:
            continue
        if show_last_online and client.get("last_online"):
            label = f"{email} | {format_datetime(int(client['last_online']), tz_name)}"
            text = _truncate_button_text(f"🕘 {label}")
        elif mode == "lr" and client.get("remaining_bytes") is not None:
            remaining = format_bytes(int(client.get("remaining_bytes") or 0), lang)
            text = _truncate_button_text(f"🪫 {email} | {remaining}")
        elif bool(client.get("enabled", True)):
            text = _truncate_button_text(f"🟢 {email}")
        else:
            text = _truncate_button_text(f"⚫ {email}")
        detail_prefix = "uodl" if mode == "ds" else "uolr" if mode == "lr" else "uol"
        page_buttons.append(inline_button(text, f"{detail_prefix}:{panel_id}:{inbound_id}:{uuid}"))
    rows = chunk_buttons(page_buttons, columns=2)
    nav_row = _pagination_nav_row(
        page=page,
        total_pages=total_pages,
        lang=lang,
        callback_for_page=lambda target_page: _build_pagination_callback(
            mode=mode,
            panel_id=panel_id,
            page=target_page,
            query=query,
        ),
    )
    if nav_row is not None:
        rows.append(nav_row)
    refresh_callback = f"uolp:{panel_id}" if mode == "on" else _build_pagination_callback(
        mode=mode,
        panel_id=panel_id,
        page=page,
        query=query,
    )
    rows.append([inline_button(t("admin_refresh_list", lang), refresh_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_config_actions_keyboard(
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    enabled: bool,
    lang: str | None = None,
    *,
    back_callback: str | None = None,
    back_text: str | None = None,
) -> InlineKeyboardMarkup:
    toggle_text = t("admin_toggle_on", lang) if enabled else t("admin_toggle_off", lang)
    rows = [
        [
            inline_button(t("btn_refresh_config", lang), f"pec:detail:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
        [
            inline_button(t("btn_rotate_link", lang), f"pec:rotate_ask:{panel_id}:{inbound_id}:{client_uuid}"),
            inline_button(t("btn_get_config", lang), f"pec:get_config:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
        [
            inline_button(t("admin_edit_add_traffic", lang), f"pec:traffic_input:{panel_id}:{inbound_id}:{client_uuid}"),
            inline_button(t("admin_edit_add_days", lang), f"pec:days_input:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
        [inline_button(t("admin_set_tg", lang), f"pec:tg_input:{panel_id}:{inbound_id}:{client_uuid}")],
        [inline_button(toggle_text, f"pec:toggle:{panel_id}:{inbound_id}:{client_uuid}")],
        [inline_button(t("admin_edit_delete_client", lang), f"pec:delete_ask:{panel_id}:{inbound_id}:{client_uuid}")],
    ]
    if back_callback:
        rows.append([inline_button(back_text or t("admin_back", lang), back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_actions_keyboard(
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    enabled: bool,
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    return edit_config_actions_keyboard(panel_id, inbound_id, client_uuid, enabled, lang)


def client_confirm_reset_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button(t("admin_confirm_reset", lang), f"ry:{panel_id}:{inbound_id}:{client_uuid}")],
            [inline_button(t("admin_cancel_reset", lang), f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        ]
    )


def client_traffic_menu_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [inline_button(t("admin_cancel", lang), f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            inline_button(t("admin_unlimited_reset", lang), f"ts:{panel_id}:{inbound_id}:{client_uuid}:unlimited"),
            inline_button(t("admin_custom", lang), f"tc:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
    ]
    _append_preset_rows(
        rows,
        items=[(f"{gb} GB", f"ts:{panel_id}:{inbound_id}:{client_uuid}:{gb}") for gb in [1, 5, 10, 20, 30, 40, 50, 60, 80, 100, 150, 200]],
        columns=3,
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_expiry_menu_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [inline_button(t("admin_cancel_reset", lang), f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            inline_button(t("admin_unlimited_reset", lang), f"es:{panel_id}:{inbound_id}:{client_uuid}:unlimited"),
            inline_button(t("admin_custom", lang), f"ec:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
    ]
    _append_preset_rows(
        rows,
        items=[
            ("7d", f"es:{panel_id}:{inbound_id}:{client_uuid}:7"),
            ("10d", f"es:{panel_id}:{inbound_id}:{client_uuid}:10"),
            ("14d", f"es:{panel_id}:{inbound_id}:{client_uuid}:14"),
            ("20d", f"es:{panel_id}:{inbound_id}:{client_uuid}:20"),
            ("1m", f"es:{panel_id}:{inbound_id}:{client_uuid}:30"),
            ("3m", f"es:{panel_id}:{inbound_id}:{client_uuid}:90"),
            ("6m", f"es:{panel_id}:{inbound_id}:{client_uuid}:180"),
            ("12m", f"es:{panel_id}:{inbound_id}:{client_uuid}:365"),
        ],
        columns=2,
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_iplimit_menu_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [inline_button(t("admin_cancel_ip_limit", lang), f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            inline_button(t("admin_unlimited_reset", lang), f"is:{panel_id}:{inbound_id}:{client_uuid}:unlimited"),
            inline_button(t("admin_custom", lang), f"ic:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
    ]
    _append_preset_rows(
        rows,
        items=[(str(value), f"is:{panel_id}:{inbound_id}:{client_uuid}:{value}") for value in range(1, 11)],
        columns=3,
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_ips_log_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button(t("admin_clear_ip_log", lang), f"ix:{panel_id}:{inbound_id}:{client_uuid}")],
            [inline_button(t("admin_back", lang), f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        ]
    )


def human_bytes(value: int, lang: str | None = None) -> str:
    return format_bytes(value, lang or "fa")


def _inbound_client_state_counts(inbound: dict) -> tuple[int, int, int]:
    clients = inbound.get("clientStats")
    if not isinstance(clients, list):
        return 0, 0, 0
    total_count = len(clients)
    active_count = 0
    inactive_count = 0
    for client in clients:
        enabled = client.get("enable")
        if enabled is None:
            enabled = client.get("enabled", True)
        if bool(enabled):
            active_count += 1
        else:
            inactive_count += 1
    return total_count, active_count, inactive_count


def format_inbounds_list(panel_name: str, rows: list[dict], lang: str | None = None) -> str:
    if not rows:
        return f"{t('admin_inbounds_title', lang)}\n{t('admin_panel_label', lang)}: {panel_name}\n\n{t('admin_no_inbounds', lang)}"
    lines = [f"{t('admin_inbounds_title', lang)}", f"{t('admin_panel_label', lang)}: {panel_name}", ""]
    for offset, inbound in enumerate(rows):
        status = t("admin_enabled", lang) if inbound.get("enable") else t("admin_disabled", lang)
        client_count, _, inactive_count = _inbound_client_state_counts(inbound)
        remark = str(inbound.get("remark") or "-")
        up_value = int(inbound.get("up") or 0)
        down_value = int(inbound.get("down") or 0)
        up = human_bytes(up_value, lang)
        down = human_bytes(down_value, lang)
        total = human_bytes(up_value + down_value, lang)
        expiry = inbound.get("expiryTime")
        expiry_epoch = parse_epoch(expiry)
        expiry_text = t("admin_unlimited", lang) if not expiry_epoch else to_jalali_datetime(expiry_epoch, "Asia/Tehran")
        lines.append(
            f"{t('admin_inbound_name', lang)}: {remark}\n"
            f"{t('admin_port', lang)}: {inbound.get('port', '-')}\n"
            f"{t('admin_traffic', lang)}: {total}\n"
            f"({t('admin_download', lang)}: {down} , {t('admin_upload', lang)}: {up})\n"
            f"{t('admin_expiry', lang)}: {expiry_text}\n"
            f"{t('admin_clients_count', lang)}: {client_count}\n"
            f"{t('admin_inactive_clients_count', lang)}: {inactive_count}\n"
            f"{t('admin_status', lang)}: {status}"
        )
        if offset != len(rows) - 1:
            lines.append("")
    return "\n".join(lines)


def format_inbounds_overview(
    panel_name: str,
    rows: list[dict],
    lang: str | None = None,
    *,
    total_usage_bytes: int | None = None,
    total_clients_count: int | None = None,
    total_active_clients_count: int | None = None,
    total_inactive_clients_count: int | None = None,
    total_inbounds_count: int | None = None,
) -> str:
    if not rows:
        return (
            f"{t('admin_inbounds_overview_title', lang)}\n"
            f"{t('admin_panel_label', lang)}: {panel_name}\n\n"
            f"{t('admin_no_inbounds', lang)}"
        )
    total_usage = 0 if total_usage_bytes is None else total_usage_bytes
    total_clients = 0 if total_clients_count is None else total_clients_count
    total_active_clients = 0 if total_active_clients_count is None else total_active_clients_count
    total_inactive_clients = 0 if total_inactive_clients_count is None else total_inactive_clients_count
    total_inbounds = len(rows) if total_inbounds_count is None else total_inbounds_count
    if (
        total_usage_bytes is None
        or total_clients_count is None
        or total_active_clients_count is None
        or total_inactive_clients_count is None
    ):
        total_usage = 0
        total_clients = 0
        total_active_clients = 0
        total_inactive_clients = 0
        for inbound in rows:
            up_value = int(inbound.get("up") or 0)
            down_value = int(inbound.get("down") or 0)
            total_usage += up_value + down_value
            client_count, active_count, inactive_count = _inbound_client_state_counts(inbound)
            total_clients += client_count
            total_active_clients += active_count
            total_inactive_clients += inactive_count

    lines = [
        f"{t('admin_inbounds_overview_title', lang)}",
        f"{t('admin_panel_label', lang)}: {panel_name}",
        f"{t('admin_panel_total_usage', lang)}: {human_bytes(total_usage, lang)}",
        f"{t('admin_inbounds_count', lang)}: {to_persian_digits(total_inbounds) if (lang or 'fa') == 'fa' else total_inbounds}",
        f"{t('admin_active_clients_count', lang)}: {to_persian_digits(total_active_clients) if (lang or 'fa') == 'fa' else total_active_clients}",
        f"{t('admin_inactive_clients_count', lang)}: {to_persian_digits(total_inactive_clients) if (lang or 'fa') == 'fa' else total_inactive_clients}",
        "",
    ]
    for offset, inbound in enumerate(rows):
        client_count, _, inactive_count = _inbound_client_state_counts(inbound)
        remark = str(inbound.get("remark") or "-")
        up_value = int(inbound.get("up") or 0)
        down_value = int(inbound.get("down") or 0)
        total = human_bytes(up_value + down_value, lang)
        up = human_bytes(up_value, lang)
        down = human_bytes(down_value, lang)
        expiry = inbound.get("expiryTime")
        expiry_epoch = parse_epoch(expiry)
        expiry_text = t("admin_unlimited_reset_value", lang) if not expiry_epoch else to_jalali_datetime(expiry_epoch, "Asia/Tehran")
        status = t("admin_enabled", lang) if inbound.get("enable") else t("admin_disabled", lang)
        lines.append(
            f"{t('admin_inbound_name', lang)}: {remark}\n"
            f"{t('admin_port', lang)}: {to_persian_digits(inbound.get('port', '-')) if (lang or 'fa') == 'fa' else inbound.get('port', '-')}\n"
            f"{t('admin_traffic', lang)}: {total}\n"
            f"({t('admin_download', lang)}: {down} , {t('admin_upload', lang)}: {up})\n"
            f"{t('admin_expiry', lang)}: {expiry_text}\n"
            f"{t('admin_clients_count', lang)}: {to_persian_digits(client_count) if (lang or 'fa') == 'fa' else client_count}\n"
            f"{t('admin_inactive_clients_count', lang)}: {to_persian_digits(inactive_count) if (lang or 'fa') == 'fa' else inactive_count}\n"
            f"{t('admin_status', lang)}: {status}"
        )
        if offset != len(rows) - 1:
            lines.append("")
    return "\n".join(lines)


def split_inbounds_for_telegram(panel_name: str, rows: list[dict], chunk_size: int = 12, lang: str | None = None) -> list[str]:
    if not rows:
        return [format_inbounds_list(panel_name, rows, lang)]
    chunks: list[str] = []
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        chunks.append(format_inbounds_list(panel_name, chunk, lang))
    return chunks


def split_inbounds_overview_for_telegram(
    panel_name: str,
    rows: list[dict],
    chunk_size: int = 8,
    lang: str | None = None,
) -> list[str]:
    if not rows:
        return [format_inbounds_overview(panel_name, rows, lang)]
    total_usage = 0
    total_clients = 0
    total_active_clients = 0
    total_inactive_clients = 0
    total_inbounds = len(rows)
    for inbound in rows:
        up_value = int(inbound.get("up") or 0)
        down_value = int(inbound.get("down") or 0)
        total_usage += up_value + down_value
        client_count, active_count, inactive_count = _inbound_client_state_counts(inbound)
        total_clients += client_count
        total_active_clients += active_count
        total_inactive_clients += inactive_count
    chunks: list[str] = []
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        chunks.append(
            format_inbounds_overview(
                panel_name,
                chunk,
                lang,
                total_usage_bytes=total_usage,
                total_clients_count=total_clients,
                total_active_clients_count=total_active_clients,
                total_inactive_clients_count=total_inactive_clients,
                total_inbounds_count=total_inbounds,
            )
        )
    return chunks


async def show_inbounds_overview_for_panel(message: Message, services: ServiceContainer, settings: Settings, panel_id: int) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(
            t("admin_panel_not_found", None),
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    await message.answer(t("admin_fetching_inbounds_alt", None))
    try:
        rows = await services.panel_service.list_inbounds(panel_id)
    except Exception as exc:
        await message.answer(
            f"{t('admin_error_fetch_inbounds', None)}:\n{exc}",
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    cards = split_inbounds_overview_for_telegram(panel["name"], rows)
    for idx, card in enumerate(cards):
        await message.answer(
            card,
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services) if idx == 0 else None,
        )


def parse_client_callback(data: str, prefix: str) -> tuple[int, int, str]:
    try:
        action, panel_raw, inbound_raw, client_uuid = data.split(":", 3)
        if action != prefix:
            raise ValueError
        return int(panel_raw), int(inbound_raw), client_uuid
    except Exception as exc:
        raise ValueError("callback_data_invalid") from exc


def parse_client_callback_with_value(data: str, prefix: str) -> tuple[int, int, str, str]:
    try:
        action, panel_raw, inbound_raw, client_uuid, value = data.split(":", 4)
        if action != prefix:
            raise ValueError
        return int(panel_raw), int(inbound_raw), client_uuid, value
    except Exception as exc:
        raise ValueError("callback_data_invalid") from exc


def format_datetime(epoch_seconds: int | None, tz_name: str, lang: str | None = None) -> str:
    if not epoch_seconds:
        return t("admin_unlimited", lang)
    return to_jalali_datetime(epoch_seconds, tz_name)


def format_client_detail(detail: dict, tz_name: str, lang: str | None = None) -> str:
    enabled_text = t("admin_yes", lang) if detail.get("enabled") else t("admin_no", lang)
    online_text = t("admin_online", lang) if detail.get("online") else t("admin_offline", lang)
    expiry = detail.get("expiry")
    expiry_line = format_datetime(expiry, tz_name, lang)
    if expiry:
        expiry_line = f"{expiry_line} ({relative_remaining_time(expiry, tz_name, lang)})"
    up = human_bytes(int(detail.get("up") or 0), lang)
    down = human_bytes(int(detail.get("down") or 0), lang)
    used = human_bytes(int(detail.get("used") or 0), lang)
    total_raw = int(detail.get("total") or 0)
    total_text = t("admin_unlimited_reset_value", lang) if total_raw <= 0 else human_bytes(total_raw, lang)
    refreshed_at = now_jalali_datetime(tz_name)
    return t(
        "admin_detail",
        lang,
        email=detail.get("email"),
        enabled=enabled_text,
        online=online_text,
        expiry=expiry_line,
        up=up,
        down=down,
        used=used,
        total=total_text,
        refreshed_at=refreshed_at,
    )


async def render_client_detail(
    callback: CallbackQuery | Message,
    services: ServiceContainer,
    settings: Settings,
    *,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    lang: str | None = None,
    back_callback: str | None = None,
    back_text: str | None = None,
) -> None:
    target_message = callback.message if isinstance(callback, CallbackQuery) else callback
    if target_message is None:
        return
    resolved_lang = lang
    if resolved_lang is None and callback.from_user is not None:
        resolved_lang = await services.db.get_user_language(callback.from_user.id)
    try:
        detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
    except Exception as exc:
        if isinstance(callback, CallbackQuery):
            await target_message.edit_text(f"{t('admin_error_fetch_client', resolved_lang)}:\n{exc}")
        else:
            await target_message.answer(f"{t('admin_error_fetch_client', resolved_lang)}:\n{exc}")
        return
    text = format_client_detail(detail, settings.timezone, resolved_lang)
    markup = edit_config_actions_keyboard(
        panel_id,
        inbound_id,
        client_uuid,
        bool(detail.get("enabled")),
        resolved_lang,
        back_callback=back_callback,
        back_text=back_text,
    )
    if isinstance(callback, CallbackQuery):
        await target_message.edit_text(text, reply_markup=markup)
    else:
        await target_message.answer(text, reply_markup=markup)


async def ensure_client_access(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    panel_id: int,
    inbound_id: int,
    client_uuid: str | None,
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
    comment_owner = str(detail.get("comment") or "").strip().split(":", 1)[0].strip()
    return comment_owner == str(owner_filter)


def actor_display_name(source: Message | CallbackQuery) -> str:
    user = source.from_user
    if user is None:
        return "unknown"
    return display_name_from_parts(
        full_name=user.full_name,
        username=user.username,
        fallback=user.id,
    )


async def set_client_action_context(state: FSMContext, *, panel_id: int, inbound_id: int, client_uuid: str) -> None:
    await state.update_data(
        client_manage_panel_id=panel_id,
        client_manage_inbound_id=inbound_id,
        client_manage_uuid=client_uuid,
    )


async def refresh_panels_message(callback: CallbackQuery, services: ServiceContainer, settings: Settings) -> None:
    if callback.message is None:
        return
    panels = await services.access_service.list_accessible_panels(
        user_id=callback.from_user.id,
        settings=settings,
    )
    if not panels:
        await callback.message.edit_text(t("bind_no_panel", None))
        return
    await callback.message.edit_text(panels_list_text(), reply_markup=panels_glass_keyboard(panels))


async def show_inbounds_for_panel(message: Message, services: ServiceContainer, settings: Settings, panel_id: int) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(
            t("admin_panel_not_found", None),
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    await message.answer(t("admin_fetching_inbounds_alt", None))
    try:
        rows = await services.panel_service.list_inbounds(panel_id)
    except Exception as exc:
        await message.answer(
            f"{t('admin_error_fetch_inbounds', None)}:\n{exc}",
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    cards = split_inbounds_for_telegram(panel["name"], rows)
    for idx, card in enumerate(cards):
        await message.answer(
            card,
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services) if idx == 0 else None,
        )


async def show_users_inbounds_for_panel_message(
    message: Message,
    services: ServiceContainer,
    settings: Settings,
    panel_id: int,
    *,
    allowed_inbound_ids: set[int] | None = None,
) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(
            t("admin_panel_not_found", None),
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    await message.answer(t("admin_fetching_inbounds", None))
    try:
        inbounds = await services.panel_service.list_inbounds(panel_id)
    except Exception as exc:
        await message.answer(
            f"{t('admin_error_fetch_inbounds', None)}:\n{exc}",
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    if allowed_inbound_ids is not None:
        inbounds = [item for item in inbounds if int(item.get("id") or 0) in allowed_inbound_ids]
    if not inbounds:
        await message.answer(
            t("admin_no_inbound_for_panel", None),
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    await message.answer(
        t("admin_panel_and_pick_inbound", None, name=panel["name"]),
        reply_markup=users_inbounds_keyboard(panel_id, inbounds),
    )


async def show_users_inbounds_for_panel_callback(
    callback: CallbackQuery,
    services: ServiceContainer,
    panel_id: int,
    *,
    allowed_inbound_ids: set[int] | None = None,
) -> None:
    if callback.message is None:
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.message.edit_text(t("admin_panel_not_found", None))
        return
    try:
        inbounds = await services.panel_service.list_inbounds(panel_id)
    except Exception as exc:
        await callback.message.edit_text(f"{t('admin_error_fetch_inbounds', None)}:\n{exc}")
        return
    if allowed_inbound_ids is not None:
        inbounds = [item for item in inbounds if int(item.get("id") or 0) in allowed_inbound_ids]
    if not inbounds:
        await callback.message.edit_text(t("admin_no_inbound_for_panel", None))
        return
    await callback.message.edit_text(
        t("admin_panel_and_pick_inbound", None, name=panel["name"]),
        reply_markup=users_inbounds_keyboard(panel_id, inbounds),
    )


async def show_online_clients_for_panel_message(
    message: Message,
    services: ServiceContainer,
    settings: Settings,
    panel_id: int,
    *,
    owner_admin_user_id: int | None = None,
    allowed_inbound_ids: set[int] | None = None,
) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(
            t("admin_panel_not_found", None),
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    await message.answer(t("admin_fetching_online", None))
    try:
        clients = await services.panel_service.list_online_clients(
            panel_id,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
    except Exception as exc:
        await message.answer(
            f"{t('admin_error_fetch_online', None)}:\n{exc}",
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    if not clients:
        await message.answer(
            t("admin_no_online", None, name=panel["name"]),
            reply_markup=await admin_reply_markup_for_message(message, settings=settings, services=services),
        )
        return
    await message.answer(
        t("admin_online_header", None, name=panel["name"], count=len(clients)),
        reply_markup=online_clients_keyboard(panel_id, clients),
    )


async def show_online_clients_for_panel_callback(
    callback: CallbackQuery,
    services: ServiceContainer,
    panel_id: int,
    *,
    owner_admin_user_id: int | None = None,
    allowed_inbound_ids: set[int] | None = None,
) -> None:
    if callback.message is None:
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.message.edit_text(t("admin_panel_not_found", None))
        return
    try:
        clients = await services.panel_service.list_online_clients(
            panel_id,
            owner_admin_user_id=owner_admin_user_id,
            allowed_inbound_ids=allowed_inbound_ids,
        )
    except Exception as exc:
        await callback.message.edit_text(f"{t('admin_error_fetch_online', None)}:\n{exc}")
        return
    if not clients:
        await callback.message.edit_text(t("admin_no_online", None, name=panel["name"]))
        return
    await callback.message.edit_text(
        t("admin_online_header", None, name=panel["name"], count=len(clients)),
        reply_markup=online_clients_keyboard(panel_id, clients),
    )


def bind_usage_text(lang: str | None = None) -> str:
    return t("bind_usage", lang)


def parse_bind_command_args(args: list[str]) -> tuple[int | None, int, str, str | None]:
    if len(args) < 2:
        raise ValueError("usage")
    try:
        first_num = int(args[0])
    except ValueError as exc:
        raise ValueError("ids_must_be_int") from exc

    explicit_panel_id: int | None = None
    if len(args) >= 3:
        try:
            second_num = int(args[1])
            explicit_panel_id = first_num
            telegram_user_id = second_num
            client_email = args[2].strip()
            service_name = " ".join(args[3:]).strip() if len(args) > 3 else None
        except ValueError:
            telegram_user_id = first_num
            client_email = args[1].strip()
            service_name = " ".join(args[2:]).strip() if len(args) > 2 else None
    else:
        telegram_user_id = first_num
        client_email = args[1].strip()
        service_name = None

    if not client_email:
        raise ValueError("client_email_empty")
    if service_name == "":
        service_name = None
    return explicit_panel_id, telegram_user_id, client_email, service_name
