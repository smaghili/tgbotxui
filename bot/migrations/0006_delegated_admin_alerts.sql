CREATE TABLE IF NOT EXISTS delegated_admin_client_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delegated_admin_user_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    alert_state TEXT NOT NULL DEFAULT 'normal',
    last_notified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(delegated_admin_user_id, panel_id, inbound_id, client_uuid)
);

CREATE INDEX IF NOT EXISTS idx_delegated_admin_client_alerts_admin
ON delegated_admin_client_alerts(delegated_admin_user_id);
