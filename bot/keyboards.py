from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.i18n import btn, get_current_lang


def main_keyboard(is_admin: bool, lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    rows = [[KeyboardButton(text=btn("btn_status", lang))]]
    if is_admin:
        rows.append(
            [
                KeyboardButton(text=btn("btn_manage_finance", lang)),
                KeyboardButton(text=btn("btn_manage", lang)),
            ]
        )
        rows.append(
            [KeyboardButton(text=btn("btn_change_language", lang))]
        )
    else:
        rows.append([KeyboardButton(text=btn("btn_change_language", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=False)


def admin_keyboard(mode: str = "full", lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    if mode == "limited":
        rows = [
            [KeyboardButton(text=btn("btn_inbounds_overview", lang)), KeyboardButton(text=btn("btn_list_users", lang))],
            [KeyboardButton(text=btn("btn_disabled_users", lang)), KeyboardButton(text=btn("btn_online_users", lang))],
            [KeyboardButton(text=btn("btn_low_traffic_users", lang)), KeyboardButton(text=btn("btn_create_user", lang))],
            [KeyboardButton(text=btn("btn_edit_config", lang)), KeyboardButton(text=btn("btn_bulk_operations", lang))],
            [KeyboardButton(text=btn("btn_back", lang))],
        ]
    else:
        rows = [
            [KeyboardButton(text=btn("btn_add_panel", lang)), KeyboardButton(text=btn("btn_list_panels", lang))],
            [KeyboardButton(text=btn("btn_inbounds_overview", lang)), KeyboardButton(text=btn("btn_list_users", lang))],
            [KeyboardButton(text=btn("btn_disabled_users", lang)), KeyboardButton(text=btn("btn_online_users", lang))],
            [KeyboardButton(text=btn("btn_low_traffic_users", lang)), KeyboardButton(text=btn("btn_create_user", lang))],
            [KeyboardButton(text=btn("btn_edit_config", lang)), KeyboardButton(text=btn("btn_bulk_operations", lang))],
            [KeyboardButton(text=btn("btn_cleanup_settings", lang)), KeyboardButton(text=btn("btn_manage_admins", lang))],
            [KeyboardButton(text=btn("btn_back", lang))],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=False)


def cancel_only_keyboard(lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn("btn_cancel_operation", lang))]],
        resize_keyboard=True,
        is_persistent=False,
    )


def finance_primary_delegated_keyboard(lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=btn("finance_view_credit", lang))],
            [
                KeyboardButton(text=btn("finance_delegates_list", lang)),
                KeyboardButton(text=btn("finance_today_sales", lang)),
            ],
            [KeyboardButton(text=btn("finance_today_reports", lang))],
            [KeyboardButton(text=btn("btn_back", lang))],
        ],
        resize_keyboard=True,
        is_persistent=False,
    )


def finance_limited_delegated_keyboard(lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=btn("finance_today_sales", lang)),
                KeyboardButton(text=btn("finance_today_reports", lang)),
            ],
            [KeyboardButton(text=btn("btn_back", lang))],
        ],
        resize_keyboard=True,
        is_persistent=False,
    )


def finance_root_delegated_keyboard(lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=btn("finance_delegates_list", lang)),
                KeyboardButton(text=btn("finance_today_sales", lang)),
            ],
            [KeyboardButton(text=btn("finance_today_reports", lang))],
            [KeyboardButton(text=btn("btn_back", lang))],
        ],
        resize_keyboard=True,
        is_persistent=False,
    )
