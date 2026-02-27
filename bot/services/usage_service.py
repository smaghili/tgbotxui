from __future__ import annotations

import logging
from typing import List

from bot.db import Database
from bot.i18n import t
from bot.metrics import PANEL_COUNT, SYNC_RUNS, USER_SERVICE_COUNT, USER_STATUS_REQUESTS
from bot.services.panel_service import PanelService
from bot.utils import format_gb, relative_remaining_time, status_emoji, to_local_date

logger = logging.getLogger(__name__)


class UsageService:
    def __init__(self, db: Database, panel_service: PanelService, timezone: str) -> None:
        self.db = db
        self.panel_service = panel_service
        self.timezone = timezone

    async def refresh_user_services(self, telegram_user_id: int) -> None:
        services = await self.db.get_user_services(telegram_user_id)
        had_error = False
        for row in services:
            try:
                await self.panel_service.sync_single_service(row)
            except Exception:
                had_error = True
                logger.exception("failed to sync service", extra={"service_id": row.get("id")})
        SYNC_RUNS.labels(result="error" if had_error else "ok").inc()

    async def refresh_all_services(self) -> None:
        services = await self.db.get_all_user_services()
        had_error = False
        for row in services:
            try:
                await self.panel_service.sync_single_service(row)
            except Exception:
                had_error = True
                logger.exception("failed to sync service", extra={"service_id": row.get("id")})
        SYNC_RUNS.labels(result="error" if had_error else "ok").inc()
        await self.refresh_cardinality_metrics()

    async def refresh_cardinality_metrics(self) -> None:
        PANEL_COUNT.set(await self.db.count_panels())
        USER_SERVICE_COUNT.set(await self.db.count_user_services())

    def _format_status_card(self, service: dict, lang: str) -> str:
        status_text = status_emoji(service.get("status", "unknown"), lang)
        name = service.get("service_name") or service.get("client_email")
        total = int(service.get("total_bytes", -1))
        used = int(service.get("used_bytes", 0))
        expire_at = service.get("expire_at")

        if total < 0:
            traffic_text = t("us_unlimited", lang)
            used_text = format_gb(used, lang)
            remain_text = t("us_unlimited", lang)
            percent_text = "-"
        else:
            remain = max(total - used, 0)
            percent = (remain / total * 100) if total > 0 else 0
            traffic_text = format_gb(total, lang)
            used_text = format_gb(used, lang)
            remain_text = format_gb(remain, lang)
            percent_text = f"{percent:.2f}%"

        return (
            f"{t('us_service_status', lang)}: {status_text}\n"
            f"{t('us_service_name', lang)}: {name}\n\n"
            f"{t('us_traffic', lang)}: {traffic_text}\n"
            f"{t('us_used', lang)}: {used_text}\n"
            f"{t('us_remaining', lang)}: {remain_text} ({percent_text})\n\n"
            f"{t('us_expiry_date', lang)}: {to_local_date(expire_at, self.timezone, lang)} "
            f"({relative_remaining_time(expire_at, self.timezone, lang)})"
        )

    async def get_user_status_messages(self, telegram_user_id: int, force_refresh: bool = False) -> List[str]:
        if force_refresh:
            await self.refresh_user_services(telegram_user_id)
        lang = await self.db.get_user_language(telegram_user_id)
        services = await self.db.get_user_services(telegram_user_id)
        USER_STATUS_REQUESTS.labels(result="empty" if not services else "ok").inc()
        return [self._format_status_card(service, lang) for service in services]
