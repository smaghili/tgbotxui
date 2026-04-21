CREATE TABLE IF NOT EXISTS admin_activity_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    sent_at INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_activity_notifications_pending
ON admin_activity_notifications(sent_at, next_attempt_at, id);
