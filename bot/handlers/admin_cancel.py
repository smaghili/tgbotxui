from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import main_keyboard
from bot.services.container import ServiceContainer

from .admin_shared import admin_keyboard_for_user

router = Router(name="admin_cancel")


@router.message(Command("cancel"), StateFilter("*"))
@router.message(F.text.in_(button_variants("btn_cancel_operation")), StateFilter("*"))
@router.message(F.text.in_(button_variants("btn_cancel")), StateFilter("*"))
async def handle_cancel(message: Message, state: FSMContext, settings: Settings, services: ServiceContainer) -> None:
    await state.clear()
    is_admin = await services.access_service.is_any_admin(message.from_user.id, settings)
    await message.answer(
        t("operation_cancelled", None),
        reply_markup=await admin_keyboard_for_user(user_id=message.from_user.id, settings=settings, services=services)
        if is_admin
        else main_keyboard(False),
    )
