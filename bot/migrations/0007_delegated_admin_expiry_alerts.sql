ALTER TABLE delegated_admin_client_alerts
ADD COLUMN traffic_alert_state TEXT NOT NULL DEFAULT 'normal';

ALTER TABLE delegated_admin_client_alerts
ADD COLUMN expiry_alert_state TEXT NOT NULL DEFAULT 'normal';

UPDATE delegated_admin_client_alerts
SET traffic_alert_state = alert_state
WHERE COALESCE(traffic_alert_state, '') = '';
