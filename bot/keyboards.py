from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.i18n import btn, get_current_lang


def main_keyboard(is_admin: bool, lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    rows = [[KeyboardButton(text=btn("btn_status", lang))]]
    if is_admin:
        rows.append(
            [
                KeyboardButton(text=btn("btn_manage", lang)),
                KeyboardButton(text=btn("btn_change_language", lang)),
            ]
        )
    else:
        rows.append([KeyboardButton(text=btn("btn_change_language", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def admin_keyboard(lang: str | None = None) -> ReplyKeyboardMarkup:
    lang = lang or get_current_lang()
    rows = [
        [KeyboardButton(text=btn("btn_add_panel", lang)), KeyboardButton(text=btn("btn_list_panels", lang))],
        [KeyboardButton(text=btn("btn_list_inbounds", lang)), KeyboardButton(text=btn("btn_list_users", lang))],
        [KeyboardButton(text=btn("btn_online_users", lang))],
        [KeyboardButton(text=btn("btn_search_user", lang)), KeyboardButton(text=btn("btn_disabled_users", lang))],
        [KeyboardButton(text=btn("btn_last_online_users", lang))],
        [KeyboardButton(text=btn("btn_back", lang))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)
