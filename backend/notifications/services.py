from scheduling.models import Appointment
from .models import Notification


def notify_appointment_approved(*, appointment):
    notification, _created = Notification.objects.get_or_create(
        practice=appointment.practice,
        recipient=appointment.practitioner,
        appointment=appointment,
        kind=Notification.Kind.APPOINTMENT_APPROVED,
        defaults={
            "title": "Appointment approved",
            "message": (
                f"Appointment {appointment.id} was approved."
            ),
        },
    )

    return notification


def notify_appointment_rejected(*, appointment):
    notification, _created = Notification.objects.get_or_create(
        practice=appointment.practice,
        recipient=appointment.practitioner,
        appointment=appointment,
        kind=Notification.Kind.APPOINTMENT_REJECTED,
        defaults={
            "title": "Appointment rejected",
            "message": (
                f"Appointment {appointment.id} was rejected: "
                f"{appointment.decision_reason}"
            ),
        },
    )

    return notification


def create_upcoming_appointment_reminders(
    *,
    now,
    window,
):
    window_ends_at = now + window

    appointments = Appointment.objects.filter(
        status=Appointment.Status.CONFIRMED,
        starts_at__gt=now,
        starts_at__lte=window_ends_at,
        patient__portal_user__isnull=False,
    ).select_related(
        "practice",
        "patient",
        "patient__portal_user",
    )

    created_count = 0

    for appointment in appointments:
        _notification, created = Notification.objects.get_or_create(
            practice=appointment.practice,
            recipient=appointment.patient.portal_user,
            appointment=appointment,
            kind=Notification.Kind.APPOINTMENT_REMINDER,
            defaults={
                "title": "Appointment reminder",
                "message": (
                    f"Appointment {appointment.id} starts at "
                    f"{appointment.starts_at.isoformat()}."
                ),
            },
        )

        if created:
            created_count += 1

    return created_count
