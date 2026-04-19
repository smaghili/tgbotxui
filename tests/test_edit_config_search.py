from bot.handlers.admin_provisioning import _edit_search_results_keyboard


def test_edit_search_results_keyboard_uses_edit_callbacks() -> None:
    clients = [
        {"email": "alpha-user", "inbound_id": 1, "uuid": "uuid-1", "enabled": True},
        {"email": "beta-user", "inbound_id": 2, "uuid": "uuid-2", "enabled": False},
    ]

    markup = _edit_search_results_keyboard(7, clients, query="user", page=1)

    rows = markup.inline_keyboard
    assert rows[0][0].text.startswith("🟢 ")
    assert rows[0][1].text.startswith("⚫ ")
    assert rows[0][0].callback_data == "pecs:7:1:uuid-1:1:user"
    assert rows[0][1].callback_data == "pecs:7:2:uuid-2:1:user"


def test_edit_search_results_keyboard_adds_pagination_callbacks() -> None:
    clients = [{"email": f"user-{idx}", "inbound_id": 1, "uuid": f"uuid-{idx}", "enabled": True} for idx in range(25)]

    markup = _edit_search_results_keyboard(3, clients, query="sample", page=2)

    nav_row = markup.inline_keyboard[-2]
    assert nav_row[0].callback_data == "pecp:3:1:sample"
    assert nav_row[1].text == "2/2"
    assert markup.inline_keyboard[-1][0].callback_data == "pecsr:3:sample"
