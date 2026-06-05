from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.states import PanelGroupStates

from .admin_shared import answer_with_cancel

router = Router(name="admin_panel_groups")


def _parse_panel_id(callback_data: str, *, index: int = 2) -> int:
    return int(callback_data.split(":")[index])


def _parse_panel_group_ids(callback_data: str) -> tuple[int, int]:
    _, _, panel_id_raw, group_id_raw = callback_data.split(":")
    return int(panel_id_raw), int(group_id_raw)


def _parse_panel_group_inbound_ids(callback_data: str) -> tuple[int, int, int]:
    _, _, panel_id_raw, group_id_raw, inbound_id_raw = callback_data.split(":")
    return int(panel_id_raw), int(group_id_raw), int(inbound_id_raw)


async def _lang(callback: CallbackQuery | Message, services: ServiceContainer) -> str | None:
    return await services.db.get_user_language(callback.from_user.id)


async def _render(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=reply_markup)


async def _load_group_detail_context(
    *,
    panel_id: int,
    group_id: int,
    services: ServiceContainer,
) -> tuple[dict, set[int], list[dict]] | None:
    group = await services.admin_provisioning_service.client_group_service.get_group(panel_id=panel_id, group_id=group_id)
    if group is None:
        return None
    members = await services.admin_provisioning_service.client_group_service.get_group_members(panel_id=panel_id, group_id=group_id)
    selected_ids = {int(row["inbound_id"]) for row in members}
    inbounds = await services.panel_service.list_inbounds(panel_id)
    return group, selected_ids, inbounds


async def _render_group_detail_picker(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    panel_id: int,
    group_id: int,
    group: dict,
    selected_ids: set[int],
    inbounds: list[dict],
    lang: str | None,
) -> None:
    await state.set_state(PanelGroupStates.waiting_inbound_selection)
    await state.update_data(
        panel_group_panel_id=panel_id,
        panel_group_group_id=group_id,
        panel_group_selected_ids=sorted(selected_ids),
    )
    await _render(
        callback,
        t("panel_group_pick_inbounds", lang, name=str(group.get("name") or "")),
        _group_inbound_keyboard(panel_id, group_id, inbounds, selected_ids, lang),
    )


async def _selected_inbound_ids_from_state(state: FSMContext) -> set[int]:
    data = await state.get_data()
    return {int(value) for value in data.get("panel_group_selected_ids", [])}


def _group_menu_keyboard(panel_id: int, lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("panel_group_add", lang), callback_data=f"pg:add:{panel_id}")],
            [InlineKeyboardButton(text=t("panel_group_list", lang), callback_data=f"pg:list:{panel_id}")],
            [InlineKeyboardButton(text=t("admin_back", lang), callback_data=f"panel_actions:{panel_id}")],
        ]
    )


def _group_list_keyboard(panel_id: int, groups: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups:
        label = str(group.get("name") or "").strip() or f"group-{group.get('id')}"
        if bool(group.get("is_default")):
            label = f"⭐ {label}"
        rows.append([InlineKeyboardButton(text=label[:48], callback_data=f"pg:detail:{panel_id}:{int(group['id'])}")])
    rows.append([InlineKeyboardButton(text=t("admin_back", lang), callback_data=f"pg:menu:{panel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_inbound_keyboard(
    panel_id: int,
    group_id: int,
    inbounds: list[dict],
    selected_ids: set[int],
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for inbound in inbounds:
        inbound_id = int(inbound.get("id") or 0)
        if inbound_id <= 0:
            continue
        title = str(inbound.get("remark") or "").strip() or f"inbound-{inbound_id}"
        prefix = "✅ " if inbound_id in selected_ids else ""
        rows.append([InlineKeyboardButton(text=f"{prefix}{title}"[:62], callback_data=f"pg:toggle:{panel_id}:{group_id}:{inbound_id}")])
    rows.append([InlineKeyboardButton(text=t("panel_access_save", lang), callback_data=f"pg:save:{panel_id}:{group_id}")])
    rows.append([InlineKeyboardButton(text=t("admin_back", lang), callback_data=f"pg:list:{panel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("pg:menu:"))
async def group_menu(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await _lang(callback, services)
    try:
        panel_id = _parse_panel_id(callback.data)
    except (IndexError, ValueError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    await _render(callback, t("panel_group_menu_title", lang), _group_menu_keyboard(panel_id, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("pg:list:"))
async def group_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await _lang(callback, services)
    try:
        panel_id = _parse_panel_id(callback.data)
    except (IndexError, ValueError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    groups = await services.admin_provisioning_service.client_group_service.list_groups(panel_id=panel_id)
    await _render(callback, t("panel_group_list_title", lang), _group_list_keyboard(panel_id, groups, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("pg:add:"))
async def group_add(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await _lang(callback, services)
    try:
        panel_id = _parse_panel_id(callback.data)
    except (IndexError, ValueError):
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    await state.set_state(PanelGroupStates.waiting_group_name)
    await state.update_data(panel_group_panel_id=panel_id)
    await answer_with_cancel(callback.message, t("panel_group_add_prompt", lang), lang=lang)
    await callback.answer()


@router.message(PanelGroupStates.waiting_group_name)
async def group_add_submit(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    lang = await _lang(message, services)
    data = await state.get_data()
    panel_id = int(data.get("panel_group_panel_id") or 0)
    name = str(message.text or "").strip()
    if panel_id <= 0 or not name:
        await message.answer(t("panel_group_add_invalid", lang))
        return
    try:
        await services.admin_provisioning_service.client_group_service.create_group(panel_id=panel_id, name=name)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    groups = await services.admin_provisioning_service.client_group_service.list_groups(panel_id=panel_id)
    await message.answer(t("panel_group_created", lang, name=name), reply_markup=_group_list_keyboard(panel_id, groups, lang))


@router.callback_query(F.data.startswith("pg:detail:"))
async def group_detail(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await _lang(callback, services)
    try:
        panel_id, group_id = _parse_panel_group_ids(callback.data)
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    context = await _load_group_detail_context(panel_id=panel_id, group_id=group_id, services=services)
    if context is None:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    group, selected_ids, inbounds = context
    await _render_group_detail_picker(
        callback,
        state,
        panel_id=panel_id,
        group_id=group_id,
        group=group,
        selected_ids=selected_ids,
        inbounds=inbounds,
        lang=lang,
    )
    await callback.answer()


@router.callback_query(PanelGroupStates.waiting_inbound_selection, F.data.startswith("pg:toggle:"))
async def group_toggle(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await _lang(callback, services)
    try:
        panel_id, group_id, inbound_id = _parse_panel_group_inbound_ids(callback.data)
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    selected = await _selected_inbound_ids_from_state(state)
    if inbound_id in selected:
        selected.remove(inbound_id)
    else:
        selected.add(inbound_id)
    await state.update_data(panel_group_selected_ids=sorted(selected))
    context = await _load_group_detail_context(panel_id=panel_id, group_id=group_id, services=services)
    group_name = str((context[0] if context is not None else {}).get("name") or "")
    inbounds = context[2] if context is not None else await services.panel_service.list_inbounds(panel_id)
    await _render(
        callback,
        t("panel_group_pick_inbounds", lang, name=group_name),
        _group_inbound_keyboard(panel_id, group_id, inbounds, selected, lang),
    )
    await callback.answer()


@router.callback_query(PanelGroupStates.waiting_inbound_selection, F.data.startswith("pg:save:"))
async def group_save(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await _lang(callback, services)
    try:
        panel_id, group_id = _parse_panel_group_ids(callback.data)
    except ValueError:
        await callback.answer(t("bind_invalid_id", lang), show_alert=True)
        return
    selected = await _selected_inbound_ids_from_state(state)
    await services.admin_provisioning_service.client_group_service.sync_group_inbounds(
        panel_id=panel_id,
        group_id=group_id,
        inbound_ids=selected,
    )
    await state.clear()
    groups = await services.admin_provisioning_service.client_group_service.list_groups(panel_id=panel_id)
    await _render(callback, t("panel_group_saved", lang), _group_list_keyboard(panel_id, groups, lang))
    await callback.answer()
