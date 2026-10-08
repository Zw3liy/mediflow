import uuid

from django.conf import settings
from django.db import models


class Encounter(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    practice = models.ForeignKey(
        "tenancy.Practice",
        on_delete=models.PROTECT,
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="encounters",
    )
    appointment = models.OneToOneField(
        "scheduling.Appointment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    practitioner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
    )


class Diagnosis(models.Model):
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.PROTECT,
        related_name="diagnoses",
    )
    code_system = models.CharField(
        max_length=80,
        blank=True,
    )
    code = models.CharField(
        max_length=40,
        blank=True,
    )
    description = models.CharField(max_length=300)
    status = models.CharField(
        max_length=20,
        choices=[
            ("provisional", "Provisional"),
            ("confirmed", "Confirmed"),
            ("ruled_out", "Ruled out"),
        ],
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    recorded_at = models.DateTimeField(auto_now_add=True)


class Observation(models.Model):
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.PROTECT,
        related_name="observations",
    )
    name = models.CharField(max_length=120)
    value = models.DecimalField(
        max_digits=12,
        decimal_places=3,
    )
    unit = models.CharField(max_length=40)
    measured_at = models.DateTimeField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )


class ClinicalNote(models.Model):
    encounter = models.OneToOneField(
        Encounter,
        on_delete=models.PROTECT,
        related_name="note",
    )
    current_version = models.PositiveIntegerField(default=0)


class ClinicalNoteVersion(models.Model):
    note = models.ForeignKey(
        ClinicalNote,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    body = models.TextField()
    reason = models.CharField(
        max_length=240,
        blank=True,
    )
    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    authored_at = models.DateTimeField(auto_now_add=True)
    signed_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    content_sha256 = models.CharField(
        max_length=64,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["note", "version"],
                name="uq_note_version",
            ),
        ]


class Prescription(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        CANCELLED = "cancelled", "Cancelled"

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.PROTECT,
        related_name="prescriptions",
    )
    prescribed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="prescriptions",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    general_instructions = models.TextField(
        blank=True,
        default="",
    )
    issued_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="items",
    )
    medication_name = models.CharField(
        max_length=180,
    )
    dosage = models.CharField(
        max_length=100,
    )
    route = models.CharField(
        max_length=60,
        blank=True,
        default="",
    )
    frequency = models.CharField(
        max_length=100,
    )
    duration = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    quantity = models.CharField(
        max_length=80,
        blank=True,
        default="",
    )
    instructions = models.TextField(
        blank=True,
        default="",
    )


class HealthEntry(models.Model):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="health_entries")
    kind = models.CharField(max_length=16, choices=[("vitals", "Vitals"), ("wellness", "Wellness"), ("report", "Report")])
    data = models.JSONField(default=dict)
    recorded_at = models.DateTimeField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_health_entries")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-recorded_at", "-pk"]
