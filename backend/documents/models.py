import uuid

from django.conf import settings
from django.db import models


class PrescriptionDocument(models.Model):
    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEAN = "clean", "Clean"
        INFECTED = "infected", "Infected"
        FAILED = "failed", "Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    practice = models.ForeignKey(
        "tenancy.Practice",
        on_delete=models.PROTECT,
        related_name="prescription_documents",
    )
    prescription = models.ForeignKey(
        "clinical.Prescription",
        on_delete=models.PROTECT,
        related_name="documents",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_prescription_documents",
    )
    original_name = models.CharField(
        max_length=255,
    )
    object_key = models.CharField(
        max_length=500,
        unique=True,
    )
    content_type = models.CharField(
        max_length=100,
    )
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(
        max_length=64,
    )
    scan_status = models.CharField(
        max_length=20,
        choices=ScanStatus.choices,
        default=ScanStatus.PENDING,
    )
    released_to_patient_at = models.DateTimeField(
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

    def __str__(self):
        return self.original_name
