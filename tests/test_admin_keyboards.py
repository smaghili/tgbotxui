from bot.handlers.admin_shared import (
    client_expiry_menu_keyboard,
    client_iplimit_menu_keyboard,
    client_traffic_menu_keyboard,
    edit_config_actions_keyboard,
    format_inbounds_overview,
    client_list_keyboard,
    panels_glass_keyboard,
    panel_select_keyboard,
    users_clients_keyboard,
    yes_no_inline_keyboard,
)
from bot.handlers.admin_access import _delegated_detail_keyboard, _delegated_subordinates_keyboard
from bot.i18n import btn, t
from bot.keyboards import admin_keyboard


def test_admin_keyboard_removes_search_user_button() -> None:
    markup = admin_keyboard(lang="fa")
    labels = [button.text for row in markup.keyboard for button in row]

    assert btn("btn_search_user", "fa") not in labels
    assert btn("btn_edit_config", "fa") in labels
    assert btn("btn_inbounds_overview", "fa") in labels
    assert btn("btn_low_traffic_users", "fa") in labels
    assert btn("btn_bulk_operations", "fa") in labels
    assert btn("btn_list_inbounds", "fa") not in labels
    assert btn("btn_last_online_users", "fa") not in labels


def test_limited_admin_keyboard_includes_low_traffic_users() -> None:
    markup = admin_keyboard(mode="limited", lang="fa")
    labels = [button.text for row in markup.keyboard for button in row]

    assert btn("btn_low_traffic_users", "fa") in labels


def test_edit_config_actions_keyboard_includes_toggle_button() -> None:
    markup = edit_config_actions_keyboard(1, 2, "uuid-1", True, "fa")
    labels = [button.text for row in markup.inline_keyboard for button in row]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert btn("btn_get_config", "fa") in labels
    assert btn("btn_rotate_link", "fa") in labels
    assert "pec:get_config:1:2:uuid-1" in callbacks
    assert "pec:rotate_ask:1:2:uuid-1" in callbacks
    assert t("admin_toggle_on", "fa") in labels
    assert "pec:toggle:1:2:uuid-1" in callbacks
    assert t("admin_edit_show_detail", "fa") not in labels


def test_users_clients_keyboard_does_not_include_bulk_button() -> None:
    markup = users_clients_keyboard(1, 2, [{"email": "u1", "uuid": "uuid-1"}], "fa")
    labels = [button.text for row in markup.inline_keyboard for button in row]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert t("admin_bulk_actions", "fa") not in labels
    assert "uo:1:2:uuid-1" in callbacks


def test_disabled_clients_keyboard_uses_disabled_detail_callback() -> None:
    markup = client_list_keyboard(
        1,
        [{"email": "u1", "uuid": "uuid-1", "inbound_id": 2, "enabled": False}],
        "fa",
        mode="ds",
    )
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert "uodl:1:2:uuid-1" in callbacks
    assert "uol:1:2:uuid-1" not in callbacks


def test_low_traffic_clients_keyboard_uses_low_traffic_detail_callback() -> None:
    markup = client_list_keyboard(
        1,
        [{"email": "u1", "uuid": "uuid-1", "inbound_id": 2, "remaining_bytes": 50 * 1024 * 1024}],
        "fa",
        mode="lr",
    )
    labels = [button.text for row in markup.inline_keyboard for button in row]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert any("u1" in label for label in labels)
    assert "uolr:1:2:uuid-1" in callbacks
    assert "uop:lr:1:1" in callbacks


def test_inbounds_overview_includes_status_and_inactive_counts() -> None:
    text = format_inbounds_overview(
        "xui CDN",
        [
            {
                "remark": "Work",
                "port": 8880,
                "up": 10,
                "down": 20,
                "enable": False,
                "expiryTime": 0,
                "clientStats": [
                    {"enable": True},
                    {"enable": False},
                    {"enabled": False},
                ],
            }
        ],
        "fa",
    )

    assert t("admin_inactive_clients_count", "fa") in text
    assert t("admin_status", "fa") in text
    assert t("admin_disabled", "fa") in text


def test_panel_select_keyboard_uses_default_and_health_markers() -> None:
    markup = panel_select_keyboard(
        [
            {"id": 7, "name": "xui CDN", "last_login_ok": True, "is_default": True},
            {"id": 8, "name": "Backup", "last_login_ok": False, "is_default": False},
        ],
        "pick",
    )

    first_row = markup.inline_keyboard[0][0]
    second_row = markup.inline_keyboard[1][0]

    assert first_row.text == "⭐ ✅ xui CDN"
    assert first_row.callback_data == "pick:7"
    assert second_row.text == "❌ Backup"
    assert second_row.callback_data == "pick:8"


def test_panels_glass_keyboard_includes_panel_access_button() -> None:
    markup = panels_glass_keyboard(
        [{"id": 7, "name": "xui CDN", "last_login_ok": True, "is_default": True}]
    )

    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert "panel_access_ask:7" in callbacks
    assert "panel_delete_ask:7" in callbacks


def test_yes_no_inline_keyboard_builds_two_buttons() -> None:
    markup = yes_no_inline_keyboard("yes:1", "no:1", "fa")
    row = markup.inline_keyboard[0]

    assert len(row) == 2
    assert row[0].text == t("btn_yes", "fa")
    assert row[0].callback_data == "yes:1"
    assert row[1].text == t("btn_no", "fa")
    assert row[1].callback_data == "no:1"


def test_delegated_detail_keyboard_toggles_primary_parent_directly() -> None:
    markup = _delegated_detail_keyboard(
        55,
        is_active=True,
        charge_basis="consumed",
        admin_scope="limited",
        allow_negative_wallet=False,
        lang="fa",
    )
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert "dag:toggle_parent:55" in callbacks
    assert "dag:subs:55" in callbacks
    assert "dag:field:parent_user_id:55" not in callbacks


def test_delegated_detail_keyboard_hides_primary_parent_for_full_delegate() -> None:
    markup = _delegated_detail_keyboard(
        100,
        is_active=True,
        charge_basis="consumed",
        admin_scope="full",
        allow_negative_wallet=False,
        lang="fa",
    )
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert "dag:toggle_parent:100" not in callbacks
    assert "dag:subs:100" in callbacks


def test_delegated_subordinates_keyboard_adds_and_removes_children() -> None:
    markup = _delegated_subordinates_keyboard(
        100,
        [
            {"telegram_user_id": 100, "title": "parent", "parent_user_id": None},
            {"telegram_user_id": 55, "title": "child", "parent_user_id": 100},
            {"telegram_user_id": 66, "title": "other", "parent_user_id": None},
        ],
        "fa",
    )
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]

    assert "dag:subtoggle:100:55" in callbacks
    assert "dag:subtoggle:100:66" in callbacks
    assert "dag:subtoggle:100:100" not in callbacks
    assert "dag:detail:100" in callbacks


def test_client_traffic_menu_groups_presets_in_three_columns() -> None:
    markup = client_traffic_menu_keyboard(1, 2, "uuid-1", "fa")

    assert [button.text for button in markup.inline_keyboard[0]] == [t("admin_cancel", "fa")]
    assert len(markup.inline_keyboard[1]) == 2
    assert [button.text for button in markup.inline_keyboard[2]] == ["1 GB", "5 GB", "10 GB"]
    assert markup.inline_keyboard[-1][-1].callback_data == "ts:1:2:uuid-1:200"


def test_client_expiry_and_iplimit_menus_keep_expected_layouts() -> None:
    expiry_markup = client_expiry_menu_keyboard(1, 2, "uuid-1", "fa")
    ip_markup = client_iplimit_menu_keyboard(1, 2, "uuid-1", "fa")

    assert [button.text for button in expiry_markup.inline_keyboard[2]] == ["7d", "10d"]
    assert expiry_markup.inline_keyboard[-1][-1].callback_data == "es:1:2:uuid-1:365"
    assert [button.text for button in ip_markup.inline_keyboard[2]] == ["1", "2", "3"]
    assert ip_markup.inline_keyboard[-1][-1].callback_data == "is:1:2:uuid-1:10"
