from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.utils import build_admin_activity_notice

from .admin_shared import actor_display_name


def delegated_profile_error_text(
    exc: Exception,
    lang: str | None,
    *,
    include_duplicate: bool = False,
) -> str | None:
    text = str(exc).lower()
    mapping: list[tuple[str, str]] = [
        ("max clients reached", "admin_delegated_limit_error_max_clients"),
        ("traffic is below", "admin_delegated_limit_error_traffic_min"),
        ("traffic is above", "admin_delegated_limit_error_traffic_max"),
        ("expiry is below", "admin_delegated_limit_error_days_min"),
        ("expiry is above", "admin_delegated_limit_error_days_max"),
        ("inactive", "admin_delegated_inactive"),
        ("expired", "admin_delegated_expired"),
    ]
    if include_duplicate:
        mapping.insert(0, ("already exists on this inbound", "admin_duplicate_client_email"))
    for needle, key in mapping:
        if needle in text:
            return t(key, lang)
    return None


async def safe_panel_inbound_names(
    services: ServiceContainer,
    *,
    panel_id: int,
    inbound_id: int,
) -> tuple[str, str]:
    try:
        return await services.panel_service.panel_inbound_names(panel_id, inbound_id)
    except Exception:
        return str(panel_id), f"inbound-{inbound_id}"


async def notify_admin_activity_for_source(
    source: Message | CallbackQuery,
    *,
    settings: Settings,
    services: ServiceContainer,
    lang: str | None,
    action_key: str,
    user: str,
    panel: str,
    inbound: str,
    details: list[str] | None = None,
) -> None:
    await services.admin_provisioning_service.record_admin_activity(
        actor_user_id=source.from_user.id,
        settings=settings,
        text=build_admin_activity_notice(
            lang=lang,
            actor=actor_display_name(source),
            action_text=t(action_key, lang),
            user=user,
            panel=panel,
            inbound=inbound,
            details=details,
        ),
    )
