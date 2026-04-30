CREATE TABLE IF NOT EXISTS delegated_admin_panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delegated_admin_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(delegated_admin_id, panel_id),
    FOREIGN KEY(delegated_admin_id) REFERENCES delegated_admins(id) ON DELETE CASCADE,
    FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO delegated_admin_panels (delegated_admin_id, panel_id, created_at, updated_at)
SELECT DISTINCT delegated_admin_id, panel_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM delegated_admin_inbounds;

CREATE INDEX IF NOT EXISTS idx_delegated_admin_panels_admin ON delegated_admin_panels(delegated_admin_id);
CREATE INDEX IF NOT EXISTS idx_delegated_admin_panels_panel ON delegated_admin_panels(panel_id);
