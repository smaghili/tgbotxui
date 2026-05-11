"""Pricing FSM handlers (root)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.states import FinanceStates
from bot.utils import parse_price_per_gb_with_tiers

from bot.handlers.admin_finance_helpers import _format_amount, wallet_currency_label

from .admin_finance_keyboards import _pricing_history_choice_keyboard
from .admin_finance_ops import _save_pricing_and_answer
from .admin_shared import answer_with_cancel, reject_callback_if_not_any_admin, reject_if_not_any_admin

router = Router(name="admin_finance_pricing")


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
        price_gb, allocated_tiers_json = parse_price_per_gb_with_tiers((message.text or "").strip())
        if price_gb < 0:
            raise ValueError
    except ValueError:
        await answer_with_cancel(message, t("finance_invalid_amount", lang), lang=lang)
        return
    await state.update_data(finance_price_per_gb=price_gb)
    await state.update_data(finance_allocated_tiers_json=allocated_tiers_json)
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
    allocated_tiers_json = data.get("finance_allocated_tiers_json")
    current_pricing = await services.financial_service.get_pricing(target_user_id)
    old_price_gb = int(current_pricing.get("price_per_gb") or 0)
    if old_price_gb != price_gb:
        await state.update_data(
            finance_price_per_day=price_day,
            finance_old_price_per_gb=old_price_gb,
            finance_pricing_currency=wallet_currency_label(current_pricing.get("currency"), lang=lang),
            finance_allocated_tiers_json=allocated_tiers_json,
        )
        await state.set_state(FinanceStates.waiting_pricing_history_choice)
        await message.answer(
            t(
                "finance_pricing_history_confirm",
                lang,
                old_price_gb=_format_amount(old_price_gb),
                new_price_gb=_format_amount(price_gb),
                currency=wallet_currency_label(current_pricing.get("currency"), lang=lang),
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
        allocated_tiers_json=allocated_tiers_json if isinstance(allocated_tiers_json, str) else None,
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
        allocated_tiers_json=(
            str(data.get("finance_allocated_tiers_json"))
            if data.get("finance_allocated_tiers_json") is not None
            else None
        ),
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
        allocated_tiers_json=(
            str(data.get("finance_allocated_tiers_json"))
            if data.get("finance_allocated_tiers_json") is not None
            else None
        ),
        apply_to_past_reports=False,
        settings=settings,
        services=services,
        lang=lang,
    )
    await callback.answer()
