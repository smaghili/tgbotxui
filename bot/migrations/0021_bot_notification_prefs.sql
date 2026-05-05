CREATE TABLE IF NOT EXISTS user_bot_notification_prefs (
    telegram_user_id INTEGER PRIMARY KEY,
    disabled_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE admin_activity_notifications ADD COLUMN notification_kind TEXT;
