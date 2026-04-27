CREATE TABLE IF NOT EXISTS client_owners (
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    client_email TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(panel_id, inbound_id, client_uuid),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_client_owners_owner_user_id
ON client_owners(owner_user_id);
