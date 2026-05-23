"""Admin finance: menus and composed routers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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

from bot.handlers.admin_finance_helpers import _format_amount, wallet_currency_label
from bot.handlers.admin_finance_pricing import router as pricing_router
from bot.handlers.admin_finance_today import router as today_router
from bot.handlers.admin_finance_wallet import router as wallet_router

from .admin_finance_keyboards import (
    _finance_delegated_keyboard,
    _finance_delegates_keyboard,
    _finance_root_keyboard,
    _wallet_action_keyboard,
)
from .admin_finance_ops import (
    _answer_sales_report,
    _finance_menu_text_and_keyboard,
    _is_primary_delegated_admin,
    _main_menu_markup,
)
from .admin_shared import answer_with_cancel, reject_callback_if_not_any_admin, reject_if_not_any_admin

router = Router(name="admin_finance")
router.include_router(today_router)
router.include_router(wallet_router)
router.include_router(pricing_router)


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


@router.callback_query(F.data == "fin:delegated:back")
async def finance_delegated_back(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    text, reply_markup = await _finance_menu_text_and_keyboard(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )
    if callback.message is not None:
        await callback.message.answer(text, reply_markup=reply_markup)
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
        currency=wallet_currency_label(report.get("currency"), lang=lang),
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


