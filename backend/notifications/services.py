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
            "message": doctor_intake_message(appointment),
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
                "message": patient_appointment_message(appointment, reminder=True),
            },
        )

        if created:
            created_count += 1

    return created_count


def patient_appointment_message(appointment, *, ready_now=False, reminder=False):
    from django.utils import timezone
    from zoneinfo import ZoneInfo
    when = timezone.localtime(appointment.starts_at, ZoneInfo("Africa/Johannesburg")).strftime("%d %b %Y at %H:%M SAST")
    doctor = appointment.practitioner.get_full_name() or appointment.practitioner.username
    if reminder:
        return f"Hello {appointment.patient.given_name}, your appointment with Dr {doctor} at {appointment.practice.name} is scheduled for {when}. Check your app for personal readiness updates."
    if ready_now:
        return f"Hello {appointment.patient.given_name}, Dr {doctor} is ready to see you now at {appointment.practice.name}. Your scheduled appointment is {when}."
    return f"Hello {appointment.patient.given_name}, Dr {doctor} has approved your appointment and will be ready for you on {when} at {appointment.practice.name}. Check this app for updates."


def notify_doctor_ready(*, appointment, ready_now=False):
    from tenancy.models import Membership
    user = appointment.patient.portal_user
    if user is None or not user.is_active or not Membership.objects.filter(
        practice=appointment.practice, user=user, active=True, role="patient").exists():
        return None
    notification, _ = Notification.objects.get_or_create(practice=appointment.practice,
        recipient=user, appointment=appointment,
        kind=Notification.Kind.PATIENT_CALLED if ready_now else Notification.Kind.DOCTOR_READY,
        defaults={"title": "Your doctor is ready now" if ready_now else "Your doctor has approved your appointment",
                  "message": patient_appointment_message(appointment, ready_now=ready_now)})
    return notification


def doctor_intake_message(appointment):
    from django.utils import timezone
    from zoneinfo import ZoneInfo
    when = timezone.localtime(appointment.starts_at, ZoneInfo("Africa/Johannesburg")).strftime("%d %b %Y at %H:%M SAST")
    bp = f"{appointment.blood_pressure_systolic}/{appointment.blood_pressure_diastolic} mmHg" if appointment.blood_pressure_systolic else "Not yet measured"
    return (f"{appointment.patient.given_name} {appointment.patient.family_name} is booked for {when}. "
        f"Reported symptoms: {appointment.reason_for_visit or 'Not recorded yet'}. Blood pressure: {bp}. "
        "Review the appointment and approve it for the patient.")
