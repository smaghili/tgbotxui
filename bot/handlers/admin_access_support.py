from __future__ import annotations

import json
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.utils import (
    format_db_timestamp as shared_format_db_timestamp,
    format_gb_exact as shared_format_gb_exact,
    parse_detail_pairs,
    to_persian_digits,
)


def parse_finex_name_tokens(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


def match_email_token(email: str, token: str) -> bool:
    token_value = token.strip().lower()
    email_value = email.strip().lower()
    if not token_value or not email_value:
        return False
    local, _, _ = email_value.partition("@")
    if local == token_value:
        return True
    return token_value in email_value


async def search_clients_by_email_tokens(
    services: ServiceContainer,
    tokens: list[str],
) -> list[dict[str, Any]]:
    if not tokens:
        return []
    seen: set[tuple[int, int, str]] = set()
    out: list[dict[str, Any]] = []
    for panel in await services.panel_service.list_panels():
        panel_id = int(panel["id"])
        try:
            rows = await services.panel_service.list_clients(panel_id)
        except Exception:
            continue
        for row in rows:
            email = str(row.get("email") or "").strip()
            if not email or not any(match_email_token(email, tok) for tok in tokens):
                continue
            client_uuid = str(row.get("uuid") or "").strip()
            inbound_id = int(row.get("inbound_id") or 0)
            if not client_uuid or inbound_id <= 0:
                continue
            key = (panel_id, inbound_id, client_uuid)
            if key in seen:
                continue
            seen.add(key)
            out.append({"panel_id": panel_id, "inbound_id": inbound_id, "uuid": client_uuid, "email": email})
    return out


async def safe_edit_menu_message(
    message: Message,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        err = str(exc).lower()
        if "message is not modified" in err or "message_not_modified" in err:
            return
        raise


def format_gb_exact(value: float | int) -> str:
    return shared_format_gb_exact(value)


def format_db_timestamp(raw: str | None, *, settings: Settings, lang: str | None) -> str:
    return shared_format_db_timestamp(raw, tz_name=settings.timezone, lang=lang)


def parse_detail_pairs_text(raw: str | None) -> dict[str, str]:
    return parse_detail_pairs(raw)


def manage_admins_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("admin_add_delegated", lang), callback_data="dag:add")],
            [InlineKeyboardButton(text=t("admin_list_delegated", lang), callback_data="dag:list")],
        ]
    )


def delegated_inbound_select_keyboard(
    rows: list,
    selected: set[tuple[int, int]],
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        mark = "✅ " if (row.panel_id, row.inbound_id) in selected else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{row.panel_name} | {row.inbound_name}",
                    callback_data=f"dag:toggle:{row.panel_id}:{row.inbound_id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text=t("btn_confirm", lang), callback_data="dag:confirm"),
            InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="dag:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delegated_access_list_keyboard(rows: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    seen_users: set[int] = set()
    for row in rows:
        user_id = int(row["telegram_user_id"])
        if user_id in seen_users:
            continue
        seen_users.add(user_id)
        title = str(row.get("title") or row.get("full_name") or row.get("username") or user_id)
        buttons.append(
            [
                InlineKeyboardButton(text=title[:42], callback_data=f"dag:detail:{user_id}"),
                InlineKeyboardButton(text="⚙️", callback_data=f"dag:detail:{user_id}"),
                InlineKeyboardButton(text="🗑️", callback_data=f"dag:remove_user:{user_id}"),
            ]
        )
    if not buttons:
        buttons = [[InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delegated_subordinates_keyboard(
    parent_user_id: int,
    rows: list[dict],
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    seen_users: set[int] = set()
    for row in rows:
        child_user_id = int(row["telegram_user_id"])
        if child_user_id == parent_user_id or child_user_id in seen_users:
            continue
        seen_users.add(child_user_id)
        title = str(row.get("title") or row.get("full_name") or row.get("username") or child_user_id)
        current_parent_user_id = int(row.get("parent_user_id") or 0) or None
        is_attached = current_parent_user_id == parent_user_id
        action_label = t("admin_delegated_subordinate_remove", lang) if is_attached else t("admin_delegated_subordinate_add", lang)
        buttons.append(
            [
                InlineKeyboardButton(text=title[:34], callback_data=f"dag:detail:{child_user_id}"),
                InlineKeyboardButton(text=action_label, callback_data=f"dag:subtoggle:{parent_user_id}:{child_user_id}"),
            ]
        )
    if not buttons:
        buttons = [[InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")]]
    buttons.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"dag:detail:{parent_user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def pricing_history_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="dag:pricing:history:apply"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="dag:pricing:history:keep"),
            ]
        ]
    )


def delegated_self_readonly_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_back", lang), callback_data="fin:delegated:back")]]
    )


def format_amount(value: int) -> str:
    return f"{value:,}"


def value_or_unlimited(value: float | int, lang: str | None) -> str:
    return t("admin_delegated_unlimited", lang) if value <= 0 else format_gb_exact(value)


def wallet_operation_title(operation: str, email: str | None) -> str:
    if operation == "create_client":
        return f"ساخت کاربر جدید {email or '-'}"
    if operation == "add_client_total_gb":
        return f"افزایش حجم کاربر {email or '-'}"
    if operation == "extend_client_expiry_days":
        return f"افزایش تاریخ انقضای کاربر {email or '-'}"
    if operation == "set_client_total_gb":
        return f"تنظیم حجم کاربر {email or '-'}"
    if operation == "set_client_expiry_days":
        return f"تنظیم تاریخ انقضای کاربر {email or '-'}"
    if operation == "wallet_set_balance":
        return "تنظیم موجودی کیف پول"
    if operation == "wallet_adjust_balance":
        return "تغییر دستی موجودی"
    return operation or "تراکنش"


def format_wallet_entry(item: dict, *, settings: Settings, lang: str | None) -> str:
    created_at = format_db_timestamp(str(item.get("created_at") or ""), settings=settings, lang=lang)
    amount = format_amount(abs(int(item.get("amount") or 0)))
    currency = str(item.get("currency") or "تومان")
    operation = str(item.get("operation") or item.get("kind") or "")
    details = parse_detail_pairs_text(item.get("details"))
    email = details.get("email") or details.get("client_email")
    try:
        metadata = json.loads(item.get("metadata_json") or "{}")
    except Exception:
        metadata = {}
    traffic_gb = float(metadata.get("traffic_gb") or 0)
    expiry_days = int(metadata.get("expiry_days") or 0)
    parts = [f"- {created_at}", wallet_operation_title(operation, email)]
    if traffic_gb > 0:
        traffic_label = format_gb_exact(traffic_gb)
        parts.append(f"مقدار: {to_persian_digits(traffic_label) if lang == 'fa' else traffic_label} گیگ")
    if expiry_days > 0:
        parts.append(f"مقدار: {to_persian_digits(expiry_days) if lang == 'fa' else expiry_days} روز")
    parts.append(f"قیمت: {amount} {currency}")
    return "\n".join(parts)


def format_panel_price_entry(row: dict, *, lang: str | None) -> str:
    panel_name = str(row.get("panel_name") or row.get("panel_id") or "-")
    gb = format_amount(int(row.get("price_per_gb") or 0))
    day = format_amount(int(row.get("price_per_day") or 0))
    tiers_text = ""
    raw_tiers = str(row.get("allocated_pricing_tiers_json") or "[]")
    try:
        tiers = json.loads(raw_tiers)
    except Exception:
        tiers = []
    if isinstance(tiers, list):
        tier_parts: list[str] = []
        for item in tiers:
            if not isinstance(item, dict):
                continue
            traffic_gb = int(item.get("traffic_gb") or 0)
            amount = int(item.get("amount") or 0)
            if traffic_gb <= 0 or amount < 0:
                continue
            tier_parts.append(f"{traffic_gb}GB={format_amount(amount)}")
        if tier_parts:
            tiers_text = f" ({', '.join(tier_parts)})"
    return f"- {panel_name}: {gb}/{day}{tiers_text}"


def format_activity_entry(item: dict, *, settings: Settings, lang: str | None) -> str | None:
    action = str(item.get("action") or "")
    if action == "view_status":
        return None
    if action == "admin_activity":
        details = str(item.get("details") or "").strip()
        return f"- {details}" if details else None
    details = parse_detail_pairs_text(item.get("details"))
    created_at = format_db_timestamp(str(item.get("created_at") or ""), settings=settings, lang=lang)
    if action == "create_client":
        return f"- {created_at}\nساخت کاربر جدید {details.get('email') or '-'}"
    if action == "add_client_traffic":
        gb = details.get("gb") or "-"
        return f"- {created_at}\nافزایش حجم کاربر\nمقدار: {to_persian_digits(gb) if lang == 'fa' and gb != '-' else gb} گیگ"
    if action == "extend_client_expiry":
        days = details.get("days") or "-"
        return f"- {created_at}\nافزایش تاریخ انقضا\nمقدار: {to_persian_digits(days) if lang == 'fa' and days != '-' else days} روز"
    return None
