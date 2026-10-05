from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Membership, Practice
from auditlog.services import record_audit_event
from notifications.services import (
    notify_appointment_approved,
    notify_appointment_rejected,
)

from .models import Appointment


ACTIVE_BOOKING_STATUSES = [
    Appointment.Status.REQUESTED,
    Appointment.Status.HELD,
    Appointment.Status.CONFIRMED,
    Appointment.Status.ARRIVED,
]


@transaction.atomic
def book(
    *,
    practice,
    patient,
    practitioner,
    service,
    starts_at,
):
    # Lock an existing row even when the appointment slot is empty.
    Practice.objects.select_for_update().get(pk=practice.pk)

    if patient.practice_id != practice.id:
        raise ValidationError(
            "The patient does not belong to this practice."
        )

    if service.practice_id != practice.id:
        raise ValidationError(
            "The service does not belong to this practice."
        )

    practitioner_is_active = Membership.objects.filter(
        practice=practice,
        user=practitioner,
        active=True,
        role__in=[
            Membership.Role.DOCTOR,
            Membership.Role.NURSE,
        ],
    ).exists()

    if not practitioner_is_active:
        raise ValidationError(
            "The practitioner is not active in this practice."
        )

    if starts_at <= timezone.now():
        raise ValidationError(
            "Choose a future appointment time."
        )

    ends_at = starts_at + timedelta(
        minutes=service.duration_minutes,
    )

    clash_exists = (
        Appointment.objects.select_for_update()
        .filter(
            practice=practice,
            practitioner=practitioner,
            status__in=ACTIVE_BOOKING_STATUSES,
            starts_at__lt=ends_at,
            ends_at__gt=starts_at,
        )
        .exists()
    )

    if clash_exists:
        raise ValidationError(
            "That appointment time is no longer available."
        )

    return Appointment.objects.create(
        practice=practice,
        patient=patient,
        practitioner=practitioner,
        service=service,
        starts_at=starts_at,
        ends_at=ends_at,
        status=Appointment.Status.REQUESTED,
        hold_expires_at=None,
    )


@transaction.atomic
def approve_booking(
    *,
    appointment_id,
    practice,
    actor,
):
    Practice.objects.select_for_update().get(pk=practice.pk)

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
            "Only active reception or owner staff may approve bookings."
        )

    try:
        appointment = Appointment.objects.select_for_update().get(
            id=appointment_id,
            practice=practice,
        )
    except Appointment.DoesNotExist as error:
        raise ValidationError(
            "Appointment was not found in this practice."
        ) from error

    if appointment.status != Appointment.Status.REQUESTED:
        raise ValidationError(
            "Only requested appointments may be approved."
        )

    reviewed_at = timezone.now()

    appointment.status = Appointment.Status.HELD
    appointment.hold_expires_at = (
        reviewed_at + timedelta(minutes=10)
    )
    appointment.reviewed_by = actor
    appointment.reviewed_at = reviewed_at
    appointment.decision_reason = ""

    appointment.save(
        update_fields=[
            "status",
            "hold_expires_at",
            "reviewed_by",
            "reviewed_at",
            "decision_reason",
        ]
    )

    record_audit_event(
        practice=practice,
        actor=actor,
        action="appointment.approved",
        object_type="appointment",
        object_id=appointment.id,
        purpose="Approve requested appointment",
        outcome="success",
        metadata={
            "status": appointment.status,
        },
    )

    notify_appointment_approved(
        appointment=appointment,
    )

    return appointment


@transaction.atomic
def reject_booking(
    *,
    appointment_id,
    practice,
    actor,
    reason,
):
    Practice.objects.select_for_update().get(pk=practice.pk)

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
            "Only active reception or owner staff may reject bookings."
        )

    clean_reason = reason.strip()

    if not clean_reason:
        raise ValidationError(
            "A rejection reason is required."
        )

    try:
        appointment = Appointment.objects.select_for_update().get(
            id=appointment_id,
            practice=practice,
        )
    except Appointment.DoesNotExist as error:
        raise ValidationError(
            "Appointment was not found in this practice."
        ) from error

    if appointment.status != Appointment.Status.REQUESTED:
        raise ValidationError(
            "Only requested appointments may be rejected."
        )

    reviewed_at = timezone.now()

    appointment.status = Appointment.Status.REJECTED
    appointment.hold_expires_at = None
    appointment.reviewed_by = actor
    appointment.reviewed_at = reviewed_at
    appointment.decision_reason = clean_reason

    appointment.save(
        update_fields=[
            "status",
            "hold_expires_at",
            "reviewed_by",
            "reviewed_at",
            "decision_reason",
        ]
    )

    record_audit_event(
        practice=practice,
        actor=actor,
        action="appointment.rejected",
        object_type="appointment",
        object_id=appointment.id,
        purpose="Reject requested appointment",
        outcome="success",
        metadata={
            "status": appointment.status,
        },
    )

    notify_appointment_rejected(
        appointment=appointment,
    )

    return appointment


@transaction.atomic
def update_booking(*, appointment_id, practice, actor, changes):
    # Use the same lock order as creation, approval, rejection and audit writes.
    Practice.objects.select_for_update().get(pk=practice.pk)
    appointment = Appointment.objects.select_for_update().get(
        pk=appointment_id, practice=practice,
    )
    membership = Membership.objects.filter(
        practice=practice, user=actor, active=True,
        role__in=[Membership.Role.OWNER, Membership.Role.RECEPTION,
                  Membership.Role.DOCTOR, Membership.Role.NURSE],
    ).first()
    if membership is None or (
        membership.role in [Membership.Role.DOCTOR, Membership.Role.NURSE]
        and appointment.practitioner_id != actor.pk
    ):
        raise ValidationError("Appointment update denied.")
    if appointment.status != Appointment.Status.REQUESTED:
        raise ValidationError("Only requested appointments may be edited.")

    patient = changes.get("patient", appointment.patient)
    practitioner = changes.get("practitioner", appointment.practitioner)
    service = changes.get("service", appointment.service)
    starts_at = changes.get("starts_at", appointment.starts_at)
    if patient.practice_id != practice.pk or service.practice_id != practice.pk:
        raise ValidationError("Cross-practice booking denied.")
    if not Membership.objects.filter(
        practice=practice, user=practitioner, active=True,
        role__in=[Membership.Role.DOCTOR, Membership.Role.NURSE],
    ).exists():
        raise ValidationError("The practitioner is not active in this practice.")
    if starts_at <= timezone.now():
        raise ValidationError("Choose a future appointment time.")
    ends_at = starts_at + timedelta(minutes=service.duration_minutes)
    if Appointment.objects.filter(
        practice=practice, practitioner=practitioner,
        status__in=ACTIVE_BOOKING_STATUSES,
        starts_at__lt=ends_at, ends_at__gt=starts_at,
    ).exclude(pk=appointment.pk).exists():
        raise ValidationError("That appointment time is no longer available.")
    appointment.patient = patient
    appointment.practitioner = practitioner
    appointment.service = service
    appointment.starts_at = starts_at
    appointment.ends_at = ends_at
    appointment.save(update_fields=[
        "patient", "practitioner", "service", "starts_at", "ends_at",
    ])
    return appointment
