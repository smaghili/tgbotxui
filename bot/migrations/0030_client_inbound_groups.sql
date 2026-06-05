CREATE TABLE IF NOT EXISTS client_inbound_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(panel_id, name)
);

CREATE TABLE IF NOT EXISTS client_inbound_group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    inbound_remark TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, inbound_id),
    FOREIGN KEY(group_id) REFERENCES client_inbound_groups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_client_inbound_groups_panel
ON client_inbound_groups(panel_id);

CREATE INDEX IF NOT EXISTS idx_client_inbound_group_members_group
ON client_inbound_group_members(group_id, position, inbound_id);
