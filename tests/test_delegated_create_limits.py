from bot.handlers.admin_provisioning import _delegated_min_create_error


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
