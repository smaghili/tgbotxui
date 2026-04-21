from __future__ import annotations

import asyncio
import logging
import time
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import main_keyboard
from bot.services.container import ServiceContainer

from .admin_shared import (
    callback_error_alert,
    format_client_detail,
    inline_button,
    two_button_inline_keyboard,
    yes_no_inline_keyboard,
)
from .config_bundle import send_existing_config_bundle_for_email, send_rotation_preview_bundle_for_email

router = Router(name="common")
logger = logging.getLogger(__name__)
STATUS_AUTOBIND_COOLDOWN_SECONDS = 15


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


def _status_autobind_cache_key(user_id: int) -> str:
    return f"status_autobind_last:{user_id}"


async def _user_lang(services: ServiceContainer, user_id: int) -> str:
    return await services.db.get_user_language(user_id)


async def _is_any_admin(user_id: int, settings: Settings, services: ServiceContainer) -> bool:
    return await services.access_service.is_any_admin(user_id, settings)


async def _main_menu_markup(
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str,
):
    return main_keyboard(await _is_any_admin(user_id, settings, services), lang)


async def _answer_with_main_menu(
    message: Message,
    text: str,
    *,
    user_id: int,
    settings: Settings,
    services: ServiceContainer,
    lang: str,
) -> None:
    await message.answer(
        text,
        reply_markup=await _main_menu_markup(
            user_id=user_id,
            settings=settings,
            services=services,
            lang=lang,
        ),
    )


def _language_keyboard() -> InlineKeyboardMarkup:
    return two_button_inline_keyboard(
        "🇮🇷 Persian",
        "lang:set:fa",
        "🇬🇧 English",
        "lang:set:en",
    )


def _status_service_keyboard(service_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button(t("btn_rotate_link", lang), f"status_rotate_uuid:{service_id}"),
                inline_button(t("btn_get_config", lang), f"status_get_config:{service_id}"),
            ]
        ]
    )


def _status_rotate_confirm_keyboard(service_id: int, lang: str) -> InlineKeyboardMarkup:
    return yes_no_inline_keyboard(f"status_rotate_yes:{service_id}", f"status_rotate_no:{service_id}", lang)


def _status_services_choice_keyboard(service_rows: list[dict], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in service_rows:
        service_id = int(row["id"])
        title = str(row.get("service_name") or row.get("client_email") or service_id).strip() or str(service_id)
        rows.append([inline_button(title[:48], f"status_show:{service_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_status_for_service_row(
    message: Message,
    *,
    row: dict,
    settings: Settings,
    services: ServiceContainer,
    lang: str,
) -> None:
    card = None
    try:
        detail = await services.panel_service.get_client_detail(
            int(row["panel_id"]),
            int(row["inbound_id"] or 0),
            str(row["client_id"] or ""),
        )
        card = format_client_detail(detail, settings.timezone, lang)
    except Exception:
        pass

    if card is None:
        try:
            status_messages = await services.usage_service.get_user_status_messages(int(row["telegram_user_id"]), force_refresh=False)
            service_rows = await services.db.get_user_services(int(row["telegram_user_id"]))
            for idx, service_row in enumerate(service_rows):
                if int(service_row["id"]) == int(row["id"]) and idx < len(status_messages):
                    card = status_messages[idx]
                    break
        except Exception:
            logger.exception("failed to fallback to cached service status", extra={"service_id": row.get("id")})

    if card is None:
        raise ValueError(t("status_not_found", lang))

    await message.answer(card, reply_markup=_status_service_keyboard(int(row["id"]), lang))


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
    if message.from_user is not None and message.from_user.id == user_id:
        # Keep user identity fresh and try auto-bind on demand, so users do not need /start again.
        await services.db.upsert_user(
            telegram_user_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            is_admin=_is_admin(message.from_user.id, settings),
        )
        existing_services = await services.db.get_user_services(user_id)
        should_autobind = not existing_services
        if not should_autobind:
            last_run_raw = await services.db.get_app_setting(_status_autobind_cache_key(user_id), "0")
            try:
                last_run_ts = int(last_run_raw or "0")
            except ValueError:
                last_run_ts = 0
            should_autobind = int(time.time()) - last_run_ts >= STATUS_AUTOBIND_COOLDOWN_SECONDS
        if should_autobind:
            try:
                await services.panel_service.bind_services_for_telegram_identity(
                    telegram_user_id=user_id,
                    username=message.from_user.username,
                )
            except Exception:
                logger.exception("auto-bind by telegram identity failed", extra={"telegram_user_id": user_id})
            else:
                await services.db.set_app_setting(_status_autobind_cache_key(user_id), str(int(time.time())))
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
        await _answer_with_main_menu(
            message,
            t("status_fetch_error", lang),
            user_id=user_id,
            settings=settings,
            services=services,
            lang=lang,
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
        await _answer_with_main_menu(
            message,
            t("status_empty", lang),
            user_id=user_id,
            settings=settings,
            services=services,
            lang=lang,
        )
        return

    await services.db.add_audit_log(
        actor_user_id=user_id,
        action="view_status",
        target_type="user_service",
        success=True,
    )
    if len(service_rows) > 1:
        await message.answer(
            t("status_choose_service", lang),
            reply_markup=_status_services_choice_keyboard(service_rows, lang),
        )
        return
    await _render_status_for_service_row(
        message,
        row=service_rows[0],
        settings=settings,
        services=services,
        lang=lang,
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
    await services.panel_service.bind_services_for_telegram_identity(
        telegram_user_id=user.id,
        username=user.username,
    )
    lang = await _user_lang(services, user.id)
    await _answer_with_main_menu(
        message,
        t("welcome", lang),
        user_id=user.id,
        settings=settings,
        services=services,
        lang=lang,
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
    await _answer_with_main_menu(
        message,
        "\n".join(lines),
        user_id=message.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
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
            reply_markup=await _main_menu_markup(
                user_id=callback.from_user.id,
                settings=settings,
                services=services,
                lang=lang,
            ),
        )


@router.callback_query(F.data.startswith("status_rotate_uuid:"))
async def rotate_uuid_from_status(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    lang = await _user_lang(services, callback.from_user.id)
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    try:
        service_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("status_invalid_id", lang), show_alert=True)
        return
    await callback.message.answer(
        t("status_rotate_confirm", lang),
        reply_markup=_status_rotate_confirm_keyboard(service_id, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("status_show:"))
async def show_status_service(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    lang = await _user_lang(services, callback.from_user.id)
    if callback.data is None or callback.message is None:
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
    try:
        await _render_status_for_service_row(
            callback.message,
            row=row,
            settings=settings,
            services=services,
            lang=lang,
        )
    except Exception as exc:
        await callback_error_alert(callback, exc, lang)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("status_rotate_no:"))
async def rotate_uuid_cancel(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("status_rotate_yes:"))
async def rotate_uuid_confirm(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
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
        if callback.message is not None:
            fresh = await services.db.get_user_service_by_id(service_id) or row
            await callback.message.answer(
                f"{t('status_rotate_done_bundle', lang)}\n{settings.config_rotate_apply_delay_seconds} {t('unit_second', lang)}"
            )
            prepared = await send_rotation_preview_bundle_for_email(
                callback.message,
                services=services,
                settings=settings,
                panel_id=int(row["panel_id"]),
                inbound_id=row.get("inbound_id"),
                client_email=str(row["client_email"]),
                config_name=str(fresh.get("service_name") or fresh.get("client_email") or row["client_email"]),
                total_bytes=int(fresh.get("total_bytes", -1)),
                expiry=fresh.get("expire_at"),
                lang=lang,
            )
        else:
            prepared = await services.panel_service.prepare_client_rotation_by_email(
                panel_id=int(row["panel_id"]),
                inbound_id=row.get("inbound_id"),
                client_email=str(row["client_email"]),
            )
        await asyncio.sleep(max(0, int(settings.config_rotate_apply_delay_seconds)))
        await services.panel_service.apply_prepared_client_rotation(
            panel_id=int(prepared["panel_id"]),
            inbound_id=int(prepared["inbound_id"]),
            old_uuid=str(prepared["old_uuid"]),
            new_uuid=str(prepared["new_uuid"]),
            new_sub_id=str(prepared["new_sub_id"]),
        )
        await services.panel_service.bind_service_to_user(
            panel_id=int(row["panel_id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            client_email=str(row["client_email"]),
            service_name=row.get("service_name"),
            inbound_id=row.get("inbound_id"),
        )
    except Exception as exc:
        await callback_error_alert(callback, exc, lang)
        return
    if callback.message is not None:
        await callback.message.answer(t("status_rotated", lang))


@router.callback_query(F.data.startswith("status_get_config:"))
async def get_config_from_status(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
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
        if callback.message is not None:
            await send_existing_config_bundle_for_email(
                callback.message,
                services=services,
                settings=settings,
                panel_id=int(row["panel_id"]),
                inbound_id=row.get("inbound_id"),
                client_email=str(row["client_email"]),
                config_name=str(row.get("service_name") or row.get("client_email")),
                total_bytes=int(row.get("total_bytes", -1)),
                expiry=row.get("expire_at"),
                lang=lang,
            )
    except Exception as exc:
        await callback_error_alert(callback, exc, lang)
        return
