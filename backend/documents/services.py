import re
from pathlib import PurePath

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from clinical.models import Prescription
from tenancy.models import Membership

from .models import PrescriptionDocument


MAX_PRESCRIPTION_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_PRESCRIPTION_CONTENT_TYPES = {
    "application/pdf",
}
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


@transaction.atomic
def register_prescription_document(
    *,
    prescription_id,
    practice,
    actor,
    original_name,
    object_key,
    content_type,
    size_bytes,
    sha256,
):
    actor_is_authorized = Membership.objects.filter(
        practice=practice,
        user=actor,
        active=True,
        role__in=[
            Membership.Role.RECEPTION,
            Membership.Role.OWNER,
        ],
    ).exists()

    if not actor_is_authorized:
        raise ValidationError(
            "Only active reception or owner staff may register files."
        )

    try:
        prescription = (
            Prescription.objects.select_for_update()
            .select_related(
                "encounter",
                "encounter__practice",
            )
            .get(
                pk=prescription_id,
                encounter__practice=practice,
            )
        )
    except Prescription.DoesNotExist as error:
        raise ValidationError(
            "Prescription was not found in this practice."
        ) from error

    if prescription.status != Prescription.Status.ISSUED:
        raise ValidationError(
            "Only issued prescriptions may receive files."
        )

    clean_name = (original_name or "").strip()

    if (
        not clean_name
        or PurePath(clean_name).name != clean_name
        or "\x00" in clean_name
    ):
        raise ValidationError(
            "A safe original file name is required."
        )

    if content_type not in ALLOWED_PRESCRIPTION_CONTENT_TYPES:
        raise ValidationError(
            "Only PDF prescription files are allowed."
        )

    if (
        not isinstance(size_bytes, int)
        or size_bytes <= 0
        or size_bytes > MAX_PRESCRIPTION_FILE_SIZE
    ):
        raise ValidationError(
            "Prescription file size must be between 1 byte and 10 MB."
        )

    clean_sha256 = (sha256 or "").strip().lower()

    if not SHA256_PATTERN.fullmatch(clean_sha256):
        raise ValidationError(
            "A valid SHA-256 checksum is required."
        )

    expected_prefix = (
        f"practices/{practice.id}/"
        f"prescriptions/{prescription.id}/"
    )

    if not object_key.startswith(expected_prefix):
        raise ValidationError(
            "The storage key does not belong to this prescription."
        )

    return PrescriptionDocument.objects.create(
        practice=practice,
        prescription=prescription,
        uploaded_by=actor,
        original_name=clean_name,
        object_key=object_key,
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=clean_sha256,
        scan_status=PrescriptionDocument.ScanStatus.PENDING,
    )


@transaction.atomic
def release_prescription_document(
    *,
    document_id,
    practice,
    actor,
):
    actor_is_authorized = Membership.objects.filter(
        practice=practice,
        user=actor,
        active=True,
        role__in=[
            Membership.Role.RECEPTION,
            Membership.Role.OWNER,
        ],
    ).exists()

    if not actor_is_authorized:
        raise ValidationError(
            "Only active reception or owner staff may release files."
        )

    try:
        document = (
            PrescriptionDocument.objects.select_for_update()
            .select_related(
                "prescription",
                "prescription__encounter",
            )
            .get(
                pk=document_id,
                practice=practice,
            )
        )
    except PrescriptionDocument.DoesNotExist as error:
        raise ValidationError(
            "Document was not found in this practice."
        ) from error

    if document.prescription.status != Prescription.Status.ISSUED:
        raise ValidationError(
            "Only issued prescription files may be released."
        )

    if document.scan_status != PrescriptionDocument.ScanStatus.CLEAN:
        raise ValidationError(
            "Only clean files may be released to patients."
        )

    if document.released_to_patient_at is None:
        document.released_to_patient_at = timezone.now()
        document.save(
            update_fields=[
                "released_to_patient_at",
            ]
        )

    return document
