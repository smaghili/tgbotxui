# Telegram 3x-ui Bot (Rust, Production-Oriented)

ربات تلگرام بازنویسی‌شده با Rust برای مصرف CPU/RAM پایین‌تر و معماری قابل توسعه در محیط عملیاتی.

## ویژگی‌ها

- معماری ماژولار: `config`, `db`, `service`, `xui`, `bot`, `metrics`
- SQLite + migration versioned (`migrations/`)
- رمزنگاری AES-256-GCM برای اطلاعات حساس پنل
- RBAC ادمین با `ADMIN_IDS`
- rate-limit برای عملیات مدیریتی
- audit log برای عملیات حساس
- endpoint مانیتورینگ:
  - `/healthz`
  - `/metrics` (Prometheus)
- sync دوره‌ای مصرف سرویس‌ها

## منوی ربات

- کاربر:
  - `📊 وضعیت سرویس من`
- ادمین:
  - `مدیریت`
  - `افزودن پنل`
  - `لیست پنل‌ها`
  - `اتصال سرویس به کاربر`
  - `همگام‌سازی مصرف`

## کانفیگ `.env`

فایل نمونه: `.env.example`

مهم‌ترین کلیدها:
- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_URL=sqlite:data/bot.db`
- `ENCRYPTION_KEY` (base64 کلید 32 بایتی)
- `METRICS_ENABLED`, `METRICS_HOST`, `METRICS_PORT`

## اجرای لوکال

```bash
cargo run --release
```

## نصب روی سرور

```bash
chmod +x scripts/install.sh
sudo bash scripts/install.sh
```

اسکریپت نصب:
- به‌صورت تعاملی `BOT_TOKEN` و `ADMIN_IDS` می‌گیرد
- اگر `ENCRYPTION_KEY` مقدار معتبر نداشته باشد، خودکار تولید می‌کند
- باینری release می‌سازد
- سرویس systemd سخت‌سازی‌شده نصب می‌کند
- build را با تنظیمات مناسب VPS کم‌منبع اجرا می‌کند (`CARGO_BUILD_JOBS=1`)

### اگر سرور 1GB RAM است

- قبل از build بهتر است 2 تا 4 گیگ swap داشته باشید.
- اسکریپت نصب build را کم‌مصرف‌تر انجام می‌دهد، ولی بدون swap همچنان امکان OOM وجود دارد.

## عملیات

- لاگ:
```bash
sudo journalctl -u tgbot -f
```

- وضعیت:
```bash
sudo systemctl status tgbot
```

- metrics:
```bash
curl http://127.0.0.1:9090/metrics
```

## نکته مهم

در این محیط توسعه، toolchain Rust نصب نبود و compile/runtime تست نگرفتم. برای اطمینان نهایی روی سرور:
- `cargo build --release`
- `cargo clippy -- -D warnings`
