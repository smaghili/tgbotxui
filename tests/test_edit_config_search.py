from bot.handlers.admin_provisioning import EDIT_SEARCH_MIN_QUERY_LEN, _edit_search_results_keyboard
from bot.handlers.admin_shared import parse_client_callback


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


def test_edit_detail_callback_payload_keeps_panel_inbound_and_uuid() -> None:
    callback_data = "pec:detail:7:2:uuid-1"

    _, _, panel_raw, inbound_raw, client_uuid = callback_data.split(":", 4)

    assert int(panel_raw) == 7
    assert int(inbound_raw) == 2
    assert client_uuid == "uuid-1"


def test_edit_search_result_callback_payload_matches_handler_parser() -> None:
    callback_data = "pecs:7:2:uuid-1:3:sample-query"

    _, panel_raw, inbound_raw, client_uuid, page_raw, query = callback_data.split(":", 5)

    assert int(panel_raw) == 7
    assert int(inbound_raw) == 2
    assert client_uuid == "uuid-1"
    assert int(page_raw) == 3
    assert query == "sample-query"


def test_shared_client_callback_parser_still_supports_cr_prefix() -> None:
    assert parse_client_callback("cr:7:2:uuid-1", "cr") == (7, 2, "uuid-1")


def test_edit_search_requires_stable_min_query_length() -> None:
    assert EDIT_SEARCH_MIN_QUERY_LEN == 3
