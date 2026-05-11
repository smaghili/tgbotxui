"""Split bot/handlers/admin_finance.py into smaller modules (run once)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "bot/handlers/admin_finance.py"
lines = SRC.read_text(encoding="utf-8").splitlines(True)


def w(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- keyboards (original lines 41-117, 0-based slice 40:117)
kb_header = '''"""Finance inline keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.i18n import t


'''
w(ROOT / "bot/handlers/admin_finance_keyboards.py", kb_header + "".join(lines[39:117]))

# --- ops: _is_primary .. _save_pricing_and_answer (line 663–882 file -> idx 662:882 exclusive end)
ops_header = '''"""Shared finance helpers: access checks, menus, sales/pricing responses."""
from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.keyboards import (
    finance_limited_delegated_keyboard,
    finance_primary_delegated_keyboard,
    finance_root_delegated_keyboard,
    main_keyboard,
)
from bot.services.container import ServiceContainer

from bot.handlers.admin_finance_helpers import (
    _format_amount,
    _format_gb_exact,
    wallet_currency_label,
)


'''
w(ROOT / "bot/handlers/admin_finance_ops.py", ops_header + "".join(lines[662:882]))

today_header = '''"""Today's sales/reports formatting and handlers."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.types import Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.services.container import ServiceContainer
from bot.utils import to_persian_digits

from bot.handlers.admin_finance_helpers import (
    _actor_title,
    _create_activity_signature,
    _extract_create_client_amounts,
    _format_amount,
    _format_db_timestamp,
    _parse_admin_activity_text,
    _parse_detail_pairs,
    _resolve_panel_inbound_names_from_details,
    _today_utc_range_strings,
    _transaction_email,
    _wallet_create_client_signature,
)

from .admin_finance_ops import _can_access_today_finance
from .admin_shared import reject_if_not_any_admin

router = Router(name="admin_finance_today")


'''
today_body = "".join(lines[331:661])

handlers_today = "".join(lines[916:956]) + "".join(lines[1166:1190])

w(
    ROOT / "bot/handlers/admin_finance_today.py",
    today_header + today_body + "\n\n" + handlers_today,
)

wallet_header = '''"""Wallet adjustment handlers (authorized targets only)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.states import FinanceStates

from bot.handlers.admin_finance_helpers import _format_amount, wallet_currency_label

from .admin_finance_keyboards import _wallet_action_keyboard
from .admin_finance_ops import (
    _can_manage_finance_target,
    _main_menu_markup,
    _wallet_target_summary_text,
)
from .admin_shared import (
    answer_with_cancel,
    reject_callback_if_not_any_admin,
    reject_if_not_any_admin,
)

router = Router(name="admin_finance_wallet")


'''
w(ROOT / "bot/handlers/admin_finance_wallet.py", wallet_header + "".join(lines[1191:1426]))

pricing_header = '''"""Pricing FSM handlers (root)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import t
from bot.services.container import ServiceContainer
from bot.states import FinanceStates
from bot.utils import parse_price_per_gb_with_tiers

from bot.handlers.admin_finance_helpers import _format_amount, wallet_currency_label

from .admin_finance_keyboards import _pricing_history_choice_keyboard
from .admin_finance_ops import _save_pricing_and_answer
from .admin_shared import answer_with_cancel, reject_callback_if_not_any_admin, reject_if_not_any_admin

router = Router(name="admin_finance_pricing")


'''
w(ROOT / "bot/handlers/admin_finance_pricing.py", pricing_header + "".join(lines[1427:1588]))

main_header = '''"""Admin finance: menus and composed routers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.i18n import button_variants, t
from bot.keyboards import (
    finance_limited_delegated_keyboard,
    finance_primary_delegated_keyboard,
    finance_root_delegated_keyboard,
    main_keyboard,
)
from bot.services.container import ServiceContainer
from bot.states import FinanceStates

from bot.handlers.admin_finance_helpers import _format_amount, wallet_currency_label
from bot.handlers.admin_finance_pricing import router as pricing_router
from bot.handlers.admin_finance_today import router as today_router
from bot.handlers.admin_finance_wallet import router as wallet_router

from .admin_finance_keyboards import (
    _finance_delegated_keyboard,
    _finance_delegates_keyboard,
    _finance_root_keyboard,
    _wallet_action_keyboard,
)
from .admin_finance_ops import (
    _answer_sales_report,
    _finance_menu_text_and_keyboard,
    _is_primary_delegated_admin,
    _main_menu_markup,
)
from .admin_shared import answer_with_cancel, reject_callback_if_not_any_admin, reject_if_not_any_admin

router = Router(name="admin_finance")
router.include_router(today_router)
router.include_router(wallet_router)
router.include_router(pricing_router)


'''
# Menus + callbacks, excluding today handlers (917–956) and fin:sales:today callback (1167–1190)
main_body = "".join(lines[883:916]) + "".join(lines[956:1166])
w(ROOT / "bot/handlers/admin_finance.py", main_header + main_body)

print("done")
