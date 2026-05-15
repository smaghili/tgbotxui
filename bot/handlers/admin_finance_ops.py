"""Shared finance helpers: access checks, menus, sales/pricing responses."""
from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.keyboards import (
    finance_limited_delegated_keyboard,
    finance_primary_delegated_keyboard,
    finance_root_delegated_keyboard,
    main_keyboard,
)
from bot.services.container import ServiceContainer

from bot.handlers.admin_finance_helpers import (
    _format_amount,
    _format_gb_exact,
    payable_from_wallet,
    wallet_currency_label,
)


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


async def _can_manage_finance_target(
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
        currency=wallet_currency_label(wallet.get("currency"), lang=lang),
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
        payable_amount = payable_from_wallet(int(wallet["balance"] or 0))
        extra_lines = t(
            "finance_credit_consumed_lines",
            lang,
            consumed_gb=_format_gb_exact(summary["consumed_gb"] or 0),
            debt_amount=_format_amount(int(summary["debt_amount"] or 0)),
            payable_amount=_format_amount(payable_amount),
            remaining_gb=_format_gb_exact(summary["remaining_gb"] or 0),
            remaining_amount=_format_amount(int(summary["remaining_amount"] or 0)),
            currency=wallet_currency_label(wallet.get("currency"), lang=lang),
        )
    if context.delegated_scope == "full":
        text = t(
            "finance_credit_report_text",
            lang,
            title=_display_title(await services.db.get_user_by_telegram_id(report_user_id), report_user_id),
            balance=_format_amount(int(wallet["balance"] or 0)),
            currency=wallet_currency_label(wallet.get("currency"), lang=lang),
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
            currency=wallet_currency_label(wallet.get("currency"), lang=lang),
            clients=int(summary["clients_count"] or 0),
            allocated_gb=int(summary["allocated_gb"] or 0),
            sale_amount=_format_amount(int(summary["sale_amount"] or 0)),
            extra_lines=extra_lines,
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
    allocated_tiers_json: str | None,
    apply_to_past_reports: bool | None,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
) -> None:
    current = await services.financial_service.get_pricing(target_user_id)
    consumed_snap: int | None = None
    if apply_to_past_reports is False and str(current.get("charge_basis") or "allocated") == "consumed":
        summary = await services.admin_provisioning_service.get_admin_scope_financial_summary(
            actor_user_id=target_user_id,
            settings=settings,
        )
        consumed_snap = int(summary.get("consumed_bytes") or 0)
    pricing = await services.financial_service.set_pricing(
        actor_user_id=actor_user_id,
        telegram_user_id=target_user_id,
        price_per_gb=price_gb,
        price_per_day=price_day,
        charge_basis=str(current.get("charge_basis") or "allocated"),
        allocated_pricing_tiers_json=(
            allocated_tiers_json
            if allocated_tiers_json is not None
            else str(current.get("allocated_pricing_tiers_json") or "[]")
        ),
        apply_price_to_past_reports=apply_to_past_reports,
        consumed_bytes_snapshot=consumed_snap,
    )
    await message.answer(
        t(
            "finance_pricing_saved",
            lang,
            price_gb=_format_amount(int(pricing["price_per_gb"] or 0)),
            price_day=_format_amount(int(pricing["price_per_day"] or 0)),
            currency=wallet_currency_label(pricing.get("currency"), lang=lang),
        ),
        reply_markup=await _main_menu_markup(
            user_id=actor_user_id,
            settings=settings,
            services=services,
            lang=lang,
        ),
    )

