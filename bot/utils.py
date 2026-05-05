from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import jdatetime

from bot.i18n import t

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
PERSIAN_TO_ENGLISH_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
BYTES_PER_GB = 1024**3


def to_persian_digits(value: str | int) -> str:
    return str(value).translate(PERSIAN_DIGITS)


def parse_epoch(raw: int | str | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > 10_000_000_000:
        value = value // 1000
    return value


def bytes_to_gb(value: int) -> float:
    return value / BYTES_PER_GB


def parse_gb_amount(raw: str) -> float:
    value = raw.strip().translate(PERSIAN_TO_ENGLISH_DIGITS).replace(",", "")
    if value.startswith("."):
        value = f"0{value}"
    if not value:
        raise ValueError("empty_gb_amount")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid_gb_amount") from exc
    if amount < 0:
        raise ValueError("negative_gb_amount")
    return float(amount)


def parse_price_per_gb_with_tiers(raw: str) -> tuple[int, str | None]:
    normalized = raw.strip().translate(PERSIAN_TO_ENGLISH_DIGITS)
    if not normalized:
        raise ValueError("empty_price")
    compact = normalized.replace(" ", "")
    if "|" not in compact:
        return int(compact.replace(",", "")), None
    base_raw, tiers_raw = compact.split("|", 1)
    price_per_gb = int(base_raw.replace(",", ""))
    if price_per_gb < 0:
        raise ValueError("negative_base_price")
    tiers_map: dict[int, int] = {}
    for part in tiers_raw.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" in item:
            traffic_raw, amount_raw = item.split("=", 1)
        elif ":" in item:
            traffic_raw, amount_raw = item.split(":", 1)
        else:
            raise ValueError("invalid_tier_format")
        traffic_gb = int(traffic_raw)
        amount = int(amount_raw)
        if traffic_gb <= 0 or amount < 0:
            raise ValueError("invalid_tier_values")
        tiers_map[traffic_gb] = amount
    tiers = [{"traffic_gb": key, "amount": tiers_map[key]} for key in sorted(tiers_map.keys())]
    return price_per_gb, json.dumps(tiers, separators=(",", ":"))


def gb_to_bytes(value: float | int) -> int:
    amount = Decimal(str(value))
    if amount <= 0:
        return 0
    return int((amount * BYTES_PER_GB).to_integral_value(rounding=ROUND_FLOOR))


def format_gb(value: int, lang: str = "fa") -> str:
    amount = f"{bytes_to_gb(value):.2f}"
    if lang == "fa":
        amount = to_persian_digits(amount)
    return f"{amount} {t('unit_gb', lang)}"


def format_bytes(value: int, lang: str = "fa") -> str:
    size = float(max(0, value))
    units = [
        ("B", "بایت"),
        ("KB", "کیلوبایت"),
        ("MB", "مگابایت"),
        ("GB", "گیگابایت"),
        ("TB", "ترابایت"),
    ]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    amount = f"{size:.2f}"
    unit = units[idx][0] if lang != "fa" else units[idx][1]
    if lang == "fa":
        amount = to_persian_digits(amount)
    return f"{amount} {unit}"


def format_gb_exact(value: float | int) -> str:
    formatted = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return formatted or "0"


def parse_detail_pairs(raw: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_db_timestamp(raw: str | None) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_db_timestamp(raw: str | None, *, tz_name: str, lang: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return t("na_value", lang)
    dt = parse_db_timestamp(value)
    if dt is None:
        return value
    local_dt = dt.astimezone(ZoneInfo(tz_name))
    if lang == "fa":
        return to_jalali_datetime(int(local_dt.timestamp()), tz_name)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def inbound_display_name(inbound: Mapping[str, Any]) -> str:
    remark = str(inbound.get("remark") or "").strip()
    if remark:
        return remark
    port = inbound.get("port")
    if port:
        return f"inbound-{port}"
    inbound_id = inbound.get("id")
    return f"inbound-{inbound_id}" if inbound_id is not None else "inbound-unknown"


def display_name_from_parts(*, full_name: str | None, username: str | None, fallback: str | int) -> str:
    full_name_value = str(full_name or "").strip()
    if full_name_value:
        return full_name_value
    username_value = str(username or "").strip().lstrip("@")
    if username_value:
        return f"@{username_value}"
    return str(fallback)


def activity_details_block(details: list[str] | None) -> str:
    if not details:
        return ""
    return "\n" + "\n".join(details)


def build_admin_activity_notice(
    *,
    lang: str | None,
    actor: str,
    action_text: str,
    user: str,
    panel: str,
    inbound: str,
    details: list[str] | None = None,
) -> str:
    return t(
        "admin_activity_notify_template",
        lang,
        actor=actor,
        action=action_text,
        user=user,
        panel=panel,
        inbound=inbound,
        details=activity_details_block(details),
    )


def to_jalali_date(epoch_seconds: int | None, tz_name: str) -> str:
    if not epoch_seconds:
        return t("na_value", "fa")
    tz = ZoneInfo(tz_name)
    dt = datetime.fromtimestamp(epoch_seconds, tz=tz)
    jd = jdatetime.datetime.fromgregorian(datetime=dt)
    return to_persian_digits(jd.strftime("%Y/%m/%d"))


def to_local_date(epoch_seconds: int | None, tz_name: str, lang: str = "fa") -> str:
    if not epoch_seconds:
        return t("na_value", lang)
    tz = ZoneInfo(tz_name)
    dt = datetime.fromtimestamp(epoch_seconds, tz=tz)
    if lang == "fa":
        jd = jdatetime.datetime.fromgregorian(datetime=dt)
        return to_persian_digits(jd.strftime("%Y/%m/%d"))
    return dt.strftime("%Y-%m-%d")


def to_jalali_datetime(epoch_seconds: int | None, tz_name: str) -> str:
    if not epoch_seconds:
        return t("na_value", "fa")
    tz = ZoneInfo(tz_name)
    dt = datetime.fromtimestamp(epoch_seconds, tz=tz)
    jd = jdatetime.datetime.fromgregorian(datetime=dt)
    return to_persian_digits(jd.strftime("%Y/%m/%d %H:%M:%S"))


def now_jalali_datetime(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    dt = datetime.now(tz)
    jd = jdatetime.datetime.fromgregorian(datetime=dt)
    return to_persian_digits(jd.strftime("%Y/%m/%d %H:%M:%S"))


def relative_remaining_time(epoch_seconds: int | None, tz_name: str, lang: str = "fa") -> str:
    if not epoch_seconds:
        return t("unknown_value", lang)
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    target = datetime.fromtimestamp(epoch_seconds, tz=tz)
    if target <= now:
        return t("expired_value", lang)

    delta = target - now
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60

    if lang == "fa":
        months = days // 30
        days = days % 30
        parts = []
        if months:
            parts.append(f"{to_persian_digits(months)} {t('time_months', lang)}")
        if days:
            parts.append(f"{to_persian_digits(days)} {t('time_days', lang)}")
        if hours:
            parts.append(f"{to_persian_digits(hours)} {t('time_hours', lang)}")
        if minutes:
            parts.append(f"{to_persian_digits(minutes)} {t('time_minutes', lang)}")
        if not parts:
            parts = [t("time_lt_minute", lang)]
        return f"{' '.join(parts)} {t('time_left', lang)}"

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts = [t("time_lt_minute", lang)]
    return " ".join(parts) + " " + t("time_left", lang)


def status_emoji(status: str, lang: str = "fa") -> str:
    mapping = {
        "active": t("st_active", lang),
        "expired": t("st_expired", lang),
        "depleted": t("st_depleted", lang),
        "suspended": t("st_suspended", lang),
        "error": t("st_error", lang),
    }
    return mapping.get(status, t("st_unknown", lang))
