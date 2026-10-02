import uuid

from django.conf import settings
from django.db import models


class Practice(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True)


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"
        RECEPTION = "reception", "Reception"
        PATIENT = "patient", "Patient"

    practice = models.ForeignKey(
        Practice,
        on_delete=models.PROTECT,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
    )
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["practice", "user"],
                name="uq_practice_user",
            ),
        ]
