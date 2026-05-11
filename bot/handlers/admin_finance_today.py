"""Today's sales/reports formatting and handlers."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.types import Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.utils import to_persian_digits

from bot.handlers.admin_finance_helpers import (
    _actor_title,
    _create_activity_signature,
    _extract_create_client_amounts,
    _format_amount,
    _format_db_timestamp,
    _parse_admin_activity_text,
    _parse_detail_pairs,
    _resolve_panel_inbound_names_from_details,
    _today_utc_range_strings,
    _transaction_email,
    _wallet_create_client_signature,
)

from .admin_finance_ops import _can_access_today_finance
from .admin_shared import reject_if_not_any_admin

router = Router(name="admin_finance_today")


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
    traffic_gb = float(metadata.get("traffic_gb") or 0)
    expiry_days = int(metadata.get("expiry_days") or 0)
    amount = _format_amount(abs(int(item.get("amount") or 0)))
    currency = str(item.get("currency") or t("finance_currency_default", lang))
    amount_label = f"{amount} {currency}"
    row_label = str(row_number)
    traffic_label = str(traffic_gb).rstrip("0").rstrip(".")
    expiry_label = str(expiry_days)
    if lang != "en":
        row_label = to_persian_digits(row_label)
        traffic_label = to_persian_digits(traffic_label)
        expiry_label = to_persian_digits(expiry_label)
    if services.access_service.is_root_admin(actor_user_id, settings):
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
        root_admin_ids = set(settings.admin_ids)
        delegate_rows = await services.db.list_delegated_admins(manager_user_id=None)
        owner_ids = sorted(
            {
                actor_user_id,
                *[
                    int(row["telegram_user_id"])
                    for row in delegate_rows
                    if int(row["telegram_user_id"]) not in root_admin_ids
                ],
            }
        )
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

    currency = str(rows[0].get("currency") or t("finance_currency_default", lang))
    total_sales_raw = sum(abs(int(r.get("amount") or 0)) for r in rows)
    total_line = t(
        "finance_today_sales_total_line",
        lang,
        total=_format_amount(total_sales_raw),
        currency=currency,
    )
    title_line = t("finance_today_sales_title", lang)
    header_block = f"{title_line}\n\n{total_line}"

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
    buffer = header_block
    for line in lines:
        candidate = f"{buffer}\n\n{line}" if buffer != header_block else f"{header_block}\n\n{line}"
        if len(candidate) > 3500 and buffer != header_block:
            await message.answer(buffer)
            buffer = f"{header_block}\n\n{line}"
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
        root_admin_ids = set(settings.admin_ids)
        delegate_rows = await services.db.list_delegated_admins(manager_user_id=None)
        owner_ids = sorted(
            {
                actor_user_id,
                *[
                    int(row["telegram_user_id"])
                    for row in delegate_rows
                    if int(row["telegram_user_id"]) not in root_admin_ids
                ],
            }
        )
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

