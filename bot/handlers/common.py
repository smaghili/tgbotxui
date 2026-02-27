from __future__ import annotations

import logging
from html import escape
from io import BytesIO

import qrcode
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import main_keyboard
from bot.services.container import ServiceContainer

router = Router(name="common")
logger = logging.getLogger(__name__)


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


async def _user_lang(services: ServiceContainer, user_id: int) -> str:
    return await services.db.get_user_language(user_id)


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇮🇷 Persian", callback_data="lang:set:fa"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:set:en"),
            ]
        ]
    )


def _status_service_keyboard(service_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_rotate_link", lang), callback_data=f"status_rotate_uuid:{service_id}"),
                InlineKeyboardButton(text=t("btn_get_config", lang), callback_data=f"status_get_config:{service_id}"),
            ]
        ]
    )


async def _send_service_status(
    message: Message,
    *,
    settings: Settings,
    services: ServiceContainer,
    force_refresh: bool = True,
    target_user_id: int | None = None,
) -> None:
    user_id = target_user_id if target_user_id is not None else message.from_user.id
    lang = await _user_lang(services, user_id)
    try:
        status_messages = await services.usage_service.get_user_status_messages(user_id, force_refresh=force_refresh)
        service_rows = await services.db.get_user_services(user_id)
    except Exception as exc:
        logger.exception("failed to fetch status", extra={"telegram_user_id": user_id})
        await services.db.add_audit_log(
            actor_user_id=user_id,
            action="view_status",
            target_type="user_service",
            success=False,
            details=str(exc)[:500],
        )
        await message.answer(
            t("status_fetch_error", lang),
            reply_markup=main_keyboard(_is_admin(user_id, settings), lang),
        )
        return

    if not status_messages:
        await services.db.add_audit_log(
            actor_user_id=user_id,
            action="view_status",
            target_type="user_service",
            success=True,
            details="empty",
        )
        await message.answer(
            t("status_empty", lang),
            reply_markup=main_keyboard(_is_admin(user_id, settings), lang),
        )
        return

    await services.db.add_audit_log(
        actor_user_id=user_id,
        action="view_status",
        target_type="user_service",
        success=True,
    )
    for idx, card in enumerate(status_messages):
        await message.answer(
            card,
            reply_markup=_status_service_keyboard(int(service_rows[idx]["id"]), lang) if idx < len(service_rows) else None,
        )


@router.message(CommandStart())
async def handle_start(message: Message, settings: Settings, services: ServiceContainer) -> None:
    user = message.from_user
    await services.db.upsert_user(
        telegram_user_id=user.id,
        full_name=user.full_name,
        username=user.username,
        is_admin=_is_admin(user.id, settings),
    )
    lang = await _user_lang(services, user.id)
    await message.answer(
        t("welcome", lang),
        reply_markup=main_keyboard(_is_admin(user.id, settings), lang),
    )


@router.message(Command("help"))
async def handle_help(message: Message, settings: Settings, services: ServiceContainer) -> None:
    lang = await _user_lang(services, message.from_user.id)
    lines = ["/start", "/status", "/help", "/cancel"]
    if _is_admin(message.from_user.id, settings):
        lines.extend(
            [
                "",
                "/sync_all",
                t("help_manage_hint", lang),
                "/bind <panel_id> <telegram_user_id> <client_email> [service_name]",
                t("help_bind_default", lang),
            ]
        )
    await message.answer(
        "\n".join(lines),
        reply_markup=main_keyboard(_is_admin(message.from_user.id, settings), lang),
    )


@router.message(Command("status"))
@router.message(F.text.in_(button_variants("btn_status")))
async def handle_status(message: Message, settings: Settings, services: ServiceContainer) -> None:
    await _send_service_status(
        message,
        settings=settings,
        services=services,
        force_refresh=True,
        target_user_id=message.from_user.id,
    )


@router.message(F.text.in_(button_variants("btn_change_language")))
async def open_language_menu(message: Message, services: ServiceContainer) -> None:
    lang = await _user_lang(services, message.from_user.id)
    await message.answer(t("language_title", lang), reply_markup=_language_keyboard())


@router.callback_query(F.data.startswith("lang:set:"))
async def set_language(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if callback.data is None:
        await callback.answer()
        return
    lang = callback.data.split(":", 2)[2]
    if lang not in {"fa", "en"}:
        await callback.answer("Invalid language", show_alert=True)
        return
    await services.db.set_user_language(callback.from_user.id, lang)
    text_key = "language_changed_fa" if lang == "fa" else "language_changed_en"
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(text_key, lang),
            reply_markup=main_keyboard(_is_admin(callback.from_user.id, settings), lang),
        )


@router.callback_query(F.data.startswith("status_rotate_uuid:"))
async def rotate_uuid_from_status(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    lang = await _user_lang(services, callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        service_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("status_invalid_id", lang), show_alert=True)
        return
    row = await services.db.get_user_service_by_id(service_id)
    if row is None:
        await callback.answer(t("status_not_found", lang), show_alert=True)
        return
    if int(row["telegram_user_id"]) != callback.from_user.id:
        await callback.answer(t("status_no_access", lang), show_alert=True)
        return
    await callback.answer(t("status_rotating", lang))
    try:
        await services.panel_service.rotate_client_uuid_by_email(
            panel_id=int(row["panel_id"]),
            inbound_id=row.get("inbound_id"),
            client_email=str(row["client_email"]),
        )
        await services.panel_service.bind_service_to_user(
            panel_id=int(row["panel_id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            client_email=str(row["client_email"]),
            service_name=row.get("service_name"),
            inbound_id=row.get("inbound_id"),
        )
    except Exception as exc:
        await callback.answer(f"{t('error_prefix', lang)}: {exc}", show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(t("status_rotated", lang))


@router.callback_query(F.data.startswith("status_get_config:"))
async def get_config_from_status(callback: CallbackQuery, services: ServiceContainer) -> None:
    lang = await _user_lang(services, callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        service_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("status_invalid_id", lang), show_alert=True)
        return
    row = await services.db.get_user_service_by_id(service_id)
    if row is None:
        await callback.answer(t("status_not_found", lang), show_alert=True)
        return
    if int(row["telegram_user_id"]) != callback.from_user.id:
        await callback.answer(t("status_no_access", lang), show_alert=True)
        return
    await callback.answer(t("status_prepare_config", lang))
    try:
        uri = await services.panel_service.get_client_vless_uri_by_email(
            panel_id=int(row["panel_id"]),
            inbound_id=row.get("inbound_id"),
            client_email=str(row["client_email"]),
        )
    except Exception as exc:
        await callback.answer(f"{t('error_prefix', lang)}: {exc}", show_alert=True)
        return

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0B5ED7", back_color="#F7F7E8")
    buf = BytesIO()
    img.save(buf, format="PNG")
    file = BufferedInputFile(buf.getvalue(), filename="config_qr.png")

    if callback.message is not None:
        caption = t("config_caption", lang, uri=escape(uri))
        await callback.message.answer_photo(file, caption=caption, parse_mode="HTML")

