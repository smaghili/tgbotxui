from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.handlers.admin_outbound_panel import send_panel_outbounds_overview
from bot.handlers.admin_shared import (
    admin_keyboard_for_user,
    inline_button,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
)
from bot.i18n import button_variants, t
from bot.pagination import chunk_buttons
from bot.services.admin_provisioning_service import InboundAccess
from bot.services.container import ServiceContainer
from bot.services.xui_client import XUIError
from bot.states import InboundLocationStates

router = Router(name="admin_inbound_location")


def _group_rows_by_panel(rows: list[InboundAccess]) -> dict[int, list[InboundAccess]]:
    grouped: dict[int, list[InboundAccess]] = {}
    for row in rows:
        grouped.setdefault(int(row.panel_id), []).append(row)
    return grouped


def _inbound_multi_keyboard(
    *,
    panel_id: int,
    panel_rows: list[InboundAccess],
    selected: list[int],
    lang: str | None,
) -> InlineKeyboardMarkup:
    sel_set = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    for row in sorted(panel_rows, key=lambda r: (r.inbound_name.lower(), r.inbound_id)):
        prefix = "✅ " if row.inbound_id in sel_set else ""
        label = prefix + (row.inbound_name[:50] if len(row.inbound_name) <= 50 else row.inbound_name[:47] + "...")
        rows.append(
            [
                inline_button(
                    label,
                    f"ibloc:toggle:{panel_id}:{row.inbound_id}",
                )
            ]
        )
    rows.append(
        [
            inline_button(t("admin_ibloc_confirm", lang), "ibloc:confirm"),
            inline_button(t("admin_ibloc_cancel", lang), "ibloc:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ib_manage_panel_keyboard(panels: list[dict], lang: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in panels:
        pid = int(p["id"])
        name = str(p.get("name") or f"#{pid}")
        rows.append([inline_button(name[:55], f"ibob:{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _panel_choice_keyboard(panels: list[tuple[int, str]], lang: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for panel_id, name in panels:
        rows.append([inline_button(name[:55], f"ibloc:pnl:{panel_id}")])
    rows.append([inline_button(t("admin_ibloc_cancel", lang), "ibloc:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _outbound_pick_keyboard(
    *,
    panel_id: int,
    outbound_rows: list[tuple[str, str]],
    lang: str | None,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for idx, (_tag, label) in enumerate(outbound_rows):
        text_label = label if len(label) <= 28 else label[:25] + "..."
        buttons.append(InlineKeyboardButton(text=text_label, callback_data=f"ibloc:ob:{panel_id}:{idx}"))
    rows = chunk_buttons(buttons, columns=2)
    rows.append([inline_button(t("admin_ibloc_cancel", lang), "ibloc:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_inbound_pick_ui(
    target: Message | CallbackQuery,
    *,
    services: ServiceContainer,
    settings: Settings,
    state: FSMContext,
    lang: str,
    panel_id: int,
    rows_all: list[InboundAccess],
) -> None:
    panel_rows = [r for r in rows_all if r.panel_id == panel_id]
    await state.set_state(InboundLocationStates.choosing_inbounds)
    await state.update_data(ibloc_panel_id=panel_id, ibloc_selected=[])
    text = t("admin_ibloc_pick_inbounds", lang)
    markup = _inbound_multi_keyboard(
        panel_id=panel_id,
        panel_rows=panel_rows,
        selected=[],
        lang=lang,
    )
    if isinstance(target, CallbackQuery) and target.message:
        await target.message.edit_text(text, reply_markup=markup)
    else:
        assert isinstance(target, Message)
        await target.answer(text, reply_markup=markup)


@router.message(F.text.in_(button_variants("btn_manage_inbound")))
async def inbound_manage_outbounds_entry(
    message: Message,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    panels = await services.access_service.list_accessible_panels(
        user_id=message.from_user.id,
        settings=settings,
    )
    if not panels:
        await message.answer(t("bind_no_panel", lang))
        return
    if len(panels) == 1:
        pid = int(panels[0]["id"])
        await send_panel_outbounds_overview(
            message,
            services=services,
            settings=settings,
            panel_id=pid,
            actor_user_id=message.from_user.id,
            lang=lang,
        )
        return
    await message.answer(
        t("admin_ibloc_pick_panel", lang),
        reply_markup=_ib_manage_panel_keyboard(panels, lang),
    )


@router.callback_query(F.data.startswith("ibob:"))
async def inbound_manage_outbounds_panel_pick(
    callback: CallbackQuery,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        panel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await send_panel_outbounds_overview(
        callback.message,
        services=services,
        settings=settings,
        panel_id=panel_id,
        actor_user_id=callback.from_user.id,
        lang=lang,
    )
    await callback.answer()


@router.message(F.text.in_(button_variants("btn_change_inbound_location")))
async def inbound_location_start(
    message: Message,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    rows = await services.admin_provisioning_service.list_accessible_inbounds_for_actor(
        actor_user_id=message.from_user.id,
        settings=settings,
    )
    if not rows:
        await message.answer(t("admin_ibloc_no_access", lang))
        return
    grouped = _group_rows_by_panel(rows)
    await state.clear()
    if len(grouped) > 1:
        panels = [(pid, grouped[pid][0].panel_name) for pid in sorted(grouped.keys())]
        await state.set_state(InboundLocationStates.choosing_panel)
        await message.answer(
            t("admin_ibloc_pick_panel", lang),
            reply_markup=_panel_choice_keyboard(panels, lang),
        )
        return
    panel_id = next(iter(grouped.keys()))
    await _show_inbound_pick_ui(
        message,
        services=services,
        settings=settings,
        state=state,
        lang=lang,
        panel_id=panel_id,
        rows_all=rows,
    )


@router.callback_query(F.data.startswith("ibloc:pnl:"))
async def inbound_location_panel_picked(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        parts = callback.data.split(":", 2)
        panel_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    rows = await services.admin_provisioning_service.list_accessible_inbounds_for_actor(
        actor_user_id=callback.from_user.id,
        settings=settings,
    )
    if not any(r.panel_id == panel_id for r in rows):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await _show_inbound_pick_ui(
        callback,
        services=services,
        settings=settings,
        state=state,
        lang=lang,
        panel_id=panel_id,
        rows_all=rows,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ibloc:toggle:"))
async def inbound_location_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        _, _, panel_raw, inbound_raw = callback.data.split(":", 3)
        panel_id = int(panel_raw)
        inbound_id = int(inbound_raw)
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await services.access_service.can_access_inbound(
        user_id=callback.from_user.id,
        settings=settings,
        panel_id=panel_id,
        inbound_id=inbound_id,
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    data = await state.get_data()
    if int(data.get("ibloc_panel_id") or 0) != panel_id:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    rows = await services.admin_provisioning_service.list_accessible_inbounds_for_actor(
        actor_user_id=callback.from_user.id,
        settings=settings,
    )
    panel_rows = [r for r in rows if r.panel_id == panel_id]
    sel = [int(x) for x in (data.get("ibloc_selected") or [])]
    if inbound_id in sel:
        sel = [x for x in sel if x != inbound_id]
    else:
        sel.append(inbound_id)
    await state.update_data(ibloc_selected=sel)
    await callback.message.edit_reply_markup(
        reply_markup=_inbound_multi_keyboard(
            panel_id=panel_id,
            panel_rows=panel_rows,
            selected=sel,
            lang=lang,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "ibloc:confirm")
async def inbound_location_confirm_inbounds(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    panel_id = int(data.get("ibloc_panel_id") or 0)
    sel = [int(x) for x in (data.get("ibloc_selected") or [])]
    if panel_id <= 0 or not sel:
        await callback.answer(t("admin_ibloc_none_selected", lang), show_alert=True)
        return
    try:
        rows = await services.panel_service.list_outbound_tags_labels_for_actor(
            panel_id,
            callback.from_user.id,
            settings,
            services.access_service,
        )
    except Exception as exc:
        await callback.answer(t("admin_ibloc_error", lang, error=exc), show_alert=True)
        return
    if not rows:
        await callback.answer(t("panel_outbounds_empty", lang), show_alert=True)
        return
    await state.set_state(InboundLocationStates.choosing_outbound)
    await callback.message.edit_text(
        t("admin_ibloc_pick_outbound", lang),
        reply_markup=_outbound_pick_keyboard(panel_id=panel_id, outbound_rows=rows, lang=lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ibloc:ob:"))
async def inbound_location_pick_outbound(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        parts = callback.data.split(":", 3)
        panel_id = int(parts[2])
        idx = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    data = await state.get_data()
    if int(data.get("ibloc_panel_id") or 0) != panel_id:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    sel = [int(x) for x in (data.get("ibloc_selected") or [])]
    if not sel:
        await callback.answer(t("admin_ibloc_none_selected", lang), show_alert=True)
        return
    try:
        rows = await services.panel_service.list_outbound_tags_labels_for_actor(
            panel_id,
            callback.from_user.id,
            settings,
            services.access_service,
        )
    except Exception as exc:
        await callback.answer(t("admin_ibloc_error", lang, error=exc), show_alert=True)
        return
    if idx < 0 or idx >= len(rows):
        await callback.answer(t("admin_edit_location_bad", lang), show_alert=True)
        return
    outbound_tag = rows[idx][0]
    try:
        n = await services.panel_service.set_inbounds_default_outbound_routing_for_actor(
            panel_id,
            sel,
            outbound_tag,
            callback.from_user.id,
            settings,
            services.access_service,
        )
    except (XUIError, ValueError) as exc:
        await callback.answer(t("admin_ibloc_error", lang, error=exc), show_alert=True)
        return
    except Exception as exc:
        await callback.answer(t("admin_ibloc_error", lang, error=exc), show_alert=True)
        return
    await state.clear()
    kb = await admin_keyboard_for_user(
        user_id=callback.from_user.id,
        settings=settings,
        services=services,
        lang=lang,
    )
    if n <= 0:
        await callback.message.answer(t("admin_ibloc_noop", lang), reply_markup=kb)
    else:
        await callback.message.answer(t("admin_ibloc_done", lang, tag=outbound_tag), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "ibloc:cancel")
async def inbound_location_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.clear()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        kb = await admin_keyboard_for_user(
            user_id=callback.from_user.id,
            settings=settings,
            services=services,
            lang=lang,
        )
        await callback.message.answer(t("admin_cancel", lang), reply_markup=kb)
    await callback.answer()
