ALTER TABLE user_pricing
ADD COLUMN consumed_pricing_tiers_json TEXT NOT NULL DEFAULT '[]';
