from __future__ import annotations

from aiogram import Router

from bot.handlers import admin_bind, admin_clients, admin_panels

router = Router(name="admin")
router.include_router(admin_panels.router)
router.include_router(admin_clients.router)
router.include_router(admin_bind.router)
