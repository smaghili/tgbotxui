from __future__ import annotations

NOTIFICATION_KIND_LABEL_KEY: dict[str, str] = {
    "admin_activity_action_create_client": "admin_activity_action_create_client",
    "admin_activity_action_toggle_client": "admin_activity_action_toggle_client",
    "admin_activity_action_rotate_client": "admin_activity_action_rotate_client",
    "admin_activity_action_set_tg_id": "admin_activity_action_set_tg_id",
    "admin_activity_action_add_traffic": "admin_activity_action_add_traffic",
    "admin_activity_action_add_days": "admin_activity_action_add_days",
    "admin_activity_action_delete_client": "admin_activity_action_delete_client",
    "admin_activity_action_set_total_gb": "admin_activity_action_set_total_gb",
    "admin_activity_action_set_expiry_days": "admin_activity_action_set_expiry_days",
    "admin_activity_action_reset_traffic": "admin_activity_action_reset_traffic",
    "admin_activity_action_change_location": "admin_activity_action_change_location",
    "admin_activity_action_set_ip_limit": "admin_activity_action_set_ip_limit",
    "bot_notify_auto_cleanup_deleted": "notif_kind_auto_cleanup_deleted",
    "bot_notify_manager_service_depleted": "notif_kind_manager_service_depleted",
    "bot_notify_manager_service_expired": "notif_kind_manager_service_expired",
    "bot_notify_manager_service_threshold": "notif_kind_manager_service_threshold",
    "bot_notify_user_service_threshold": "notif_kind_user_service_threshold",
    "bot_notify_user_service_depleted": "notif_kind_user_service_depleted",
    "bot_notify_user_service_expired": "notif_kind_user_service_expired",
    "bot_notify_delegated_panel_traffic_low": "notif_kind_delegated_traffic_low",
    "bot_notify_delegated_panel_traffic_depleted": "notif_kind_delegated_traffic_depleted",
    "bot_notify_delegated_panel_expiry_low": "notif_kind_delegated_expiry_low",
    "bot_notify_delegated_panel_expiry_expired": "notif_kind_delegated_expiry_expired",
    "bot_notify_user_traffic_increased": "notif_kind_user_traffic_increased",
    "bot_notify_user_expiry_extended": "notif_kind_user_expiry_extended",
}

ORDERED_NOTIFICATION_KINDS: tuple[str, ...] = tuple(NOTIFICATION_KIND_LABEL_KEY.keys())

ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS: tuple[str, ...] = (
    "bot_notify_user_service_threshold",
    "bot_notify_user_service_depleted",
    "bot_notify_user_service_expired",
    "bot_notify_user_traffic_increased",
    "bot_notify_user_expiry_extended",
)


def visible_notification_kinds(
    *,
    is_root_admin: bool,
    is_delegated_admin: bool,
) -> tuple[str, ...]:
    out: list[str] = []
    for kind in ORDERED_NOTIFICATION_KINDS:
        if kind in ROOT_GLOBAL_ENDUSER_NOTIFICATION_KINDS:
            continue
        if kind.startswith("admin_activity_action_"):
            if not (is_root_admin or is_delegated_admin):
                continue
        if kind.startswith("bot_notify_delegated_panel_"):
            if not is_delegated_admin or is_root_admin:
                continue
        out.append(kind)
    return tuple(out)
