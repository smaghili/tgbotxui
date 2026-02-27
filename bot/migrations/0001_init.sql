CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    full_name TEXT,
    username TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    web_base_path TEXT NOT NULL DEFAULT '',
    login_path TEXT NOT NULL DEFAULT '/login/',
    username_enc TEXT NOT NULL,
    password_enc TEXT NOT NULL,
    two_factor_enc TEXT,
    created_by INTEGER NOT NULL,
    last_login_ok INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS panel_sessions (
    panel_id INTEGER PRIMARY KEY,
    cookies_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER,
    client_email TEXT NOT NULL,
    client_id TEXT,
    service_name TEXT NOT NULL,
    total_bytes INTEGER NOT NULL DEFAULT -1,
    used_bytes INTEGER NOT NULL DEFAULT 0,
    expire_at INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    last_synced_at INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(telegram_user_id, panel_id, client_email),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usage_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_service_id INTEGER NOT NULL,
    used_bytes INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL,
    remaining_bytes INTEGER,
    status TEXT NOT NULL,
    synced_at INTEGER NOT NULL,
    FOREIGN KEY(user_service_id) REFERENCES user_services(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_services_telegram_user_id ON user_services(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_user_services_panel_id ON user_services(panel_id);
CREATE INDEX IF NOT EXISTS idx_usage_snapshots_user_service_id ON usage_snapshots(user_service_id);
