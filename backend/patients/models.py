import uuid

from django.conf import settings
from django.db import models

from tenancy.models import Practice


class Patient(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    practice = models.ForeignKey(
        Practice,
        on_delete=models.PROTECT,
    )
    portal_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patient_profiles",
    )
    file_number = models.CharField(max_length=32)
    given_name = models.CharField(max_length=100)
    family_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(
        null=True,
        blank=True,
    )
    mobile = models.CharField(
        max_length=32,
        blank=True,
    )
    email = models.EmailField(blank=True)
    emergency_contact_name = models.CharField(
        max_length=160,
        blank=True,
    )
    emergency_contact_mobile = models.CharField(
        max_length=32,
        blank=True,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["practice", "file_number"],
                name="uq_practice_file_number",
            ),
        ]
        indexes = [
            models.Index(
                fields=["practice", "family_name", "given_name"],
            ),
        ]


class ConsentRecord(models.Model):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="consents",
    )
    purpose = models.CharField(max_length=120)
    decision = models.CharField(
        max_length=16,
        choices=[
            ("granted", "Granted"),
            ("withdrawn", "Withdrawn"),
        ],
    )
    policy_version = models.CharField(max_length=40)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
