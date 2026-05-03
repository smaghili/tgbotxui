CREATE TABLE IF NOT EXISTS delegated_admin_parent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    old_parent_user_id INTEGER,
    new_parent_user_id INTEGER,
    actor_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_delegated_parent_events_user
ON delegated_admin_parent_events(telegram_user_id, id);
