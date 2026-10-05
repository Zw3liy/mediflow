import hashlib
import uuid

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError

from .models import PrescriptionDocument
from .services import (
    ALLOWED_PRESCRIPTION_CONTENT_TYPES,
    MAX_PRESCRIPTION_FILE_SIZE,
    register_prescription_document,
)


DOWNLOAD_TOKEN_SALT = "mediflow.prescription-document-download"


def upload_prescription_document(
    *,
    prescription_id,
    practice,
    actor,
    uploaded_file,
    storage,
):
    content_type = getattr(
        uploaded_file,
        "content_type",
        "",
    )

    if content_type not in ALLOWED_PRESCRIPTION_CONTENT_TYPES:
        raise ValidationError(
            "Only PDF prescription files are allowed."
        )

    size_bytes = getattr(
        uploaded_file,
        "size",
        None,
    )

    if (
        not isinstance(size_bytes, int)
        or size_bytes <= 0
        or size_bytes > MAX_PRESCRIPTION_FILE_SIZE
    ):
        raise ValidationError(
            "Prescription file size must be between 1 byte and 10 MB."
        )

    content = b"".join(
        uploaded_file.chunks()
    )

    if len(content) != size_bytes:
        raise ValidationError(
            "Uploaded file size does not match its content."
        )

    if not content.startswith(b"%PDF-"):
        raise ValidationError(
            "Uploaded file is not a valid PDF."
        )

    original_name = getattr(
        uploaded_file,
        "name",
        "",
    )
    object_key = (
        f"practices/{practice.id}/"
        f"prescriptions/{prescription_id}/"
        f"{uuid.uuid4()}.pdf"
    )
    sha256 = hashlib.sha256(content).hexdigest()

    storage.save(
        object_key=object_key,
        content=content,
    )

    try:
        return register_prescription_document(
            prescription_id=prescription_id,
            practice=practice,
            actor=actor,
            original_name=original_name,
            object_key=object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
    except Exception:
        storage.delete(
            object_key=object_key,
        )
        raise


def _patient_can_access_document(*, document, user):
    return (
        document.scan_status
        == PrescriptionDocument.ScanStatus.CLEAN
        and document.released_to_patient_at is not None
        and (
            document.prescription.encounter.patient.portal_user_id
            == user.id
        )
    )


def create_patient_download_token(
    *,
    document,
    user,
):
    if not _patient_can_access_document(
        document=document,
        user=user,
    ):
        raise PermissionDenied(
            "Document is not available to this patient."
        )

    return signing.dumps(
        {
            "document_id": str(document.id),
            "user_id": user.id,
        },
        salt=DOWNLOAD_TOKEN_SALT,
        compress=True,
    )


def resolve_patient_download_token(
    *,
    token,
    user,
    max_age,
):
    try:
        payload = signing.loads(
            token,
            salt=DOWNLOAD_TOKEN_SALT,
            max_age=max_age,
        )
    except signing.BadSignature as error:
        raise PermissionDenied(
            "Invalid or expired download token."
        ) from error

    if payload.get("user_id") != user.id:
        raise PermissionDenied(
            "Document is not available to this patient."
        )

    try:
        document = PrescriptionDocument.objects.select_related(
            "prescription",
            "prescription__encounter",
            "prescription__encounter__patient",
        ).get(
            pk=payload.get("document_id"),
        )
    except (
        PrescriptionDocument.DoesNotExist,
        ValueError,
        TypeError,
    ) as error:
        raise PermissionDenied(
            "Document is not available to this patient."
        ) from error

    if not _patient_can_access_document(
        document=document,
        user=user,
    ):
        raise PermissionDenied(
            "Document is not available to this patient."
        )

    return document
