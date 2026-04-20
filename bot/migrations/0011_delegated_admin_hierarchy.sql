ALTER TABLE delegated_admins
ADD COLUMN parent_user_id INTEGER;

ALTER TABLE delegated_admins
ADD COLUMN admin_scope TEXT NOT NULL DEFAULT 'limited';

UPDATE delegated_admins
SET parent_user_id = CASE
    WHEN parent_user_id IS NULL THEN created_by
    ELSE parent_user_id
END;

CREATE INDEX IF NOT EXISTS idx_delegated_admins_parent_user_id
ON delegated_admins(parent_user_id);

CREATE INDEX IF NOT EXISTS idx_delegated_admins_scope
ON delegated_admins(admin_scope);
