import hashlib
import json

from django.db import transaction
from django.utils import timezone

from tenancy.models import Practice

from .exceptions import AuditChainError
from .models import AuditEvent


def _canonical_event_payload(
    *,
    practice_id,
    actor_id,
    action,
    object_type,
    object_id,
    purpose,
    outcome,
    metadata,
    occurred_at,
    previous_hash,
):
    return {
        "practice_id": str(practice_id),
        "actor_id": actor_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "purpose": purpose,
        "outcome": outcome,
        "metadata": metadata,
        "occurred_at": occurred_at.isoformat(
            timespec="microseconds",
        ),
        "previous_hash": previous_hash,
    }


def _calculate_event_hash(**values):
    payload = _canonical_event_payload(**values)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def record_audit_event(
    *,
    practice,
    actor,
    action,
    object_type,
    object_id,
    purpose,
    outcome,
    metadata=None,
):
    locked_practice = (
        Practice.objects.select_for_update()
        .get(pk=practice.pk)
    )
    previous = (
        AuditEvent.objects.filter(
            practice=locked_practice,
        )
        .order_by("-id")
        .first()
    )
    previous_hash = (
        previous.event_hash if previous else ""
    )
    occurred_at = timezone.now()
    clean_metadata = metadata or {}

    event_hash = _calculate_event_hash(
        practice_id=locked_practice.pk,
        actor_id=getattr(actor, "pk", None),
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        purpose=purpose,
        outcome=outcome,
        metadata=clean_metadata,
        occurred_at=occurred_at,
        previous_hash=previous_hash,
    )

    return AuditEvent.objects.create(
        practice=locked_practice,
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        purpose=purpose,
        outcome=outcome,
        metadata=clean_metadata,
        occurred_at=occurred_at,
        previous_hash=previous_hash,
        event_hash=event_hash,
    )


def verify_audit_chain(*, practice):
    expected_previous_hash = ""

    events = AuditEvent.objects.filter(
        practice=practice,
    ).order_by("id")

    for event in events:
        if event.previous_hash != expected_previous_hash:
            return False

        expected_hash = _calculate_event_hash(
            practice_id=event.practice_id,
            actor_id=event.actor_id,
            action=event.action,
            object_type=event.object_type,
            object_id=event.object_id,
            purpose=event.purpose,
            outcome=event.outcome,
            metadata=event.metadata,
            occurred_at=event.occurred_at,
            previous_hash=event.previous_hash,
        )

        if event.event_hash != expected_hash:
            return False

        expected_previous_hash = event.event_hash

    return True
