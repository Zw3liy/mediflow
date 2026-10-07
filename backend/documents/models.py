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


class PatientDocumentScan(models.Model):
    """Private OCR draft; attaching it to a patient requires explicit review."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    practice = models.ForeignKey('tenancy.Practice', on_delete=models.PROTECT)
    patient = models.ForeignKey('patients.Patient', null=True, blank=True, on_delete=models.PROTECT, related_name='scanned_documents')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    title = models.CharField(max_length=160, default='Scanned document')
    original_key = models.CharField(max_length=500, unique=True)
    pdf_key = models.CharField(max_length=500, unique=True)
    original_content_type = models.CharField(max_length=100)
    original_sha256 = models.CharField(max_length=64)
    extracted_text = models.TextField(blank=True)
    reviewed_text = models.TextField(blank=True)
    suggestions = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
