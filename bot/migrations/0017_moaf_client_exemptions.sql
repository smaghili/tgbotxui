CREATE TABLE IF NOT EXISTS moaf_client_exemptions (
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    moaf_user_id INTEGER NOT NULL,
    exempt_after_bytes INTEGER NOT NULL,
    client_email TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(panel_id, inbound_id, client_uuid),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_moaf_client_exemptions_owner
ON moaf_client_exemptions(owner_user_id);
