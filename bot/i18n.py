from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

Lang = Literal["fa", "en"]
DEFAULT_LANG: Lang = "fa"
SUPPORTED_LANGS: tuple[Lang, ...] = ("fa", "en")
_CURRENT_LANG: ContextVar[str] = ContextVar("current_lang", default=DEFAULT_LANG)


TEXTS: dict[str, dict[Lang, str]] = {
    "btn_status": {"fa": "📊 وضعیت سرویس من", "en": "📊 My Service Status"},
    "btn_manage": {"fa": "🛠 مدیریت پنل", "en": "🛠 Panel Management"},
    "btn_manage_finance": {"fa": "💰 مدیریت مالی", "en": "💰 Financial Management"},
    "btn_change_language": {"fa": "🌐 تغییر زبان", "en": "🌐 Change Language"},
    "btn_back": {"fa": "بازگشت", "en": "Back"},
    "btn_add_panel": {"fa": "افزودن پنل", "en": "Add Panel"},
    "btn_list_panels": {"fa": "لیست پنل‌ها", "en": "Panel List"},
    "btn_list_inbounds": {"fa": "لیست ورودی‌ها", "en": "Inbound List"},
    "btn_list_users": {"fa": "لیست کاربران", "en": "Users List"},
    "btn_online_users": {"fa": "کاربران آنلاین", "en": "Online Users"},
    "btn_low_traffic_users": {"fa": "🪫 کاربران کم‌حجم", "en": "🪫 Low Traffic Users"},
    "btn_search_user": {"fa": "🔎 جستجوی کاربر", "en": "🔎 Search User"},
    "btn_disabled_users": {"fa": "🚫 کاربران غیرفعال", "en": "🚫 Disabled Users"},
    "btn_last_online_users": {"fa": "🕘 آخرین آنلاین", "en": "🕘 Last Online"},
    "btn_inbounds_overview": {"fa": "📋 اطلاعات کلی ورودی‌ها", "en": "📋 Inbound Overview"},
    "btn_create_user": {"fa": "➕ ساخت کاربر", "en": "➕ Create User"},
    "btn_edit_config": {"fa": "🛠 ویرایش کانفیگ", "en": "🛠 Edit Config"},
    "btn_manage_admins": {"fa": "👥 مدیریت ادمین‌ها", "en": "👥 Manage Admins"},
    "btn_cleanup_settings": {"fa": "⏱ تنظیم حذف خودکار", "en": "⏱ Auto cleanup"},
    "btn_bulk_operations": {"fa": "عملیات گروهی", "en": "Bulk Operations"},
    "btn_cancel": {"fa": "لغو", "en": "Cancel"},
    "btn_cancel_operation": {"fa": "لغو عملیات", "en": "Cancel Operation"},
    "btn_bind_service": {"fa": "اتصال سرویس به کاربر", "en": "Bind Service to User"},
    "btn_sync_usage": {"fa": "همگام‌سازی مصرف", "en": "Sync Usage"},
    "btn_rotate_link": {"fa": "تغییر کانفیگ ⚙️", "en": "Change Config ⚙️"},
    "btn_get_config": {"fa": "دریافت کانفیگ 📥", "en": "Get Config 📥"},
    "btn_refresh_config": {"fa": "🔄 بروزرسانی", "en": "🔄 Refresh"},
    "btn_yes": {"fa": "بله", "en": "Yes"},
    "btn_no": {"fa": "خیر", "en": "No"},
    "btn_confirm": {"fa": "تایید", "en": "Confirm"},
    "btn_show_report": {"fa": "📈 گزارش", "en": "📈 Report"},
    "btn_wallet_set": {"fa": "تنظیم موجودی", "en": "Set Balance"},
    "btn_wallet_add": {"fa": "افزایش موجودی", "en": "Increase Balance"},
    "btn_wallet_subtract": {"fa": "کاهش موجودی", "en": "Decrease Balance"},
    "btn_wallet_show": {"fa": "نمایش کیف پول", "en": "Show Wallet"},

    "menu_management": {"fa": "پنل مدیریت:", "en": "Management Panel:"},
    "menu_main": {"fa": "منوی اصلی", "en": "Main Menu"},
    "operation_cancelled": {"fa": "عملیات لغو شد.", "en": "Operation cancelled."},

    "welcome": {
        "fa": "سلام به ربات همشهری خوش آمدید 👋\n\n📌 جهت استفاده از ربات لطفا یکی از موارد زیر را انتخاب کنید",
        "en": "Welcome to Hamshahri bot 👋\n\n📌 Please choose one of the options below.",
    },
    "help_manage_hint": {"fa": "مدیریت: لیست ورودی‌ها", "en": "Management: Inbound list"},
    "help_bind_default": {
        "fa": "/bind <telegram_user_id> <client_email> [service_name] (با پنل پیش‌فرض)",
        "en": "/bind <telegram_user_id> <client_email> [service_name] (with default panel)",
    },
    "language_title": {"fa": "زبان موردنظر را انتخاب کنید:", "en": "Choose your language:"},
    "language_changed_fa": {"fa": "✅ زبان شما به فارسی تغییر کرد.", "en": "✅ Your language changed to Persian."},
    "language_changed_en": {"fa": "✅ زبان شما به انگلیسی تغییر کرد.", "en": "✅ Your language changed to English."},
    "no_admin_access": {"fa": "شما دسترسی ادمین ندارید.", "en": "You do not have admin access."},
    "finance_root_title": {
        "fa": "مدیریت مالی:\n- کیف پول کاربران\n- قیمت‌گذاری کاربران/مدیران\n- گزارش مالی کلی",
        "en": "Financial management:\n- User wallets\n- User/admin pricing\n- Overall financial report",
    },
    "finance_root_delegate_menu": {
        "fa": "مدیریت مالی مدیر اصلی:\n- نمایندگی‌ها\n- فروش امروز\n- گزارش‌های امروز",
        "en": "Root financial management:\n- Delegates\n- Today's sales\n- Today's reports",
    },
    "finance_delegated_title": {
        "fa": "مدیریت مالی:\n- مشاهده اعتبار\n- نمایندگی‌ها\n- فروش امروز\n- گزارش‌های امروز\n- بازگشت",
        "en": "Financial management:\n- View credit\n- Delegates\n- Today's sales\n- Today's reports\n- Back",
    },
    "finance_limited_delegated_title": {
        "fa": "مدیریت مالی:\n- فروش امروز\n- گزارش‌های امروز\n- بازگشت",
        "en": "Financial management:\n- Today's sales\n- Today's reports\n- Back",
    },
    "finance_wallet_manage": {"fa": "👛 کیف پول کاربران", "en": "👛 User Wallets"},
    "finance_pricing_manage": {"fa": "💳 تنظیم قیمت کاربران", "en": "💳 User Pricing"},
    "finance_overall_report": {"fa": "📊 گزارش مالی کلی", "en": "📊 Overall Financial Report"},
    "finance_my_sales_report": {"fa": "📈 گزارش فروش من", "en": "📈 My Sales Report"},
    "finance_view_credit": {"fa": "💰 مشاهده اعتبار", "en": "💰 View Credit"},
    "finance_delegates_list": {"fa": "👥 نمایندگی‌ها", "en": "👥 Delegates"},
    "finance_today_sales": {"fa": "💵 فروش امروز", "en": "💵 Today's Sales"},
    "finance_today_reports": {"fa": "🗒 گزارش‌های امروز", "en": "🗒 Today's Reports"},
    "finance_delegates_list_header": {"fa": "لیست نمایندگی‌ها:", "en": "Delegates list:"},
    "finance_enter_target": {
        "fa": "آیدی عددی یا @username کاربر را وارد کنید.",
        "en": "Enter numeric user id or @username.",
    },
    "finance_wallet_target_summary": {
        "fa": "کاربر: {title}\nموجودی: {balance} {currency}\nقیمت هر گیگ: {price_gb} {currency}\nقیمت هر روز: {price_day} {currency}",
        "en": "User: {title}\nBalance: {balance} {currency}\nPer-GB price: {price_gb} {currency}\nPer-day price: {price_day} {currency}",
    },
    "finance_choose_wallet_action": {
        "fa": "عملیات کیف پول را انتخاب کنید:",
        "en": "Choose wallet action:",
    },
    "finance_enter_amount": {
        "fa": "مقدار را به تومان وارد کنید:",
        "en": "Enter amount:",
    },
    "finance_wallet_updated": {
        "fa": "کیف پول بروزرسانی شد.\nموجودی جدید: {balance} {currency}",
        "en": "Wallet updated.\nNew balance: {balance} {currency}",
    },
    "finance_enter_price_per_gb": {
        "fa": "قیمت هر گیگ را وارد کنید:",
        "en": "Enter price per GB:",
    },
    "finance_enter_price_per_day": {
        "fa": "قیمت هر روز را وارد کنید:",
        "en": "Enter price per day:",
    },
    "finance_pricing_saved": {
        "fa": "قیمت‌گذاری ذخیره شد.\nهر گیگ: {price_gb} {currency}\nهر روز: {price_day} {currency}",
        "en": "Pricing saved.\nPer GB: {price_gb} {currency}\nPer day: {price_day} {currency}",
    },
    "finance_pricing_history_confirm": {
        "fa": "قبلا قیمت هر گیگ {old_price_gb} {currency} بوده است.\nقیمت جدید: {new_price_gb} {currency}\n\nآیا می‌خواهید قیمت جدید برای گزارش‌های قبلی هم اعمال شود؟",
        "en": "Previous per-GB price was {old_price_gb} {currency}.\nNew price: {new_price_gb} {currency}\n\nDo you want to apply the new price to previous reports as well?",
    },
    "finance_overall_report_text": {
        "fa": "گزارش مالی کلی\n\nتعداد کیف پول: {wallets}\nمجموع موجودی: {balance} {currency}\nفروش کل: {sales} {currency}\nتعداد فروش‌ها: {sales_count}\nتعداد تراکنش‌ها: {transactions}\nپروفایل‌های قیمت‌گذاری: {pricing_profiles}",
        "en": "Overall financial report\n\nWallets: {wallets}\nTotal balance: {balance} {currency}\nTotal sales: {sales} {currency}\nSales count: {sales_count}\nTransactions: {transactions}\nPricing profiles: {pricing_profiles}",
    },
    "finance_sales_report_text": {
        "fa": "گزارش فروش\n\nموجودی فعلی: {balance} {currency}\nهر گیگ: {price_gb} {currency}\nهر روز: {price_day} {currency}\nفروش کل: {sales} {currency}\nتعداد تراکنش‌ها: {transactions}",
        "en": "Sales report\n\nCurrent balance: {balance} {currency}\nPer GB: {price_gb} {currency}\nPer day: {price_day} {currency}\nTotal sales: {sales} {currency}\nTransactions: {transactions}",
    },
    "finance_credit_report_text": {
        "fa": "گزارش نمایندگی\n\nنماینده: {title}\nموجودی: {balance} {currency}\nهر گیگ: {price_gb} {currency}\nهر روز: {price_day} {currency}\nکل فروش نمایندگی‌ها: {sale_amount} {currency}\nتعداد تراکنش‌ها: {transactions}\nکاربران ساخته‌شده: {clients}{extra_lines}",
        "en": "Delegated report\n\nDelegate: {title}\nBalance: {balance} {currency}\nPer GB: {price_gb} {currency}\nPer day: {price_day} {currency}\nTotal sales: {sale_amount} {currency}\nTransactions: {transactions}\nCreated users: {clients}{extra_lines}",
    },
    "finance_credit_consumed_lines": {
        "fa": "\nحجم مصرف‌شده: {consumed_gb} گیگ\nبدهکاری فعلی: {debt_amount} {currency}",
        "en": "\nConsumed traffic: {consumed_gb} GB\nCurrent debt: {debt_amount} {currency}",
    },
    "finance_today_sales_title": {
        "fa": "فروش امروز",
        "en": "Today's Sales",
    },
    "finance_today_sales_empty": {
        "fa": "برای امروز فروش ثبت‌شده‌ای وجود ندارد.",
        "en": "There are no sales recorded for today.",
    },
    "finance_amount_unknown": {
        "fa": "نامشخص",
        "en": "Unknown",
    },
    "finance_today_reports_soon": {
        "fa": "بخش گزارش‌های امروز بعدا تکمیل می‌شود.",
        "en": "Today's reports will be added later.",
    },
    "finance_today_reports_title": {
        "fa": "گزارش امروز",
        "en": "Today's Reports",
    },
    "finance_today_reports_empty": {
        "fa": "برای امروز گزارشی ثبت نشده است.",
        "en": "There are no reports recorded for today.",
    },
    "finance_currency_default": {
        "fa": "تومان",
        "en": "Toman",
    },
    "finance_report_traffic_part": {
        "fa": "حجم {value} گیگ",
        "en": "Traffic {value} GB",
    },
    "finance_report_expiry_part": {
        "fa": "{value} روزه",
        "en": "{value} days",
    },
    "finance_report_actor_part": {
        "fa": "توسط {value}",
        "en": "By {value}",
    },
    "finance_report_panel_part": {
        "fa": "پنل {value}",
        "en": "Panel {value}",
    },
    "finance_report_inbound_part": {
        "fa": "اینباند {value}",
        "en": "Inbound {value}",
    },
    "finance_report_time_part": {
        "fa": "در تاریخ {value}",
        "en": "At {value}",
    },
    "finance_report_amount_part": {
        "fa": "مبلغ {value}",
        "en": "Amount {value}",
    },
    "finance_unit_gb_short": {
        "fa": "گیگ",
        "en": "GB",
    },
    "finance_unit_day_short": {
        "fa": "روز",
        "en": "days",
    },
    "admin_activity_notice_title": {
        "fa": "اطلاع مدیر",
        "en": "Manager notice",
    },
    "admin_activity_label_actor": {
        "fa": "ادمین",
        "en": "Admin",
    },
    "admin_activity_label_action": {
        "fa": "عملیات",
        "en": "Operation",
    },
    "admin_activity_label_user": {
        "fa": "کاربر",
        "en": "User",
    },
    "admin_activity_label_panel": {
        "fa": "پنل",
        "en": "Panel",
    },
    "admin_activity_label_inbound": {
        "fa": "اینباند",
        "en": "Inbound",
    },
    "admin_activity_label_time": {
        "fa": "زمان",
        "en": "Time",
    },
    "finance_master_report_text": {
        "fa": "گزارش مالی کلی\n\nکیف پول: {balance} {currency}\nقیمت هر گیگ {basis_label}: {price_gb} {currency}\nتعداد کاربران: {clients}\nحجم تخصیص‌یافته: {allocated_gb} گیگ\nمبلغ کل فروش: {sale_amount} {currency}\nحجم مصرف‌شده: {consumed_gb} گیگ\nبدهکاری: {debt_amount} {currency}",
        "en": "Overall financial report\n\nWallet: {balance} {currency}\nPer-GB {basis_label}: {price_gb} {currency}\nClients: {clients}\nAllocated traffic: {allocated_gb} GB\nTotal sales: {sale_amount} {currency}\nConsumed traffic: {consumed_gb} GB\nDebt: {debt_amount} {currency}",
    },
    "finance_limited_report_text": {
        "fa": "گزارش مالی کلی\n\nکیف پول: {balance} {currency}\nکاربر ساخته‌شده: {clients}\nگیگ تخصیصی: {allocated_gb} گیگ\nقیمت کل: {sale_amount} {currency}",
        "en": "Overall financial report\n\nWallet: {balance} {currency}\nCreated users: {clients}\nAllocated traffic: {allocated_gb} GB\nTotal price: {sale_amount} {currency}",
    },
    "finance_target_unknown": {
        "fa": "کاربر در دیتابیس ربات پیدا نشد.",
        "en": "User was not found in bot database.",
    },
    "finance_invalid_amount": {
        "fa": "مقدار واردشده نامعتبر است.",
        "en": "Invalid amount.",
    },
    "finance_insufficient_wallet": {
        "fa": "موجودی کیف پول کافی نیست.",
        "en": "Insufficient wallet balance.",
    },
    "finance_unlimited_not_allowed": {
        "fa": "برای مدیران فرعی تنظیم نامحدود مجاز نیست.",
        "en": "Unlimited values are not allowed for delegated admins.",
    },
    "admin_duplicate_client_email": {
        "fa": "این نام کاربری/ایمیل از قبل در این اینباند وجود دارد.",
        "en": "This client email already exists on this inbound.",
    },

    "status_fetch_error": {
        "fa": "در دریافت وضعیت سرویس خطا رخ داد. کمی بعد دوباره تلاش کنید.",
        "en": "Failed to fetch service status. Please try again later.",
    },
    "status_empty": {
        "fa": "سرویسی به اکانت شما متصل نشده است. برای اتصال با ادمین هماهنگ کنید.",
        "en": "No service is connected to your account. Contact admin to bind a service.",
    },
    "status_choose_service": {
        "fa": "لطفا یکی از سرویس های خود را انتخاب کنید.",
        "en": "Please select one of your services.",
    },
    "status_invalid_id": {"fa": "شناسه نامعتبر است.", "en": "Invalid ID."},
    "status_not_found": {"fa": "سرویس پیدا نشد.", "en": "Service not found."},
    "status_no_access": {"fa": "شما به این سرویس دسترسی ندارید.", "en": "You do not have access to this service."},
    "status_rotating": {"fa": "در حال تغییر لینک...", "en": "Rotating link..."},
    "status_rotated": {"fa": "✅ لینک با UUID جدید بروزرسانی شد.", "en": "✅ Link was refreshed with a new UUID."},
    "status_prepare_config": {"fa": "در حال آماده‌سازی کانفیگ...", "en": "Preparing config..."},
    "status_rotate_confirm": {
        "fa": "با این عملیات کانفیگ فعلی شما قطع می‌شود و کانفیگ و لینک اشتراک جدید دریافت می‌کنید. مطمئن هستید؟",
        "en": "This will invalidate your current config and issue a new config and subscription link. Are you sure?",
    },
    "status_rotate_done_bundle": {
        "fa": "کانفیگ جدید شما آماده شد.",
        "en": "Your new config is ready.",
    },
    "error_prefix": {"fa": "خطا", "en": "Error"},

    "bind_invalid_default_panel": {
        "fa": "پنل پیش‌فرض نامعتبر است. دوباره انتخاب کنید.",
        "en": "Configured default panel is invalid. Please re-select.",
    },
    "bind_default_panel_selected": {
        "fa": "پنل پیش‌فرض انتخاب شد: {name}\ntelegram_user_id کاربر را وارد کنید:",
        "en": "Default panel selected: {name}\nEnter target telegram_user_id:",
    },
    "bind_no_panel": {"fa": "هیچ پنلی ثبت نشده است.", "en": "No panel registered."},
    "bind_select_panel": {
        "fa": "پنل پیش‌فرض انتخاب نشده است.\nلطفا پنل را برای این عملیات انتخاب کنید:",
        "en": "Default panel is not selected.\nPlease select a panel for this operation:",
    },
    "bind_invalid_id": {"fa": "شناسه نامعتبر است.", "en": "Invalid ID."},
    "bind_panel_not_found": {"fa": "پنل پیدا نشد.", "en": "Panel not found."},
    "bind_panel_selected": {
        "fa": "پنل انتخاب شد: {name}\ntelegram_user_id کاربر را وارد کنید:",
        "en": "Panel selected: {name}\nEnter target telegram_user_id:",
    },
    "bind_choose_panel_inline": {
        "fa": "لطفا یکی از پنل‌ها را از دکمه‌های شیشه‌ای انتخاب کنید.",
        "en": "Please choose a panel using inline buttons.",
    },
    "bind_tg_id_number": {"fa": "telegram_user_id باید عدد باشد.", "en": "telegram_user_id must be numeric."},
    "bind_enter_config_id": {
        "fa": "شناسه کانفیگ (email/client) را وارد کنید:",
        "en": "Enter config identifier (email/client):",
    },
    "bind_config_id_empty": {"fa": "شناسه کانفیگ نمی‌تواند خالی باشد.", "en": "Config identifier cannot be empty."},
    "bind_enter_service_name": {
        "fa": "نام سرویس را وارد کنید (اختیاری، اگر ندارید - بزنید):",
        "en": "Enter service name (optional, send - to skip):",
    },
    "bind_checking_service": {"fa": "در حال بررسی سرویس روی پنل...", "en": "Checking service on panel..."},
    "bind_failed": {"fa": "اتصال سرویس ناموفق بود", "en": "Service binding failed"},
    "bind_success": {
        "fa": "سرویس با موفقیت متصل شد.\nسرویس: {service}\nوضعیت: {status}",
        "en": "Service bound successfully.\nService: {service}\nStatus: {status}",
    },
    "sync_start": {"fa": "شروع همگام‌سازی...", "en": "Starting synchronization..."},
    "sync_done": {"fa": "همگام‌سازی کامل شد.", "en": "Synchronization completed."},
    "bind_ids_numeric": {"fa": "شناسه‌ها باید عدد باشند.\n\n", "en": "IDs must be numeric.\n\n"},
    "bind_need_default_panel": {
        "fa": "برای این عملیات از «لیست پنل‌ها» یک پنل پیش‌فرض انتخاب کنید.",
        "en": "For this operation, choose a default panel from Panel List.",
    },

    "unit_gb": {"fa": "گیگابایت", "en": "GB"},
    "unit_day": {"fa": "روز", "en": "days"},
    "unit_second": {"fa": "ثانیه", "en": "seconds"},
    "na_value": {"fa": "ندارد", "en": "N/A"},
    "unknown_value": {"fa": "نامشخص", "en": "Unknown"},
    "expired_value": {"fa": "منقضی شده", "en": "Expired"},
    "time_months": {"fa": "ماه", "en": "months"},
    "time_days": {"fa": "روز", "en": "days"},
    "time_hours": {"fa": "ساعت", "en": "hours"},
    "time_minutes": {"fa": "دقیقه", "en": "minutes"},
    "time_lt_minute": {"fa": "کمتر از یک دقیقه", "en": "less than a minute"},
    "time_left": {"fa": "دیگر", "en": "left"},

    "st_active": {"fa": "✅ فعال", "en": "✅ Active"},
    "st_expired": {"fa": "⛔ منقضی", "en": "⛔ Expired"},
    "st_depleted": {"fa": "🚫 اتمام حجم", "en": "🚫 Depleted"},
    "st_suspended": {"fa": "⚠️ تعلیق", "en": "⚠️ Suspended"},
    "st_error": {"fa": "❌ خطا", "en": "❌ Error"},
    "st_unknown": {"fa": "❓ نامشخص", "en": "❓ Unknown"},

    "us_unlimited": {"fa": "نامحدود", "en": "Unlimited"},
    "us_service_status": {"fa": "📊 وضعیت سرویس", "en": "📊 Service Status"},
    "us_service_name": {"fa": "👤 نام سرویس", "en": "👤 Service Name"},
    "us_traffic": {"fa": "🔋 ترافیک", "en": "🔋 Traffic"},
    "us_used": {"fa": "📥 حجم مصرفی", "en": "📥 Used"},
    "us_remaining": {"fa": "💢 حجم باقی مانده", "en": "💢 Remaining"},
    "service_threshold_warning": {
        "fa": "هشدار سرویس:\nحجم باقی مانده سرویس {service_name} به کمتر از {threshold_mb} مگابایت رسیده است.\nحجم باقی مانده: {remaining}",
        "en": "Service warning:\nYour service {service_name} is below {threshold_mb} MB remaining.\nRemaining traffic: {remaining}",
    },
    "admin_service_threshold_warning": {
        "fa": "هشدار سرویس:\nکاربر {client_email} کمتر از {threshold_mb} مگابایت حجم دارد.\nسرویس: {service_name}\nپنل: {panel}\nاینباند: {inbound}\nحجم باقی‌مانده: {remaining}",
        "en": "Service warning:\nUser {client_email} is below {threshold_mb} MB remaining.\nService: {service_name}\nPanel: {panel}\nInbound: {inbound}\nRemaining traffic: {remaining}",
    },
    "us_expiry_date": {"fa": "📅 تاریخ اتمام", "en": "📅 Expiry Date"},

    "config_caption": {
        "fa": "QR کانفیگ شما\n\nلینک کانفیگ (برای کپی راحت‌تر روی متن کد نگه دارید):\n<code>{uri}</code>",
        "en": "Your config QR\n\nConfig link (hold on the code block to copy):\n<code>{uri}</code>",
    },

    "admin_panels_list": {
        "fa": "پنل‌های ثبت‌شده:\nبرای حذف روی آیکون سطل کلیک کنید.\nبرای تنظیم یا برداشتن پنل پیش‌فرض روی نام پنل بزنید.\nپنل پیش‌فرض با ستاره مشخص شده.",
        "en": "Registered panels:\nTap trash icon to delete.\nTap panel name to set or unset the default panel.\nDefault panel is marked with a star.",
    },
    "admin_none": {"fa": "هیچ موردی ثبت نشده است.", "en": "No records found."},
    "admin_panel_not_found": {"fa": "پنل پیدا نشد.", "en": "Panel not found."},
    "admin_inbound_not_found": {"fa": "اینباند پیدا نشد.", "en": "Inbound not found."},
    "admin_client_not_found": {"fa": "کاربر پیدا نشد.", "en": "Client not found."},
    "admin_invalid_data": {"fa": "داده نامعتبر است.", "en": "Invalid payload."},
    "admin_refresh_done": {"fa": "تازه‌سازی شد.", "en": "Refreshed."},
    "admin_error_fetch_client": {"fa": "خطا در دریافت اطلاعات کاربر", "en": "Failed to fetch client data"},
    "admin_error_fetch_inbounds": {"fa": "خطا در دریافت لیست اینباندها", "en": "Failed to fetch inbounds"},
    "admin_error_fetch_online": {"fa": "خطا در دریافت کاربران آنلاین", "en": "Failed to fetch online users"},
    "admin_error_fetch_low_traffic": {"fa": "خطا در دریافت کاربران کم‌حجم", "en": "Failed to fetch low traffic users"},

    "admin_back_to_inbounds": {"fa": "⬅️ بازگشت به اینباندها", "en": "⬅️ Back to inbounds"},
    "admin_back_to_users": {"fa": "⬅️ بازگشت به کاربران", "en": "⬅️ Back to users"},
    "admin_back": {"fa": "⬅️ بازگشت", "en": "⬅️ Back"},
    "admin_refresh_list": {"fa": "🔄 تازه‌سازی لیست", "en": "🔄 Refresh list"},
    "admin_search_user": {"fa": "🔎 جستجوی کاربر", "en": "🔎 Search User"},
    "admin_disabled_users": {"fa": "🚫 کاربران غیرفعال", "en": "🚫 Disabled Users"},
    "admin_last_online_users": {"fa": "🕘 آخرین آنلاین", "en": "🕘 Last Online"},
    "admin_refresh": {"fa": "🔄 تازه‌سازی", "en": "🔄 Refresh"},
    "admin_toggle_on": {"fa": "فعال / غیرفعال 🟢", "en": "Enable / Disable 🟢"},
    "admin_toggle_off": {"fa": "فعال / غیرفعال ⚪️", "en": "Enable / Disable ⚪️"},
    "admin_limit_traffic": {"fa": "📈 محدودیت ترافیک", "en": "📈 Traffic limit"},
    "admin_reset_traffic": {"fa": "📉 تنظیم مجدد ترافیک", "en": "📉 Reset traffic"},
    "admin_reset_expiry": {"fa": "📅 تنظیم مجدد تاریخ‌انقضا", "en": "📅 Reset expiry"},
    "admin_ip_log": {"fa": "📋 لاگ آدرس‌های IP", "en": "📋 IP logs"},
    "admin_ip_limit": {"fa": "🔢 محدودیت IP", "en": "🔢 IP limit"},
    "admin_set_tg": {"fa": "👤 تنظیم کاربر تلگرام", "en": "👤 Set Telegram user"},
    "admin_confirm_reset": {"fa": "✅ تایید تنظیم مجدد ترافیک", "en": "✅ Confirm reset traffic"},
    "admin_cancel_reset": {"fa": "❌ لغو تنظیم مجدد", "en": "❌ Cancel reset"},
    "admin_cancel": {"fa": "❌ لغو", "en": "❌ Cancel"},
    "admin_unlimited_reset": {"fa": "♾️ نامحدود(ریست)", "en": "♾️ Unlimited (reset)"},
    "admin_custom": {"fa": "🔢 سفارشی", "en": "🔢 Custom"},
    "admin_cancel_ip_limit": {"fa": "❌ لغو محدودیت آی‌پی", "en": "❌ Cancel IP limit"},
    "admin_clear_ip_log": {"fa": "🧹 پاکسازی لاگ IP", "en": "🧹 Clear IP logs"},

    "admin_inbounds_title": {"fa": "📥 لیست ورودی‌ها", "en": "📥 Inbound List"},
    "admin_inbounds_overview_title": {"fa": "📋 اطلاعات کلی ورودی‌ها", "en": "📋 Inbound Overview"},
    "admin_panel_label": {"fa": "پنل", "en": "Panel"},
    "admin_panel_total_usage": {"fa": "📦 مصرف کل پنل", "en": "📦 Total panel usage"},
    "admin_inbounds_count": {"fa": "🧩 تعداد اینباند", "en": "🧩 Inbounds count"},
    "admin_inbound_name": {"fa": "📍 نام‌ورودی", "en": "📍 Inbound"},
    "admin_port": {"fa": "🔌 پورت", "en": "🔌 Port"},
    "admin_traffic": {"fa": "🚦 ترافیک", "en": "🚦 Traffic"},
    "admin_download": {"fa": "دانلود", "en": "Download"},
    "admin_upload": {"fa": "آپلود", "en": "Upload"},
    "admin_expiry": {"fa": "📅 تاریخ‌انقضا", "en": "📅 Expiry"},
    "admin_clients_count": {"fa": "👥 تعداد کاربر", "en": "👥 Clients"},
    "admin_active_clients_count": {"fa": "👥 تعداد کاربر فعال", "en": "👥 Active clients"},
    "admin_inactive_clients_count": {"fa": "👥 تعداد کاربر غیرفعال", "en": "👥 Inactive clients"},
    "admin_status": {"fa": "🟢 وضعیت", "en": "🟢 Status"},
    "admin_enabled": {"fa": "فعال ✅", "en": "Enabled ✅"},
    "admin_disabled": {"fa": "غیرفعال ❌", "en": "Disabled ❌"},
    "admin_no_inbounds": {"fa": "هیچ ورودی‌ای ثبت نشده است.", "en": "No inbounds found."},
    "admin_unlimited": {"fa": "♾️ نامحدود", "en": "♾️ Unlimited"},

    "admin_yes": {"fa": "✅ بله", "en": "✅ Yes"},
    "admin_no": {"fa": "❌ خیر", "en": "❌ No"},
    "admin_online": {"fa": "🟢 آنلاین", "en": "🟢 Online"},
    "admin_offline": {"fa": "⚫️ آفلاین", "en": "⚫️ Offline"},
    "admin_unlimited_reset_value": {"fa": "♾️ نامحدود(ریست)", "en": "♾️ Unlimited (reset)"},
    "admin_detail": {
        "fa": "📧 ایمیل: {email}\n🚨 وضعیت: {enabled}\n🌐 وضعیت اتصال: {online}\n💡 فعال: {enabled}\n📅 تاریخ‌انقضا: {expiry}\n\n🔼 آپلود↑: {up}\n🔽 دانلود↓: {down}\n🔄 کل: {used} / {total}\n\n📋🔄 تازه‌سازی شده در: {refreshed_at}",
        "en": "📧 Email: {email}\n🚨 Status: {enabled}\n🌐 Connection: {online}\n💡 Active: {enabled}\n📅 Expiry: {expiry}\n\n🔼 Upload↑: {up}\n🔽 Download↓: {down}\n🔄 Total: {used} / {total}\n\n📋🔄 Refreshed at: {refreshed_at}",
    },

    "bind_usage": {
        "fa": "فرمت:\n/bind <panel_id> <telegram_user_id> <client_email> [service_name]\nیا:\n/bind <telegram_user_id> <client_email> [service_name] (با پنل پیش‌فرض)",
        "en": "Format:\n/bind <panel_id> <telegram_user_id> <client_email> [service_name]\nor:\n/bind <telegram_user_id> <client_email> [service_name] (with default panel)",
    },

    "admin_default_not_selected_list_users": {
        "fa": "پنل پیش‌فرض انتخاب نشده است.\nبرای مشاهده کاربران، پنل را انتخاب کنید:",
        "en": "Default panel is not selected.\nChoose a panel to view users:",
    },
    "admin_default_not_selected_online": {
        "fa": "پنل پیش‌فرض انتخاب نشده است.\nبرای مشاهده کاربران آنلاین، پنل را انتخاب کنید:",
        "en": "Default panel is not selected.\nChoose a panel to view online users:",
    },
    "admin_default_not_selected_search": {
        "fa": "پنل پیش‌فرض انتخاب نشده است.\nبرای جستجوی کاربر، پنل را انتخاب کنید:",
        "en": "Default panel is not selected.\nChoose a panel to search users:",
    },
    "admin_default_not_selected_disabled": {
        "fa": "پنل پیش‌فرض انتخاب نشده است.\nبرای مشاهده کاربران غیرفعال، پنل را انتخاب کنید:",
        "en": "Default panel is not selected.\nChoose a panel to view disabled users:",
    },
    "admin_default_not_selected_last_online": {
        "fa": "پنل پیش‌فرض انتخاب نشده است.\nبرای مشاهده آخرین آنلاین، پنل را انتخاب کنید:",
        "en": "Default panel is not selected.\nChoose a panel to view last-online users:",
    },
    "admin_panel_and_pick_inbound": {"fa": "پنل: {name}\nیکی از اینباندها را انتخاب کنید:", "en": "Panel: {name}\nSelect an inbound:"},
    "admin_no_inbound_for_panel": {"fa": "هیچ اینباندی برای این پنل ثبت نشده است.", "en": "No inbound is configured for this panel."},
    "admin_fetching_inbounds": {"fa": "در حال دریافت لیست اینباندها...", "en": "Fetching inbounds..."},
    "admin_fetching_inbounds_alt": {"fa": "در حال دریافت لیست ورودی‌ها...", "en": "Fetching inbounds list..."},
    "admin_fetching_online": {"fa": "در حال دریافت کاربران آنلاین...", "en": "Fetching online users..."},
    "admin_no_online": {"fa": "پنل: {name}\n\nکاربر آنلاینی پیدا نشد.", "en": "Panel: {name}\n\nNo online users found."},
    "admin_online_header": {"fa": "پنل: {name}\nتعداد کاربران آنلاین: {count}\n\nروی کاربر کلیک کنید:", "en": "Panel: {name}\nOnline users: {count}\n\nTap a user:"},
    "admin_inbound_clients_empty": {"fa": "پنل: {panel}\nاینباند: {inbound}\n\nکاربری برای این اینباند ثبت نشده است.", "en": "Panel: {panel}\nInbound: {inbound}\n\nNo clients for this inbound."},
    "admin_inbound_clients_header": {"fa": "پنل: {panel}\nاینباند: {inbound}\nتعداد کاربران: {count}", "en": "Panel: {panel}\nInbound: {inbound}\nClients: {count}"},
    "admin_reset_done": {"fa": "ترافیک ریست شد.", "en": "Traffic has been reset."},
    "admin_traffic_limit_applied": {"fa": "محدودیت ترافیک اعمال شد.", "en": "Traffic limit applied."},
    "admin_expiry_updated": {"fa": "تاریخ انقضا بروزرسانی شد.", "en": "Expiry date updated."},
    "admin_ip_limit_updated": {"fa": "محدودیت IP بروزرسانی شد.", "en": "IP limit updated."},
    "admin_enable_on": {"fa": "فعال شد.", "en": "Enabled."},
    "admin_enable_off": {"fa": "غیرفعال شد.", "en": "Disabled."},
    "admin_enter_traffic_gb": {"fa": "حجم ترافیک را به گیگابایت وارد کنید (مثال: 25 یا 0.5):", "en": "Enter traffic in GB (example: 25 or 0.5):"},
    "admin_enter_days": {"fa": "تعداد روز سفارشی را وارد کنید:", "en": "Enter custom days:"},
    "admin_enter_ip_limit": {"fa": "تعداد IP سفارشی را وارد کنید:", "en": "Enter custom IP limit:"},
    "admin_enter_tg": {"fa": "آیدی تلگرام (عددی یا یوزرنیم) را وارد کنید. برای پاک‌کردن: -", "en": "Enter Telegram ID (numeric or username). Send - to clear."},
    "admin_invalid_gb": {"fa": "عدد معتبر گیگابایت وارد کنید.", "en": "Enter a valid GB number."},
    "admin_invalid_days": {"fa": "عدد معتبر روز وارد کنید.", "en": "Enter a valid day count."},
    "admin_invalid_ip": {"fa": "عدد معتبر محدودیت IP وارد کنید.", "en": "Enter a valid IP limit."},
    "admin_update_traffic_error": {"fa": "خطا در بروزرسانی ترافیک", "en": "Failed to update traffic"},
    "admin_update_expiry_error": {"fa": "خطا در بروزرسانی تاریخ انقضا", "en": "Failed to update expiry"},
    "admin_update_ip_error": {"fa": "خطا در بروزرسانی محدودیت IP", "en": "Failed to update IP limit"},
    "admin_update_tg_error": {"fa": "خطا در تنظیم کاربر تلگرام", "en": "Failed to set Telegram user"},
    "admin_done": {"fa": "✅ انجام شد.", "en": "✅ Done."},
    "admin_back_to_detail": {"fa": "🔄 بازگشت به جزئیات", "en": "🔄 Back to detail"},
    "admin_tgid_saved_user_not_found": {
        "fa": "✅ tgId روی پنل ذخیره شد، اما کاربر با این یوزرنیم در دیتابیس ربات پیدا نشد.\nکاربر باید حداقل یک‌بار /start بزند یا آیدی عددی تلگرام وارد شود.",
        "en": "✅ tgId was saved on panel, but this username was not found in bot database.\nUser should run /start at least once or use numeric Telegram ID.",
    },
    "admin_tgid_saved_bind_failed": {
        "fa": "tgId ذخیره شد، ولی bind داخلی انجام نشد:\n{error}\nمی‌توانید با /bind دستی متصل کنید.",
        "en": "tgId saved, but internal bind failed:\n{error}\nYou can bind manually with /bind.",
    },
    "admin_tg_done": {"fa": "✅ تنظیم کاربر تلگرام انجام شد.", "en": "✅ Telegram user updated."},
    "admin_ip_log_for": {"fa": "📋 لاگ IP برای {email}:\n{ips}", "en": "📋 IP log for {email}:\n{ips}"},
    "admin_ip_log_cleared": {"fa": "لاگ IP پاک شد.", "en": "IP log cleared."},
    "admin_back_to_online_list": {"fa": "⬅️ بازگشت به لیست آنلاین", "en": "⬅️ Back to online list"},
    "admin_back_to_users_list": {"fa": "⬅️ بازگشت به لیست کاربران", "en": "⬅️ Back to users list"},
    "admin_back_to_disabled_list": {"fa": "⬅️ بازگشت به لیست غیرفعال‌ها", "en": "⬅️ Back to disabled list"},
    "admin_back_to_low_traffic_list": {"fa": "⬅️ بازگشت به لیست کم‌حجم‌ها", "en": "⬅️ Back to low traffic list"},
    "admin_default_not_selected_low_traffic": {
        "fa": "برای نمایش کاربران کم‌حجم، پنل را انتخاب کنید:",
        "en": "Select a panel to show low traffic users:",
    },
    "admin_low_traffic_empty": {
        "fa": "پنل: {panel}\n\nکاربری با حجم باقی‌مانده کمتر از {threshold_mb} مگابایت پیدا نشد.",
        "en": "Panel: {panel}\n\nNo user below {threshold_mb} MB remaining was found.",
    },
    "admin_low_traffic_header": {
        "fa": "پنل: {panel}\nکاربران با حجم کمتر از {threshold_mb} مگابایت\nتعداد: {count}\n\nروی کاربر کلیک کنید:",
        "en": "Panel: {panel}\nUsers below {threshold_mb} MB remaining\nCount: {count}\n\nTap a user:",
    },
    "admin_page_prev": {"fa": "◀️ قبلی", "en": "◀️ Prev"},
    "admin_page_next": {"fa": "بعدی ▶️", "en": "Next ▶️"},
    "admin_search_prompt": {
        "fa": "بخشی از ایمیل کاربر را وارد کنید (حداقل 2 کاراکتر):",
        "en": "Enter part of user email (at least 2 characters):",
    },
    "admin_search_too_short": {
        "fa": "عبارت جستجو کوتاه است. حداقل 2 کاراکتر وارد کنید.",
        "en": "Search query is too short. Enter at least 2 characters.",
    },
    "admin_search_empty": {
        "fa": "پنل: {panel}\n\nنتیجه‌ای برای «{query}» پیدا نشد.",
        "en": "Panel: {panel}\n\nNo results found for '{query}'.",
    },
    "admin_search_result_header": {
        "fa": "پنل: {panel}\nجستجو: {query}\nتعداد نتیجه: {count}",
        "en": "Panel: {panel}\nSearch: {query}\nResults: {count}",
    },
    "admin_disabled_empty": {
        "fa": "پنل: {panel}\n\nکاربر غیرفعالی پیدا نشد.",
        "en": "Panel: {panel}\n\nNo disabled users found.",
    },
    "admin_disabled_header": {
        "fa": "پنل: {panel}\nکاربران غیرفعال: {count}",
        "en": "Panel: {panel}\nDisabled users: {count}",
    },
    "admin_last_online_empty": {
        "fa": "پنل: {panel}\n\nداده‌ای برای آخرین آنلاین موجود نیست.",
        "en": "Panel: {panel}\n\nNo last-online data available.",
    },
    "admin_last_online_header": {
        "fa": "پنل: {panel}\nلیست آخرین آنلاین: {count}",
        "en": "Panel: {panel}\nLast-online list: {count}",
    },

    "panel_add_enter_name": {"fa": "یک نام برای پنل وارد کنید:", "en": "Enter panel name:"},
    "panel_add_name_empty": {"fa": "نام پنل نمی‌تواند خالی باشد.", "en": "Panel name cannot be empty."},
    "panel_add_enter_login": {"fa": "لینک لاگین را وارد کنید:\nhttp://HOST:PORT/WEBBASEPATH/login/", "en": "Enter login URL:\nhttp://HOST:PORT/WEBBASEPATH/login/"},
    "panel_add_enter_user": {"fa": "یوزرنیم پنل را وارد کنید:", "en": "Enter panel username:"},
    "panel_add_enter_pass": {"fa": "پسورد پنل را وارد کنید:", "en": "Enter panel password:"},
    "panel_add_twofa_q": {"fa": "آیا twoFactor فعال است؟", "en": "Is twoFactor enabled?"},
    "panel_add_testing": {"fa": "در حال تست اتصال به پنل...", "en": "Testing panel connection..."},
    "panel_add_invalid_credentials": {"fa": "اتصال ناموفق بود: اطلاعات ورود اشتباه است.", "en": "Login failed: invalid credentials."},
    "panel_add_rate_limit": {"fa": "پنل مقصد محدودیت نرخ دارد. کمی بعد دوباره تلاش کنید.", "en": "Target panel is rate limited. Try again later."},
    "panel_add_validation": {"fa": "ورودی نامعتبر است:\n{error}", "en": "Invalid input:\n{error}"},
    "panel_add_xui_error": {"fa": "اتصال ناموفق بود:\n{error}", "en": "Connection failed:\n{error}"},
    "panel_add_unexpected": {"fa": "خطای غیرمنتظره:\n{error}", "en": "Unexpected error:\n{error}"},
    "panel_add_ok": {"fa": "✅ با موفقیت وارد شد و پنل ذخیره شد.", "en": "✅ Login successful and panel saved."},
    "panel_add_enter_twofa": {"fa": "کد twoFactorCode را وارد کنید:", "en": "Enter twoFactorCode:"},
    "panel_add_twofa_empty": {"fa": "کد twoFactorCode نمی‌تواند خالی باشد. یا گزینه «خیر» را انتخاب کنید.", "en": "twoFactorCode cannot be empty. Choose No if disabled."},
    "panel_default_set": {"fa": "پنل پیش‌فرض تنظیم شد.", "en": "Default panel set."},
    "panel_default_unset": {"fa": "پنل پیش‌فرض حذف شد.", "en": "Default panel unset."},
    "panel_deleted": {"fa": "✅ پنل حذف شد.", "en": "✅ Panel deleted."},
    "panel_already_deleted": {"fa": "این پنل قبلا حذف شده است.", "en": "This panel is already deleted."},
    "panel_delete_confirm": {"fa": "نام پنل: {name}\nوضعیت اتصال: {status}\n\nآیا از حذف مطمئن هستید؟", "en": "Panel: {name}\nConnection: {status}\n\nAre you sure to delete?"},
    "inbounds_select_panel": {"fa": "پنل پیش‌فرض انتخاب نشده است.\nبرای دریافت لیست ورودی‌ها، پنل را انتخاب کنید:", "en": "Default panel is not selected.\nSelect a panel to view inbounds:"},

    "admin_manage_admins_title": {
        "fa": "مدیریت ادمین‌های محدود:\n- افزودن دسترسی جدید\n- مشاهده و حذف دسترسی‌ها",
        "en": "Delegated admin management:\n- Add new access\n- View and revoke accesses",
    },
    "admin_add_delegated": {"fa": "➕ افزودن ادمین محدود", "en": "➕ Add delegated admin"},
    "admin_list_delegated": {"fa": "📋 لیست ادمین‌های محدود", "en": "📋 Delegated admins list"},
    "admin_delegated_details": {"fa": "📋 جزئیات نمایندگی", "en": "📋 Delegated Details"},
    "admin_delegated_update": {"fa": "بروزرسانی ♻️", "en": "Refresh ♻️"},
    "admin_delegated_delete": {"fa": "حذف نماینده 🗑️", "en": "Delete Delegate 🗑️"},
    "admin_delegated_access": {"fa": "سطح دسترسی 👥", "en": "Access Level 👥"},
    "admin_delegated_prefix": {"fa": "پیشوند نام کاربری 🏷", "en": "Username Prefix 🏷"},
    "admin_delegated_max_users": {"fa": "محدودیت کاربران 👥", "en": "User Limit 👥"},
    "admin_delegated_expiry": {"fa": "تاریخ انقضا ⏳", "en": "Expiry Date ⏳"},
    "admin_delegated_status": {"fa": "وضعیت نماینده ⚙️", "en": "Delegate Status ⚙️"},
    "admin_delegated_price_gb": {"fa": "قیمت هر گیگ حجم 🧃", "en": "Per GB Price 🧃"},
    "admin_delegated_price_day": {"fa": "قیمت هر روز زمان 💰", "en": "Per Day Price 💰"},
    "admin_delegated_min_traffic": {"fa": "حداقل خرید حجم 📉", "en": "Min Traffic 📉"},
    "admin_delegated_max_traffic": {"fa": "حداکثر خرید حجم 📈", "en": "Max Traffic 📈"},
    "admin_delegated_min_days": {"fa": "حداقل خرید زمان 🕘", "en": "Min Days 🕘"},
    "admin_delegated_max_days": {"fa": "حداکثر خرید زمان ⏱", "en": "Max Days ⏱"},
    "admin_delegated_wallet": {"fa": "کیف پول 👛", "en": "Wallet 👛"},
    "admin_delegated_report": {"fa": "گزارش 📊", "en": "Report 📊"},
    "admin_delegated_charge_basis": {"fa": "نوع فروش 📦", "en": "Charge Basis 📦"},
    "admin_delegated_charge_allocated": {"fa": "بر اساس حجم تخصیصی", "en": "Allocated Traffic"},
    "admin_delegated_charge_consumed": {"fa": "بر اساس حجم مصرفی", "en": "Consumed Traffic"},
    "admin_delegated_buy_without_balance_yes": {"fa": "خرید بدون موجودی . بله", "en": "Buy without balance . Yes"},
    "admin_delegated_buy_without_balance_no": {"fa": "خرید بدون موجودی . خیر", "en": "Buy without balance . No"},
    "admin_delegated_scope": {"fa": "سطح دسترسی", "en": "Access Scope"},
    "admin_delegated_scope_full": {"fa": "کامل", "en": "Full"},
    "admin_delegated_scope_limited": {"fa": "محدود", "en": "Limited"},
    "admin_delegated_status_active": {"fa": "فعال", "en": "Active"},
    "admin_delegated_status_inactive": {"fa": "غیرفعال", "en": "Inactive"},
    "admin_delegated_unlimited": {"fa": "نامحدود", "en": "Unlimited"},
    "admin_delegated_not_found": {"fa": "نماینده پیدا نشد.", "en": "Delegated admin not found."},
    "admin_delegated_enter_prefix": {"fa": "پیشوند نام کاربری را وارد کنید. برای حذف، - بفرستید.", "en": "Enter username prefix. Send - to clear."},
    "admin_delegated_enter_max_users": {"fa": "حداکثر کاربر قابل ساخت را وارد کنید. 0 یعنی نامحدود.", "en": "Enter max clients. 0 means unlimited."},
    "admin_delegated_enter_min_traffic": {"fa": "حداقل خرید حجم را به گیگ وارد کنید. عدد اعشاری و 0 مجاز است.", "en": "Enter minimum traffic in GB. Decimal values and 0 are allowed."},
    "admin_delegated_enter_max_traffic": {"fa": "حداکثر خرید حجم را به گیگ وارد کنید. عدد اعشاری مجاز است و 0 یعنی نامحدود.", "en": "Enter maximum traffic in GB. Decimal values are allowed; 0 means unlimited."},
    "admin_delegated_enter_min_days": {"fa": "حداقل خرید زمان را به روز وارد کنید.", "en": "Enter minimum days."},
    "admin_delegated_enter_max_days": {"fa": "حداکثر خرید زمان را به روز وارد کنید. 0 یعنی نامحدود.", "en": "Enter maximum days. 0 means unlimited."},
    "admin_delegated_enter_expiry": {"fa": "تعداد روز تا انقضای نماینده را وارد کنید. 0 یعنی نامحدود.", "en": "Enter days until delegate expiry. 0 means unlimited."},
    "admin_delegated_profile_saved": {"fa": "تنظیمات نمایندگی ذخیره شد.", "en": "Delegated profile saved."},
    "admin_delegated_report_text": {
        "fa": "گزارش نمایندگی\n\nنماینده: {title}\nموجودی: {balance} {currency}\nهر گیگ: {price_gb} {currency}\nهر روز: {price_day} {currency}\nکل فروش: {sales} {currency}\nتعداد تراکنش‌ها: {transactions}\nکاربران ساخته‌شده: {owned_clients}{extra_lines}\n\nآخرین تراکنش‌ها:\n{wallet_lines}\n\nآخرین فعالیت‌ها:\n{activity_lines}",
        "en": "Delegated report\n\nDelegate: {title}\nBalance: {balance} {currency}\nPer GB: {price_gb} {currency}\nPer day: {price_day} {currency}\nSales: {sales} {currency}\nTransactions: {transactions}\nOwned clients: {owned_clients}{extra_lines}\n\nRecent wallet transactions:\n{wallet_lines}\n\nRecent activities:\n{activity_lines}",
    },
    "admin_delegated_details_text": {
        "fa": "📋 جزئیات نمایندگی\n\nنام کاربری: {title}\nپیشوند نام کاربری: {prefix}\n\nحداکثر کاربران قابل ساخت: {max_users}\nحداقل/حداکثر خرید حجم: {min_traffic}GB / {max_traffic}GB\nحداقل/حداکثر خرید زمان: {min_days} روز / {max_days} روز\n\nقیمت هر روز زمان: {price_day} {currency}\nقیمت هر گیگ حجم: {price_gb} {currency}\nنوع فروش: {charge_basis}{balance_line}\nفروش کل: {total_sales} {currency}{extra_lines}\n\nتاریخ انقضای نماینده: {expires_at}\nوضعیت نماینده: {status}\nکاربران ساخته‌شده: {owned_clients}",
        "en": "Delegated details\n\nUsername: {title}\nUsername prefix: {prefix}\n\nMax clients: {max_users}\nMin/Max traffic: {min_traffic}GB / {max_traffic}GB\nMin/Max days: {min_days} days / {max_days} days\n\nDay price: {price_day} {currency}\nGB price: {price_gb} {currency}\nCharge basis: {charge_basis}{balance_line}\nTotal sales: {total_sales} {currency}{extra_lines}\n\nExpiry: {expires_at}\nDelegate status: {status}\nOwned clients: {owned_clients}",
    },
    "admin_delegated_balance_line": {
        "fa": "\nموجودی: {balance} {currency}",
        "en": "\nBalance: {balance} {currency}",
    },
    "admin_delegated_consumed_lines": {
        "fa": "\nحجم مصرف‌شده واقعی: {consumed_gb} گیگ",
        "en": "\nReal consumed traffic: {consumed_gb} GB",
    },
    "admin_delegated_limit_error_max_clients": {"fa": "سقف تعداد کاربران این نماینده پر شده است.", "en": "Delegate max clients limit reached."},
    "admin_delegated_limit_error_traffic_min": {"fa": "مقدار حجم کمتر از حداقل مجاز نماینده است.", "en": "Traffic is below delegate minimum."},
    "admin_delegated_limit_error_traffic_max": {"fa": "مقدار حجم بیشتر از حداکثر مجاز نماینده است.", "en": "Traffic is above delegate maximum."},
    "admin_delegated_limit_error_days_min": {"fa": "مقدار زمان کمتر از حداقل مجاز نماینده است.", "en": "Duration is below delegate minimum."},
    "admin_delegated_limit_error_days_max": {"fa": "مقدار زمان بیشتر از حداکثر مجاز نماینده است.", "en": "Duration is above delegate maximum."},
    "admin_delegated_inactive": {"fa": "نماینده غیرفعال است.", "en": "Delegated admin is inactive."},
    "admin_delegated_expired": {"fa": "تاریخ نماینده به پایان رسیده است.", "en": "Delegated admin has expired."},
    "admin_enter_delegated_target": {
        "fa": "آیدی عددی یا یوزرنیم ادمین محدود را وارد کنید:",
        "en": "Enter delegated admin numeric ID or username:",
    },
    "admin_enter_delegated_title": {
        "fa": "یک نام نمایشی برای این ادمین وارد کنید. اگر نمی‌خواهید، `-` بفرستید:",
        "en": "Enter a display title for this admin. Send - to skip:",
    },
    "admin_pick_inbound_for_delegated": {
        "fa": "اینباندی که این ادمین به آن دسترسی دارد را انتخاب کنید:",
        "en": "Select inbound that this admin can access:",
    },
    "admin_delegated_saved": {
        "fa": "✅ دسترسی ادمین محدود ذخیره شد.",
        "en": "✅ Delegated admin access saved.",
    },
    "admin_delegated_pick_one": {
        "fa": "حداقل یک اینباند را انتخاب کنید.",
        "en": "Select at least one inbound.",
    },
    "admin_delegated_empty": {
        "fa": "هیچ ادمین محدودی ثبت نشده است.",
        "en": "No delegated admin access is registered.",
    },
    "admin_delegated_list_header": {
        "fa": "لیست دسترسی‌های ادمین محدود:",
        "en": "Delegated admin accesses:",
    },
    "admin_delegated_removed": {
        "fa": "✅ دسترسی حذف شد.",
        "en": "✅ Access removed.",
    },
    "admin_delegated_target_unknown": {
        "fa": "این یوزرنیم در دیتابیس ربات پیدا نشد. کاربر باید حداقل یک‌بار /start بزند یا آیدی عددی وارد شود.",
        "en": "Username was not found in bot database. User should run /start once or use numeric ID.",
    },
    "admin_bulk_actions": {"fa": "عملیات گروهی", "en": "Bulk Actions"},
    "admin_bulk_add_traffic": {"fa": "افزودن حجم به تمامی کاربران", "en": "Add traffic to all users"},
    "admin_bulk_add_days": {"fa": "افزودن روز به تمامی کاربران", "en": "Add days to all users"},
    "admin_back_to_users": {"fa": "بازگشت به لیست کاربران", "en": "Back to users list"},
    "admin_bulk_menu_text": {
        "fa": "عملیات گروهی برای کل پنل را انتخاب کنید:",
        "en": "Choose a bulk action for the whole panel:",
    },
    "admin_bulk_pick_panel": {
        "fa": "برای عملیات گروهی، پنل را انتخاب کنید:",
        "en": "Select a panel for bulk operations:",
    },
    "admin_bulk_enter_traffic": {
        "fa": "مقدار حجمی که باید به همه کاربران این پنل اضافه شود را به گیگابایت وارد کنید (مثال: 0.5 یا 2.6):",
        "en": "Enter traffic in GB to add to all clients in this panel (example: 0.5 or 2.6):",
    },
    "admin_bulk_enter_days": {
        "fa": "تعداد روزی که باید به همه کاربران این پنل اضافه شود را وارد کنید:",
        "en": "Enter days to add to all clients in this panel:",
    },
    "admin_bulk_started": {
        "fa": "در حال اعمال عملیات گروهی...",
        "en": "Applying bulk action...",
    },
    "admin_bulk_done": {
        "fa": "عملیات گروهی انجام شد.\nموفق: {success}\nناموفق: {failed}",
        "en": "Bulk action completed.\nSuccess: {success}\nFailed: {failed}",
    },
    "admin_bulk_empty": {
        "fa": "هیچ کاربری در این پنل برای اعمال عملیات پیدا نشد.",
        "en": "No clients were found in this panel for bulk action.",
    },
    "admin_create_user_pick_inbound": {
        "fa": "برای ساخت کاربر، اینباند مقصد را انتخاب کنید:",
        "en": "Select target inbound to create client:",
    },
    "admin_create_user_no_access": {
        "fa": "هیچ اینباند مجازی برای شما ثبت نشده است.",
        "en": "No allowed inbound is registered for you.",
    },
    "admin_create_enter_email": {
        "fa": "نام/ایمیل کاربر را وارد کنید:",
        "en": "Enter client name/email:",
    },
    "admin_create_enter_traffic": {
        "fa": "حجم کاربر را به گیگابایت وارد کنید (مثال: 0.5 یا 2.6):",
        "en": "Enter traffic in GB (example: 0.5 or 2.6):",
    },
    "admin_create_enter_days": {
        "fa": "تعداد روز کاربر را وارد کنید:",
        "en": "Enter number of days:",
    },
    "admin_create_set_tg_title": {
        "fa": "تنظیم ایدی تلگرام",
        "en": "Set Telegram ID",
    },
    "admin_create_set_tg_text": {
        "fa": "آیا می‌خواهید برای این کاربر آیدی تلگرام تنظیم شود؟",
        "en": "Do you want to set a Telegram ID for this client?",
    },
    "admin_create_enter_tg": {
        "fa": "آیدی تلگرام را وارد کنید. هم عددی و هم با @ قابل قبول است:",
        "en": "Enter Telegram ID. Both numeric IDs and @usernames are accepted:",
    },
    "admin_tgid_invalid": {
        "fa": "آیدی تلگرام باید عددی باشد یا با @ شروع شود.",
        "en": "Telegram ID must be numeric or start with @.",
    },
    "admin_create_success": {
        "fa": "✅ کاربر ساخته شد.\n📧 ایمیل: {email}\n🔑 UUID: <code>{uuid}</code>\n🔗 ساب: <code>{sub_url}</code>\n\nلینک VLESS:\n<code>{vless_uri}</code>",
        "en": "✅ Client created.\n📧 Email: {email}\n🔑 UUID: <code>{uuid}</code>\n🔗 Sub: <code>{sub_url}</code>\n\nVLESS link:\n<code>{vless_uri}</code>",
    },
    "admin_create_preparing": {
        "fa": "در حال ساخت کاربر و تولید کانفیگ...",
        "en": "Creating client and generating config...",
    },
    "admin_edit_config_prompt": {
        "fa": "لطفا کانفیگ VLESS یا بخشی از نام کاربر را ارسال کنید:",
        "en": "Please send the VLESS config or part of the client name:",
    },
    "admin_edit_config_resolved": {
        "fa": "کاربر پیدا شد:\nپنل: {panel}\nاینباند: {inbound}\nایمیل: {email}",
        "en": "Client resolved:\nPanel: {panel}\nInbound: {inbound}\nEmail: {email}",
    },
    "admin_edit_config_error": {
        "fa": "در پردازش کانفیگ خطا رخ داد:\n{error}",
        "en": "Failed to process config:\n{error}",
    },
    "admin_edit_search_pick_panel": {
        "fa": "برای جستجو و ویرایش کانفیگ، پنل را انتخاب کنید:",
        "en": "Choose a panel to search and edit config:",
    },
    "admin_edit_search_result_header": {
        "fa": "پنل: {panel}\nجستجو برای ویرایش: {query}\nتعداد نتیجه: {count}",
        "en": "Panel: {panel}\nEdit search: {query}\nResults: {count}",
    },
    "admin_edit_add_traffic": {"fa": "➕ افزودن حجم", "en": "➕ Add traffic"},
    "admin_edit_add_days": {"fa": "➕ افزودن روز", "en": "➕ Add days"},
    "admin_edit_delete_client": {"fa": "🗑 حذف کاربر", "en": "🗑 Delete client"},
    "admin_edit_show_detail": {"fa": "🔎 نمایش جزئیات", "en": "🔎 Show detail"},
    "admin_edit_enter_add_traffic": {
        "fa": "مقدار حجمی که باید اضافه شود را به گیگابایت وارد کنید (مثال: 0.5 یا 2.6):",
        "en": "Enter GB amount to add (example: 0.5 or 2.6):",
    },
    "admin_edit_enter_add_days": {
        "fa": "تعداد روزی که باید اضافه شود را وارد کنید:",
        "en": "Enter number of days to add:",
    },
    "admin_edit_deleted": {
        "fa": "✅ کاربر حذف شد.",
        "en": "✅ Client deleted.",
    },
    "admin_edit_traffic_added": {
        "fa": "✅ حجم اضافه شد.",
        "en": "✅ Traffic added.",
    },
    "admin_edit_days_added": {
        "fa": "✅ روز اضافه شد.",
        "en": "✅ Days added.",
    },
    "admin_edit_rotate_confirm": {
        "fa": "با این عملیات کانفیگ فعلی کاربر قطع می‌شود و کانفیگ جدید ساخته می‌شود. مطمئن هستید؟",
        "en": "This will invalidate the current config and generate a new one. Are you sure?",
    },
    "admin_edit_rotate_done": {
        "fa": "کانفیگ جدید کاربر آماده شد.",
        "en": "The client's new config is ready.",
    },
    "admin_activity_notify_template": {
        "fa": "اطلاع مدیر:\nادمین: {actor}\nعملیات: {action}\nکاربر: {user}\nپنل: {panel}\nاینباند: {inbound}{details}",
        "en": "Manager notice:\nAdmin: {actor}\nOperation: {action}\nUser: {user}\nPanel: {panel}\nInbound: {inbound}{details}",
    },
    "admin_activity_action_create_client": {"fa": "ساخت کاربر جدید", "en": "Create client"},
    "admin_activity_action_toggle_client": {"fa": "تغییر وضعیت کاربر", "en": "Toggle client status"},
    "admin_activity_action_rotate_client": {"fa": "چرخش کانفیگ کاربر", "en": "Rotate client config"},
    "admin_activity_action_set_tg_id": {"fa": "تغییر tgId کاربر", "en": "Set client tgId"},
    "admin_activity_action_add_traffic": {"fa": "افزایش حجم کاربر", "en": "Increase client traffic"},
    "admin_activity_action_add_days": {"fa": "افزایش روز کاربر", "en": "Extend client expiry"},
    "admin_activity_action_delete_client": {"fa": "حذف کاربر", "en": "Delete client"},
    "admin_activity_action_set_total_gb": {"fa": "تنظیم حجم کاربر", "en": "Set client traffic"},
    "admin_activity_action_set_expiry_days": {"fa": "تنظیم تاریخ انقضا", "en": "Set client expiry"},
    "admin_activity_action_reset_traffic": {"fa": "ریست ترافیک کاربر", "en": "Reset client traffic"},
    "admin_activity_action_set_ip_limit": {"fa": "تغییر محدودیت IP کاربر", "en": "Set client IP limit"},
    "admin_activity_status_active": {"fa": "فعال", "en": "active"},
    "admin_activity_status_inactive": {"fa": "غیرفعال", "en": "inactive"},
    "admin_activity_detail_amount_gb": {"fa": "مقدار: {value} گیگ", "en": "Amount: {value} GB"},
    "admin_activity_detail_amount_days": {"fa": "مقدار: {value} روز", "en": "Amount: {value} days"},
    "admin_activity_detail_traffic_change": {"fa": "حجم از {before} به {after} افزایش یافت", "en": "Traffic increased from {before} to {after}"},
    "admin_activity_detail_expiry_change": {"fa": "تاریخ از {before} به {after} تغییر کرد", "en": "Expiry changed from {before} to {after}"},
    "admin_activity_detail_new_value": {"fa": "مقدار جدید: {value}", "en": "New value: {value}"},
    "admin_activity_detail_new_status": {"fa": "وضعیت جدید: {value}", "en": "New status: {value}"},
    "admin_invalid_positive_number": {
        "fa": "عدد معتبر و بزرگ‌تر از صفر وارد کنید.",
        "en": "Enter a valid positive number.",
    },
    "admin_delegated_min_create_traffic": {
        "fa": "برای ادمین فرعی حداقل حجم ساخت کاربر {minimum} گیگابایت است.",
        "en": "For delegated admins, the minimum traffic for client creation is {minimum} GB.",
    },
    "admin_delegated_min_create_days": {
        "fa": "برای ادمین فرعی حداقل زمان ساخت کاربر {minimum} روز است.",
        "en": "For delegated admins, the minimum client duration is {minimum} days.",
    },
    "admin_cleanup_hours_prompt": {
        "fa": "حذف خودکار کاربران اتمام‌حجم یا منقضی بعد از چند ساعت از آخرین آنلاین انجام شود؟\nپیش‌فرض فعلی: {hours} ساعت",
        "en": "Delete depleted or expired users after how many hours since last online?\nCurrent default: {hours} hours",
    },
    "admin_cleanup_hours_saved": {
        "fa": "تنظیم حذف خودکار روی {hours} ساعت ذخیره شد.",
        "en": "Automatic cleanup is now set to {hours} hours.",
    },
    "admin_auto_cleanup_deleted_notification": {
        "fa": "حذف خودکار کاربر\nکاربر {email} به علت عدم تمدید و گذشت {hours} ساعت از آخرین آنلاین، حذف شد.\nپنل: {panel}\nاینباند: {inbound}",
        "en": "Automatic user cleanup\nUser {email} was deleted due to non-renewal after {hours} hours since last online.\nPanel: {panel}\nInbound: {inbound}",
    },
    "config_full_caption": {
        "fa": "QR کانفیگ\n\nنام کانفیگ: <code>{config_name}</code>\nحجم: <code>{total}</code>\nانقضا: <code>{expiry}</code>\n\nکانفیگ VLESS:\n<code>{vless_uri}</code>\n\nلینک ساب:\n<code>{sub_url}</code>",
        "en": "Config QR\n\nConfig name: <code>{config_name}</code>\nTraffic: <code>{total}</code>\nExpiry: <code>{expiry}</code>\n\nVLESS config:\n<code>{vless_uri}</code>\n\nSubscription link:\n<code>{sub_url}</code>",
    },
}


def normalize_lang(value: str | None) -> Lang:
    if value is None:
        value = _CURRENT_LANG.get()
    if value in SUPPORTED_LANGS:
        return value
    return DEFAULT_LANG


def set_current_lang(lang: str | None) -> None:
    _CURRENT_LANG.set(normalize_lang(lang))


def get_current_lang() -> Lang:
    return normalize_lang(_CURRENT_LANG.get())


def t(key: str, lang: str | None, **kwargs: object) -> str:
    lang_norm = normalize_lang(lang)
    row = TEXTS.get(key)
    if row is None:
        return key
    text = row[lang_norm]
    if kwargs:
        return text.format(**kwargs)
    return text


def btn(key: str, lang: str | None) -> str:
    return t(key, lang)


def button_variants(key: str) -> tuple[str, str]:
    return (t(key, "fa"), t(key, "en"))
