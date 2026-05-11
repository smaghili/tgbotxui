"""Wallet adjustment handlers (authorized targets only)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.states import FinanceStates

from bot.handlers.admin_finance_helpers import _format_amount, wallet_currency_label

from .admin_finance_keyboards import _wallet_action_keyboard
from .admin_finance_ops import (
    _can_manage_finance_target,
    _main_menu_markup,
    _wallet_target_summary_text,
)
from .admin_shared import (
    answer_with_cancel,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
)

router = Router(name="admin_finance_wallet")


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
        reply_markup=_wallet_action_keyboard(
            target_user_id,
            lang,
            show_reset=services.access_service.is_root_admin(message.from_user.id, settings),
        ),
    )
    await state.clear()


@router.callback_query(F.data.startswith("fin:wallet:rsa:"))
async def finance_wallet_reset_apply(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    try:
        target_user_id = int(callback.data.rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_finance_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await services.financial_service.clear_wallet_ledger_for_user(telegram_user_id=target_user_id)
    summary = await _wallet_target_summary_text(target_user_id=target_user_id, services=services, lang=lang)
    await callback.message.answer(
        f"{t('finance_wallet_reset_done', lang)}\n\n{summary}\n\n{t('finance_choose_wallet_action', lang)}",
        reply_markup=_wallet_action_keyboard(target_user_id, lang, show_reset=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fin:wallet:rno:"))
async def finance_wallet_reset_cancel(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_finance_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    summary = await _wallet_target_summary_text(target_user_id=target_user_id, services=services, lang=lang)
    await callback.message.answer(
        f"{summary}\n\n{t('finance_choose_wallet_action', lang)}",
        reply_markup=_wallet_action_keyboard(
            target_user_id,
            lang,
            show_reset=services.access_service.is_root_admin(callback.from_user.id, settings),
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fin:wallet:rst:"))
async def finance_wallet_reset_prompt(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if not services.access_service.is_root_admin(callback.from_user.id, settings):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    try:
        target_user_id = int(callback.data.rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await _can_manage_finance_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    await callback.message.answer(
        t("finance_wallet_reset_confirm", lang),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=t("btn_yes", lang), callback_data=f"fin:wallet:rsa:{target_user_id}"),
                    InlineKeyboardButton(text=t("btn_no", lang), callback_data=f"fin:wallet:rno:{target_user_id}"),
                ],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fin:wallet:"))
async def finance_wallet_action(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
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
    if not await _can_manage_finance_target(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await callback.answer(t("no_admin_access", None), show_alert=True)
        return
    if action == "show":
        summary = await _wallet_target_summary_text(target_user_id=target_user_id, services=services, lang=lang)
        await callback.message.answer(
            f"{summary}\n\n{t('finance_choose_wallet_action', lang)}",
            reply_markup=_wallet_action_keyboard(
                target_user_id,
                lang,
                show_reset=services.access_service.is_root_admin(callback.from_user.id, settings),
            ),
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
    if not await _can_manage_finance_target(
        actor_user_id=message.from_user.id,
        target_user_id=target_user_id,
        settings=settings,
        services=services,
    ):
        await message.answer(t("no_admin_access", None))
        return
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
            currency=wallet_currency_label(result.get("currency"), lang=lang),
        ),
        reply_markup=await _main_menu_markup(
            user_id=message.from_user.id,
            settings=settings,
            services=services,
            lang=lang,
        ),
    )

