from __future__ import annotations

from aiogram import Router

from bot.handlers import admin_access, admin_bind, admin_cancel, admin_clients, admin_finance, admin_panels, admin_provisioning

router = Router(name="admin")
router.include_router(admin_cancel.router)
router.include_router(admin_finance.router)
router.include_router(admin_panels.router)
router.include_router(admin_access.router)
router.include_router(admin_provisioning.router)
router.include_router(admin_clients.router)
router.include_router(admin_bind.router)
