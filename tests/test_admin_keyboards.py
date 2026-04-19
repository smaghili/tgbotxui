from bot.handlers.admin_shared import edit_config_actions_keyboard, users_clients_keyboard
from bot.i18n import btn, t
from bot.keyboards import admin_keyboard


def test_admin_keyboard_removes_search_user_button() -> None:
    markup = admin_keyboard(lang="fa")
    labels = [button.text for row in markup.keyboard for button in row]

    assert btn("btn_search_user", "fa") not in labels
    assert btn("btn_edit_config", "fa") in labels
    assert btn("btn_inbounds_overview", "fa") in labels
    assert btn("btn_bulk_operations", "fa") in labels


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

    assert t("admin_bulk_actions", "fa") not in labels
