from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import jdatetime

from bot.i18n import t

PERSIAN_DIGITS = str.maketrans("0123456789", "0123456789")


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
    return value / (1024**3)


def format_gb(value: int, lang: str = "fa") -> str:
    return f"{bytes_to_gb(value):.2f} {t('unit_gb', lang)}"


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
