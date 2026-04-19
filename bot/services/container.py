from __future__ import annotations

from dataclasses import dataclass

from bot.db import Database
from bot.services.access_service import AccessService
from bot.services.admin_panel_service import AdminPanelService
from bot.services.admin_provisioning_service import AdminProvisioningService
from bot.services.panel_service import PanelService
from bot.services.usage_service import UsageService


@dataclass(slots=True)
class ServiceContainer:
    db: Database
    panel_service: PanelService
    admin_panel_service: AdminPanelService
    access_service: AccessService
    admin_provisioning_service: AdminProvisioningService
    usage_service: UsageService
