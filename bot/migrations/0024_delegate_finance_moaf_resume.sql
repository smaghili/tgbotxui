CREATE TABLE IF NOT EXISTS moaf_resume_delegate_caps (
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    delegate_user_id INTEGER NOT NULL,
    cap_total_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(panel_id, inbound_id, client_uuid, delegate_user_id),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_moaf_resume_caps_delegate
ON moaf_resume_delegate_caps(delegate_user_id);

CREATE TABLE IF NOT EXISTS delegate_finance_excluded_inbounds (
    delegate_user_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(delegate_user_id, panel_id, inbound_id)
);
