ALTER TABLE panels ADD COLUMN api_version TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE panels ADD COLUMN api_token_enc TEXT;
