ALTER TABLE panels ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_panels_single_default
ON panels(is_default)
WHERE is_default = 1;
