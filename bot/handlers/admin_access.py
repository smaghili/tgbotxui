from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.states import DelegatedAdminStates

from .admin_shared import reject_callback_if_not_admin, reject_if_not_admin

router = Router(name="admin_access")


def _manage_admins_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("admin_add_delegated", lang), callback_data="dag:add")],
            [InlineKeyboardButton(text=t("admin_list_delegated", lang), callback_data="dag:list")],
        ]
    )


def _inbound_pick_keyboard(rows: list, prefix: str, lang: str | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for row in rows:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{row.panel_name} | {row.inbound_name}",
                    callback_data=f"{prefix}:{row.panel_id}:{row.inbound_id}",
                )
            ]
        )
    if not buttons:
        buttons = [[InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _delegated_inbound_select_keyboard(
    rows: list,
    selected: set[tuple[int, int]],
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        is_selected = (row.panel_id, row.inbound_id) in selected
        mark = "✅ " if is_selected else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{row.panel_name} | {row.inbound_name}",
                    callback_data=f"dag:toggle:{row.panel_id}:{row.inbound_id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text=t("btn_confirm", lang), callback_data="dag:confirm"),
            InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="dag:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _delegated_access_list_keyboard(rows: list[dict], lang: str | None = None) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        title = str(row.get("title") or row.get("full_name") or row.get("username") or row["telegram_user_id"])
        inbound = str(row.get("inbound_name") or f"inbound-{row['inbound_id']}")
        text = f"{title} | {row['panel_name']} | {inbound}"
        buttons.append(
            [
                InlineKeyboardButton(text=text[:56], callback_data="noop"),
                InlineKeyboardButton(text="✏️", callback_data=f"dag:edit:{row['telegram_user_id']}"),
                InlineKeyboardButton(text="🗑️", callback_data=f"dag:revoke:{row['access_id']}"),
            ]
        )
    if not buttons:
        buttons = [[InlineKeyboardButton(text=t("admin_none", lang), callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _start_delegated_inbound_selection(
    *,
    state: FSMContext,
    services: ServiceContainer,
    lang: str | None,
    target_user_id: int,
    title: str | None,
    selected: set[tuple[int, int]],
    mode: str,
    existing_access_ids: dict[tuple[int, int], int] | None = None,
) -> tuple[str, InlineKeyboardMarkup] | None:
    rows = await services.admin_provisioning_service.list_all_inbounds()
    if not rows:
        await state.clear()
        return None
    await state.update_data(
        delegated_mode=mode,
        delegated_target_user_id=target_user_id,
        delegated_title=title,
        delegated_inbound_rows=[(row.panel_id, row.panel_name, row.inbound_id, row.inbound_name) for row in rows],
        delegated_selected_inbounds=[list(item) for item in selected],
        delegated_existing_access_ids={f"{key[0]}:{key[1]}": value for key, value in (existing_access_ids or {}).items()},
    )
    await state.set_state(DelegatedAdminStates.waiting_inbound_selection)
    return (
        t("admin_pick_inbound_for_delegated", lang),
        _delegated_inbound_select_keyboard(rows, selected, lang),
    )


@router.message(F.text.in_(button_variants("btn_manage_admins")))
async def manage_admins_menu(message: Message, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_admin(message, settings):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    await message.answer(
        t("admin_manage_admins_title", lang),
        reply_markup=_manage_admins_keyboard(lang),
    )


@router.callback_query(F.data == "dag:add")
async def delegated_admin_add_start(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    await state.set_state(DelegatedAdminStates.waiting_target)
    if callback.message is not None:
        await callback.message.answer(t("admin_enter_delegated_target", lang))
    await callback.answer()


@router.message(DelegatedAdminStates.waiting_target)
async def delegated_admin_target_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_admin(message, settings):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    target_raw = (message.text or "").strip()
    try:
        target_user_id, resolved_title = await services.admin_provisioning_service.resolve_admin_target(target_raw)
    except ValueError as exc:
        text = str(exc)
        if "username was not found" in text:
            await message.answer(t("admin_delegated_target_unknown", lang))
            return
        await message.answer(text)
        return
    await state.update_data(
        delegated_target_user_id=target_user_id,
        delegated_resolved_title=resolved_title,
    )
    await state.set_state(DelegatedAdminStates.waiting_title)
    await message.answer(t("admin_enter_delegated_title", lang))


@router.message(DelegatedAdminStates.waiting_title)
async def delegated_admin_title_input(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_if_not_admin(message, settings):
        return
    lang = await services.db.get_user_language(message.from_user.id)
    title_raw = (message.text or "").strip()
    title = None if title_raw in {"", "-"} else title_raw
    data = await state.get_data()
    resolved_title = str(data.get("delegated_resolved_title") or "").strip() or None
    if title is None:
        title = resolved_title
    result = await _start_delegated_inbound_selection(
        state=state,
        services=services,
        lang=lang,
        target_user_id=int(data["delegated_target_user_id"]),
        title=title,
        selected=set(),
        mode="create",
    )
    if result is None:
        await message.answer(t("bind_no_panel", lang))
        return
    text, markup = result
    await message.answer(text, reply_markup=markup)


@router.callback_query(DelegatedAdminStates.waiting_inbound_selection, F.data.startswith("dag:toggle:"))
async def delegated_admin_toggle_inbound(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
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
    data = await state.get_data()
    rows = [
        type("InboundRow", (), {"panel_id": row[0], "panel_name": row[1], "inbound_id": row[2], "inbound_name": row[3]})
        for row in data.get("delegated_inbound_rows", [])
    ]
    selected = {tuple(item) for item in data.get("delegated_selected_inbounds", [])}
    key = (panel_id, inbound_id)
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)
    await state.update_data(delegated_selected_inbounds=[list(item) for item in selected])
    await callback.message.edit_reply_markup(reply_markup=_delegated_inbound_select_keyboard(rows, selected, lang))
    await callback.answer()


@router.callback_query(DelegatedAdminStates.waiting_inbound_selection, F.data == "dag:cancel")
async def delegated_admin_cancel_inbound_selection(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    await state.clear()
    await callback.answer()


@router.callback_query(DelegatedAdminStates.waiting_inbound_selection, F.data == "dag:confirm")
async def delegated_admin_confirm_inbound_selection(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    data = await state.get_data()
    selected = [tuple(item) for item in data.get("delegated_selected_inbounds", [])]
    if not selected:
        await callback.answer(t("admin_delegated_pick_one", lang), show_alert=True)
        return
    target_user_id = int(data["delegated_target_user_id"])
    title = data.get("delegated_title")
    mode = str(data.get("delegated_mode") or "create")
    selected_set = {(int(panel_id), int(inbound_id)) for panel_id, inbound_id in selected}
    existing_access_ids_raw = data.get("delegated_existing_access_ids", {})
    existing_access_ids = {
        tuple(map(int, key.split(":", 1))): int(value)
        for key, value in existing_access_ids_raw.items()
    }
    if mode == "edit":
        for key, access_id in existing_access_ids.items():
            if key not in selected_set:
                await services.admin_provisioning_service.revoke_delegated_admin_access(
                    actor_user_id=callback.from_user.id,
                    access_id=access_id,
                )
    for panel_id, inbound_id in selected_set:
        if mode != "edit" or (panel_id, inbound_id) not in existing_access_ids:
            await services.admin_provisioning_service.grant_delegated_admin_access(
                actor_user_id=callback.from_user.id,
                telegram_user_id=target_user_id,
                title=str(title) if title else None,
                panel_id=panel_id,
                inbound_id=inbound_id,
            )
    await state.clear()
    await callback.message.answer(t("admin_delegated_saved", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("dag:edit:"))
async def delegated_admin_edit(callback: CallbackQuery, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    try:
        target_user_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    access_rows = await services.db.list_admin_access_rows_for_user(target_user_id)
    delegated = await services.db.get_delegated_admin_by_user_id(target_user_id)
    if not access_rows or delegated is None:
        await callback.answer(t("admin_panel_not_found", lang), show_alert=True)
        return
    selected = {(int(row["panel_id"]), int(row["inbound_id"])) for row in access_rows}
    existing_access_ids = {
        (int(row["panel_id"]), int(row["inbound_id"])): int(row["access_id"])
        for row in access_rows
    }
    result = await _start_delegated_inbound_selection(
        state=state,
        services=services,
        lang=lang,
        target_user_id=target_user_id,
        title=str(delegated.get("title") or "").strip() or None,
        selected=selected,
        mode="edit",
        existing_access_ids=existing_access_ids,
    )
    if result is None:
        await callback.answer(t("bind_no_panel", lang), show_alert=True)
        return
    text, markup = result
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data == "dag:list")
async def delegated_admin_list(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    if callback.message is None:
        await callback.answer()
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    rows = await services.admin_provisioning_service.list_delegated_admin_accesses()
    text = t("admin_delegated_empty", lang) if not rows else t("admin_delegated_list_header", lang)
    await callback.message.answer(text, reply_markup=_delegated_access_list_keyboard(rows, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("dag:revoke:"))
async def delegated_admin_revoke(callback: CallbackQuery, settings: Settings, services: ServiceContainer) -> None:
    if await reject_callback_if_not_admin(callback, settings):
        return
    lang = await services.db.get_user_language(callback.from_user.id)
    if callback.data is None:
        await callback.answer()
        return
    try:
        access_id = int(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer(t("admin_invalid_data", lang), show_alert=True)
        return
    revoked = await services.admin_provisioning_service.revoke_delegated_admin_access(
        actor_user_id=callback.from_user.id,
        access_id=access_id,
    )
    if callback.message is not None:
        rows = await services.admin_provisioning_service.list_delegated_admin_accesses()
        text = t("admin_delegated_empty", lang) if not rows else t("admin_delegated_list_header", lang)
        await callback.message.edit_text(text, reply_markup=_delegated_access_list_keyboard(rows, lang))
    await callback.answer(t("admin_delegated_removed", lang) if revoked else t("admin_panel_not_found", lang))
