from django.urls import path

from .views import (
    CreateDepositCheckoutView,
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
        "sandbox/<uuid:payment_id>/",
        SandboxCheckoutView.as_view(),
        name="sandbox-checkout",
    ),
]