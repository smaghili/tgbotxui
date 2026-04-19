from types import SimpleNamespace

from bot.handlers.admin_provisioning import _delegated_min_create_error


def test_delegated_min_create_traffic_applies_only_to_delegated_admin() -> None:
    settings = SimpleNamespace(
        delegated_admin_min_create_gb=2,
        delegated_admin_min_create_days=15,
    )

    assert _delegated_min_create_error(
        is_delegated_admin=True,
        traffic_gb=1,
        settings=settings,
    ) == ("admin_delegated_min_create_traffic", 2)
    assert _delegated_min_create_error(
        is_delegated_admin=False,
        traffic_gb=1,
        settings=settings,
    ) is None


def test_delegated_min_create_days_applies_only_to_delegated_admin() -> None:
    settings = SimpleNamespace(
        delegated_admin_min_create_gb=2,
        delegated_admin_min_create_days=15,
    )

    assert _delegated_min_create_error(
        is_delegated_admin=True,
        expiry_days=14,
        settings=settings,
    ) == ("admin_delegated_min_create_days", 15)
    assert _delegated_min_create_error(
        is_delegated_admin=False,
        expiry_days=14,
        settings=settings,
    ) is None
