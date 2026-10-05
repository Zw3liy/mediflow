from io import StringIO
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership, Practice

from .models import Notification
from .services import create_upcoming_appointment_reminders


User = get_user_model()


class AppointmentReminderServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Reminder Practice",
        )

        self.doctor = User.objects.create_user(
            username="reminder-doctor",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="reminder-patient",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )
        Membership.objects.create(
            practice=self.practice,
            user=self.patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            portal_user=self.patient_user,
            file_number="REMINDER-001",
            given_name="Reminder",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="General consultation",
            duration_minutes=30,
        )

        self.now = timezone.now()

        self.appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            service=self.service,
            starts_at=self.now + timedelta(hours=23),
            ends_at=self.now + timedelta(hours=23, minutes=30),
            status=Appointment.Status.CONFIRMED,
        )

    def test_upcoming_confirmed_appointment_creates_one_reminder(self):
        first_count = create_upcoming_appointment_reminders(
            now=self.now,
            window=timedelta(hours=24),
        )
        second_count = create_upcoming_appointment_reminders(
            now=self.now,
            window=timedelta(hours=24),
        )

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(Notification.objects.count(), 1)

        notification = Notification.objects.get()

        self.assertEqual(
            notification.practice,
            self.practice,
        )
        self.assertEqual(
            notification.recipient,
            self.patient_user,
        )
        self.assertEqual(
            notification.appointment,
            self.appointment,
        )
        self.assertEqual(
            notification.kind,
            "appointment_reminder",
        )
        self.assertEqual(
            notification.title,
            "Appointment reminder",
        )
        self.assertIsNone(
            notification.read_at,
        )

    def test_cancelled_appointment_does_not_create_reminder(self):
        self.appointment.status = Appointment.Status.CANCELLED
        self.appointment.save(
            update_fields=[
                "status",
            ]
        )

        created_count = create_upcoming_appointment_reminders(
            now=self.now,
            window=timedelta(hours=24),
        )

        self.assertEqual(created_count, 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_appointment_outside_window_does_not_create_reminder(self):
        self.appointment.starts_at = self.now + timedelta(hours=25)
        self.appointment.ends_at = (
            self.appointment.starts_at + timedelta(minutes=30)
        )
        self.appointment.save(
            update_fields=[
                "starts_at",
                "ends_at",
            ]
        )

        created_count = create_upcoming_appointment_reminders(
            now=self.now,
            window=timedelta(hours=24),
        )

        self.assertEqual(created_count, 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_patient_without_portal_user_gets_no_reminder(self):
        self.patient.portal_user = None
        self.patient.save(
            update_fields=[
                "portal_user",
            ]
        )

        created_count = create_upcoming_appointment_reminders(
            now=self.now,
            window=timedelta(hours=24),
        )

        self.assertEqual(created_count, 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_management_command_creates_reminders_idempotently(self):
        first_output = StringIO()
        second_output = StringIO()

        call_command(
            "send_appointment_reminders",
            hours=24,
            stdout=first_output,
        )
        call_command(
            "send_appointment_reminders",
            hours=24,
            stdout=second_output,
        )

        self.assertEqual(Notification.objects.count(), 1)
        self.assertIn(
            "Created 1 appointment reminder",
            first_output.getvalue(),
        )
        self.assertIn(
            "Created 0 appointment reminders",
            second_output.getvalue(),
        )
