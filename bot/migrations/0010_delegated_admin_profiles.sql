CREATE TABLE IF NOT EXISTS delegated_admin_profiles (
    telegram_user_id INTEGER PRIMARY KEY,
    username_prefix TEXT,
    max_clients INTEGER NOT NULL DEFAULT 0,
    min_traffic_gb INTEGER NOT NULL DEFAULT 1,
    max_traffic_gb INTEGER NOT NULL DEFAULT 0,
    min_expiry_days INTEGER NOT NULL DEFAULT 1,
    max_expiry_days INTEGER NOT NULL DEFAULT 0,
    charge_basis TEXT NOT NULL DEFAULT 'allocated',
    is_active INTEGER NOT NULL DEFAULT 1,
    expires_at INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_delegated_admin_profiles_active
ON delegated_admin_profiles(is_active);
