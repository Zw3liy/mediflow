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
