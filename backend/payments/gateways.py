from dataclasses import dataclass
from typing import Protocol

from .models import DepositPayment


@dataclass(frozen=True)
class HostedCheckout:
    provider_reference: str
    checkout_url: str


class PaymentGateway(Protocol):
    provider_name: str

    def create_checkout(
        self,
        *,
        payment: DepositPayment,
    ) -> HostedCheckout:
        """Create a hosted checkout without receiving card details."""
        ...
