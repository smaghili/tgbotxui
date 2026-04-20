ALTER TABLE user_pricing
ADD COLUMN apply_price_to_past_reports INTEGER NOT NULL DEFAULT 1;
