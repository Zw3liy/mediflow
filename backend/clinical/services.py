import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from tenancy.models import Membership

from .models import (
    ClinicalNote,
    ClinicalNoteVersion,
    Encounter,
    Prescription,
    PrescriptionItem,
)


@transaction.atomic
def sign_note(
    *,
    note_id,
    actor,
    body,
    reason="",
):
    note = (
        ClinicalNote.objects.select_for_update()
        .select_related("encounter")
        .get(pk=note_id)
    )

    if note.encounter.practitioner_id != actor.id:
        raise ValidationError(
            "Only the responsible practitioner may sign."
        )

    version = note.current_version + 1

    item = ClinicalNoteVersion.objects.create(
        note=note,
        version=version,
        body=body,
        reason=reason,
        authored_by=actor,
        signed_at=timezone.now(),
        content_sha256=hashlib.sha256(
            body.encode("utf-8"),
        ).hexdigest(),
    )

    note.current_version = version
    note.save(
        update_fields=[
            "current_version",
        ]
    )

    return item


@transaction.atomic
def create_prescription(
    *,
    encounter_id,
    actor,
    items,
    general_instructions="",
):
    try:
        encounter = (
            Encounter.objects.select_for_update()
            .select_related(
                "practice",
                "practitioner",
            )
            .get(pk=encounter_id)
        )
    except Encounter.DoesNotExist as error:
        raise ValidationError(
            "Encounter was not found."
        ) from error

    actor_is_active_doctor = Membership.objects.filter(
        practice=encounter.practice,
        user=actor,
        role=Membership.Role.DOCTOR,
        active=True,
    ).exists()

    if not actor_is_active_doctor:
        raise ValidationError(
            "Only an active doctor may create prescriptions."
        )

    if encounter.practitioner_id != actor.id:
        raise ValidationError(
            "Only the responsible doctor may prescribe."
        )

    prescription_items = list(items)

    if not prescription_items:
        raise ValidationError(
            "At least one prescription item is required."
        )

    normalized_items = []

    for item in prescription_items:
        if not isinstance(item, dict):
            raise ValidationError(
                "Each prescription item must be an object."
            )

        medication_name = (
            item.get("medication_name") or ""
        ).strip()
        dosage = (
            item.get("dosage") or ""
        ).strip()
        frequency = (
            item.get("frequency") or ""
        ).strip()

        if not medication_name or not dosage or not frequency:
            raise ValidationError(
                "Medication name, dosage, and frequency are required."
            )

        normalized_items.append(
            {
                "medication_name": medication_name,
                "dosage": dosage,
                "route": (item.get("route") or "").strip(),
                "frequency": frequency,
                "duration": (item.get("duration") or "").strip(),
                "quantity": (item.get("quantity") or "").strip(),
                "instructions": (
                    item.get("instructions") or ""
                ).strip(),
            }
        )

    prescription = Prescription.objects.create(
        encounter=encounter,
        prescribed_by=actor,
        status=Prescription.Status.DRAFT,
        general_instructions=(
            general_instructions or ""
        ).strip(),
    )

    PrescriptionItem.objects.bulk_create(
        [
            PrescriptionItem(
                prescription=prescription,
                **item,
            )
            for item in normalized_items
        ]
    )

    return prescription


@transaction.atomic
def issue_prescription(
    *,
    prescription_id,
    actor,
):
    try:
        prescription = (
            Prescription.objects.select_for_update()
            .select_related(
                "encounter",
                "encounter__practice",
                "prescribed_by",
            )
            .get(pk=prescription_id)
        )
    except Prescription.DoesNotExist as error:
        raise ValidationError(
            "Prescription was not found."
        ) from error

    actor_is_active_doctor = Membership.objects.filter(
        practice=prescription.encounter.practice,
        user=actor,
        role=Membership.Role.DOCTOR,
        active=True,
    ).exists()

    if not actor_is_active_doctor:
        raise ValidationError(
            "Only an active doctor may issue prescriptions."
        )

    if prescription.prescribed_by_id != actor.id:
        raise ValidationError(
            "Only the prescribing doctor may issue this prescription."
        )

    if prescription.status != Prescription.Status.DRAFT:
        raise ValidationError(
            "Only draft prescriptions may be issued."
        )

    if not prescription.items.exists():
        raise ValidationError(
            "A prescription must contain at least one item."
        )

    prescription.status = Prescription.Status.ISSUED
    prescription.issued_at = timezone.now()
    prescription.save(
        update_fields=[
            "status",
            "issued_at",
            "updated_at",
        ]
    )

    return prescription
