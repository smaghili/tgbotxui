"""Finance inline keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.i18n import t



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


def _wallet_action_keyboard(
    target_user_id: int, lang: str | None = None, *, show_reset: bool = False
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text=t("btn_wallet_show", lang), callback_data=f"fin:wallet:show:{target_user_id}"),
            InlineKeyboardButton(text=t("btn_wallet_set", lang), callback_data=f"fin:wallet:set:{target_user_id}"),
        ],
        [
            InlineKeyboardButton(text=t("btn_wallet_add", lang), callback_data=f"fin:wallet:add:{target_user_id}"),
            InlineKeyboardButton(text=t("btn_wallet_subtract", lang), callback_data=f"fin:wallet:sub:{target_user_id}"),
        ],
    ]
    if show_reset:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("finance_wallet_reset_btn", lang),
                    callback_data=f"fin:wallet:rst:{target_user_id}",
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pricing_history_choice_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="fin:pricing:history:apply"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="fin:pricing:history:keep"),
            ]
        ]
    )
