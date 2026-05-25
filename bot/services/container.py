from __future__ import annotations

from dataclasses import dataclass

from bot.db import Database
from bot.services.access_service import AccessService
from bot.services.admin_access_handler_service import AdminAccessHandlerService
from bot.services.admin_panel_service import AdminPanelService
from bot.services.admin_provisioning_service import AdminProvisioningService
from bot.services.common_handler_service import CommonHandlerService
from bot.services.financial_service import FinancialService
from bot.services.handler_context_service import HandlerContextService
from bot.services.operation_guard_service import OperationGuardService
from bot.services.payment_service import PaymentService
from bot.services.panel_service import PanelService
from bot.services.usage_service import UsageService


@dataclass(slots=True)
class ServiceContainer:
    db: Database
    panel_service: PanelService
    admin_panel_service: AdminPanelService
    access_service: AccessService
    admin_access_handler_service: AdminAccessHandlerService
    admin_provisioning_service: AdminProvisioningService
    common_handler_service: CommonHandlerService
    financial_service: FinancialService
    handler_context_service: HandlerContextService
    operation_guard_service: OperationGuardService
    payment_service: PaymentService
    usage_service: UsageService
