CREATE TABLE IF NOT EXISTS panel_outbound_display (
    panel_id INTEGER NOT NULL,
    outbound_tag TEXT NOT NULL,
    display_label TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (panel_id, outbound_tag),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS panel_outbound_owner (
    panel_id INTEGER NOT NULL,
    outbound_tag TEXT NOT NULL,
    owner_telegram_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (panel_id, outbound_tag),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS panel_outbound_delegate_grant (
    panel_id INTEGER NOT NULL,
    outbound_tag TEXT NOT NULL,
    delegate_telegram_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (panel_id, outbound_tag, delegate_telegram_user_id),
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_panel_outbound_grant_delegate
ON panel_outbound_delegate_grant(delegate_telegram_user_id);
