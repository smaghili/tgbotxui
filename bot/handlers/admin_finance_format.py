from __future__ import annotations

from bot.config import Settings
from bot.handlers.admin_finance_helpers import consumed_basis_payable_remainder
from bot.i18n import t
from bot.utils import format_db_timestamp, format_gb_exact, parse_detail_pairs


def format_amount(value: int) -> str:
    return f"{value:,}"


def format_admin_timestamp(raw: str | None, *, settings: Settings, lang: str | None) -> str:
    return format_db_timestamp(raw, tz_name=settings.timezone, lang=lang)


def format_exact_gb(value: float | int) -> str:
    return format_gb_exact(value)


def parse_details(raw: str | None) -> dict[str, str]:
    return parse_detail_pairs(raw)


def consumed_credit_lines(summary: dict, *, lang: str | None, currency: str) -> str:
    if str(summary.get("pricing", {}).get("charge_basis") or "allocated") != "consumed":
        return ""
    return t(
        "finance_credit_consumed_lines",
        lang,
        consumed_gb=format_exact_gb(summary.get("consumed_gb") or 0),
        debt_amount=format_amount(int(summary.get("debt_amount") or 0)),
        payable_amount=format_amount(
            consumed_basis_payable_remainder(
                debt_amount=int(summary.get("debt_amount") or 0),
                wallet_balance=int(summary.get("wallet", {}).get("balance") or 0),
            )
        ),
        remaining_gb=format_exact_gb(summary.get("remaining_gb") or 0),
        remaining_amount=format_amount(int(summary.get("remaining_amount") or 0)),
        currency=currency,
    )


def delegated_consumed_lines(summary: dict, *, lang: str | None, currency: str) -> str:
    if str(summary.get("pricing", {}).get("charge_basis") or "allocated") != "consumed":
        return ""
    return t(
        "admin_delegated_consumed_lines",
        lang,
        consumed_gb=format_exact_gb(summary.get("consumed_gb") or 0),
        payable_amount=format_amount(
            consumed_basis_payable_remainder(
                debt_amount=int(summary.get("debt_amount") or 0),
                wallet_balance=int(summary.get("wallet", {}).get("balance") or 0),
            )
        ),
        remaining_gb=format_exact_gb(summary.get("remaining_gb") or 0),
        remaining_amount=format_amount(int(summary.get("remaining_amount") or 0)),
        currency=currency,
    )


def delegated_sales_value(summary: dict, sales_report: dict) -> int:
    if str(summary.get("pricing", {}).get("charge_basis") or "allocated") == "consumed":
        return int(summary.get("debt_amount") or 0)
    return int(sales_report.get("total_sales") or 0)
