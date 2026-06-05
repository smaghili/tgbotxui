from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import NOOP
from bot.config import Settings
from bot.i18n import t
from bot.pagination import chunk_buttons, paginate_window
from bot.services.container import ServiceContainer
from bot.utils import format_gb, gb_to_bytes

from .admin_shared import inline_button, panel_select_keyboard, yes_no_inline_keyboard
from .config_bundle import send_config_bundle_card

EDIT_SEARCH_RESULTS_PER_PAGE = 20


def inbound_access_keyboard(rows: list, prefix: str, *, include_panel_name: bool = True) -> InlineKeyboardMarkup:
    buttons = []
    for row in rows:
        text = f"{row.panel_name} | {row.inbound_name}" if include_panel_name else row.inbound_name
        buttons.append([inline_button(text, f"{prefix}:{row.panel_id}:{row.inbound_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def group_select_keyboard(groups: list[dict], prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    for group in groups:
        group_id = int(group.get("id") or 0)
        if group_id <= 0:
            continue
        name = str(group.get("name") or "").strip() or f"group-{group_id}"
        if bool(group.get("is_default")):
            name = f"⭐ {name}"
        buttons.append([inline_button(name[:60], f"{prefix}:{group_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_tg_id_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard("pcu:tg_choice:yes", "pcu:tg_choice:no", lang)


def truncate_button_text(text: str, max_len: int = 60) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def edit_panel_select_keyboard(panels: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    return panel_select_keyboard(panels, "pecsp")


def edit_search_results_keyboard(
    scope: str,
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
        panel_id = int(client.get("panel_id") or scope)
        inbound_id = int(client.get("inbound_id") or 0)
        client_uuid = str(client.get("uuid") or "").strip()
        if not email or inbound_id <= 0 or not client_uuid:
            continue
        prefix = "🟢" if bool(client.get("enabled", True)) else "⚫"
        page_buttons.append(
            inline_button(
                truncate_button_text(f"{prefix} {email}"),
                f"pecs:{panel_id}:{inbound_id}:{client_uuid}:{page}:{query}",
            )
        )
    rows = chunk_buttons(page_buttons, columns=2)
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(inline_button(t("admin_page_prev", lang), f"pecp:{scope}:{page - 1}:{query}"))
        nav_row.append(inline_button(f"{page}/{total_pages}", NOOP))
        if page < total_pages:
            nav_row.append(inline_button(t("admin_page_next", lang), f"pecp:{scope}:{page + 1}:{query}"))
        rows.append(nav_row)
    rows.append([inline_button(t("admin_refresh_list", lang), f"pecsr:{scope}:{query}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_keyboard(panel_id: int, inbound_id: int, client_uuid: str, lang: str | None = None) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard(
        f"pec:delete_yes:{panel_id}:{inbound_id}:{client_uuid}",
        f"pec:detail:{panel_id}:{inbound_id}:{client_uuid}",
        lang,
    )


def owner_pick_keyboard(
    *,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    owner_rows: list[dict],
    lang: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in owner_rows:
        user_id = int(row["telegram_user_id"])
        title = str(row.get("title") or "").strip()
        full_name = str(row.get("full_name") or "").strip()
        username = str(row.get("username") or "").strip()
        label = title or full_name or (f"@{username}" if username else str(user_id))
        rows.append([inline_button(truncate_button_text(label), f"pec:owner_set:{user_id}")])
    rows.append([inline_button(t("admin_back", lang), f"pec:detail:{panel_id}:{inbound_id}:{client_uuid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def candidate_owner_rows(settings: Settings, services: ServiceContainer, lang: str | None) -> list[dict]:
    delegated_rows = [
        row
        for row in await services.handler_context_service.delegated_admins()
        if int(row.get("is_active") or 0) == 1
    ]
    root_rows = [
        {
            "telegram_user_id": rid,
            "title": t("admin_root_label", lang),
            "full_name": t("admin_root_label", lang),
            "username": "",
        }
        for rid in sorted(settings.admin_ids)
    ]
    return root_rows + delegated_rows


async def send_config_bundle(
    message: Message,
    *,
    config_name: str,
    total_gb: float,
    expiry_days: int,
    vless_uri: str,
    sub_url: str,
    lang: str | None,
) -> None:
    await send_config_bundle_card(
        message,
        config_name=config_name,
        total_label=format_gb(gb_to_bytes(total_gb), lang or "fa"),
        expiry_label=f"{expiry_days} {t('unit_day', lang)}",
        vless_uri=vless_uri,
        sub_url=sub_url,
        lang=lang,
        filename="client_config_qr.png",
    )
