from django.conf import settings
from django.db import models

from scheduling.models import Appointment
from tenancy.models import Practice


class Notification(models.Model):
    class Kind(models.TextChoices):
        APPOINTMENT_APPROVED = (
            "appointment_approved",
            "Appointment approved",
        )
        APPOINTMENT_REJECTED = (
            "appointment_rejected",
            "Appointment rejected",
        )
        DOCTOR_READY = "doctor_ready", "Doctor approved appointment"
        PATIENT_CALLED = "patient_called", "Doctor ready now"
        APPOINTMENT_REMINDER = (
            "appointment_reminder",
            "Appointment reminder",
        )

    practice = models.ForeignKey(
        Practice,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    kind = models.CharField(
        max_length=32,
        choices=Kind.choices,
    )
    title = models.CharField(
        max_length=160,
    )
    message = models.TextField()
    read_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "appointment",
                    "recipient",
                    "kind",
                ],
                name="unique_appointment_notification",
            ),
        ]

    def __str__(self):
        return f"{self.recipient}: {self.title}"
