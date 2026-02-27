from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import NOOP, encode_inbound_page, encode_online_page
from bot.config import Settings
from bot.i18n import t
from bot.keyboards import admin_keyboard
from bot.pagination import chunk_buttons, paginate_window
from bot.services.container import ServiceContainer
from bot.utils import now_jalali_datetime, parse_epoch, relative_remaining_time, to_jalali_datetime

CLIENTS_PER_PAGE = 20


def _truncate_button_text(text: str, max_len: int = 60) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


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
        row.append(InlineKeyboardButton(text=t("admin_page_prev", lang), callback_data=callback_for_page(page - 1)))
    row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data=NOOP))
    if page < total_pages:
        row.append(InlineKeyboardButton(text=t("admin_page_next", lang), callback_data=callback_for_page(page + 1)))
    return row


def is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


async def reject_if_not_admin(message: Message, settings: Settings) -> bool:
    if is_admin(message.from_user.id, settings):
        return False
    await message.answer(t("no_admin_access", None))
    return True


async def reject_callback_if_not_admin(callback: CallbackQuery, settings: Settings) -> bool:
    if is_admin(callback.from_user.id, settings):
        return False
    await callback.answer(t("no_admin_access", None), show_alert=True)
    return True


def two_factor_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="twofa_yes"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="twofa_no"),
            ]
        ]
    )


def panels_list_text(lang: str | None = None) -> str:
    return t("admin_panels_list", lang)


def panels_glass_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        ok = "✅" if p["last_login_ok"] else "❌"
        star = "⭐ " if p.get("is_default") else ""
        text = f"{star}{ok} {p['name']}"
        rows.append(
            [
                InlineKeyboardButton(text=text, callback_data=f"panel_default_toggle:{p['id']}"),
                InlineKeyboardButton(text="🗑️", callback_data=f"panel_delete_ask:{p['id']}"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_delete_confirm_keyboard(panel_id: int, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data=f"panel_delete_yes:{panel_id}"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="panel_delete_no"),
            ]
        ]
    )


def bind_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        ok = "✅" if p["last_login_ok"] else "❌"
        star = "⭐ " if p.get("is_default") else ""
        rows.append([InlineKeyboardButton(text=f"{star}{ok} {p['name']}", callback_data=f"bind_panel_pick:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inbounds_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        ok = "✅" if p["last_login_ok"] else "❌"
        star = "⭐ " if p.get("is_default") else ""
        rows.append([InlineKeyboardButton(text=f"{star}{ok} {p['name']}", callback_data=f"inbounds_panel_pick:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        ok = "✅" if p["last_login_ok"] else "❌"
        star = "⭐ " if p.get("is_default") else ""
        rows.append([InlineKeyboardButton(text=f"{star}{ok} {p['name']}", callback_data=f"users_panel_pick:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def online_panel_select_keyboard(panels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        ok = "✅" if p["last_login_ok"] else "❌"
        star = "⭐ " if p.get("is_default") else ""
        rows.append([InlineKeyboardButton(text=f"{star}{ok} {p['name']}", callback_data=f"online_panel_pick:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inbound_display_name(inbound: dict) -> str:
    remark = str(inbound.get("remark") or "").strip()
    if remark:
        return remark
    port = inbound.get("port")
    if port:
        return f"inbound-{port}"
    inbound_id = inbound.get("id")
    return f"inbound-{inbound_id}" if inbound_id is not None else "inbound-unknown"


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
        page_buttons.append(
            InlineKeyboardButton(text=_truncate_button_text(email), callback_data=f"uo:{panel_id}:{inbound_id}:{uuid}")
        )
    rows = chunk_buttons(page_buttons, columns=2)
    nav_row = _pagination_nav_row(
        page=page,
        total_pages=total_pages,
        lang=lang,
        callback_for_page=lambda target_page: encode_inbound_page(panel_id, inbound_id, target_page),
    )
    if nav_row is not None:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text=t("admin_back_to_inbounds", lang), callback_data=f"users_panel_pick:{panel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    return online_filtered_clients_keyboard(
        panel_id,
        clients,
        lang,
        mode="on",
        page=page,
    )


def action_panel_select_keyboard(panels: list[dict], action_prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        ok = "✅" if p["last_login_ok"] else "❌"
        star = "⭐ " if p.get("is_default") else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{star}{ok} {p['name']}",
                    callback_data=f"{action_prefix}:{p['id']}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def online_filtered_clients_keyboard(
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
        elif bool(client.get("enabled", True)):
            text = _truncate_button_text(f"🟢 {email}")
        else:
            text = _truncate_button_text(f"⚫ {email}")
        page_buttons.append(InlineKeyboardButton(text=text, callback_data=f"uol:{panel_id}:{inbound_id}:{uuid}"))
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
    rows.append([InlineKeyboardButton(text=t("admin_refresh_list", lang), callback_data=f"uolp:{panel_id}")])
    rows.append([InlineKeyboardButton(text=t("admin_back_to_online_list", lang), callback_data=f"uolp:{panel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_actions_keyboard(
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    enabled: bool,
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    toggle_text = t("admin_toggle_on", lang) if enabled else t("admin_toggle_off", lang)
    rows = [
        [InlineKeyboardButton(text=t("admin_refresh", lang), callback_data=f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            InlineKeyboardButton(text=t("admin_limit_traffic", lang), callback_data=f"tm:{panel_id}:{inbound_id}:{client_uuid}"),
            InlineKeyboardButton(text=t("admin_reset_traffic", lang), callback_data=f"ra:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
        [InlineKeyboardButton(text=t("admin_reset_expiry", lang), callback_data=f"em:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            InlineKeyboardButton(text=t("admin_ip_log", lang), callback_data=f"il:{panel_id}:{inbound_id}:{client_uuid}"),
            InlineKeyboardButton(text=t("admin_ip_limit", lang), callback_data=f"im:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
        [InlineKeyboardButton(text=t("admin_set_tg", lang), callback_data=f"ti:{panel_id}:{inbound_id}:{client_uuid}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"te:{panel_id}:{inbound_id}:{client_uuid}")],
        [InlineKeyboardButton(text=t("admin_back_to_users", lang), callback_data=f"users_inbound_pick:{panel_id}:{inbound_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_confirm_reset_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("admin_confirm_reset", lang), callback_data=f"ry:{panel_id}:{inbound_id}:{client_uuid}")],
            [InlineKeyboardButton(text=t("admin_cancel_reset", lang), callback_data=f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        ]
    )


def client_traffic_menu_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("admin_cancel", lang), callback_data=f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            InlineKeyboardButton(text=t("admin_unlimited_reset", lang), callback_data=f"ts:{panel_id}:{inbound_id}:{client_uuid}:unlimited"),
            InlineKeyboardButton(text=t("admin_custom", lang), callback_data=f"tc:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
    ]
    for gb in [1, 5, 10, 20, 30, 40, 50, 60, 80, 100, 150, 200]:
        if len(rows) == 2 or len(rows[-1]) == 3:
            rows.append([])
        rows[-1].append(InlineKeyboardButton(text=f"{gb} GB", callback_data=f"ts:{panel_id}:{inbound_id}:{client_uuid}:{gb}"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_expiry_menu_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("admin_cancel_reset", lang), callback_data=f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            InlineKeyboardButton(text=t("admin_unlimited_reset", lang), callback_data=f"es:{panel_id}:{inbound_id}:{client_uuid}:unlimited"),
            InlineKeyboardButton(text=t("admin_custom", lang), callback_data=f"ec:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
    ]
    for days, label in [
        (7, "7d"),
        (10, "10d"),
        (14, "14d"),
        (20, "20d"),
        (30, "1m"),
        (90, "3m"),
        (180, "6m"),
        (365, "12m"),
    ]:
        if len(rows) == 2 or len(rows[-1]) == 2:
            rows.append([])
        rows[-1].append(InlineKeyboardButton(text=label, callback_data=f"es:{panel_id}:{inbound_id}:{client_uuid}:{days}"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_iplimit_menu_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("admin_cancel_ip_limit", lang), callback_data=f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        [
            InlineKeyboardButton(text=t("admin_unlimited_reset", lang), callback_data=f"is:{panel_id}:{inbound_id}:{client_uuid}:unlimited"),
            InlineKeyboardButton(text=t("admin_custom", lang), callback_data=f"ic:{panel_id}:{inbound_id}:{client_uuid}"),
        ],
    ]
    for value in range(1, 11):
        if len(rows) == 2 or len(rows[-1]) == 3:
            rows.append([])
        rows[-1].append(InlineKeyboardButton(text=str(value), callback_data=f"is:{panel_id}:{inbound_id}:{client_uuid}:{value}"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_ips_log_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("admin_clear_ip_log", lang), callback_data=f"ix:{panel_id}:{inbound_id}:{client_uuid}")],
            [InlineKeyboardButton(text=t("admin_back", lang), callback_data=f"cr:{panel_id}:{inbound_id}:{client_uuid}")],
        ]
    )


def human_bytes(value: int) -> str:
    size = float(max(0, value))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def format_inbounds_list(panel_name: str, rows: list[dict], lang: str | None = None) -> str:
    if not rows:
        return f"{t('admin_inbounds_title', lang)}\n{t('admin_panel_label', lang)}: {panel_name}\n\n{t('admin_no_inbounds', lang)}"
    lines = [f"{t('admin_inbounds_title', lang)}", f"{t('admin_panel_label', lang)}: {panel_name}", ""]
    for offset, inbound in enumerate(rows):
        status = t("admin_enabled", lang) if inbound.get("enable") else t("admin_disabled", lang)
        clients = inbound.get("clientStats")
        client_count = len(clients) if isinstance(clients, list) else 0
        remark = str(inbound.get("remark") or "-")
        up_value = int(inbound.get("up") or 0)
        down_value = int(inbound.get("down") or 0)
        up = human_bytes(up_value)
        down = human_bytes(down_value)
        total = human_bytes(up_value + down_value)
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
    up = human_bytes(int(detail.get("up") or 0))
    down = human_bytes(int(detail.get("down") or 0))
    used = human_bytes(int(detail.get("used") or 0))
    total_raw = int(detail.get("total") or 0)
    total_text = t("admin_unlimited_reset_value", lang) if total_raw <= 0 else human_bytes(total_raw)
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
    callback: CallbackQuery,
    services: ServiceContainer,
    settings: Settings,
    *,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
) -> None:
    if callback.message is None:
        return
    try:
        detail = await services.panel_service.get_client_detail(panel_id, inbound_id, client_uuid)
    except Exception as exc:
        await callback.message.edit_text(f"{t('admin_error_fetch_client', None)}:\n{exc}")
        return
    text = format_client_detail(detail, settings.timezone)
    await callback.message.edit_text(
        text,
        reply_markup=client_actions_keyboard(panel_id, inbound_id, client_uuid, bool(detail.get("enabled"))),
    )


async def set_client_action_context(state: FSMContext, *, panel_id: int, inbound_id: int, client_uuid: str) -> None:
    await state.update_data(
        client_manage_panel_id=panel_id,
        client_manage_inbound_id=inbound_id,
        client_manage_uuid=client_uuid,
    )


async def refresh_panels_message(callback: CallbackQuery, services: ServiceContainer) -> None:
    if callback.message is None:
        return
    panels = await services.panel_service.list_panels()
    if not panels:
        await callback.message.edit_text(t("bind_no_panel", None))
        return
    await callback.message.edit_text(panels_list_text(), reply_markup=panels_glass_keyboard(panels))


async def show_inbounds_for_panel(message: Message, services: ServiceContainer, panel_id: int) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(t("admin_panel_not_found", None), reply_markup=admin_keyboard())
        return
    await message.answer(t("admin_fetching_inbounds_alt", None))
    try:
        rows = await services.panel_service.list_inbounds(panel_id)
    except Exception as exc:
        await message.answer(f"{t('admin_error_fetch_inbounds', None)}:\n{exc}", reply_markup=admin_keyboard())
        return
    cards = split_inbounds_for_telegram(panel["name"], rows)
    for idx, card in enumerate(cards):
        await message.answer(card, reply_markup=admin_keyboard() if idx == 0 else None)


async def show_users_inbounds_for_panel_message(message: Message, services: ServiceContainer, panel_id: int) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(t("admin_panel_not_found", None), reply_markup=admin_keyboard())
        return
    await message.answer(t("admin_fetching_inbounds", None))
    try:
        inbounds = await services.panel_service.list_inbounds(panel_id)
    except Exception as exc:
        await message.answer(f"{t('admin_error_fetch_inbounds', None)}:\n{exc}", reply_markup=admin_keyboard())
        return
    if not inbounds:
        await message.answer(t("admin_no_inbound_for_panel", None), reply_markup=admin_keyboard())
        return
    await message.answer(
        t("admin_panel_and_pick_inbound", None, name=panel["name"]),
        reply_markup=users_inbounds_keyboard(panel_id, inbounds),
    )


async def show_users_inbounds_for_panel_callback(callback: CallbackQuery, services: ServiceContainer, panel_id: int) -> None:
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
    if not inbounds:
        await callback.message.edit_text(t("admin_no_inbound_for_panel", None))
        return
    await callback.message.edit_text(
        t("admin_panel_and_pick_inbound", None, name=panel["name"]),
        reply_markup=users_inbounds_keyboard(panel_id, inbounds),
    )


async def show_online_clients_for_panel_message(message: Message, services: ServiceContainer, panel_id: int) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await message.answer(t("admin_panel_not_found", None), reply_markup=admin_keyboard())
        return
    await message.answer(t("admin_fetching_online", None))
    try:
        clients = await services.panel_service.list_online_clients(panel_id)
    except Exception as exc:
        await message.answer(f"{t('admin_error_fetch_online', None)}:\n{exc}", reply_markup=admin_keyboard())
        return
    if not clients:
        await message.answer(t("admin_no_online", None, name=panel["name"]), reply_markup=admin_keyboard())
        return
    await message.answer(
        t("admin_online_header", None, name=panel["name"], count=len(clients)),
        reply_markup=online_clients_keyboard(panel_id, clients),
    )


async def show_online_clients_for_panel_callback(callback: CallbackQuery, services: ServiceContainer, panel_id: int) -> None:
    if callback.message is None:
        return
    panel = await services.panel_service.get_panel(panel_id)
    if panel is None:
        await callback.message.edit_text(t("admin_panel_not_found", None))
        return
    try:
        clients = await services.panel_service.list_online_clients(panel_id)
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
