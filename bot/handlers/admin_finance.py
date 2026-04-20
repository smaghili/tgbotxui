from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import finance_primary_delegated_keyboard, finance_root_delegated_keyboard, main_keyboard
from bot.services.container import ServiceContainer
from bot.states import FinanceStates

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
            [InlineKeyboardButton(text=t("finance_delegates_list", lang), callback_data="fin:delegates:mine")],
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


async def _is_primary_delegated_admin(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
) -> bool:
    context = await services.access_service.get_admin_context(user_id, settings)
    if not context.is_delegated_admin or context.delegated_scope != "full":
        return False
    delegated = await services.db.get_delegated_admin_by_user_id(user_id)
    if delegated is None:
        return False
    parent_user_id = int(delegated.get("parent_user_id") or 0)
    return parent_user_id in set(settings.admin_ids)


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
        currency=str(wallet["currency"] or "تومان"),
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
            consumed_gb=int(summary["consumed_gb"] or 0),
            debt_amount=_format_amount(int(summary["debt_amount"] or 0)),
            currency=str(wallet["currency"] or "تومان"),
        )
    if context.delegated_scope == "full":
        text = t(
            "finance_credit_report_text",
            lang,
            title=_display_title(await services.db.get_user_by_telegram_id(report_user_id), report_user_id),
            balance=_format_amount(int(wallet["balance"] or 0)),
            currency=str(wallet["currency"] or "تومان"),
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
            currency=str(wallet["currency"] or "تومان"),
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
            currency=str(pricing["currency"] or "تومان"),
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
    if services.access_service.is_root_admin(message.from_user.id, settings):
        await message.answer(
            t("finance_root_delegate_menu", lang),
            reply_markup=finance_root_delegated_keyboard(lang),
        )
        return
    if await _is_primary_delegated_admin(user_id=message.from_user.id, settings=settings, services=services):
        await message.answer(
            t("finance_delegated_title", lang),
            reply_markup=finance_primary_delegated_keyboard(lang),
        )
        return
    await message.answer(t("finance_delegated_title", lang))


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
        currency=str(report["currency"] or "تومان"),
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
            currency=str(result["currency"] or "تومان"),
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
            finance_pricing_currency=str(current_pricing.get("currency") or "تومان"),
        )
        await state.set_state(FinanceStates.waiting_pricing_history_choice)
        await message.answer(
            t(
                "finance_pricing_history_confirm",
                lang,
                old_price_gb=_format_amount(old_price_gb),
                new_price_gb=_format_amount(price_gb),
                currency=str(current_pricing.get("currency") or "تومان"),
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
