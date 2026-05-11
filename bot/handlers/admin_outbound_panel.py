from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.handlers.admin_shared import (
    inline_button,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
)
from bot.i18n import t
from bot.pagination import chunk_buttons
from bot.services.container import ServiceContainer
from bot.states import OutboundGrantStates, OutboundPanelStates

router = Router(name="admin_outbound_panel")


def _chunk_text_by_lines(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    lines = text.split("\n")
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for line in lines:
        if len(line) > max_len:
            if buf:
                chunks.append("\n".join(buf))
                buf = []
                cur = 0
            for j in range(0, len(line), max_len):
                chunks.append(line[j : j + max_len])
            continue
        add = len(line) + (1 if buf else 0)
        if cur + add > max_len and buf:
            chunks.append("\n".join(buf))
            buf = [line]
            cur = len(line)
        else:
            buf.append(line)
            cur += add
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def _outbound_list_keyboard(
    *,
    panel_id: int,
    show_grant_add: bool,
    show_alias: bool,
    tag_rows: list[tuple[str, str]],
    lang: str | None,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if show_grant_add:
        rows.append(
            [
                inline_button(t("panel_ob_add_link", lang), f"panel_ob_add:{panel_id}"),
                inline_button(t("panel_ob_grant_menu", lang), f"panel_ob_grant:{panel_id}"),
            ]
        )
    alias_buttons: list[InlineKeyboardButton] = []
    if show_alias and tag_rows:
        for idx, (_tag, label) in enumerate(tag_rows):
            alias_buttons.append(
                InlineKeyboardButton(text=f"✏️{idx + 1}", callback_data=f"panel_ob_a:{panel_id}:{idx}")
            )
        rows.extend(chunk_buttons(alias_buttons, columns=6))
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _grant_delegates_keyboard(
    panel_id: int, admins: list[dict], lang: str | None
) -> InlineKeyboardMarkup:
    out_rows: list[list[InlineKeyboardButton]] = []
    for admin in admins:
        tid = int(admin["telegram_user_id"])
        title = str(admin.get("title") or admin.get("full_name") or admin.get("username") or tid)
        out_rows.append([inline_button(title[:42], f"panel_ob_gadm:{panel_id}:{tid}")])
    if not out_rows:
        out_rows.append([InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")])
    out_rows.append([inline_button(t("admin_back", lang), f"panel_ob_back:{panel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=out_rows)


def _grant_outbound_row_label(tag: str, display_label: str) -> str:
    lab = display_label.strip() or tag
    return lab if len(lab) <= 40 else lab[:37] + "..."


def _grant_outbounds_pick_keyboard(
    *,
    panel_id: int,
    delegate_tid: int,
    tags: list[str],
    labels: list[str],
    selected: set[str],
    lang: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, (tag, lab) in enumerate(zip(tags, labels)):
        mark = "✅ " if tag in selected else ""
        text = mark + _grant_outbound_row_label(tag, lab)
        if len(text) > 64:
            text = text[:61] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"panel_ob_gt:{panel_id}:{delegate_tid}:{idx}",
                )
            ]
        )
    rows.append(
        [
            inline_button(t("admin_ibloc_confirm", lang), f"panel_ob_gcf:{panel_id}:{delegate_tid}"),
            inline_button(t("admin_back", lang), f"panel_ob_gbk:{panel_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_panel_outbounds_overview(
    message: Message,
    *,
    services: ServiceContainer,
    settings: Settings,
    panel_id: int,
    actor_user_id: int,
    lang: str,
) -> None:
    panel = await services.panel_service.get_panel(panel_id)
    if not panel:
        await message.answer(t("admin_panel_not_found", lang))
        return
    try:
        rows = await services.panel_service.list_outbound_tags_labels_for_actor(
            panel_id, actor_user_id, settings, services.access_service
        )
    except Exception as exc:
        await message.answer(t("panel_outbounds_fetch_error", lang, error=exc))
        return
    can_grant_add = await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, actor_user_id, settings, services.access_service
    )
    show_alias = bool(rows)
    if not rows:
        text = (
            t("panel_outbounds_header", lang, name=panel["name"], count=0)
            + "\n"
            + t("panel_outbounds_empty", lang)
        )
        kb = _outbound_list_keyboard(
            panel_id=panel_id,
            show_grant_add=can_grant_add,
            show_alias=False,
            tag_rows=[],
            lang=lang,
        )
        await message.answer(text, reply_markup=kb)
        return
    body_lines = [f"{i}. {label} — {tag}" for i, (tag, label) in enumerate(rows, start=1)]
    text = t("panel_outbounds_header", lang, name=panel["name"], count=len(rows)) + "\n".join(body_lines)
    kb = _outbound_list_keyboard(
        panel_id=panel_id,
        show_grant_add=can_grant_add,
        show_alias=show_alias,
        tag_rows=rows,
        lang=lang,
    )
    parts = _chunk_text_by_lines(text)
    for i, part in enumerate(parts):
        await message.answer(part, reply_markup=kb if i == 0 else None)


@router.callback_query(F.data.startswith("panel_ob_back:"))
async def panel_ob_back(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
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
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await callback.message.delete()
    await send_panel_outbounds_overview(
        callback.message,
        services=services,
        settings=settings,
        panel_id=panel_id,
        actor_user_id=callback.from_user.id,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_ob_add:"))
async def panel_ob_add(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
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
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, callback.from_user.id, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await state.set_state(OutboundPanelStates.waiting_share_link)
    await state.update_data(panel_ob_panel_id=panel_id)
    await callback.message.answer(t("panel_ob_send_link", lang))
    await callback.answer()


@router.message(OutboundPanelStates.waiting_share_link)
async def panel_ob_receive_link(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    data = await state.get_data()
    panel_id = int(data.get("panel_ob_panel_id") or 0)
    if panel_id <= 0:
        await state.clear()
        return
    if not await services.access_service.can_access_panel(
        user_id=message.from_user.id, settings=settings, panel_id=panel_id
    ):
        await state.clear()
        await message.answer(t("no_admin_access", lang))
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, message.from_user.id, settings, services.access_service
    ):
        await state.clear()
        await message.answer(t("no_admin_access", lang))
        return
    uri = (message.text or "").strip()
    try:
        tag = await services.panel_service.append_outbound_from_share_link(panel_id, uri, message.from_user.id)
    except ValueError as exc:
        await message.answer(t("panel_ob_link_invalid", lang, error=str(exc)))
        return
    except Exception as exc:
        await message.answer(t("panel_ob_link_failed", lang, error=exc))
        return
    await state.clear()
    await message.answer(t("panel_ob_added_ok", lang, tag=tag))
    await send_panel_outbounds_overview(
        message,
        services=services,
        settings=settings,
        panel_id=panel_id,
        actor_user_id=message.from_user.id,
        lang=lang,
    )


@router.callback_query(F.data.startswith("panel_ob_grant:"))
async def panel_ob_grant(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
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
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, callback.from_user.id, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    mgr = None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
    admins = await services.db.list_delegated_admins(manager_user_id=mgr)
    await callback.message.answer(
        t("panel_ob_pick_delegate", lang),
        reply_markup=_grant_delegates_keyboard(panel_id, admins, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_ob_gadm:"))
async def panel_ob_gadm(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    parts = callback.data.split(":")
    try:
        panel_id = int(parts[1])
        delegate_tid = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, callback.from_user.id, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=delegate_tid, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("panel_ob_delegate_no_panel", lang), show_alert=True)
        return
    try:
        tags = await services.panel_service.list_outbound_tags(panel_id)
    except Exception as exc:
        await callback.answer(t("panel_outbounds_fetch_error", lang, error=exc), show_alert=True)
        return
    if not tags:
        await callback.answer(t("panel_outbounds_empty", lang), show_alert=True)
        return
    dmap = await services.db.get_panel_outbound_display_map(panel_id)
    labels = [dmap.get(t, t) for t in tags]
    existing = await services.db.list_panel_outbound_grants_for_delegate(panel_id, delegate_tid)
    selected = {x for x in existing if x in tags}
    await state.set_state(OutboundGrantStates.picking)
    await state.update_data(
        obg_panel_id=panel_id,
        obg_delegate_tid=delegate_tid,
        obg_tags=json.dumps(tags, ensure_ascii=False),
        obg_selected=json.dumps(sorted(selected), ensure_ascii=False),
    )
    await callback.message.answer(
        t("panel_ob_pick_outbound_grant", lang),
        reply_markup=_grant_outbounds_pick_keyboard(
            panel_id=panel_id,
            delegate_tid=delegate_tid,
            tags=tags,
            labels=labels,
            selected=selected,
            lang=lang,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_ob_gt:"))
async def panel_ob_grant_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    cur = await state.get_state()
    if cur != OutboundGrantStates.picking.state:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        panel_id = int(parts[1])
        delegate_tid = int(parts[2])
        idx = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    data = await state.get_data()
    if int(data.get("obg_panel_id") or 0) != panel_id or int(data.get("obg_delegate_tid") or 0) != delegate_tid:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, callback.from_user.id, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    try:
        tags = json.loads(str(data.get("obg_tags") or "[]"))
    except json.JSONDecodeError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not isinstance(tags, list) or idx < 0 or idx >= len(tags):
        await callback.answer(t("admin_edit_location_bad", lang), show_alert=True)
        return
    try:
        raw_sel = json.loads(str(data.get("obg_selected") or "[]"))
        selected = set(raw_sel) if isinstance(raw_sel, list) else set()
    except json.JSONDecodeError:
        selected = set()
    tag = str(tags[idx]).strip()
    if tag in selected:
        selected.discard(tag)
    else:
        selected.add(tag)
    await state.update_data(obg_selected=json.dumps(sorted(selected), ensure_ascii=False))
    dmap = await services.db.get_panel_outbound_display_map(panel_id)
    labels = [dmap.get(str(t).strip(), str(t).strip()) for t in tags]
    await callback.message.edit_reply_markup(
        reply_markup=_grant_outbounds_pick_keyboard(
            panel_id=panel_id,
            delegate_tid=delegate_tid,
            tags=[str(x).strip() for x in tags],
            labels=labels,
            selected=selected,
            lang=lang,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_ob_gcf:"))
async def panel_ob_grant_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    services: ServiceContainer,
) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if await state.get_state() != OutboundGrantStates.picking.state:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        panel_id = int(parts[1])
        delegate_tid = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    data = await state.get_data()
    if int(data.get("obg_panel_id") or 0) != panel_id or int(data.get("obg_delegate_tid") or 0) != delegate_tid:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, callback.from_user.id, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    try:
        tags = json.loads(str(data.get("obg_tags") or "[]"))
        raw_sel = json.loads(str(data.get("obg_selected") or "[]"))
    except json.JSONDecodeError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    if not isinstance(tags, list) or not isinstance(raw_sel, list):
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    tag_set = {str(x).strip() for x in tags if str(x).strip()}
    chosen = [str(x).strip() for x in raw_sel if str(x).strip() in tag_set]
    await services.db.replace_panel_outbound_delegate_grants(panel_id, delegate_tid, chosen)
    await state.clear()
    await callback.message.edit_text(t("panel_ob_grants_saved", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("panel_ob_gbk:"))
async def panel_ob_grant_back_to_delegates(
    callback: CallbackQuery,
    state: FSMContext,
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
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    if not await services.panel_service.actor_may_grant_or_add_outbound(
        panel_id, callback.from_user.id, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await state.clear()
    mgr = None if services.access_service.is_root_admin(callback.from_user.id, settings) else callback.from_user.id
    admins = await services.db.list_delegated_admins(manager_user_id=mgr)
    await callback.message.edit_text(
        t("panel_ob_pick_delegate", lang),
        reply_markup=_grant_delegates_keyboard(panel_id, admins, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("panel_ob_a:"))
async def panel_ob_alias_start(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_any_admin(callback, settings, services):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    parts = callback.data.split(":")
    try:
        panel_id = int(parts[1])
        idx = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    if not await services.access_service.can_access_panel(
        user_id=callback.from_user.id, settings=settings, panel_id=panel_id
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    rows = await services.panel_service.list_outbound_tags_labels_for_actor(
        panel_id, callback.from_user.id, settings, services.access_service
    )
    if idx < 0 or idx >= len(rows):
        await callback.answer(t("admin_edit_location_bad", lang), show_alert=True)
        return
    tag = rows[idx][0]
    if not await services.panel_service.actor_may_set_outbound_display_label(
        panel_id, callback.from_user.id, tag, settings, services.access_service
    ):
        await callback.answer(t("no_admin_access", lang), show_alert=True)
        return
    await state.set_state(OutboundPanelStates.waiting_display_label)
    await state.update_data(panel_ob_panel_id=panel_id, panel_ob_tag=tag)
    await callback.message.answer(t("panel_ob_send_display_name", lang, tag=tag))
    await callback.answer()


@router.message(OutboundPanelStates.waiting_display_label)
async def panel_ob_display_label(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_any_admin(message, settings, services):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    data = await state.get_data()
    panel_id = int(data.get("panel_ob_panel_id") or 0)
    tag = str(data.get("panel_ob_tag") or "").strip()
    label = (message.text or "").strip()
    if panel_id <= 0 or not tag or not label:
        await state.clear()
        await message.answer(t("admin_invalid_data", lang))
        return
    if not await services.access_service.can_access_panel(
        user_id=message.from_user.id, settings=settings, panel_id=panel_id
    ):
        await state.clear()
        await message.answer(t("no_admin_access", lang))
        return
    if not await services.panel_service.actor_may_set_outbound_display_label(
        panel_id, message.from_user.id, tag, settings, services.access_service
    ):
        await state.clear()
        await message.answer(t("no_admin_access", lang))
        return
    await services.db.upsert_panel_outbound_display(panel_id, tag, label)
    await state.clear()
    await message.answer(t("panel_ob_display_saved", lang))
    await send_panel_outbounds_overview(
        message,
        services=services,
        settings=settings,
        panel_id=panel_id,
        actor_user_id=message.from_user.id,
        lang=lang,
    )
