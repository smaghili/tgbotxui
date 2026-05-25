# TgBotXUI

ربات تلگرام برای مدیریت پنل‌های `3x-ui / x-ui`.

## Features

- مدیریت چند پنل
- ساخت، ویرایش، تمدید و حذف کاربر
- نمایش کاربران آنلاین، غیرفعال و آخرین آنلاین
- پشتیبانی از ادمین اصلی و ادمین فرعی با دسترسی محدود
- ارسال کانفیگ، QR و subscription link
- هشدار اتمام حجم و پایان سرویس
- نصب و اجرا با `systemd`
- منوی مدیریتی سرور با دستور `tgbot`

## Quick Install

```bash
bash <(curl -Ls https://raw.githubusercontent.com/smaghili/tgbotxui/main/install.sh)
```

برای نصب صریح:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/smaghili/tgbotxui/main/install.sh) install
```

## Update

```bash
bash <(curl -Ls https://raw.githubusercontent.com/smaghili/tgbotxui/main/install.sh) update
```

در حالت update:

- `.env` حفظ می‌شود
- `data/` و دیتابیس حفظ می‌شوند
- از وضعیت قبلی backup گرفته می‌شود
- اگر چیزی تغییر نکرده باشد، اسکریپت زودتر خارج می‌شود

## Server Menu

بعد از نصب:

```bash
tgbot
```

منو این گزینه‌ها را می‌دهد:

- `Install`
- `Update`
- `Uninstall`
- `Start`
- `Stop`
- `Restart`
- `Check Status`
- `Show Logs`

و وضعیت واقعی سرویس را نشان می‌دهد:

- `Bot state: Running/Stopped`
- `Start automatically: Yes/No`

## Important Env

فایل نمونه: [.env.example](./.env.example)

کلیدهای ضروری:

- `BOT_TOKEN`
- `ADMIN_IDS`
- `ENCRYPTION_KEY`

کلیدهای رایج:

- `DATABASE_PATH`
- `TIMEZONE`
- `TELEGRAM_PROXIES`
- `SYNC_INTERVAL_SECONDS`

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Commands

- `/start`
- `/status`
- `/help`
- `/cancel`
- `/sync_all`

## Test

```bash
python -m pytest
```

## Paths

- App: `/opt/tgbot`
- Service: `tgbot`
- Service file: `/etc/systemd/system/tgbot.service`
