from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from scheduling.models import Appointment, Service
from scheduling.services import approve_booking, reject_booking
from tenancy.models import Membership, Practice

from .models import Notification


User = get_user_model()


class AppointmentNotificationEventTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Notification Practice",
        )

        self.receptionist = User.objects.create_user(
            username="notification-receptionist",
            password="safe-test-password",
        )
        self.doctor = User.objects.create_user(
            username="notification-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )
        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="NOTIFICATION-001",
            given_name="Notification",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="General consultation",
            duration_minutes=30,
        )

        starts_at = timezone.now() + timedelta(days=1)

        self.appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.REQUESTED,
            hold_expires_at=None,
        )

    def test_approval_notifies_assigned_doctor(self):
        approve_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        notification = Notification.objects.get()

        self.assertEqual(
            notification.practice,
            self.practice,
        )
        self.assertEqual(
            notification.recipient,
            self.doctor,
        )
        self.assertEqual(
            notification.appointment,
            self.appointment,
        )
        self.assertEqual(
            notification.kind,
            Notification.Kind.APPOINTMENT_APPROVED,
        )
        self.assertEqual(
            notification.title,
            "Appointment approved",
        )
        self.assertIsNone(
            notification.read_at,
        )

    def test_rejection_notifies_assigned_doctor_with_reason(self):
        reason = "Practitioner unavailable."

        reject_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=self.receptionist,
            reason=reason,
        )

        notification = Notification.objects.get()

        self.assertEqual(
            notification.practice,
            self.practice,
        )
        self.assertEqual(
            notification.recipient,
            self.doctor,
        )
        self.assertEqual(
            notification.appointment,
            self.appointment,
        )
        self.assertEqual(
            notification.kind,
            Notification.Kind.APPOINTMENT_REJECTED,
        )
        self.assertEqual(
            notification.title,
            "Appointment rejected",
        )
        self.assertIn(
            reason,
            notification.message,
        )
        self.assertIsNone(
            notification.read_at,
        )
