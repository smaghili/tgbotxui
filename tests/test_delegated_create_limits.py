from bot.handlers.admin_provisioning import _delegated_min_create_error, _group_inbound_rows_by_panel, _inbound_access_keyboard


class InboundRow:
    def __init__(self, panel_id: int, inbound_id: int, panel_name: str = "panel", inbound_name: str = "inbound") -> None:
        self.panel_id = panel_id
        self.inbound_id = inbound_id
        self.panel_name = panel_name
        self.inbound_name = inbound_name


def test_group_inbound_rows_by_panel_groups_rows_in_single_bucket() -> None:
    rows = [InboundRow(panel_id=1, inbound_id=101), InboundRow(panel_id=1, inbound_id=102)]
    grouped = _group_inbound_rows_by_panel(rows)

    assert set(grouped.keys()) == {1}
    assert len(grouped[1]) == 2


def test_group_inbound_rows_by_panel_groups_rows_in_multiple_buckets() -> None:
    rows = [
        InboundRow(panel_id=1, inbound_id=101),
        InboundRow(panel_id=2, inbound_id=201),
        InboundRow(panel_id=1, inbound_id=102),
    ]
    grouped = _group_inbound_rows_by_panel(rows)

    assert set(grouped.keys()) == {1, 2}
    assert len(grouped[1]) == 2
    assert len(grouped[2]) == 1


def test_inbound_access_keyboard_can_hide_panel_name_for_single_panel() -> None:
    markup = _inbound_access_keyboard(
        [InboundRow(panel_id=1, inbound_id=101, panel_name="Default", inbound_name="main")],
        "pick",
        include_panel_name=False,
    )

    button = markup.inline_keyboard[0][0]

    assert button.text == "main"
    assert button.callback_data == "pick:1:101"


def test_delegated_min_create_traffic_applies_only_to_delegated_admin() -> None:
    profile = {"min_traffic_gb": 2, "min_expiry_days": 15}

    assert _delegated_min_create_error(
        is_delegated_admin=True,
        profile=profile,
        traffic_gb=1,
    ) == ("admin_delegated_min_create_traffic", 2)
    assert _delegated_min_create_error(
        is_delegated_admin=False,
        profile=profile,
        traffic_gb=1,
    ) is None


def test_delegated_min_create_days_applies_only_to_delegated_admin() -> None:
    profile = {"min_traffic_gb": 2, "min_expiry_days": 15}

    assert _delegated_min_create_error(
        is_delegated_admin=True,
        profile=profile,
        expiry_days=14,
    ) == ("admin_delegated_min_create_days", 15)
    assert _delegated_min_create_error(
        is_delegated_admin=False,
        profile=profile,
        expiry_days=14,
    ) is None
