ALTER TABLE delegate_panel_pricing ADD COLUMN username_prefix TEXT;
ALTER TABLE delegate_panel_pricing ADD COLUMN max_clients INTEGER;
ALTER TABLE delegate_panel_pricing ADD COLUMN min_traffic_gb REAL;
ALTER TABLE delegate_panel_pricing ADD COLUMN max_traffic_gb REAL;
ALTER TABLE delegate_panel_pricing ADD COLUMN min_expiry_days INTEGER;
ALTER TABLE delegate_panel_pricing ADD COLUMN max_expiry_days INTEGER;
ALTER TABLE delegate_panel_pricing ADD COLUMN expires_at INTEGER;
