# ربات تلگرام مدیریت 3x-ui

این پروژه یک ربات تلگرام برای مدیریت پنل‌های `3x-ui / x-ui` است. ربات هم برای مدیر اصلی و هم برای ادمین فرعی جریان‌های جدا دارد و امکاناتی مثل ساخت کاربر، ویرایش کانفیگ، هشدار اتمام سرویس، مدیریت پنل‌ها و اتصال سرویس به کاربر تلگرام را پوشش می‌دهد.

## قابلیت‌ها

- مدیریت پنل‌های `3x-ui`
- تنظیم و حذف پنل پیش‌فرض
- لیست اینباندها، کاربران، کاربران آنلاین، غیرفعال و آخرین آنلاین
- ساخت کاربر جدید با ارسال QR، لینک کانفیگ و لینک ساب
- ویرایش کانفیگ، افزایش حجم، افزایش روز، تغییر `tgId` و حذف کاربر
- عملیات گروهی روی کل پنل
- هشدار اتمام حجم، نزدیک‌شدن به آستانه‌ها و پایان سرویس
- ادمین فرعی با دسترسی محدود به اینباندها/کاربرهای خودش
- چندزبانه (`فارسی / English`)
- `SQLite` + migration
- سرویس `systemd`

## نصب سریع

```bash
bash <(curl -Ls https://raw.githubusercontent.com/smaghili/tgbotxui/main/install.sh)
```

یا به‌صورت صریح با mode نصب:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/smaghili/tgbotxui/main/install.sh) install
```

اگر بخواهی می‌توانی به روش clone هم نصب کنی:

```bash
git clone https://github.com/smaghili/tgbotxui.git
cd tgbotxui
sudo bash install.sh install
```

## آپدیت سریع

برای آپدیت سریع هم همان الگو را می‌توانی اجرا کنی:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/smaghili/tgbotxui/main/install.sh) update
```

اگر سورس را محلی داری، داخل همان روت پروژه این دستور را اجرا کن:

```bash
sudo bash install.sh update
```

رفتار آپدیت:

- فایل‌های پروژه جایگزین می‌شوند
- فایل `.env` حفظ می‌شود
- دیتابیس و پوشه `data/` حفظ می‌شوند
- اگر کلید جدیدی به `.env.example` اضافه شده باشد، به `.env` فعلی اضافه می‌شود
- از وضعیت قبلی در `backups/` بکاپ گرفته می‌شود

## نصب از روی سورس

اگر ریپو را clone کرده‌ای، از داخل روت پروژه:

```bash
sudo bash install.sh install
```

برای آپدیت از روی سورس محلی:

```bash
sudo bash install.sh update
```

اگر mode ندهی، اسکریپت به صورت تعاملی بین `install` و `update` از تو سوال می‌پرسد:

```bash
sudo bash install.sh
```

## مسیرها و مقادیر پیش‌فرض نصب

- مسیر نصب: `/opt/tgbot`
- نام سرویس: `tgbot`
- کاربر سرویس: `tgbot`
- فایل سرویس: `/etc/systemd/system/tgbot.service`

در صورت نیاز می‌توانی قبل از اجرا override بدهی:

```bash
sudo APP_DIR=/opt/mybot SERVICE_NAME=mybot BOT_USER=mybot bash install.sh install
```

## متغیرهای مهم `.env`

فایل نمونه: [.env.example](./.env.example)

مهم‌ترین کلیدها:

- `BOT_TOKEN`
- `ADMIN_IDS`
- `ENCRYPTION_KEY`
- `DATABASE_PATH`
- `TIMEZONE`
- `SYNC_INTERVAL_SECONDS`
- `DEPLETED_CLIENT_DELETE_AFTER_HOURS`
- `SUB_URL_STRIP_PORT_RULES`
- `SUB_URL_BASE_OVERRIDES`

محدودیت ساخت هر ادمین فرعی از پروفایل همان ادمین در بخش مدیریت ادمین‌ها خوانده می‌شود.

## اجرای محلی توسعه

### لینوکس

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

### ویندوز

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

## دستورات مهم ربات

- `/start`
- `/status`
- `/help`
- `/cancel`
- `/bind ...`
- `/sync_all`

## منوی مدیریت

### مدیر اصلی

- افزودن پنل
- لیست پنل‌ها
- لیست اینباندها
- لیست کاربران
- کاربران آنلاین
- آخرین آنلاین
- کاربران غیرفعال
- ساخت کاربر
- ویرایش کانفیگ
- مدیریت ادمین‌ها
- تنظیم حذف خودکار
- عملیات گروهی

### ادمین فرعی

- لیست کاربران قابل‌دسترسی
- لیست اینباندهای قابل‌دسترسی
- کاربران آنلاین/غیرفعال/آخرین آنلاین در محدوده خودش
- ساخت کاربر فقط روی اینباندهای مجاز
- ویرایش فقط روی کاربرهای محدوده خودش
- بدون دسترسی به مدیریت اصلی پنل‌ها و مدیریت ادمین‌ها

## مانیتورینگ

- `GET /healthz`
- `GET /metrics`

## ساختار پروژه

- `main.py`: نقطه شروع برنامه
- `bot/handlers`: هندلرهای تلگرام و جریان‌های UI
- `bot/services`: منطق اصلی پروژه و ارتباط با پنل
- `bot/middlewares`: middlewareها
- `bot/migrations`: migrationهای دیتابیس
- `bot/i18n.py`: متن‌ها و ترجمه‌ها
- `install.sh`: نصب و آپدیت پروژه

## تست

```bash
python -m pytest
```

یا فقط تست‌های اصلی:

```bash
python -m pytest tests/test_admin_keyboards.py tests/test_delegated_visibility.py tests/test_usage_notifications.py
```

## نکات مهم

- در حالت `update`، کتابخانه‌ها از صفر پاک نمی‌شوند و `.venv` در صورت سالم بودن reuse می‌شود
- سرویس بعد از نصب/آپدیت به صورت خودکار restart می‌شود
- migrationها در startup برنامه اعمال می‌شوند
- اگر تلگرام روی سرور فیلتر باشد، می‌توانی `TELEGRAM_PROXIES` را در `.env` تنظیم کنی

## ریپو

- GitHub: <https://github.com/smaghili/tgbotxui>
