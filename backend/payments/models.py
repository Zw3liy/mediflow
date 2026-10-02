import uuid

from django.db import models
from django.db.models import Q


class DepositPayment(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    practice = models.ForeignKey(
        "tenancy.Practice",
        on_delete=models.PROTECT,
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="deposit_payments",
    )
    provider = models.CharField(max_length=40)
    provider_reference = models.CharField(
        max_length=160,
        blank=True,
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(
        max_length=3,
        default="ZAR",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CREATED,
    )
    checkout_url = models.URLField(
        max_length=500,
        blank=True,
    )
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0),
                name="deposit_amount_greater_than_zero",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_reference"],
                condition=~Q(provider_reference=""),
                name="uq_payment_provider_reference",
            ),
        ]
        indexes = [
            models.Index(
                fields=["practice", "status", "created_at"],
            ),
        ]


class PaymentWebhookEvent(models.Model):
    provider = models.CharField(max_length=40)
    event_id = models.CharField(max_length=200)
    event_type = models.CharField(max_length=100)
    signature_verified = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="uq_payment_webhook_event",
            ),
        ]
