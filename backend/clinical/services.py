import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ClinicalNote, ClinicalNoteVersion


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
