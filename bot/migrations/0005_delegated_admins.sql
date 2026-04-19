CREATE TABLE IF NOT EXISTS delegated_admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    title TEXT,
    created_by INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS delegated_admin_inbounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delegated_admin_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(delegated_admin_id, panel_id, inbound_id),
    FOREIGN KEY(delegated_admin_id) REFERENCES delegated_admins(id) ON DELETE CASCADE,
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_delegated_admins_telegram_user_id
ON delegated_admins(telegram_user_id);

CREATE INDEX IF NOT EXISTS idx_delegated_admin_inbounds_admin_id
ON delegated_admin_inbounds(delegated_admin_id);

CREATE INDEX IF NOT EXISTS idx_delegated_admin_inbounds_panel_inbound
ON delegated_admin_inbounds(panel_id, inbound_id);
