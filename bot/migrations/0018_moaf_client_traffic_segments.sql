CREATE TABLE IF NOT EXISTS moaf_client_traffic_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    actor_user_id INTEGER NOT NULL,
    start_bytes INTEGER NOT NULL,
    end_bytes INTEGER NOT NULL,
    is_billable INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    client_email TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_moaf_segments_client
ON moaf_client_traffic_segments(panel_id, inbound_id, client_uuid);

CREATE INDEX IF NOT EXISTS idx_moaf_segments_owner
ON moaf_client_traffic_segments(owner_user_id);
