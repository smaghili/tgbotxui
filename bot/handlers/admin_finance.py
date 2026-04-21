from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import (
    finance_limited_delegated_keyboard,
    finance_primary_delegated_keyboard,
    finance_root_delegated_keyboard,
    main_keyboard,
)
from bot.services.container import ServiceContainer
from bot.states import FinanceStates
from bot.utils import to_persian_digits

from .admin_shared import answer_with_cancel, reject_callback_if_not_any_admin, reject_if_not_any_admin

router = Router(name="admin_finance")


def _finance_root_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("finance_delegates_list", lang), callback_data="fin:delegates:list")],
            [InlineKeyboardButton(text=t("btn_back", lang), callback_data="fin:root:back")],
        ]
    )


def _finance_delegated_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("finance_view_credit", lang), callback_data="fin:credit:me")],
            [
                InlineKeyboardButton(text=t("finance_delegates_list", lang), callback_data="fin:delegates:mine"),
                InlineKeyboardButton(text=t("finance_today_sales", lang), callback_data="fin:sales:today"),
            ],
            [InlineKeyboardButton(text=t("btn_back", lang), callback_data="fin:delegated:back")],
        ]
    )


def _finance_delegates_keyboard(
    rows: list[dict],
    *,
    back_callback: str,
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    seen_users: set[int] = set()
    for row in rows:
        user_id = int(row["telegram_user_id"])
        if user_id in seen_users:
            continue
        seen_users.add(user_id)
        title = str(row.get("title") or row.get("full_name") or row.get("username") or user_id)
        buttons.append([InlineKeyboardButton(text=title[:48], callback_data=f"dag:detail:{user_id}")])
    if not buttons:
        buttons.append([InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")])
    buttons.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _wallet_action_keyboard(target_user_id: int, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_wallet_show", lang), callback_data=f"fin:wallet:show:{target_user_id}"),
                InlineKeyboardButton(text=t("btn_wallet_set", lang), callback_data=f"fin:wallet:set:{target_user_id}"),
            ],
            [
                InlineKeyboardButton(text=t("btn_wallet_add", lang), callback_data=f"fin:wallet:add:{target_user_id}"),
                InlineKeyboardButton(text=t("btn_wallet_subtract", lang), callback_data=f"fin:wallet:sub:{target_user_id}"),
            ],
        ]
    )


def _pricing_history_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="fin:pricing:history:apply"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="fin:pricing:history:keep"),
            ]
        ]
    )


def _format_amount(value: int) -> str:
    return f"{value:,}"


def _format_gb_exact(value: float | int) -> str:
    formatted = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _parse_db_timestamp(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_db_timestamp(raw: str, *, settings: Settings, lang: str | None) -> str:
    dt = _parse_db_timestamp(raw)
    if dt is None:
        return raw
    local_dt = dt.astimezone(ZoneInfo(settings.timezone))
    if lang == "fa":
        from bot.utils import to_jalali_datetime

        return to_jalali_datetime(int(local_dt.timestamp()), settings.timezone)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _today_utc_range_strings(tz_name: str) -> tuple[str, str]:
    local_now = datetime.now(ZoneInfo(tz_name))
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    start_utc = local_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = local_end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return start_utc, end_utc


async def _actor_title(
    *,
    actor_user_id: int | None,
    services: ServiceContainer,
) -> str:
    if actor_user_id is None:
        return "-"
    user = await services.db.get_user_by_telegram_id(actor_user_id)
    if user is not None:
        name = str(user.get("full_name") or "").strip()
        if name:
            return name
        username = str(user.get("username") or "").strip()
        if username:
            return username
    delegated = await services.db.get_delegated_admin_by_user_id(actor_user_id)
    if delegated is not None:
        title = str(delegated.get("title") or "").strip()
        if title:
            return title
    return str(actor_user_id)


async def _transaction_email(
    item: dict,
    *,
    services: ServiceContainer,
) -> str:
    details = _parse_detail_pairs(item.get("details"))
    email = str(details.get("email") or details.get("client_email") or "").strip()
    if email:
        return email
    panel_raw = details.get("panel")
    inbound_raw = details.get("inbound")
    client_uuid = str(details.get("client_uuid") or "").strip()
    if not panel_raw or not inbound_raw or not client_uuid:
        return "-"
    try:
        detail = await services.panel_service.get_client_detail(int(panel_raw), int(inbound_raw), client_uuid)
    except Exception:
        return "-"
    return str(detail.get("email") or "-").strip() or "-"


def _parse_detail_pairs(raw: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _parse_admin_activity_text(raw: str | None) -> dict[str, str | list[str]]:
    parsed: dict[str, str | list[str]] = {
        "actor": "",
        "operation": "",
        "user": "",
        "panel": "",
        "inbound": "",
        "time": "",
        "extras": [],
    }
    mapping = {
        f"{t('admin_activity_label_actor', 'fa')}:": "actor",
        f"{t('admin_activity_label_actor', 'en')}:": "actor",
        f"{t('admin_activity_label_action', 'fa')}:": "operation",
        f"{t('admin_activity_label_action', 'en')}:": "operation",
        f"{t('admin_activity_label_user', 'fa')}:": "user",
        f"{t('admin_activity_label_user', 'en')}:": "user",
        f"{t('admin_activity_label_panel', 'fa')}:": "panel",
        f"{t('admin_activity_label_panel', 'en')}:": "panel",
        f"{t('admin_activity_label_inbound', 'fa')}:": "inbound",
        f"{t('admin_activity_label_inbound', 'en')}:": "inbound",
        f"{t('admin_activity_label_time', 'fa')}:": "time",
        f"{t('admin_activity_label_time', 'en')}:": "time",
    }
    extras: list[str] = []
    for raw_line in str(raw or "").splitlines():
        line = raw_line.strip()
        if not line or line in {
            f"{t('admin_activity_notice_title', 'fa')}:",
            f"{t('admin_activity_notice_title', 'en')}:",
        }:
            continue
        for prefix, key in mapping.items():
            if line.startswith(prefix):
                parsed[key] = line[len(prefix) :].strip()
                break
        else:
            extras.append(line)
    parsed["extras"] = extras
    return parsed


def _create_activity_signature(*, actor_user_id: int, created_at: str, user: str) -> tuple[int, str, str]:
    return actor_user_id, created_at.strip(), user.strip().lower()


def _wallet_create_client_signature(item: dict) -> tuple[int, str, str] | None:
    actor_user_id = int(item.get("actor_user_id") or 0)
    details = _parse_detail_pairs(item.get("details"))
    email = str(details.get("email") or "").strip()
    created_at = str(item.get("created_at") or "").strip()
    if actor_user_id <= 0 or not email or not created_at:
        return None
    return _create_activity_signature(
        actor_user_id=actor_user_id,
        created_at=created_at,
        user=email,
    )


def _extract_create_client_amounts(
    *,
    extras: list[str] | None = None,
    wallet_item: dict | None = None,
) -> tuple[str | None, str | None]:
    traffic_value: str | None = None
    expiry_value: str | None = None

    for extra in extras or []:
        line = str(extra).strip()
        if not line:
            continue
        if traffic_value is None and any(
            token in line
            for token in (
                t("finance_unit_gb_short", "fa"),
                t("finance_unit_gb_short", "en"),
            )
        ):
            raw_value = line.split(":", 1)[1].strip() if ":" in line else line
            traffic_value = (
                raw_value.replace(t("finance_unit_gb_short", "fa"), "")
                .replace(t("finance_unit_gb_short", "en"), "")
                .strip()
            )
            continue
        if expiry_value is None and any(
            token in line
            for token in (
                t("finance_unit_day_short", "fa"),
                t("finance_unit_day_short", "en"),
                t("finance_report_expiry_part", "fa", value=""),
                t("finance_report_expiry_part", "en", value=""),
            )
        ):
            raw_value = line.split(":", 1)[1].strip() if ":" in line else line
            expiry_value = (
                raw_value.replace(t("finance_report_expiry_part", "fa", value="").strip(), "")
                .replace(t("finance_unit_day_short", "fa"), "")
                .replace(t("finance_unit_day_short", "en"), "")
                .strip()
            )

    if wallet_item is not None:
        try:
            metadata = json.loads(wallet_item.get("metadata_json") or "{}")
        except Exception:
            metadata = {}
        if traffic_value is None:
            traffic_gb = int(metadata.get("traffic_gb") or 0)
            if traffic_gb > 0:
                traffic_value = str(traffic_gb)
        if expiry_value is None:
            expiry_days = int(metadata.get("expiry_days") or 0)
            if expiry_days > 0:
                expiry_value = str(expiry_days)

    return traffic_value, expiry_value


async def _resolve_panel_inbound_names_from_details(
    details: dict[str, str],
    *,
    services: ServiceContainer,
) -> tuple[str, str]:
    panel_raw = str(details.get("panel") or "").strip()
    inbound_raw = str(details.get("inbound") or "").strip()
    panel_name = panel_raw or "-"
    inbound_name = inbound_raw or "-"
    if panel_raw.lstrip("-").isdigit():
        panel = await services.panel_service.get_panel(int(panel_raw))
        if panel is not None:
            panel_name = str(panel.get("name") or panel_raw)
        if inbound_raw.lstrip("-").isdigit():
            try:
                inbounds = await services.panel_service.list_inbounds(int(panel_raw))
                inbound = next((item for item in inbounds if int(item.get("id") or 0) == int(inbound_raw)), None)
                if inbound is not None:
                    remark = str(inbound.get("remark") or "").strip()
                    inbound_name = remark or f"inbound-{inbound_raw}"
            except Exception:
                pass
    return panel_name, inbound_name

async def _format_today_sale_line(
    item: dict,
    *,
    row_number: int,
    report_user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> str:
    try:
        metadata = json.loads(item.get("metadata_json") or "{}")
    except Exception:
        metadata = {}
    operation = str(item.get("operation") or "")
    actor_user_id = int(item.get("actor_user_id") or item.get("telegram_user_id") or 0)
    actor_name = await _actor_title(actor_user_id=actor_user_id, services=services)
    email = await _transaction_email(item, services=services)
    created_at = _format_db_timestamp(str(item.get("created_at") or ""), settings=settings, lang=lang)
    traffic_gb = int(metadata.get("traffic_gb") or 0)
    expiry_days = int(metadata.get("expiry_days") or 0)
    amount = _format_amount(abs(int(item.get("amount") or 0)))
    currency = str(item.get("currency") or t("finance_currency_default", lang))
    amount_label = f"{amount} {currency}"
    row_label = str(row_number)
    traffic_label = str(traffic_gb)
    expiry_label = str(expiry_days)
    if lang != "en":
        row_label = to_persian_digits(row_label)
        traffic_label = to_persian_digits(traffic_label)
        expiry_label = to_persian_digits(expiry_label)
    if actor_user_id == report_user_id or services.access_service.is_root_admin(actor_user_id, settings):
        amount_label = t("finance_amount_unknown", lang)

    if operation == "create_client":
        parts = [
            f"{t('admin_activity_action_create_client', lang)} {email}",
            t("finance_report_traffic_part", lang, value=traffic_label),
            t("finance_report_expiry_part", lang, value=expiry_label),
            t("finance_report_actor_part", lang, value=actor_name),
            t("finance_report_time_part", lang, value=created_at),
            t("finance_report_amount_part", lang, value=amount_label),
        ]
        return f"{row_label}. " + " - ".join(parts)
    parts = [
        f"{t('admin_activity_action_add_traffic', lang)} {email}",
        t("finance_report_traffic_part", lang, value=traffic_label),
        t("finance_report_actor_part", lang, value=actor_name),
        t("finance_report_time_part", lang, value=created_at),
        t("finance_report_amount_part", lang, value=amount_label),
    ]
    return f"{row_label}. " + " - ".join(parts)


async def _format_today_report_line(
    item: dict,
    *,
    row_number: int,
    settings: Settings,
    services: ServiceContainer,
    wallet_create_rows_by_signature: dict[tuple[int, str, str], dict] | None = None,
    lang: str | None,
) -> tuple[str, tuple[int, str, str] | None] | None:
    action = str(item.get("action") or "")
    actor_user_id = int(item.get("actor_user_id") or 0)
    if action == "admin_activity":
        parsed = _parse_admin_activity_text(item.get("details"))
        operation = str(parsed.get("operation") or "").strip()
        if not operation:
            return None

        row_label = str(row_number)
        if lang != "en":
            row_label = to_persian_digits(row_label)

        user = str(parsed.get("user") or "").strip()
        actor = str(parsed.get("actor") or "").strip()
        panel = str(parsed.get("panel") or "").strip()
        inbound = str(parsed.get("inbound") or "").strip()
        report_time = str(parsed.get("time") or "").strip()
        extras = [str(value).strip() for value in list(parsed.get("extras") or []) if str(value).strip()]

        headline = operation if not user else f"{operation} {user}"
        signature = None
        wallet_item = None
        if operation in {
            t("admin_activity_action_create_client", "fa"),
            t("admin_activity_action_create_client", "en"),
        } and user:
            signature = _create_activity_signature(
                actor_user_id=actor_user_id,
                created_at=str(item.get("created_at") or ""),
                user=user,
            )
            wallet_item = wallet_create_rows_by_signature.get(signature) if wallet_create_rows_by_signature else None

        parts = [headline]
        if signature is not None:
            traffic_value, expiry_value = _extract_create_client_amounts(extras=extras, wallet_item=wallet_item)
            if traffic_value:
                parts.append(t("finance_report_traffic_part", lang, value=traffic_value))
            if expiry_value:
                parts.append(t("finance_report_expiry_part", lang, value=expiry_value))
        else:
            parts.extend(extras)
        if actor:
            parts.append(t("finance_report_actor_part", lang, value=actor))
        if panel:
            parts.append(t("finance_report_panel_part", lang, value=panel))
        if inbound:
            parts.append(t("finance_report_inbound_part", lang, value=inbound))
        if report_time:
            parts.append(t("finance_report_time_part", lang, value=report_time))

        line = f"{row_label}. " + " - ".join(parts)
        return (to_persian_digits(line) if lang != "en" else line, signature)

    if action != "create_client":
        return None

    details = _parse_detail_pairs(item.get("details"))
    email = str(details.get("email") or "-").strip() or "-"
    actor_name = await _actor_title(actor_user_id=actor_user_id, services=services)
    created_at = _format_db_timestamp(str(item.get("created_at") or ""), settings=settings, lang=lang)
    panel_name, inbound_name = await _resolve_panel_inbound_names_from_details(details, services=services)
    signature = _create_activity_signature(
        actor_user_id=actor_user_id,
        created_at=str(item.get("created_at") or ""),
        user=email,
    )
    wallet_item = wallet_create_rows_by_signature.get(signature) if wallet_create_rows_by_signature else None
    traffic_value, expiry_value = _extract_create_client_amounts(wallet_item=wallet_item)
    row_label = str(row_number)
    if lang != "en":
        row_label = to_persian_digits(row_label)
    parts = [f"{t('admin_activity_action_create_client', lang)} {email}"]
    if traffic_value:
        parts.append(t("finance_report_traffic_part", lang, value=traffic_value))
    if expiry_value:
        parts.append(t("finance_report_expiry_part", lang, value=expiry_value))
    parts.extend(
        [
            t("finance_report_actor_part", lang, value=actor_name),
            t("finance_report_panel_part", lang, value=panel_name),
            t("finance_report_inbound_part", lang, value=inbound_name),
            t("finance_report_time_part", lang, value=created_at),
        ]
    )
    line = f"{row_label}. " + " - ".join(parts)
    return (
        to_persian_digits(line) if lang != "en" else line,
        signature,
    )



async def _answer_today_sales(
    message: Message,
    *,
    actor_user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> None:
    if services.access_service.is_root_admin(actor_user_id, settings):
        delegate_rows = await services.admin_provisioning_service.list_delegated_admin_accesses(manager_user_id=None)
        owner_ids = sorted({actor_user_id, *[int(row["telegram_user_id"]) for row in delegate_rows]})
    else:
        owner_ids = await services.admin_provisioning_service.financial_scope_user_ids(
            actor_user_id=actor_user_id,
            settings=settings,
        )
    if not owner_ids:
        await message.answer(t("finance_today_sales_empty", lang))
        return
    start_utc, end_utc = _today_utc_range_strings(settings.timezone)
    rows = await services.db.list_scope_wallet_transactions(
        owner_ids,
        operation_names=["create_client", "add_client_traffic", "add_client_total_gb"],
        kind="charge",
        created_at_from=start_utc,
        created_at_to=end_utc,
        limit=2000,
    )
    if not rows:
        await message.answer(t("finance_today_sales_empty", lang))
        return

    lines = [
        await _format_today_sale_line(
            item,
            row_number=index,
            report_user_id=actor_user_id,
            settings=settings,
            services=services,
            lang=lang,
        )
        for index, item in enumerate(rows, start=1)
    ]
    header = t("finance_today_sales_title", lang)
    buffer = header
    for line in lines:
        candidate = f"{buffer}\n\n{line}" if buffer != header else f"{header}\n\n{line}"
        if len(candidate) > 3500 and buffer != header:
            await message.answer(buffer)
            buffer = f"{header}\n\n{line}"
        else:
            buffer = candidate
    await message.answer(buffer)


async def _answer_today_reports(
    message: Message,
    *,
    actor_user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> None:
    if services.access_service.is_root_admin(actor_user_id, settings):
        delegate_rows = await services.admin_provisioning_service.list_delegated_admin_accesses(manager_user_id=None)
        owner_ids = sorted({actor_user_id, *[int(row["telegram_user_id"]) for row in delegate_rows]})
    else:
        owner_ids = await services.admin_provisioning_service.financial_scope_user_ids(
            actor_user_id=actor_user_id,
            settings=settings,
        )
    if not owner_ids:
        await message.answer(t("finance_today_reports_empty", lang))
        return

    start_utc, end_utc = _today_utc_range_strings(settings.timezone)
    rows = await services.db.list_scope_audit_logs(
        owner_ids,
        actions=["admin_activity", "create_client"],
        created_at_from=start_utc,
        created_at_to=end_utc,
        limit=2000,
    )
    wallet_rows = await services.db.list_scope_wallet_transactions(
        owner_ids,
        operation_names=["create_client"],
        kind="charge",
        created_at_from=start_utc,
        created_at_to=end_utc,
        limit=2000,
    )
    wallet_create_rows_by_signature = {
        signature: item
        for item in wallet_rows
        if (signature := _wallet_create_client_signature(item)) is not None
    }
    admin_activity_signatures: set[tuple[int, str, str]] = set()
    formatted_rows: list[tuple[dict, tuple[str, tuple[int, str, str] | None]]] = []
    for item in rows:
        formatted = await _format_today_report_line(
            item,
            row_number=0,
            settings=settings,
            services=services,
            wallet_create_rows_by_signature=wallet_create_rows_by_signature,
            lang=lang,
        )
        if formatted is None:
            continue
        line, signature = formatted
        formatted_rows.append((item, (line, signature)))
        if str(item.get("action") or "") == "admin_activity" and signature is not None:
            admin_activity_signatures.add(signature)

    lines: list[str] = []
    for item, (line, signature) in formatted_rows:
        if str(item.get("action") or "") == "create_client" and signature in admin_activity_signatures:
            continue
        line_number = len(lines) + 1
        numbered = await _format_today_report_line(
            item,
            row_number=line_number,
            settings=settings,
            services=services,
            wallet_create_rows_by_signature=wallet_create_rows_by_signature,
            lang=lang,
        )
        if numbered is None:
            continue
        lines.append(numbered[0])
    if not lines:
        await message.answer(t("finance_today_reports_empty", lang))
        return

    header = t("finance_today_reports_title", lang)
    buffer = header
    for line in lines:
        candidate = f"{buffer}\n\n{line}" if buffer != header else f"{header}\n\n{line}"
        if len(candidate) > 3500 and buffer != header:
            await message.answer(buffer)
            buffer = f"{header}\n\n{line}"
        else:
            buffer = candidate
    await message.answer(buffer)


async def _is_primary_delegated_admin(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    context = await services.access_service.get_admin_context(user_id, settings)
    return context.is_delegated_admin and context.delegated_scope == "full"


async def _is_any_delegated_admin(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    return (await services.access_service.get_admin_context(user_id, settings)).is_delegated_admin


async def _can_access_today_finance(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    if services.access_service.is_root_admin(user_id, settings):
        return True
    return await _is_any_delegated_admin(user_id=user_id, settings=settings, services=services)


async def _finance_menu_text_and_keyboard(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
):
    if services.access_service.is_root_admin(user_id, settings):
        return t("finance_root_delegate_menu", lang), finance_root_delegated_keyboard(lang)
    if await _is_primary_delegated_admin(user_id=user_id, settings=settings, services=services):
        return t("finance_delegated_title", lang), finance_primary_delegated_keyboard(lang)
    return t("finance_limited_delegated_title", lang), finance_limited_delegated_keyboard(lang)


def _display_title(user: dict | None, fallback_user_id: int) -> str:
    if user is None:
        return str(fallback_user_id)
    title = str(user.get("full_name") or "").strip()
    if title:
        return title
    username = str(user.get("username") or "").strip()
    if username:
        return f"@{username}"
    return str(fallback_user_id)


async def _main_menu_markup(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
):
    return main_keyboard(await services.access_service.is_any_admin(user_id, settings), lang)


async def _wallet_target_summary_text(
    *,
    target_user_id: int,
    services: ServiceContainer,
    lang: str | None,
) -> str:
    wallet = await services.financial_service.get_wallet(target_user_id)
    pricing = await services.financial_service.get_pricing(target_user_id)
    user = await services.db.get_user_by_telegram_id(target_user_id)
    return t(
        "finance_wallet_target_summary",
        lang,
        title=_display_title(user, target_user_id),
        balance=_format_amount(int(wallet["balance"] or 0)),
        currency=str(wallet["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
        price_gb=_format_amount(int(pricing["price_per_gb"] or 0)),
        price_day=_format_amount(int(pricing["price_per_day"] or 0)),
    )


async def _answer_sales_report(
    target: Message | CallbackQuery,
    *,
    report_user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> None:
    summary = await services.admin_provisioning_service.get_admin_scope_financial_summary(
        actor_user_id=report_user_id,
        settings=settings,
    )
    wallet = summary["wallet"]
    pricing = summary["pricing"]
    context = await services.access_service.get_admin_context(report_user_id, settings)
    charge_basis = str(pricing.get("charge_basis") or "allocated")
    extra_lines = ""
    if charge_basis == "consumed":
        extra_lines = t(
            "finance_credit_consumed_lines",
            lang,
            consumed_gb=_format_gb_exact(summary["consumed_gb"] or 0),
            debt_amount=_format_amount(int(summary["debt_amount"] or 0)),
            currency=str(wallet["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
        )
    if context.delegated_scope == "full":
        text = t(
            "finance_credit_report_text",
            lang,
            title=_display_title(await services.db.get_user_by_telegram_id(report_user_id), report_user_id),
            balance=_format_amount(int(wallet["balance"] or 0)),
            currency=str(wallet["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
            price_gb=_format_amount(int(pricing["price_per_gb"] or 0)),
            price_day=_format_amount(int(pricing["price_per_day"] or 0)),
            clients=int(summary["clients_count"] or 0),
            sale_amount=_format_amount(int(summary["sale_amount"] or 0)),
            transactions=int(summary["total_transactions"] or 0),
            extra_lines=extra_lines,
        )
    else:
        text = t(
            "finance_limited_report_text",
            lang,
            balance=_format_amount(int(wallet["balance"] or 0)),
            currency=str(wallet["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
            clients=int(summary["clients_count"] or 0),
            allocated_gb=int(summary["allocated_gb"] or 0),
            sale_amount=_format_amount(int(summary["sale_amount"] or 0)),
        )
    message = target.message if isinstance(target, CallbackQuery) else target
    if message is not None:
        if isinstance(target, CallbackQuery):
            await message.edit_text(text)
        else:
            await message.answer(text)


async def _save_pricing_and_answer(
    message: Message,
    *,
    actor_user_id: int,
    target_user_id: int,
    price_gb: int,
    price_day: int,
    apply_to_past_reports: bool | None,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> None:
    pricing = await services.financial_service.set_pricing(
        actor_user_id=actor_user_id,
        telegram_user_id=target_user_id,
        price_per_gb=price_gb,
        price_per_day=price_day,
        apply_price_to_past_reports=apply_to_past_reports,
    )
    await message.answer(
        t(
            "finance_pricing_saved",
            lang,
            price_gb=_format_amount(int(pricing["price_per_gb"] or 0)),
            price_day=_format_amount(int(pricing["price_per_day"] or 0)),
            currency=str(pricing["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
        ),
        reply_markup=await _main_menu_markup(
            user_id=actor_user_id,
            settings=settings,
            services=services,
            lang=lang,
        ),
    )


@router.message(F.text.in_(button_variants("btn_manage_finance")))
async def manage_finance_menu(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    text, reply_markup = await _finance_menu_text_and_keyboard(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )
    await message.answer(
        text,
        reply_markup=reply_markup,
    )


@router.message(F.text.in_(button_variants("finance_view_credit")))
async def finance_view_credit_message(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not await _is_primary_delegated_admin(user_id=message.from_user.id, settings=settings, services=services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await _answer_sales_report(
        message,
        report_user_id=message.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )


@router.message(F.text.in_(button_variants("finance_today_sales")))
async def finance_today_sales_message(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not await _can_access_today_finance(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
    ):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await _answer_today_sales(
        message,
        actor_user_id=message.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )


@router.message(F.text.in_(button_variants("finance_today_reports")))
async def finance_today_reports_message(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not await _can_access_today_finance(
        user_id=message.from_user.id,
        settings=settings,
        services=services,
    ):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await _answer_today_reports(
        message,
        actor_user_id=message.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )


@router.message(F.text.in_(button_variants("finance_delegates_list")))
async def finance_my_delegates_list_message(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    if services.access_service.is_root_admin(message.from_user.id, settings):
        rows = await services.admin_provisioning_service.list_delegated_admin_accesses(manager_user_id=None)
        rows = [row for row in rows if int(row.get("telegram_user_id") or 0) not in set(settings.admin_ids)]
        back_callback = "fin:root:list:close"
    elif await _is_primary_delegated_admin(user_id=message.from_user.id, settings=settings, services=services):
        rows = await services.admin_provisioning_service.list_delegated_admin_accesses(manager_user_id=message.from_user.id)
        back_callback = "fin:delegated:list:close"
    else:
        return
    text = t("admin_delegated_empty", lang) if not rows else t("finance_delegates_list_header", lang)
    await message.answer(
        text,
        reply_markup=_finance_delegates_keyboard(rows, back_callback=back_callback, lang=lang),
    )


@router.callback_query(F.data == "fin:root:menu")
async def finance_root_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.message is not None:
        await callback.message.edit_text(t("finance_root_delegate_menu", lang))
        await callback.message.answer(
            t("finance_root_delegate_menu", lang),
            reply_markup=finance_root_delegated_keyboard(lang),
        )
    await callback.answer()


@router.callback_query(F.data == "fin:delegates:list")
async def finance_delegates_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    rows = await services.admin_provisioning_service.list_delegated_admin_accesses(manager_user_id=None)
    filtered_rows = [row for row in rows if int(row.get("telegram_user_id") or 0) not in set(settings.admin_ids)]
    text = t("admin_delegated_empty", lang) if not filtered_rows else t("finance_delegates_list_header", lang)
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=_finance_delegates_keyboard(filtered_rows, back_callback="fin:root:menu", lang=lang),
        )
    await callback.answer()


@router.callback_query(F.data == "fin:delegates:mine")
async def finance_my_delegates_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not await _is_primary_delegated_admin(user_id=callback.from_user.id, settings=settings, services=services):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    rows = await services.admin_provisioning_service.list_delegated_admin_accesses(manager_user_id=callback.from_user.id)
    text = t("admin_delegated_empty", lang) if not rows else t("finance_delegates_list_header", lang)
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=_finance_delegates_keyboard(rows, back_callback="fin:delegated:list:close", lang=lang),
        )
    await callback.answer()


@router.callback_query(F.data == "fin:root:back")
async def finance_root_back(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.message is not None:
        await callback.message.answer(
            t("menu_main", lang),
            reply_markup=await _main_menu_markup(
                user_id=callback.from_user.id,
                settings=settings,
                services=services,
                lang=lang,
            ),
        )
    await callback.answer()


@router.callback_query(F.data == "fin:root:list:close")
async def finance_root_list_close(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.message is not None:
        await callback.message.edit_text(t("finance_root_delegate_menu", lang))
    await callback.answer()


@router.callback_query(F.data == "fin:delegated:list:close")
async def finance_delegated_list_close(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not await _is_primary_delegated_admin(user_id=callback.from_user.id, settings=settings, services=services):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.message is not None:
        await callback.message.edit_text(t("finance_delegated_title", lang))
    await callback.answer()


@router.callback_query(F.data == "fin:wallet")
async def finance_wallet_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.set_state(FinanceStates.waiting_wallet_target)
    await state.update_data(finance_mode="wallet")
    if callback.message is not None:
        await answer_with_cancel(callback.message, t("finance_enter_target", lang), lang=lang)
    await callback.answer()


@router.callback_query(F.data == "fin:pricing")
async def finance_pricing_prompt(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.set_state(FinanceStates.waiting_pricing_target)
    if callback.message is not None:
        await answer_with_cancel(callback.message, t("finance_enter_target", lang), lang=lang)
    await callback.answer()


@router.callback_query(F.data == "fin:report:overall")
async def finance_overall_report(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    report = await services.financial_service.get_overall_report()
    text = t(
        "finance_overall_report_text",
        lang,
        wallets=int(report["wallets_count"]),
        balance=_format_amount(int(report["total_balance"] or 0)),
        currency=str(report["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
        sales=_format_amount(int(report["total_sales"] or 0)),
        sales_count=int(report["sales_count"]),
        transactions=int(report["total_transactions"]),
        pricing_profiles=int(report["pricing_profiles"]),
    )
    if callback.message is not None:
        await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "fin:credit:me")
async def finance_my_sales_report(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not await _is_primary_delegated_admin(user_id=callback.from_user.id, settings=settings, services=services):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await _answer_sales_report(
        callback,
        report_user_id=callback.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data == "fin:sales:today")
async def finance_today_sales_callback(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    if not await _can_access_today_finance(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await _answer_today_sales(
        callback.message,
        actor_user_id=callback.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )
    await callback.answer()


@router.message(FinanceStates.waiting_wallet_target)
async def finance_wallet_target_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not services.access_service.is_root_admin(message.from_user.id, settings):
        await message.answer(t("no_admin_access", None))
        return
    lang = await services.db.get_user_language(message.from_user.id)
    target_raw = (message.text or "").strip()
    try:
        target_user_id, _ = await services.admin_provisioning_service.resolve_admin_target(target_raw)
    except ValueError:
        await answer_with_cancel(message, t("finance_target_unknown", lang), lang=lang)
        return
    await state.update_data(finance_wallet_target_user_id=target_user_id)
    summary = await _wallet_target_summary_text(target_user_id=target_user_id, services=services, lang=lang)
    await message.answer(
        f"{summary}\n\n{t('finance_choose_wallet_action', lang)}",
        reply_markup=_wallet_action_keyboard(target_user_id, lang),
    )
    await state.clear()


@router.callback_query(F.data.startswith("fin:wallet:"))
async def finance_wallet_action(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, _, action, target_raw = callback.data.split(":", 3)
        target_user_id = int(target_raw)
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if action == "show":
        summary = await _wallet_target_summary_text(target_user_id=target_user_id, services=services, lang=lang)
        await callback.message.answer(
            f"{summary}\n\n{t('finance_choose_wallet_action', lang)}",
            reply_markup=_wallet_action_keyboard(target_user_id, lang),
        )
        await callback.answer()
        return
    await state.set_state(FinanceStates.waiting_wallet_amount)
    await state.update_data(finance_wallet_target_user_id=target_user_id, finance_wallet_action=action)
    await answer_with_cancel(callback.message, t("finance_enter_amount", lang), lang=lang)
    await callback.answer()


@router.message(FinanceStates.waiting_wallet_amount)
async def finance_wallet_amount_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not services.access_service.is_root_admin(message.from_user.id, settings):
        await message.answer(t("no_admin_access", None))
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        amount = int((message.text or "").replace(",", "").strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("finance_invalid_amount", lang), lang=lang)
        return
    data = await state.get_data()
    await state.clear()
    target_user_id = int(data["finance_wallet_target_user_id"])
    action = str(data["finance_wallet_action"])
    try:
        if action == "set":
            result = await services.financial_service.set_wallet_balance(
                actor_user_id=message.from_user.id,
                telegram_user_id=target_user_id,
                amount=amount,
            )
        elif action == "add":
            result = await services.financial_service.adjust_wallet_balance(
                actor_user_id=message.from_user.id,
                telegram_user_id=target_user_id,
                delta=amount,
                details=f"wallet_add={amount}",
            )
        else:
            result = await services.financial_service.adjust_wallet_balance(
                actor_user_id=message.from_user.id,
                telegram_user_id=target_user_id,
                delta=-amount,
                details=f"wallet_subtract={amount}",
            )
    except ValueError as exc:
        text = t("finance_insufficient_wallet", lang) if "insufficient" in str(exc).lower() else t("finance_invalid_amount", lang)
        await answer_with_cancel(message, text, lang=lang)
        return
    await message.answer(
        t(
            "finance_wallet_updated",
            lang,
            balance=_format_amount(int(result["balance_after"] or 0)),
            currency=str(result["currency"] or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
        ),
        reply_markup=await _main_menu_markup(
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            lang=lang,
        ),
    )


@router.message(FinanceStates.waiting_pricing_target)
async def finance_pricing_target_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not services.access_service.is_root_admin(message.from_user.id, settings):
        await message.answer(t("no_admin_access", None))
        return
    lang = await services.db.get_user_language(message.from_user.id)
    target_raw = (message.text or "").strip()
    try:
        target_user_id, _ = await services.admin_provisioning_service.resolve_admin_target(target_raw)
    except ValueError:
        await answer_with_cancel(message, t("finance_target_unknown", lang), lang=lang)
        return
    await state.update_data(finance_pricing_target_user_id=target_user_id)
    await state.set_state(FinanceStates.waiting_pricing_gb)
    await answer_with_cancel(message, t("finance_enter_price_per_gb", lang), lang=lang)


@router.message(FinanceStates.waiting_pricing_gb)
async def finance_pricing_gb_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not services.access_service.is_root_admin(message.from_user.id, settings):
        await message.answer(t("no_admin_access", None))
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        price_gb = int((message.text or "").replace(",", "").strip())
        if price_gb < 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("finance_invalid_amount", lang), lang=lang)
        return
    await state.update_data(finance_price_per_gb=price_gb)
    await state.set_state(FinanceStates.waiting_pricing_day)
    await answer_with_cancel(message, t("finance_enter_price_per_day", lang), lang=lang)


@router.message(FinanceStates.waiting_pricing_day)
async def finance_pricing_day_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    if not services.access_service.is_root_admin(message.from_user.id, settings):
        await message.answer(t("no_admin_access", None))
        return
    lang = await services.db.get_user_language(message.from_user.id)
    try:
        price_day = int((message.text or "").replace(",", "").strip())
        if price_day < 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("finance_invalid_amount", lang), lang=lang)
        return
    data = await state.get_data()
    target_user_id = int(data["finance_pricing_target_user_id"])
    price_gb = int(data["finance_price_per_gb"])
    current_pricing = await services.financial_service.get_pricing(target_user_id)
    old_price_gb = int(current_pricing.get("price_per_gb") or 0)
    if old_price_gb != price_gb:
        await state.update_data(
            finance_price_per_day=price_day,
            finance_old_price_per_gb=old_price_gb,
            finance_pricing_currency=str(current_pricing.get("currency") or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
        )
        await state.set_state(FinanceStates.waiting_pricing_history_choice)
        await message.answer(
            t(
                "finance_pricing_history_confirm",
                lang,
                old_price_gb=_format_amount(old_price_gb),
                new_price_gb=_format_amount(price_gb),
                currency=str(current_pricing.get("currency") or "Ã˜ÂªÃ™Ë†Ã™â€¦Ã˜Â§Ã™â€ "),
            ),
            reply_markup=_pricing_history_choice_keyboard(lang),
        )
        return
    await state.clear()
    await _save_pricing_and_answer(
        message,
        actor_user_id=message.from_user.id,
        target_user_id=target_user_id,
        price_gb=price_gb,
        price_day=price_day,
        apply_to_past_reports=None,
        settings=settings,
        services=services,
        lang=lang,
    )


@router.callback_query(FinanceStates.waiting_pricing_history_choice, F.data == "fin:pricing:history:apply")
async def finance_pricing_history_apply(
    callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    await _save_pricing_and_answer(
        callback.message,
        actor_user_id=callback.from_user.id,
        target_user_id=int(data["finance_pricing_target_user_id"]),
        price_gb=int(data["finance_price_per_gb"]),
        price_day=int(data["finance_price_per_day"]),
        apply_to_past_reports=True,
        settings=settings,
        services=services,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(FinanceStates.waiting_pricing_history_choice, F.data == "fin:pricing:history:keep")
async def finance_pricing_history_keep(
    callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    await _save_pricing_and_answer(
        callback.message,
        actor_user_id=callback.from_user.id,
        target_user_id=int(data["finance_pricing_target_user_id"]),
        price_gb=int(data["finance_price_per_gb"]),
        price_day=int(data["finance_price_per_day"]),
        apply_to_past_reports=False,
        settings=settings,
        services=services,
        lang=lang,
    )
    await callback.answer()


