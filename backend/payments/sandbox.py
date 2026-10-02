from .gateways import HostedCheckout
from .gateways import DepositPayment

class SandboxGateway:
    """"
     It creates a fake hosted-checkout URL so we can test the entire
    payment workflow without using a real card or payment provider.
    """

    provider_name = "sandbox"

    def create_checkout(
        self,
        *,
        payment: DepositPayment,
    ) -> HostedCheckout:
        return HostedCheckout(
            provider_reference=f"sandbox-{payment.id}",
            checkout_url=(
                "http://127.0.0.1:8000/"
                
                f"api/payments/sandbox/{payment.id}/"
            ),
        )