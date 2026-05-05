ALTER TABLE user_pricing
ADD COLUMN allocated_pricing_tiers_json TEXT NOT NULL DEFAULT '[]';
