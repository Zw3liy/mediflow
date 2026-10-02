from django.urls import path

from .views import CreateDepositCheckoutView

app_name = "payments"

urlpatterns = [
    path(
        "deposits/checkout/",
        CreateDepositCheckoutView.as_view(),
        name="create-deposit-checkout",
    ),
]