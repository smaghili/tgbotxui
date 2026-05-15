from __future__ import annotations

import json
import time

from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.states import DelegatedAdminStates
from .admin_shared import reject_if_not_any_admin

from bot.utils import (
    format_db_timestamp as shared_format_db_timestamp,
    format_gb_exact as shared_format_gb_exact,
    parse_gb_amount,
    parse_price_per_gb_with_tiers,
    parse_detail_pairs,
    relative_remaining_time,
    to_local_date,
    to_persian_digits,
)
from .admin_finance_helpers import payable_from_wallet

router = Router(name="admin_access")

_FINEX_IB_PAGE = 8


def _parse_finex_name_tokens(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


def _match_email_token(email: str, token: str) -> bool:
    t = token.strip().lower()
    e = email.strip().lower()
    if not t or not e:
        return False
    local, _, _ = e.partition("@")
    if local == t:
        return True
    return t in e


async def _search_clients_by_email_tokens(
    services: ServiceContainer, tokens: list[str]
) -> list[dict[str, Any]]:
    if not tokens:
        return []
    seen: set[tuple[int, int, str]] = set()
    out: list[dict[str, Any]] = []
    for panel in await services.panel_service.list_panels():
        pid = int(panel["id"])
        try:
            rows = await services.panel_service.list_clients(pid)
        except Exception:
            continue
        for row in rows:
            email = str(row.get("email") or "").strip()
            if not email:
                continue
            if not any(_match_email_token(email, tok) for tok in tokens):
                continue
            uid = str(row.get("uuid") or "").strip()
            ib = int(row.get("inbound_id") or 0)
            if not uid or ib <= 0:
                continue
            key = (pid, ib, uid)
            if key in seen:
                continue
            seen.add(key)
            out.append({"panel_id": pid, "inbound_id": ib, "uuid": uid, "email": email})
    return out


async def _safe_edit_menu_message(
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


async def _delegated_finex_inbounds_render(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
    *,
    delegate_id: int,
    page: int,
    answer_notify: str | None = None,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    excluded = await services.db.list_delegate_finance_excluded_inbounds(delegate_id)
    all_rows = await services.admin_provisioning_service.list_all_inbounds()
    total = len(all_rows)
    if total <= 0:
        await _safe_edit_menu_message(
            callback.message,
            text=t("admin_delegated_finex_inbounds_empty", lang),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"dag:detail:{delegate_id}")]]
            ),
        )
        if answer_notify is not None:
            await callback.answer(answer_notify)
        else:
            await callback.answer()
        return
    start = max(0, page) * _FINEX_IB_PAGE
    chunk = all_rows[start : start + _FINEX_IB_PAGE]
    buttons: list[list[InlineKeyboardButton]] = []
    for row in chunk:
        key = (row.panel_id, row.inbound_id)
        mark = "✅ " if key in excluded else "⬜ "
        label = f"{mark}{row.panel_name[:14]}|{row.inbound_name[:18]}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label[:48],
                    callback_data=f"dag:fxibt:{delegate_id}:{row.panel_id}:{row.inbound_id}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"dag:fxib:{delegate_id}:{page - 1}"))
    if start + _FINEX_IB_PAGE < total:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"dag:fxib:{delegate_id}:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"dag:detail:{delegate_id}")])
    await _safe_edit_menu_message(
        callback.message,
        text=t(
            "admin_delegated_finex_inbounds_title",
            lang,
            page=page + 1,
            pages=max(1, (total + _FINEX_IB_PAGE - 1) // _FINEX_IB_PAGE),
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    if answer_notify is not None:
        await callback.answer(answer_notify)
    else:
        await callback.answer()


async def _delegated_finex_remain_render(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
    *,
    delegate_id: int,
    answer_notify: str | None = None,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await _safe_edit_menu_message(
        callback.message,
        text=t("admin_delegated_finex_clients_title", lang),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("admin_delegated_finex_bulk_btn", lang),
                        callback_data=f"dag:fxrmb:{delegate_id}",
                    ),
                ],
                [InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"dag:detail:{delegate_id}")],
            ]
        ),
    )
    if answer_notify is not None:
        await callback.answer(answer_notify)
    else:
        await callback.answer()


def _format_gb_exact(value: float | int) -> str:
    return shared_format_gb_exact(value)


def _format_db_timestamp(raw: str | None, *, settings: Settings, lang: str | None) -> str:
    return shared_format_db_timestamp(raw, tz_name=settings.timezone, lang=lang)


def _parse_detail_pairs(raw: str | None) -> dict[str, str]:
    return parse_detail_pairs(raw)


async def _reject_if_not_full_admin(message: Message, settings: Settings, services: ServiceContainer) -> bool:
    if await services.access_service.can_manage_admins(user_id=message.from_user.id, settings=settings):
        return False
    await message.answer(t("no_admin_access", None))
    return True


async def _reject_callback_if_not_full_admin(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> bool:
    if await services.access_service.can_manage_admins(user_id=callback.from_user.id, settings=settings):
        return False
    await callback.answer(t("no_admin_access", None), show_alert=True)
    return True


async def _can_manage_delegated_target(
    *,
    actor_user_id: int,
    target_user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    if services.access_service.is_root_admin(actor_user_id, settings):
        return True
    context = await services.access_service.get_admin_context(actor_user_id, settings)
    if not (context.is_delegated_admin and context.delegated_scope == "full"):
        return False
    subtree_ids = set(
        await services.db.get_delegated_admin_subtree_user_ids(
            manager_user_id=actor_user_id,
            include_self=True,
        )
    )
    return target_user_id in subtree_ids


def _manage_admins_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("admin_add_delegated", lang), callback_data="dag:add")],
            [InlineKeyboardButton(text=t("admin_list_delegated", lang), callback_data="dag:list")],
        ]
    )


def _delegated_inbound_select_keyboard(
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


def _delegated_access_list_keyboard(rows: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
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


def _delegated_subordinates_keyboard(
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
        action_label = (
            t("admin_delegated_subordinate_remove", lang)
            if is_attached else
            t("admin_delegated_subordinate_add", lang)
        )
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


def _pricing_history_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="dag:pricing:history:apply"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="dag:pricing:history:keep"),
            ]
        ]
    )


def _delegated_self_readonly_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_back", lang), callback_data="fin:delegated:back")]]
    )


def _delegated_detail_keyboard(
    user_id: int,
    *,
    is_active: bool,
    charge_basis: str,
    admin_scope: str,
    allow_negative_wallet: bool,
    is_root_parent: bool,
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    scope_value = str(admin_scope or "limited").strip().lower()
    status_label = (
        f"{t('admin_delegated_status', lang)}: {t('admin_delegated_status_active', lang)}"
        if is_active else
        f"{t('admin_delegated_status', lang)}: {t('admin_delegated_status_inactive', lang)}"
    )
    basis_label = (
        t("admin_delegated_charge_allocated", lang)
        if charge_basis == "allocated"
        else t("admin_delegated_charge_consumed", lang)
    )
    scope_label = (
        t("admin_delegated_scope_full", lang)
        if scope_value == "full"
        else t("admin_delegated_scope_limited", lang)
    )
    wallet_mode_label = (
        t("admin_delegated_buy_without_balance_yes", lang)
        if allow_negative_wallet
        else t("admin_delegated_buy_without_balance_no", lang)
    )
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=t("admin_delegated_update", lang), callback_data=f"dag:detail:{user_id}")],
        [
            InlineKeyboardButton(text=t("admin_delegated_delete", lang), callback_data=f"dag:remove_user:{user_id}"),
            InlineKeyboardButton(text=t("admin_delegated_max_users", lang), callback_data=f"dag:field:max_clients:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=t("admin_delegated_expiry", lang), callback_data=f"dag:field:expires_at:{user_id}"),
            InlineKeyboardButton(text=t("admin_delegated_prefix", lang), callback_data=f"dag:field:username_prefix:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=t("admin_delegated_price_day", lang), callback_data=f"dag:field:price_day:{user_id}"),
            InlineKeyboardButton(text=t("admin_delegated_price_gb", lang), callback_data=f"dag:field:price_gb:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=t("admin_delegated_min_traffic", lang), callback_data=f"dag:field:min_traffic_gb:{user_id}"),
            InlineKeyboardButton(text=t("admin_delegated_max_traffic", lang), callback_data=f"dag:field:max_traffic_gb:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=t("admin_delegated_min_days", lang), callback_data=f"dag:field:min_expiry_days:{user_id}"),
            InlineKeyboardButton(text=t("admin_delegated_max_days", lang), callback_data=f"dag:field:max_expiry_days:{user_id}"),
        ],
    ]
    rows.append(
        [
            InlineKeyboardButton(text=status_label, callback_data=f"dag:toggle_status:{user_id}"),
            InlineKeyboardButton(text=f"{t('admin_delegated_scope', lang)}: {scope_label}", callback_data=f"dag:toggle_scope:{user_id}"),
        ]
    )
    if scope_value == "limited":
        rows.append(
            [
                InlineKeyboardButton(text=t("admin_delegated_access", lang), callback_data=f"dag:edit:{user_id}"),
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=f"{t('admin_delegated_charge_basis', lang)}: {basis_label}",
                    callback_data=f"dag:toggle_basis:{user_id}",
                ),
                InlineKeyboardButton(text=t("admin_delegated_wallet", lang), callback_data=f"fin:wallet:show:{user_id}"),
            ],
            [
                InlineKeyboardButton(
                    text=wallet_mode_label,
                    callback_data=f"dag:toggle_wallet_mode:{user_id}",
                ),
            ],
        ]
    )
    relation_buttons: list[InlineKeyboardButton] = []
    if scope_value != "full":
        relation_buttons.append(
            InlineKeyboardButton(
                text=f"{t('admin_delegated_parent_root', lang)} {'✅' if is_root_parent else '❌'}",
                callback_data=f"dag:set_root_parent:{user_id}",
            )
        )
    relation_buttons.append(InlineKeyboardButton(text=t("admin_delegated_subordinates", lang), callback_data=f"dag:subs:{user_id}"))
    rows.append(relation_buttons)
    if is_root_parent:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("admin_delegated_finex_inbounds_btn", lang),
                    callback_data=f"dag:fxib:{user_id}:0",
                ),
                InlineKeyboardButton(
                    text=t("admin_delegated_finex_remain_btn", lang),
                    callback_data=f"dag:fxcr:{user_id}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text=t("admin_delegated_report", lang), callback_data=f"dag:report:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_amount(value: int) -> str:
    return f"{value:,}"


def _value_or_unlimited(value: float | int, lang: str | None) -> str:
    return t("admin_delegated_unlimited", lang) if value <= 0 else _format_gb_exact(value)


def _wallet_operation_title(operation: str, email: str | None) -> str:
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


def _format_wallet_entry(item: dict, *, settings: Settings, lang: str | None) -> str:
    created_at = _format_db_timestamp(str(item.get("created_at") or ""), settings=settings, lang=lang)
    amount = _format_amount(abs(int(item.get("amount") or 0)))
    currency = str(item.get("currency") or "تومان")
    operation = str(item.get("operation") or item.get("kind") or "")
    details = _parse_detail_pairs(item.get("details"))
    email = details.get("email") or details.get("client_email")
    try:
        metadata = json.loads(item.get("metadata_json") or "{}")
    except Exception:
        metadata = {}
    traffic_gb = float(metadata.get("traffic_gb") or 0)
    expiry_days = int(metadata.get("expiry_days") or 0)
    parts = [f"- {created_at}", _wallet_operation_title(operation, email)]
    if traffic_gb > 0:
        traffic_label = _format_gb_exact(traffic_gb)
        parts.append(f"مقدار: {to_persian_digits(traffic_label) if lang == 'fa' else traffic_label} گیگ")
    if expiry_days > 0:
        parts.append(f"مقدار: {to_persian_digits(expiry_days) if lang == 'fa' else expiry_days} روز")
    parts.append(f"قیمت: {amount} {currency}")
    return "\n".join(parts)


def _format_activity_entry(item: dict, *, settings: Settings, lang: str | None) -> str | None:
    action = str(item.get("action") or "")
    if action == "view_status":
        return None
    if action == "admin_activity":
        details = str(item.get("details") or "").strip()
        return f"- {details}" if details else None
    details = _parse_detail_pairs(item.get("details"))
    created_at = _format_db_timestamp(str(item.get("created_at") or ""), settings=settings, lang=lang)
    if action == "create_client":
        return f"- {created_at}\nساخت کاربر جدید {details.get('email') or '-'}"
    if action == "add_client_traffic":
        gb = details.get("gb") or "-"
        return f"- {created_at}\nافزایش حجم کاربر\nمقدار: {to_persian_digits(gb) if lang == 'fa' and gb != '-' else gb} گیگ"
    if action == "extend_client_expiry":
        days = details.get("days") or "-"
        return f"- {created_at}\nافزایش تاریخ انقضا\nمقدار: {to_persian_digits(days) if lang == 'fa' and days != '-' else days} روز"
    return None


async def _render_delegated_detail(
    target: Message | CallbackQuery,
    *,
    services: ServiceContainer,
    settings: Settings,
    target_user_id: int,
    lang: str | None,
    read_only: bool = False,
) -> None:
    overview = await services.admin_provisioning_service.get_delegated_admin_overview(
        telegram_user_id=target_user_id,
        settings=settings,
    )
    if overview["delegated"] is None:
        message = target.message if isinstance(target, CallbackQuery) else target
        if message is not None:
            if isinstance(target, CallbackQuery):
                await message.edit_text(t("admin_delegated_not_found", lang))
            else:
                await message.answer(t("admin_delegated_not_found", lang))
        return
    user = overview["user"] or {}
    profile = overview["profile"]
    pricing = overview["pricing"]
    wallet = overview["wallet"]
    sales_report = await services.financial_service.get_sales_report(target_user_id)
    financial_summary = await services.admin_provisioning_service.get_admin_scope_financial_summary(
        actor_user_id=target_user_id,
        settings=settings,
    )
    title = (
        str(user.get("username") or "").strip()
        or str(user.get("full_name") or "").strip()
        or str(overview["delegated"].get("title") or "").strip()
        or str(target_user_id)
    )
    expires_at = int(profile.get("expires_at") or 0)
    expires_text = t("admin_delegated_unlimited", lang) if expires_at <= 0 else (
        f"{to_local_date(expires_at, settings.timezone, lang)} ({relative_remaining_time(expires_at, settings.timezone, lang)})"
    )
    is_active = int(profile.get("is_active") or 0) == 1
    status_text = t("admin_delegated_status_active", lang) if is_active else t("admin_delegated_status_inactive", lang)
    charge_basis = str(pricing.get("charge_basis") or "allocated")
    charge_basis_key = "admin_delegated_charge_allocated" if charge_basis == "allocated" else "admin_delegated_charge_consumed"
    allow_negative_wallet = int(profile.get("allow_negative_wallet") or 0) == 1
    balance_line = t(
        "admin_delegated_balance_line",
        lang,
        balance=_format_amount(int(wallet.get("balance") or 0)),
        currency=str(wallet.get("currency") or "تومان"),
    )
    if charge_basis == "consumed":
        total_sales_value = int(financial_summary.get("debt_amount") or 0)
        payable_amount = payable_from_wallet(int(wallet.get("balance") or 0))
        extra_lines = t(
            "admin_delegated_consumed_lines",
            lang,
            consumed_gb=_format_gb_exact(financial_summary.get("consumed_gb") or 0),
            payable_amount=_format_amount(payable_amount),
            remaining_gb=_format_gb_exact(financial_summary.get("remaining_gb") or 0),
            remaining_amount=_format_amount(int(financial_summary.get("remaining_amount") or 0)),
            currency=str(wallet.get("currency") or "تومان"),
        )
    else:
        total_sales_value = int(sales_report.get("total_sales") or 0)
        debt_amt = int(financial_summary.get("debt_amount") or 0)
        payable_amount = payable_from_wallet(int(wallet.get("balance") or 0))
        extra_lines = t(
            "admin_delegated_allocated_payable_lines",
            lang,
            payable_amount=_format_amount(payable_amount),
            currency=str(wallet.get("currency") or "تومان"),
        )
    text = t(
        "admin_delegated_details_text",
        lang,
        title=title,
        prefix=str(profile.get("username_prefix") or t("admin_none", lang)),
        max_users=_value_or_unlimited(int(profile.get("max_clients") or 0), lang),
        min_traffic=_format_gb_exact(float(profile.get("min_traffic_gb") or 0)),
        max_traffic=_value_or_unlimited(float(profile.get("max_traffic_gb") or 0), lang),
        min_days=int(profile.get("min_expiry_days") or 1),
        max_days=_value_or_unlimited(int(profile.get("max_expiry_days") or 0), lang),
        price_day=_format_amount(int(pricing.get("price_per_day") or 0)),
        price_gb=_format_amount(int(pricing.get("price_per_gb") or 0)),
        currency=str(wallet.get("currency") or "تومان"),
        charge_basis=t(charge_basis_key, lang),
        balance_line=balance_line,
        total_sales=_format_amount(total_sales_value),
        extra_lines=extra_lines,
        expires_at=expires_text,
        status=status_text,
        owned_clients=int(overview["owned_clients_count"] or 0),
    )
    if read_only:
        reply_markup = _delegated_self_readonly_keyboard(lang)
    else:
        reply_markup = _delegated_detail_keyboard(
            target_user_id,
            is_active=is_active,
            charge_basis=charge_basis,
            admin_scope=str(overview["delegated"].get("admin_scope") or "limited"),
            allow_negative_wallet=allow_negative_wallet,
            is_root_parent=int(overview["delegated"].get("parent_user_id") or 0) == 0,
            lang=lang,
        )
    message = target.message if isinstance(target, CallbackQuery) else target
    if message is not None:
        if isinstance(target, CallbackQuery):
            await message.edit_text(text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)


async def _start_delegated_inbound_selection(
    *,
    state: FSMContext,
    services: ServiceContainer,
    lang: str | None,
    target_user_id: int,
    title: str | None,
    selected: set[tuple[int, int]],
    mode: str,
    existing_access_ids: dict[tuple[int, int], int] | None = None,
) -> tuple[str, InlineKeyboardMarkup] | None:
    rows = await services.admin_provisioning_service.list_grantable_inbounds_for_delegated_admin(target_user_id)
    if not rows:
        await state.clear()
        return None
    allowed = {(row.panel_id, row.inbound_id) for row in rows}
    selected = {item for item in selected if item in allowed}
    if existing_access_ids is not None:
        existing_access_ids = {
            key: value
            for key, value in existing_access_ids.items()
            if key in allowed
        }
    await state.update_data(
        delegated_mode=mode,
        delegated_target_user_id=target_user_id,
        delegated_title=title,
        delegated_inbound_rows=[(row.panel_id, row.panel_name, row.inbound_id, row.inbound_name) for row in rows],
        delegated_selected_inbounds=[list(item) for item in selected],
        delegated_existing_access_ids={f"{key[0]}:{key[1]}": value for key, value in (existing_access_ids or {}).items()},
    )
    await state.set_state(DelegatedAdminStates.waiting_inbound_selection)
    return (
        t("admin_pick_inbound_for_delegated", lang),
        _delegated_inbound_select_keyboard(rows, selected, lang),
    )


@router.message(F.text.in_(button_variants("admin_delegated_details")))
async def delegated_limited_self_detail_message(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    context = await services.access_service.get_admin_context(message.from_user.id, settings)
    if not context.is_delegated_admin or str(context.delegated_scope or "limited") != "limited":
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await _render_delegated_detail(
        message,
        services=services,
        settings=settings,
        target_user_id=message.from_user.id,
        lang=lang,
        read_only=True,
    )


@router.message(F.text.in_(button_variants("btn_manage_admins")))
async def manage_admins_menu(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await message.answer(
        t("admin_manage_admins_title", lang),
        reply_markup=_manage_admins_keyboard(lang),
    )


@router.callback_query(F.data == "dag:add")
async def delegated_admin_add_start(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.set_state(DelegatedAdminStates.waiting_target)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_delegated_target", lang))
    await callback.answer()


@router.message(DelegatedAdminStates.waiting_target)
async def delegated_admin_target_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    target_raw = (message.text or "").strip()
    try:
        target_user_id, resolved_title = await services.admin_provisioning_service.resolve_admin_target(target_raw)
    except ValueError as exc:
        text = str(exc)
        if "username was not found" in text:
            await message.answer(t("admin_delegated_target_unknown", lang))
            return
        await message.answer(text)
        return
    await state.update_data(
        delegated_target_user_id=target_user_id,
        delegated_resolved_title=resolved_title,
    )
    await state.set_state(DelegatedAdminStates.waiting_title)
    await message.answer(t("admin_enter_delegated_title", lang))


@router.message(DelegatedAdminStates.waiting_title)
async def delegated_admin_title_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    title_raw = (message.text or "").strip()
    title = None if title_raw in {"", "-"} else title_raw
    data = await state.get_data()
    resolved_title = str(data.get("delegated_resolved_title") or "").strip() or None
    if title is None:
        title = resolved_title
    result = await _start_delegated_inbound_selection(
        state=state,
        services=services,
        lang=lang,
        target_user_id=int(data["delegated_target_user_id"]),
        title=title,
        selected=set(),
        mode="create",
    )
    if result is None:
        await message.answer(t("bind_no_panel", lang))
        return
    text, markup = result
    await message.answer(text, reply_markup=markup)


@router.callback_query(DelegatedAdminStates.waiting_inbound_selection, F.data.startswith("dag:toggle:"))
async def delegated_admin_toggle_inbound(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
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
    data = await state.get_data()
    rows = [
        type("InboundRow", (), {"panel_id": row[0], "panel_name": row[1], "inbound_id": row[2], "inbound_name": row[3]})
        for row in data.get("delegated_inbound_rows", [])
    ]
    selected = {tuple(item) for item in data.get("delegated_selected_inbounds", [])}
    key = (panel_id, inbound_id)
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)
    await state.update_data(delegated_selected_inbounds=[list(item) for item in selected])
    await callback.message.edit_reply_markup(reply_markup=_delegated_inbound_select_keyboard(rows, selected, lang))
    await callback.answer()


@router.callback_query(DelegatedAdminStates.waiting_inbound_selection, F.data == "dag:cancel")
async def delegated_admin_cancel_inbound_selection(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None:
        await state.clear()
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    mode = str(data.get("delegated_mode") or "create")
    target_user_id = int(data.get("delegated_target_user_id") or 0)
    if mode == "edit" and target_user_id > 0:
        await _render_delegated_detail(
            callback,
            services=services,
            settings=settings,
            target_user_id=target_user_id,
            lang=lang,
        )
    else:
        rows = await services.admin_provisioning_service.list_delegated_admin_accesses(
            manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
        )
        text = t("admin_delegated_empty", lang) if not rows else t("admin_delegated_list_header", lang)
        await callback.message.edit_text(text, reply_markup=_delegated_access_list_keyboard(rows, lang))
    await callback.answer(t("operation_cancelled", lang))


@router.callback_query(DelegatedAdminStates.waiting_inbound_selection, F.data == "dag:confirm")
async def delegated_admin_confirm_inbound_selection(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    selected = [tuple(item) for item in data.get("delegated_selected_inbounds", [])]
    if not selected:
        await callback.answer(t("admin_delegated_pick_one", lang), show_alert=True)
        return
    target_user_id = int(data["delegated_target_user_id"])
    title = data.get("delegated_title")
    mode = str(data.get("delegated_mode") or "create")
    selected_set = {(int(panel_id), int(inbound_id)) for panel_id, inbound_id in selected}
    existing_access_ids_raw = data.get("delegated_existing_access_ids", {})
    existing_access_ids = {
        tuple(map(int, key.split(":", 1))): int(value)
        for key, value in existing_access_ids_raw.items()
    }
    try:
        if mode == "edit":
            for key, access_id in existing_access_ids.items():
                if key not in selected_set:
                    await services.admin_provisioning_service.revoke_delegated_admin_access(
                        actor_user_id=callback.from_user.id,
                        access_id=access_id,
                    )
        for panel_id, inbound_id in selected_set:
            if mode != "edit" or (panel_id, inbound_id) not in existing_access_ids:
                await services.admin_provisioning_service.grant_delegated_admin_access(
                    actor_user_id=callback.from_user.id,
                    settings=settings,
                    telegram_user_id=target_user_id,
                    title=str(title) if title else None,
                    panel_id=panel_id,
                    inbound_id=inbound_id,
                )
    except Exception as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    await state.clear()
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer(t("admin_delegated_profile_saved", lang))


@router.callback_query(F.data.startswith("dag:edit:"))
async def delegated_admin_edit(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    access_rows = await services.db.list_admin_access_rows_for_user(target_user_id)
    delegated = await services.db.get_delegated_admin_by_user_id(target_user_id)
    if delegated is None:
        await callback.answer(t("admin_delegated_not_found", lang), show_alert=True)
        return
    selected = {(int(row["panel_id"]), int(row["inbound_id"])) for row in access_rows}
    existing_access_ids = {
        (int(row["panel_id"]), int(row["inbound_id"])): int(row["access_id"])
        for row in access_rows
    }
    result = await _start_delegated_inbound_selection(
        state=state,
        services=services,
        lang=lang,
        target_user_id=target_user_id,
        title=str(delegated.get("title") or "").strip() or None,
        selected=selected,
        mode="edit",
        existing_access_ids=existing_access_ids,
    )
    if result is None:
        await callback.answer(t("bind_no_panel", lang), show_alert=True)
        return
    text, markup = result
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data == "dag:list")
async def delegated_admin_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    rows = await services.admin_provisioning_service.list_delegated_admin_accesses(
        manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
    )
    text = t("admin_delegated_empty", lang) if not rows else t("admin_delegated_list_header", lang)
    await callback.message.edit_text(text, reply_markup=_delegated_access_list_keyboard(rows, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("dag:detail:"))
async def delegated_admin_detail(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    actor_id = callback.from_user.id
    read_only = False
    if await services.access_service.can_manage_admins(user_id=actor_id, settings=settings):
        read_only = False
    elif target_user_id == actor_id and await services.access_service.is_delegated_admin(actor_id):
        read_only = True
    elif await _can_manage_delegated_target(
        actor_user_id=actor_id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        read_only = False
    else:
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
        read_only=read_only,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:subs:"))
async def delegated_admin_subordinates(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        parent_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=parent_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    parent = await services.db.get_delegated_admin_by_user_id(parent_user_id)
    if parent is None:
        await callback.answer(t("admin_delegated_not_found", lang), show_alert=True)
        return
    rows = await services.admin_provisioning_service.list_delegated_admin_accesses(
        manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
    )
    title = str(parent.get("title") or parent_user_id)
    await callback.message.edit_text(
        t("admin_delegated_subordinates_title", lang, title=title),
        reply_markup=_delegated_subordinates_keyboard(parent_user_id, rows, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:subtoggle:"))
async def delegated_admin_subordinate_toggle(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, _, parent_raw, child_raw = callback.data.split(":", 3)
        parent_user_id = int(parent_raw)
        child_user_id = int(child_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=parent_user_id,
        settings=settings,
        services=services,
    ) or not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=child_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    parent = await services.db.get_delegated_admin_by_user_id(parent_user_id)
    child = await services.db.get_delegated_admin_by_user_id(child_user_id)
    if parent is None or child is None:
        await callback.answer(t("admin_delegated_not_found", lang), show_alert=True)
        return
    current_parent_user_id = int(child.get("parent_user_id") or 0) or None
    new_parent_user_id = None if current_parent_user_id == parent_user_id else parent_user_id
    try:
        await services.admin_provisioning_service.change_delegated_admin_parent(
            actor_user_id=callback.from_user.id,
            child_user_id=child_user_id,
            new_parent_user_id=new_parent_user_id,
        )
    except Exception as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    rows = await services.admin_provisioning_service.list_delegated_admin_accesses(
        manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
    )
    title = str(parent.get("title") or parent_user_id)
    await callback.message.edit_text(
        t("admin_delegated_subordinates_title", lang, title=title),
        reply_markup=_delegated_subordinates_keyboard(parent_user_id, rows, lang),
    )
    await callback.answer(
        t("admin_delegated_parent_attached" if new_parent_user_id is not None else "admin_delegated_parent_detached", lang),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("dag:set_root_parent:"))
async def delegated_admin_set_root_parent(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    delegated = await services.db.get_delegated_admin_by_user_id(target_user_id)
    if delegated is None:
        await callback.answer(t("admin_delegated_not_found", lang), show_alert=True)
        return
    current_parent_user_id = int(delegated.get("parent_user_id") or 0) or None
    new_parent_user_id: int | None = None
    if current_parent_user_id is None:
        last_event = await services.db.get_last_delegated_admin_parent_event(target_user_id)
        candidate_parent = int((last_event or {}).get("old_parent_user_id") or 0) or None
        if candidate_parent == target_user_id:
            candidate_parent = None
        if candidate_parent is not None and await services.db.get_delegated_admin_by_user_id(candidate_parent) is None:
            candidate_parent = None
        if candidate_parent is None:
            await callback.answer(t("admin_delegated_parent_toggle_no_alt", lang), show_alert=True)
            return
        new_parent_user_id = candidate_parent
    try:
        await services.admin_provisioning_service.change_delegated_admin_parent(
            actor_user_id=callback.from_user.id,
            child_user_id=target_user_id,
            new_parent_user_id=new_parent_user_id,
        )
    except Exception as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer(
        t("admin_delegated_parent_root_set", lang)
        if new_parent_user_id is None
        else t("admin_delegated_parent_root_unset", lang),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("dag:field:"))
async def delegated_admin_field_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, _, field_name, target_raw = callback.data.split(":", 3)
        target_user_id = int(target_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    prompts = {
        "username_prefix": t("admin_delegated_enter_prefix", lang),
        "max_clients": t("admin_delegated_enter_max_users", lang),
        "min_traffic_gb": t("admin_delegated_enter_min_traffic", lang),
        "max_traffic_gb": t("admin_delegated_enter_max_traffic", lang),
        "min_expiry_days": t("admin_delegated_enter_min_days", lang),
        "max_expiry_days": t("admin_delegated_enter_max_days", lang),
        "expires_at": t("admin_delegated_enter_expiry", lang),
        "price_gb": t("finance_enter_price_per_gb", lang),
        "price_day": t("finance_enter_price_per_day", lang),
    }
    prompt = prompts.get(field_name)
    if prompt is None:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    await state.update_data(
        delegated_profile_field=field_name,
        delegated_profile_target_user_id=target_user_id,
    )
    await state.set_state(DelegatedAdminStates.waiting_profile_value)
    await callback.message.answer(prompt)
    await callback.answer()


@router.message(DelegatedAdminStates.waiting_profile_value)
async def delegated_admin_profile_value(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    data = await state.get_data()
    field_name = str(data.get("delegated_profile_field") or "")
    target_user_id = int(data.get("delegated_profile_target_user_id") or 0)
    raw = (message.text or "").strip()
    if not field_name or target_user_id <= 0:
        await state.clear()
        await message.answer(t("admin_invalid_data", lang))
        return
    if not await _can_manage_delegated_target(
        actor_user_id=message.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await state.clear()
        await message.answer(t("no_admin_access", None))
        return
    await state.clear()
    try:
        if field_name == "username_prefix":
            value = None if raw in {"", "-"} else raw
            await services.db.update_delegated_admin_profile(
                telegram_user_id=target_user_id,
                username_prefix=value,
            )
        elif field_name == "expires_at":
            days = int(raw)
            if days < 0:
                raise ValueError
            expires_at = None if days == 0 else int(time.time()) + (days * 86400)
            await services.db.update_delegated_admin_profile(
                telegram_user_id=target_user_id,
                expires_at=expires_at,
            )
        elif field_name in {"price_gb", "price_day"}:
            amount, tiers_json = parse_price_per_gb_with_tiers(raw) if field_name == "price_gb" else (int(raw.replace(",", "")), None)
            if amount < 0:
                raise ValueError
            pricing = await services.financial_service.get_pricing(target_user_id)
            new_price_gb = amount if field_name == "price_gb" else int(pricing["price_per_gb"] or 0)
            new_price_day = amount if field_name == "price_day" else int(pricing["price_per_day"] or 0)
            if field_name == "price_gb" and new_price_gb != int(pricing.get("price_per_gb") or 0):
                await state.update_data(
                    delegated_profile_target_user_id=target_user_id,
                    delegated_profile_new_price_gb=new_price_gb,
                    delegated_profile_new_price_day=new_price_day,
                    delegated_profile_charge_basis=str(pricing.get("charge_basis") or "allocated"),
                    delegated_profile_currency=str(pricing.get("currency") or "تومان"),
                    delegated_profile_old_price_gb=int(pricing.get("price_per_gb") or 0),
                    delegated_profile_allocated_tiers_json=tiers_json,
                )
                await state.set_state(DelegatedAdminStates.waiting_price_history_choice)
                await message.answer(
                    t(
                        "finance_pricing_history_confirm",
                        lang,
                        old_price_gb=_format_amount(int(pricing.get("price_per_gb") or 0)),
                        new_price_gb=_format_amount(new_price_gb),
                        currency=str(pricing.get("currency") or "تومان"),
                    ),
                    reply_markup=_pricing_history_choice_keyboard(lang),
                )
                return
            await services.financial_service.set_pricing(
                actor_user_id=message.from_user.id,
                telegram_user_id=target_user_id,
                price_per_gb=new_price_gb,
                price_per_day=new_price_day,
                charge_basis=str(pricing.get("charge_basis") or "allocated"),
                allocated_pricing_tiers_json=(
                    tiers_json
                    if field_name == "price_gb" and tiers_json is not None
                    else str(pricing.get("allocated_pricing_tiers_json") or "[]")
                ),
            )
        elif field_name in {"min_traffic_gb", "max_traffic_gb"}:
            number = parse_gb_amount(raw)
            await services.db.update_delegated_admin_profile(
                telegram_user_id=target_user_id,
                **{field_name: number},
            )
        else:
            number = int(raw)
            if number < 0:
                raise ValueError
            await services.db.update_delegated_admin_profile(
                telegram_user_id=target_user_id,
                **{field_name: number},
            )
    except ValueError:
        await message.answer(t("finance_invalid_amount", lang))
        return
    await message.answer(t("admin_delegated_profile_saved", lang))
    await _render_delegated_detail(
        message,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )


@router.callback_query(DelegatedAdminStates.waiting_price_history_choice, F.data == "dag:pricing:history:apply")
async def delegated_admin_price_history_apply(
    callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    target_user_id = int(data["delegated_profile_target_user_id"])
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await services.financial_service.set_pricing(
        actor_user_id=callback.from_user.id,
        telegram_user_id=target_user_id,
        price_per_gb=int(data["delegated_profile_new_price_gb"]),
        price_per_day=int(data["delegated_profile_new_price_day"]),
        charge_basis=str(data.get("delegated_profile_charge_basis") or "allocated"),
        apply_price_to_past_reports=True,
        allocated_pricing_tiers_json=str(data.get("delegated_profile_allocated_tiers_json") or "[]"),
    )
    await callback.message.answer(t("admin_delegated_profile_saved", lang))
    await _render_delegated_detail(
        callback.message,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(DelegatedAdminStates.waiting_price_history_choice, F.data == "dag:pricing:history:keep")
async def delegated_admin_price_history_keep(
    callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    target_user_id = int(data["delegated_profile_target_user_id"])
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    summary = await services.admin_provisioning_service.get_admin_scope_financial_summary(
        actor_user_id=target_user_id,
        settings=settings,
    )
    await services.financial_service.set_pricing(
        actor_user_id=callback.from_user.id,
        telegram_user_id=target_user_id,
        price_per_gb=int(data["delegated_profile_new_price_gb"]),
        price_per_day=int(data["delegated_profile_new_price_day"]),
        charge_basis=str(data.get("delegated_profile_charge_basis") or "allocated"),
        apply_price_to_past_reports=False,
        consumed_bytes_snapshot=int(summary.get("consumed_bytes") or 0),
        allocated_pricing_tiers_json=str(data.get("delegated_profile_allocated_tiers_json") or "[]"),
    )
    await callback.message.answer(t("admin_delegated_profile_saved", lang))
    await _render_delegated_detail(
        callback.message,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:toggle_status:"))
async def delegated_admin_toggle_status(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    profile = await services.db.get_delegated_admin_profile(target_user_id)
    new_status = 0 if int(profile.get("is_active") or 0) == 1 else 1
    await services.db.update_delegated_admin_profile(
        telegram_user_id=target_user_id,
        is_active=new_status,
    )
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:toggle_scope:"))
async def delegated_admin_toggle_scope(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    delegated = await services.db.get_delegated_admin_by_user_id(target_user_id)
    if delegated is None:
        await callback.answer(t("admin_delegated_not_found", lang), show_alert=True)
        return
    next_scope = "full" if str(delegated.get("admin_scope") or "limited") == "limited" else "limited"
    await services.db.set_delegated_admin_scope(
        telegram_user_id=target_user_id,
        admin_scope=next_scope,
    )
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:toggle_basis:"))
async def delegated_admin_toggle_basis(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    pricing = await services.financial_service.get_pricing(target_user_id)
    next_basis = "consumed" if str(pricing.get("charge_basis") or "allocated") == "allocated" else "allocated"
    await services.financial_service.set_pricing(
        actor_user_id=callback.from_user.id,
        telegram_user_id=target_user_id,
        price_per_gb=int(pricing.get("price_per_gb") or 0),
        price_per_day=int(pricing.get("price_per_day") or 0),
        charge_basis=next_basis,
        allocated_pricing_tiers_json=str(pricing.get("allocated_pricing_tiers_json") or "[]"),
    )
    await services.db.update_delegated_admin_profile(
        telegram_user_id=target_user_id,
        charge_basis=next_basis,
    )
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:toggle_wallet_mode:"))
async def delegated_admin_toggle_wallet_mode(
    callback: CallbackQuery, settings: Settings, services: ServiceContainer
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    profile = await services.db.get_delegated_admin_profile(target_user_id)
    next_value = 0 if int(profile.get("allow_negative_wallet") or 0) == 1 else 1
    await services.db.update_delegated_admin_profile(
        telegram_user_id=target_user_id,
        allow_negative_wallet=next_value,
    )
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:report:"))
async def delegated_admin_report(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    overview = await services.admin_provisioning_service.get_delegated_admin_overview(
        telegram_user_id=target_user_id,
        settings=settings,
    )
    summary = await services.admin_provisioning_service.get_admin_scope_financial_summary(
        actor_user_id=target_user_id,
        settings=settings,
    )
    report = {"wallet": summary["wallet"]}
    wallet_lines = [
        _format_wallet_entry(item, settings=settings, lang=lang)
        for item in await services.db.list_recent_wallet_transactions(telegram_user_id=target_user_id, limit=10)
    ]
    activity_lines: list[str] = []
    for item in await services.db.list_recent_actor_audit_logs(actor_user_id=target_user_id, limit=20):
        formatted = _format_activity_entry(item, settings=settings, lang=lang)
        if formatted is not None:
            activity_lines.append(formatted)
    user = overview["user"] or {}
    title = (
        str(user.get("username") or "").strip()
        or str(user.get("full_name") or "").strip()
        or str(target_user_id)
    )
    extra_lines = ""
    report_sales = int(summary["sale_amount"] or 0)
    if str(summary["pricing"].get("charge_basis") or "allocated") == "consumed":
        payable_amount = payable_from_wallet(int(summary["wallet"]["balance"] or 0))
        extra_lines = t(
            "finance_credit_consumed_lines",
            lang,
            consumed_gb=_format_gb_exact(summary["consumed_gb"] or 0),
            debt_amount=_format_amount(int(summary["debt_amount"] or 0)),
            payable_amount=_format_amount(payable_amount),
            remaining_gb=_format_gb_exact(summary["remaining_gb"] or 0),
            remaining_amount=_format_amount(int(summary["remaining_amount"] or 0)),
            currency=str(summary["wallet"]["currency"] or "تومان"),
        )
        report_sales = int(summary["debt_amount"] or 0)
    await callback.message.edit_text(
        t(
            "admin_delegated_report_text",
            lang,
            title=title,
            balance=_format_amount(int(summary["wallet"]["balance"] or 0)),
            currency=str(report["wallet"]["currency"] or "تومان"),
            price_gb=_format_amount(int(summary["pricing"]["price_per_gb"] or 0)),
            price_day=_format_amount(int(summary["pricing"]["price_per_day"] or 0)),
            sales=_format_amount(report_sales),
            transactions=int(summary["total_transactions"] or 0),
            owned_clients=int(summary["clients_count"] or 0),
            extra_lines=extra_lines,
            wallet_lines="\n\n".join(wallet_lines) if wallet_lines else "تراکنشی ثبت نشده است.",
            activity_lines="\n\n".join(activity_lines) if activity_lines else "فعالیت مهمی ثبت نشده است.",
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dag:fxib:"))
async def delegated_finex_inbounds_menu(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
    *,
    answer_notify: str | None = None,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    try:
        delegate_id = int(parts[2])
        page = int(parts[3])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=delegate_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    delegated = await services.db.get_delegated_admin_by_user_id(delegate_id)
    if delegated is None or int(delegated.get("parent_user_id") or 0) != 0:
        await callback.answer(t("admin_delegated_finex_primary_only", lang), show_alert=True)
        return
    await _delegated_finex_inbounds_render(
        callback,
        settings,
        services,
        delegate_id=delegate_id,
        page=page,
        answer_notify=answer_notify,
    )


@router.callback_query(F.data.startswith("dag:fxibt:"))
async def delegated_finex_inbound_toggle(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, _, delegate_s, panel_s, inbound_s = callback.data.split(":", 4)
        delegate_id = int(delegate_s)
        panel_id = int(panel_s)
        inbound_id = int(inbound_s)
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=delegate_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    delegated = await services.db.get_delegated_admin_by_user_id(delegate_id)
    if delegated is None or int(delegated.get("parent_user_id") or 0) != 0:
        await callback.answer(t("admin_delegated_finex_primary_only", lang), show_alert=True)
        return
    key = (panel_id, inbound_id)
    try:
        excluded = await services.db.list_delegate_finance_excluded_inbounds(delegate_id)
        if key in excluded:
            await services.db.remove_delegate_finance_excluded_inbound(
                delegate_user_id=delegate_id, panel_id=panel_id, inbound_id=inbound_id
            )
        else:
            await services.db.add_delegate_finance_excluded_inbound(
                delegate_user_id=delegate_id, panel_id=panel_id, inbound_id=inbound_id
            )
    except Exception:
        await callback.answer(t("admin_delegated_finex_db_error", lang), show_alert=True)
        return
    await _delegated_finex_inbounds_render(
        callback,
        settings,
        services,
        delegate_id=delegate_id,
        page=0,
        answer_notify=t("admin_delegated_finex_toggled", lang),
    )


@router.callback_query(F.data.startswith("dag:fxcr:"))
async def delegated_finex_remain_menu(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
    *,
    answer_notify: str | None = None,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    try:
        delegate_id = int(parts[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=delegate_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    delegated = await services.db.get_delegated_admin_by_user_id(delegate_id)
    if delegated is None or int(delegated.get("parent_user_id") or 0) != 0:
        await callback.answer(t("admin_delegated_finex_primary_only", lang), show_alert=True)
        return
    await _delegated_finex_remain_render(
        callback,
        settings,
        services,
        delegate_id=delegate_id,
        answer_notify=answer_notify,
    )


@router.callback_query(F.data.startswith("dag:fxrmb:"))
async def delegated_finex_remain_bulk_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        delegate_id = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_delegated_target(
        actor_user_id=callback.from_user.id,
        target_user_id=delegate_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    delegated = await services.db.get_delegated_admin_by_user_id(delegate_id)
    if delegated is None or int(delegated.get("parent_user_id") or 0) != 0:
        await callback.answer(t("admin_delegated_finex_primary_only", lang), show_alert=True)
        return
    await state.set_state(DelegatedAdminStates.waiting_finex_remain_bulk_tokens)
    await state.update_data(finex_remain_bulk_delegate_id=delegate_id)
    await callback.message.answer(t("admin_delegated_finex_bulk_prompt", lang))
    await callback.answer()


@router.message(DelegatedAdminStates.waiting_finex_remain_bulk_tokens)
async def delegated_finex_remain_bulk_receive(
    message: Message,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_if_not_full_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    data = await state.get_data()
    delegate_id = int(data.get("finex_remain_bulk_delegate_id") or 0)
    if delegate_id <= 0:
        await state.clear()
        await message.answer(t("admin_invalid_data", lang))
        return
    tokens = _parse_finex_name_tokens(message.text or "")
    if not tokens:
        await message.answer(t("admin_delegated_finex_bulk_none", lang))
        return
    hits = await _search_clients_by_email_tokens(services, tokens)
    if not hits:
        await message.answer(t("admin_delegated_finex_bulk_none", lang))
        return
    sample_n = 40
    lines = [f"{i + 1}. {h['email']}" for i, h in enumerate(hits[:sample_n])]
    rest = len(hits) - sample_n
    if rest > 0:
        lines.append(f"... +{rest}")
    body = "\n".join(lines)
    preview = t(
        "admin_delegated_finex_bulk_preview",
        lang,
        count=len(hits),
        list=body,
    )
    await state.update_data(finex_remain_bulk_hits=hits)
    await state.set_state(DelegatedAdminStates.waiting_finex_remain_bulk_confirm)
    await message.answer(
        preview,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=t("btn_yes", lang), callback_data=f"dag:fxrmy:{delegate_id}"),
                    InlineKeyboardButton(text=t("btn_no", lang), callback_data=f"dag:fxrmn:{delegate_id}"),
                ],
            ]
        ),
    )


@router.callback_query(DelegatedAdminStates.waiting_finex_remain_bulk_confirm, F.data.startswith("dag:fxrmy:"))
async def delegated_finex_remain_bulk_yes(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        delegate_cb = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    data = await state.get_data()
    delegate_id = int(data.get("finex_remain_bulk_delegate_id") or 0)
    hits = data.get("finex_remain_bulk_hits")
    if delegate_cb != delegate_id or not isinstance(hits, list):
        await state.clear()
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    for item in hits:
        await services.db.add_delegate_finance_exclude_client_remaining(
            delegate_user_id=delegate_id,
            panel_id=int(item["panel_id"]),
            inbound_id=int(item["inbound_id"]),
            client_uuid=str(item["uuid"]),
        )
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("admin_delegated_finex_bulk_done", lang, count=len(hits)))
    await callback.answer()


@router.callback_query(DelegatedAdminStates.waiting_finex_remain_bulk_confirm, F.data.startswith("dag:fxrmn:"))
async def delegated_finex_remain_bulk_no(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("admin_delegated_finex_bulk_cancelled", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("dag:remove_user:"))
async def delegated_admin_remove_user(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    if callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    access_rows = await services.db.list_admin_access_rows_for_user(target_user_id)
    for row in access_rows:
        await services.admin_provisioning_service.revoke_delegated_admin_access(
            actor_user_id=callback.from_user.id,
            access_id=int(row["access_id"]),
        )
    await services.db.deactivate_delegated_admin(target_user_id)
    if callback.message is not None:
        rows = await services.admin_provisioning_service.list_delegated_admin_accesses(
            manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
        )
        text = t("admin_delegated_empty", lang) if not rows else t("admin_delegated_list_header", lang)
        await callback.message.edit_text(text, reply_markup=_delegated_access_list_keyboard(rows, lang))
    await callback.answer(t("admin_delegated_removed", lang))


@router.callback_query(F.data.startswith("dag:revoke:"))
async def delegated_admin_revoke(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await _reject_callback_if_not_full_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        access_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    revoked = await services.admin_provisioning_service.revoke_delegated_admin_access(
        actor_user_id=callback.from_user.id,
        access_id=access_id,
    )
    if callback.message is not None:
        rows = await services.admin_provisioning_service.list_delegated_admin_accesses(
            manager_user_id=None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
        )
        text = t("admin_delegated_empty", lang) if not rows else t("admin_delegated_list_header", lang)
        await callback.message.edit_text(text, reply_markup=_delegated_access_list_keyboard(rows, lang))
    await callback.answer(t("admin_delegated_removed", lang) if revoked else t("admin_panel_not_found", lang))
