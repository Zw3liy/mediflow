from django.core.exceptions import ValidationError
from django.db import transaction

from scheduling.models import Appointment
from tenancy.models import Practice

from .gateways import PaymentGateway
from .models import DepositPayment


ACTIVE_PAYMENT_STATUSES = [
    DepositPayment.Status.CREATED,
    DepositPayment.Status.PENDING,
    DepositPayment.Status.PAID,
]


def create_deposit_checkout(
    *,
    appointment_id,
    practice: Practice,
    gateway: PaymentGateway,
) -> DepositPayment:
    with transaction.atomic():
        appointment = (
            Appointment.objects.select_for_update()
            .select_related(
                "practice",
                "patient",
                "service",
            )
            .get(id=appointment_id)
        )

        if appointment.practice_id != practice.id:
            raise ValidationError(
                "The appointment does not belong to this practice."
            )

        if appointment.patient.practice_id != practice.id:
            raise ValidationError(
                "The patient does not belong to this practice."
            )

        if appointment.service.practice_id != practice.id:
            raise ValidationError(
                "The service does not belong to this practice."
            )

        amount_cents = appointment.service.deposit_cents

        if amount_cents <= 0:
            raise ValidationError(
                "This appointment does not require a deposit."
            )

        existing_payment = (
            DepositPayment.objects.filter(
                appointment=appointment,
                practice=practice,
                status__in=ACTIVE_PAYMENT_STATUSES,
            )
            .order_by("-created_at")
            .first()
        )

        if existing_payment:
            return existing_payment

        payment = DepositPayment.objects.create(
            practice=practice,
            appointment=appointment,
            provider=gateway.provider_name,
            amount_cents=amount_cents,
            currency="ZAR",
        )

    try:
        checkout = gateway.create_checkout(payment=payment)
    except Exception:
        payment.status = DepositPayment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise

    payment.provider_reference = checkout.provider_reference
    payment.checkout_url = checkout.checkout_url
    payment.status = DepositPayment.Status.PENDING
    payment.save(
        update_fields=[
            "provider_reference",
            "checkout_url",
            "status",
            "updated_at",
        ],
    )

    return payment
