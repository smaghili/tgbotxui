CREATE TABLE IF NOT EXISTS delegate_finance_exclude_client_remaining (
    delegate_user_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(delegate_user_id, panel_id, inbound_id, client_uuid),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_delegate_finex_rem_delegate
ON delegate_finance_exclude_client_remaining(delegate_user_id);
