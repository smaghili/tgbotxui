from __future__ import annotations

import json
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.states import DelegatedAdminStates
from bot.utils import (
    format_db_timestamp as shared_format_db_timestamp,
    format_gb_exact as shared_format_gb_exact,
    parse_gb_amount,
    parse_detail_pairs,
    relative_remaining_time,
    to_local_date,
    to_persian_digits,
)

router = Router(name="admin_access")


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


def _pricing_history_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="dag:pricing:history:apply"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="dag:pricing:history:keep"),
            ]
        ]
    )


def _delegated_detail_keyboard(
    user_id: int,
    *,
    is_active: bool,
    charge_basis: str,
    admin_scope: str,
    allow_negative_wallet: bool,
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
            [InlineKeyboardButton(text=t("admin_delegated_report", lang), callback_data=f"dag:report:{user_id}")],
        ]
    )
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
    if charge_basis == "consumed":
        total_sales_value = int(financial_summary.get("debt_amount") or 0)
        extra_lines = t(
            "admin_delegated_consumed_lines",
            lang,
            consumed_gb=_format_gb_exact(financial_summary.get("consumed_gb") or 0),
            remaining_gb=_format_gb_exact(financial_summary.get("remaining_gb") or 0),
            remaining_amount=_format_amount(int(financial_summary.get("remaining_amount") or 0)),
            currency=str(wallet.get("currency") or "تومان"),
        )
        balance_line = ""
    else:
        total_sales_value = int(sales_report.get("total_sales") or 0)
        extra_lines = ""
        balance_line = t(
            "admin_delegated_balance_line",
            lang,
            balance=_format_amount(int(wallet.get("balance") or 0)),
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
    reply_markup = _delegated_detail_keyboard(
        target_user_id,
        is_active=is_active,
        charge_basis=charge_basis,
        admin_scope=str(overview["delegated"].get("admin_scope") or "limited"),
        allow_negative_wallet=allow_negative_wallet,
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
    rows = await services.admin_provisioning_service.list_all_inbounds()
    if not rows:
        await state.clear()
        return None
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
    await _render_delegated_detail(
        callback,
        services=services,
        settings=settings,
        target_user_id=target_user_id,
        lang=lang,
    )
    await callback.answer()


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
            amount = int(raw.replace(",", ""))
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
    await services.financial_service.set_pricing(
        actor_user_id=callback.from_user.id,
        telegram_user_id=target_user_id,
        price_per_gb=int(data["delegated_profile_new_price_gb"]),
        price_per_day=int(data["delegated_profile_new_price_day"]),
        charge_basis=str(data.get("delegated_profile_charge_basis") or "allocated"),
        apply_price_to_past_reports=True,
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
    await services.financial_service.set_pricing(
        actor_user_id=callback.from_user.id,
        telegram_user_id=target_user_id,
        price_per_gb=int(data["delegated_profile_new_price_gb"]),
        price_per_day=int(data["delegated_profile_new_price_day"]),
        charge_basis=str(data.get("delegated_profile_charge_basis") or "allocated"),
        apply_price_to_past_reports=False,
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
    pricing = await services.financial_service.get_pricing(target_user_id)
    next_basis = "consumed" if str(pricing.get("charge_basis") or "allocated") == "allocated" else "allocated"
    await services.financial_service.set_pricing(
        actor_user_id=callback.from_user.id,
        telegram_user_id=target_user_id,
        price_per_gb=int(pricing.get("price_per_gb") or 0),
        price_per_day=int(pricing.get("price_per_day") or 0),
        charge_basis=next_basis,
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
    if str(summary["pricing"].get("charge_basis") or "allocated") == "consumed":
        extra_lines = t(
            "finance_credit_consumed_lines",
            lang,
            consumed_gb=_format_gb_exact(summary["consumed_gb"] or 0),
            debt_amount=_format_amount(int(summary["debt_amount"] or 0)),
            remaining_gb=_format_gb_exact(summary["remaining_gb"] or 0),
            remaining_amount=_format_amount(int(summary["remaining_amount"] or 0)),
            currency=str(summary["wallet"]["currency"] or "تومان"),
        )
    await callback.message.edit_text(
        t(
            "admin_delegated_report_text",
            lang,
            title=title,
            balance=_format_amount(int(summary["wallet"]["balance"] or 0)),
            currency=str(report["wallet"]["currency"] or "تومان"),
            price_gb=_format_amount(int(summary["pricing"]["price_per_gb"] or 0)),
            price_day=_format_amount(int(summary["pricing"]["price_per_day"] or 0)),
            sales=_format_amount(int(summary["sale_amount"] or 0)),
            transactions=int(summary["total_transactions"] or 0),
            owned_clients=int(summary["clients_count"] or 0),
            extra_lines=extra_lines,
            wallet_lines="\n\n".join(wallet_lines) if wallet_lines else "تراکنشی ثبت نشده است.",
            activity_lines="\n\n".join(activity_lines) if activity_lines else "فعالیت مهمی ثبت نشده است.",
        )
    )
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
