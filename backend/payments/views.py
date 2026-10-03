from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from django.core.exceptions import(
    ValidationError as DjangoValidationError,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from tenancy.context import require_membership

from .sandbox import SandboxGateway
from .serializers import (
    CreateDepositCheckoutSerializer,
    DepositPaymentSerializer,
)
from . services import create_deposit_checkout

from scheduling.models import Appointment

from .models import DepositPayment, PaymentWebhookEvent

STAFF_ROLES = [
    "owner",
    "doctor",
    "nurse",
    "reception",
]

class CreateDepositCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request,):
        input_serializer = CreateDepositCheckoutSerializer(
            data=request.data,
        )
        input_serializer.is_valid(raise_exception=True)

        membership = require_membership(
            user=request.user,
            practice_id=request.headers.get("X-Practice-ID"),
            roles=STAFF_ROLES,
        )
        try:
            payment = create_deposit_checkout(
                appointment_id=input_serializer.validated_data["appointment_id"],
                practice=membership.practice,
                gateway=SandboxGateway(),
            )
            
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail":error.message},
                )from error

        output_serializer = DepositPaymentSerializer(payment)

        return Response(output_serializer.data)

class SandboxCheckoutView(View):
    template_name = "payments/sandbox_checkout.html"

    def dispatch(self, request, *args, **kwargs):
        if not settings.DEBUG:
            raise Http404("Sandbox checkout is disabled.")

        return super().dispatch(request, *args, **kwargs)

    def get_payment(self, payment_id):
        return get_object_or_404(
            DepositPayment.objects.select_related(
                "appointment",
                "appointment__service",
            ),
            id=payment_id,
            provider="sandbox",
        )

    def build_context(self, payment, result=None):
        deposit_amount = (
            Decimal(payment.amount_cents) / Decimal("100")
        ).quantize(Decimal("0.00"))

        messages = {
            "paid": "Sandbox payment completed successfully.",
            "cancelled": "Sandbox payment was cancelled.",
            "unchanged": (
                "This payment has already been processed."
            ),
        }

        return {
            "payment": payment,
            "deposit_amount": deposit_amount,
            "result_message": messages.get(result),
        }

    def get(self, request, payment_id):
        payment = self.get_payment(payment_id)

        return render(
            request,
            self.template_name,
            self.build_context(
                payment,
                request.GET.get("result"),
            ),
        )

    @transaction.atomic
    def post(self, request, payment_id):
        payment = get_object_or_404(
            DepositPayment.objects.select_for_update().select_related(
                "appointment",
                "appointment__service",
            ),
            id=payment_id,
            provider="sandbox",
        )

        if payment.status not in {
            DepositPayment.Status.CREATED,
            DepositPayment.Status.PENDING,
        }:
            return redirect(
                f"{request.path}?result=unchanged"
            )

        action = request.POST.get("action")

        if action == "pay":
            payment.status = DepositPayment.Status.PAID
            payment.paid_at = timezone.now()
            payment.save(
                update_fields=[
                    "status",
                    "paid_at",
                    "updated_at",
                ]
            )

            appointment = payment.appointment
            appointment.status = Appointment.Status.CONFIRMED
            appointment.save(update_fields=["status"])

            PaymentWebhookEvent.objects.get_or_create(
                provider="sandbox",
                event_id=f"sandbox-paid-{payment.id}",
                defaults={
                    "event_type": "checkout.paid",
                    "signature_verified": True,
                    "processed": True,
                    "processed_at": timezone.now(),
                },
            )

            return redirect(f"{request.path}?result=paid")

        if action == "cancel":
            payment.status = DepositPayment.Status.CANCELLED
            payment.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            PaymentWebhookEvent.objects.get_or_create(
                provider="sandbox",
                event_id=f"sandbox-cancelled-{payment.id}",
                defaults={
                    "event_type": "checkout.cancelled",
                    "signature_verified": True,
                    "processed": True,
                    "processed_at": timezone.now(),
                },
            )

            return redirect(
                f"{request.path}?result=cancelled"
            )

        return render(
            request,
            self.template_name,
            self.build_context(payment),
            status=400,
        )