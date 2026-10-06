from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Membership, Practice
from auditlog.services import record_audit_event
from notifications.services import (
    notify_appointment_approved,
    notify_appointment_rejected,
    doctor_intake_message,
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
    reason_for_visit="",
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
        reason_for_visit=reason_for_visit,
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
    appointment.reason_for_visit = changes.get("reason_for_visit", appointment.reason_for_visit)
    appointment.save(update_fields=[
        "patient", "practitioner", "service", "starts_at", "ends_at", "reason_for_visit",
    ])
    return appointment


@transaction.atomic
def doctor_approve_booking(*, appointment_id, practice, actor, ready_now=False):
    from notifications.services import notify_doctor_ready
    from zoneinfo import ZoneInfo
    Practice.objects.select_for_update().get(pk=practice.pk)
    appointment = Appointment.objects.select_for_update().select_related("patient", "practitioner", "practice").get(pk=appointment_id, practice=practice)
    if not Membership.objects.filter(practice=practice, user=actor, active=True, user__is_active=True, role="doctor").exists() or appointment.practitioner_id != actor.pk:
        raise ValidationError("Only the assigned active doctor can approve this appointment.")
    if appointment.status not in ["held", "confirmed", "arrived"]:
        raise ValidationError("Reception must approve this request before the doctor can confirm it.")
    if ready_now:
        if appointment.doctor_approved_at is None:
            raise ValidationError("Approve this appointment before calling the patient.")
        next_appointment = Appointment.objects.filter(practice=practice, practitioner=actor,
            status__in=["held", "confirmed", "arrived"], starts_at__date__gte=timezone.localdate()).order_by("starts_at", "pk").first()
        if next_appointment is None or next_appointment.pk != appointment.pk:
            raise ValidationError("Call the next patient in appointment order first.")
        if timezone.localtime(appointment.starts_at, ZoneInfo("Africa/Johannesburg")).date() != timezone.localdate(timezone=ZoneInfo("Africa/Johannesburg")):
            raise ValidationError("The Ready now alert is available only on the appointment day.")
        if appointment.called_at is not None:
            notify_doctor_ready(appointment=appointment, ready_now=True)
            return appointment
        appointment.called_at = timezone.now()
        appointment.save(update_fields=["called_at"])
    else:
        if appointment.doctor_approved_at is not None:
            notify_doctor_ready(appointment=appointment)
            return appointment
        appointment.doctor_approved_at = timezone.now()
        appointment.save(update_fields=["doctor_approved_at"])
    notify_doctor_ready(appointment=appointment, ready_now=ready_now)
    record_audit_event(practice=practice, actor=actor,
        action="appointment.patient_called" if ready_now else "appointment.doctor_approved",
        object_type="appointment", object_id=appointment.pk, purpose="Notify patient of doctor readiness", outcome="success")
    return appointment


@transaction.atomic
def record_intake(*, appointment_id, practice, actor, values):
    Practice.objects.select_for_update().get(pk=practice.pk)
    if not Membership.objects.filter(practice=practice, user=actor, active=True,
        role__in=["owner", "reception", "nurse"]).exists():
        raise ValidationError("Only active reception, owner or nurse staff can record intake.")
    appointment = Appointment.objects.select_for_update().get(pk=appointment_id, practice=practice)
    if appointment.status not in ["requested", "held", "confirmed", "arrived"] or appointment.doctor_approved_at:
        raise ValidationError("Record intake before doctor approval. Completed records cannot be changed here.")
    systolic = values.get("blood_pressure_systolic")
    diastolic = values.get("blood_pressure_diastolic")
    reason = values.get("reason_for_visit", "").strip()
    if (systolic is None) != (diastolic is None) or (systolic is not None and
        (not isinstance(systolic, int) or not isinstance(diastolic, int) or not 1 <= systolic <= 350 or not 1 <= diastolic <= 250)) or len(reason) > 2000:
        raise ValidationError("Check the symptoms and blood pressure values. Enter both readings or neither.")
    changed_bp = (systolic, diastolic) != (appointment.blood_pressure_systolic, appointment.blood_pressure_diastolic)
    appointment.reason_for_visit = reason
    appointment.blood_pressure_systolic = systolic
    appointment.blood_pressure_diastolic = diastolic
    if changed_bp:
        appointment.blood_pressure_recorded_at = timezone.now() if systolic is not None else None
        appointment.blood_pressure_recorded_by = actor if systolic is not None else None
    appointment.save(update_fields=["reason_for_visit", "blood_pressure_systolic", "blood_pressure_diastolic", "blood_pressure_recorded_at", "blood_pressure_recorded_by"])
    if appointment.status != "requested":
        from notifications.models import Notification
        notification = notify_appointment_approved(appointment=appointment)
        notification.message = doctor_intake_message(appointment)
        notification.read_at = None
        notification.save(update_fields=["message", "read_at"])
    record_audit_event(practice=practice, actor=actor, action="appointment.intake_recorded",
        object_type="appointment", object_id=appointment.pk, purpose="Record patient-reported symptoms and measured blood pressure", outcome="success")
    return appointment


@transaction.atomic
def complete_consultation(*, appointment_id, practice, actor):
    from clinical.models import Encounter
    Practice.objects.select_for_update().get(pk=practice.pk)
    appointment = Appointment.objects.select_for_update().get(pk=appointment_id, practice=practice)
    if appointment.practitioner_id != actor.pk or not Membership.objects.filter(
        practice=practice, user=actor, active=True, role="doctor").exists():
        raise ValidationError("Only the assigned doctor can complete a consultation.")
    encounter = Encounter.objects.select_for_update().filter(appointment=appointment, practitioner=actor).first()
    if encounter is None or appointment.doctor_approved_at is None:
        raise ValidationError("Open an approved consultation before completing it.")
    if appointment.status == "completed":
        return appointment
    if appointment.status not in ["held", "confirmed", "arrived"]:
        raise ValidationError("This consultation cannot be completed.")
    encounter.ended_at = timezone.now()
    encounter.save(update_fields=["ended_at"])
    appointment.status = "completed"
    appointment.save(update_fields=["status"])
    record_audit_event(practice=practice, actor=actor, action="appointment.consultation_completed",
        object_type="appointment", object_id=appointment.pk, purpose="Complete consultation and advance queue", outcome="success")
    return appointment
