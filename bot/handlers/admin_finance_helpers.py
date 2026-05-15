from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.utils import (
    format_db_timestamp as shared_format_db_timestamp,
    format_gb_exact as shared_format_gb_exact,
    parse_db_timestamp as shared_parse_db_timestamp,
    parse_detail_pairs as shared_parse_detail_pairs,
)


def wallet_currency_label(raw: str | None, *, lang: str | None) -> str:
    text = str(raw or "").strip()
    return text if text else t("finance_currency_default", lang)


def _format_amount(value: int) -> str:
    return f"{value:,}"


def _format_db_timestamp(raw: str, *, settings: Settings, lang: str | None) -> str:
    return shared_format_db_timestamp(raw, tz_name=settings.timezone, lang=lang)


def _format_gb_exact(value: float | int) -> str:
    return shared_format_gb_exact(value)


def payable_from_wallet(balance: int) -> int:
    return -int(balance)


def _parse_detail_pairs(raw: str | None) -> dict[str, str]:
    return shared_parse_detail_pairs(raw)


def _today_utc_range_strings(tz_name: str) -> tuple[str, str]:
    local_now = datetime.now(ZoneInfo(tz_name))
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    start_utc = local_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = local_end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return start_utc, end_utc


async def _actor_title(
    *,
    actor_user_id: int | None,
    services: ServiceContainer,
) -> str:
    if actor_user_id is None:
        return "-"
    user = await services.db.get_user_by_telegram_id(actor_user_id)
    if user is not None:
        name = str(user.get("full_name") or "").strip()
        if name:
            return name
        username = str(user.get("username") or "").strip()
        if username:
            return username
    delegated = await services.db.get_delegated_admin_by_user_id(actor_user_id)
    if delegated is not None:
        title = str(delegated.get("title") or "").strip()
        if title:
            return title
    return str(actor_user_id)


async def _transaction_email(
    item: dict,
    *,
    services: ServiceContainer,
) -> str:
    details = _parse_detail_pairs(item.get("details"))
    email = str(details.get("email") or details.get("client_email") or "").strip()
    if email:
        return email
    panel_raw = details.get("panel")
    inbound_raw = details.get("inbound")
    client_uuid = str(details.get("client_uuid") or "").strip()
    if not panel_raw or not inbound_raw or not client_uuid:
        return "-"
    try:
        detail = await services.panel_service.get_client_detail(int(panel_raw), int(inbound_raw), client_uuid)
    except Exception:
        return "-"
    return str(detail.get("email") or "-").strip() or "-"


def _parse_admin_activity_text(raw: str | None) -> dict[str, str | list[str]]:
    parsed: dict[str, str | list[str]] = {
        "actor": "",
        "operation": "",
        "user": "",
        "panel": "",
        "inbound": "",
        "time": "",
        "extras": [],
    }
    mapping = {
        f"{t('admin_activity_label_actor', 'fa')}:": "actor",
        f"{t('admin_activity_label_actor', 'en')}:": "actor",
        f"{t('admin_activity_label_action', 'fa')}:": "operation",
        f"{t('admin_activity_label_action', 'en')}:": "operation",
        f"{t('admin_activity_label_user', 'fa')}:": "user",
        f"{t('admin_activity_label_user', 'en')}:": "user",
        f"{t('admin_activity_label_panel', 'fa')}:": "panel",
        f"{t('admin_activity_label_panel', 'en')}:": "panel",
        f"{t('admin_activity_label_inbound', 'fa')}:": "inbound",
        f"{t('admin_activity_label_inbound', 'en')}:": "inbound",
        f"{t('admin_activity_label_time', 'fa')}:": "time",
        f"{t('admin_activity_label_time', 'en')}:": "time",
    }
    extras: list[str] = []
    for raw_line in str(raw or "").splitlines():
        line = raw_line.strip()
        if not line or line in {
            f"{t('admin_activity_notice_title', 'fa')}:",
            f"{t('admin_activity_notice_title', 'en')}:",
        }:
            continue
        for prefix, key in mapping.items():
            if line.startswith(prefix):
                parsed[key] = line[len(prefix) :].strip()
                break
        else:
            extras.append(line)
    parsed["extras"] = extras
    return parsed


def _create_activity_signature(*, actor_user_id: int, created_at: str, user: str) -> tuple[int, str, str]:
    return actor_user_id, created_at.strip(), user.strip().lower()


def _canonical_sale_operation_from_wallet(operation: str) -> str | None:
    value = str(operation or "").strip()
    if value == "create_client":
        return "create_client"
    if value in {"add_client_traffic", "add_client_total_gb"}:
        return "add_traffic"
    if value == "extend_client_expiry_days":
        return "add_days"
    return None


def _canonical_sale_operation_from_activity(operation: str) -> str | None:
    value = str(operation or "").strip()
    mapping = {
        t("admin_activity_action_create_client", "fa"): "create_client",
        t("admin_activity_action_create_client", "en"): "create_client",
        t("admin_activity_action_add_traffic", "fa"): "add_traffic",
        t("admin_activity_action_add_traffic", "en"): "add_traffic",
        t("admin_activity_action_add_days", "fa"): "add_days",
        t("admin_activity_action_add_days", "en"): "add_days",
    }
    return mapping.get(value)


def _sale_time_bucket(raw: str | None) -> str:
    dt = shared_parse_db_timestamp(raw)
    if dt is None:
        return str(raw or "").strip()[:16]
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _sale_signature(
    *,
    actor_user_id: int,
    created_at: str | None,
    user: str,
    operation_key: str,
) -> tuple[int, str, str, str]:
    return (
        actor_user_id,
        _sale_time_bucket(created_at),
        user.strip().lower(),
        operation_key,
    )


async def _wallet_sale_signature(item: dict, *, services: ServiceContainer) -> tuple[int, str, str, str] | None:
    operation_key = _canonical_sale_operation_from_wallet(item.get("operation") or "")
    actor_user_id = int(item.get("actor_user_id") or item.get("telegram_user_id") or 0)
    if operation_key is None or actor_user_id <= 0:
        return None
    user = await _transaction_email(item, services=services)
    if not user or user == "-":
        return None
    return _sale_signature(
        actor_user_id=actor_user_id,
        created_at=str(item.get("created_at") or ""),
        user=user,
        operation_key=operation_key,
    )


def _activity_sale_signature(item: dict, parsed: dict[str, str | list[str]]) -> tuple[int, str, str, str] | None:
    operation_key = _canonical_sale_operation_from_activity(str(parsed.get("operation") or ""))
    actor_user_id = int(item.get("actor_user_id") or 0)
    user = str(parsed.get("user") or "").strip()
    if operation_key is None or actor_user_id <= 0 or not user:
        return None
    return _sale_signature(
        actor_user_id=actor_user_id,
        created_at=str(item.get("created_at") or ""),
        user=user,
        operation_key=operation_key,
    )


def _wallet_create_client_signature(item: dict) -> tuple[int, str, str] | None:
    actor_user_id = int(item.get("actor_user_id") or 0)
    details = _parse_detail_pairs(item.get("details"))
    email = str(details.get("email") or "").strip()
    created_at = str(item.get("created_at") or "").strip()
    if actor_user_id <= 0 or not email or not created_at:
        return None
    return _create_activity_signature(
        actor_user_id=actor_user_id,
        created_at=created_at,
        user=email,
    )


def _extract_create_client_amounts(
    *,
    extras: list[str] | None = None,
    wallet_item: dict | None = None,
) -> tuple[str | None, str | None]:
    traffic_value: str | None = None
    expiry_value: str | None = None

    for extra in extras or []:
        line = str(extra).strip()
        if not line:
            continue
        if traffic_value is None and any(
            token in line
            for token in (
                t("finance_unit_gb_short", "fa"),
                t("finance_unit_gb_short", "en"),
            )
        ):
            raw_value = line.split(":", 1)[1].strip() if ":" in line else line
            traffic_value = (
                raw_value.replace(t("finance_unit_gb_short", "fa"), "")
                .replace(t("finance_unit_gb_short", "en"), "")
                .strip()
            )
            continue
        if expiry_value is None and any(
            token in line
            for token in (
                t("finance_unit_day_short", "fa"),
                t("finance_unit_day_short", "en"),
                t("finance_report_expiry_part", "fa", value=""),
                t("finance_report_expiry_part", "en", value=""),
            )
        ):
            raw_value = line.split(":", 1)[1].strip() if ":" in line else line
            expiry_value = (
                raw_value.replace(t("finance_report_expiry_part", "fa", value="").strip(), "")
                .replace(t("finance_unit_day_short", "fa"), "")
                .replace(t("finance_unit_day_short", "en"), "")
                .strip()
            )

    if wallet_item is not None:
        try:
            metadata = json.loads(wallet_item.get("metadata_json") or "{}")
        except Exception:
            metadata = {}
        if traffic_value is None:
            traffic_gb = float(metadata.get("traffic_gb") or 0)
            if traffic_gb > 0:
                traffic_value = str(traffic_gb).rstrip("0").rstrip(".")
        if expiry_value is None:
            expiry_days = int(metadata.get("expiry_days") or 0)
            if expiry_days > 0:
                expiry_value = str(expiry_days)

    return traffic_value, expiry_value


async def _resolve_panel_inbound_names_from_details(
    details: dict[str, str],
    *,
    services: ServiceContainer,
) -> tuple[str, str]:
    panel_raw = str(details.get("panel") or "").strip()
    inbound_raw = str(details.get("inbound") or "").strip()
    panel_name = panel_raw or "-"
    inbound_name = inbound_raw or "-"
    if panel_raw.lstrip("-").isdigit():
        panel_id = int(panel_raw)
        if inbound_raw.lstrip("-").isdigit():
            try:
                return await services.panel_service.panel_inbound_names(panel_id, int(inbound_raw))
            except Exception:
                return panel_name, inbound_name
        panel = await services.panel_service.get_panel(panel_id)
        if panel is not None:
            panel_name = str(panel.get("name") or panel_raw)
    return panel_name, inbound_name
