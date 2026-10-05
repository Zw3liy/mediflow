from django.conf import settings
from django.db import models


class Service(models.Model):
    practice = models.ForeignKey(
        "tenancy.Practice",
        on_delete=models.PROTECT,
    )
    name = models.CharField(max_length=120)
    duration_minutes = models.PositiveIntegerField(default=30)
    price_cents = models.PositiveIntegerField(default=0)
    deposit_cents = models.PositiveIntegerField(default=0)


class Appointment(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        HELD = "held", "Held"
        CONFIRMED = "confirmed", "Confirmed"
        ARRIVED = "arrived", "Arrived"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No-show"

    practice = models.ForeignKey(
        "tenancy.Practice",
        on_delete=models.PROTECT,
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
    )
    practitioner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.REQUESTED,
    )
    hold_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )
