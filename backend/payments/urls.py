from django.urls import path

from .views import (
    CreateDepositCheckoutView,
    DepositPaymentStatusView,
    SandboxCheckoutView,
)


app_name = "payments"


urlpatterns = [
    path(
        "deposits/checkout/",
        CreateDepositCheckoutView.as_view(),
        name="create-deposit-checkout",
    ),
    path(
        "deposits/<uuid:payment_id>/status/",
        DepositPaymentStatusView.as_view(),
        name="deposit-payment-status",
    ),
    path(
        "sandbox/<uuid:payment_id>/",
        SandboxCheckoutView.as_view(),
        name="sandbox-checkout",
    ),
]