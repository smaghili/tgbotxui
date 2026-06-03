from bot.handlers.admin_handler_helpers import delegated_profile_error_text


def test_delegated_profile_error_text_maps_legacy_wallet_error_to_localized_key() -> None:
    text = delegated_profile_error_text(ValueError("insufficient wallet balance."), "fa")

    assert text == "موجودی کیف پول کافی نیست."


def test_delegated_profile_error_text_maps_upstream_wallet_error_to_specific_message() -> None:
    text = delegated_profile_error_text(
        ValueError("insufficient wallet balance for upstream delegated admin: Parent"),
        "fa",
    )

    assert text == "ساخت انجام نشد چون کیف پول بالادستی مالی این نماینده موجودی کافی ندارد."
