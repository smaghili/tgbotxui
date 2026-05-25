from __future__ import annotations

from typing import Any

from bot.services.financial_service import FinancialService


class PaymentService:
    """Standalone boundary for external payment flows and wallet settlement."""

    def __init__(self, *, financial_service: FinancialService) -> None:
        self.financial_service = financial_service

    async def settle_successful_payment(
        self,
        *,
        actor_user_id: int,
        telegram_user_id: int,
        amount: int,
        provider: str,
        provider_ref: str,
        details: str | None = None,
    ) -> dict[str, Any]:
        return await self.financial_service.adjust_wallet_balance(
            actor_user_id=actor_user_id,
            telegram_user_id=telegram_user_id,
            amount=amount,
            allow_negative_balance=False,
            operation="payment_settlement",
            details=details or f"provider={provider};provider_ref={provider_ref}",
            metadata={"provider": provider, "provider_ref": provider_ref},
        )
