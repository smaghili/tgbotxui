CREATE TABLE IF NOT EXISTS delegate_panel_pricing (
    telegram_user_id INTEGER NOT NULL,
    panel_id INTEGER NOT NULL,
    price_per_gb INTEGER NOT NULL DEFAULT 0,
    price_per_day INTEGER NOT NULL DEFAULT 0,
    allocated_pricing_tiers_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (telegram_user_id, panel_id)
);

CREATE INDEX IF NOT EXISTS idx_delegate_panel_pricing_user
ON delegate_panel_pricing(telegram_user_id);
