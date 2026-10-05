from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Appointment, Service
from .services import book


User = get_user_model()


class BookingServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Booking Practice",
        )
        self.other_practice = Practice.objects.create(
            name="Other Practice",
        )

        self.doctor = User.objects.create_user(
            username="booking-doctor",
            password="safe-test-password",
        )
        self.other_doctor = User.objects.create_user(
            username="other-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )
        Membership.objects.create(
            practice=self.other_practice,
            user=self.other_doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="BOOK-001",
            given_name="Booking",
            family_name="Patient",
        )
        self.other_patient = Patient.objects.create(
            practice=self.other_practice,
            file_number="OTHER-BOOK-001",
            given_name="Other",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="Extended consultation",
            duration_minutes=45,
        )

        self.starts_at = timezone.now() + timedelta(days=1)

    def create_booking(self, **overrides):
        values = {
            "practice": self.practice,
            "patient": self.patient,
            "practitioner": self.doctor,
            "service": self.service,
            "starts_at": self.starts_at,
        }
        values.update(overrides)

        return book(**values)

    def test_duration_and_requested_state_are_calculated_by_service(self):
        appointment = self.create_booking()

        self.assertEqual(
            appointment.ends_at,
            self.starts_at + timedelta(minutes=45),
        )
        self.assertEqual(
            appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(appointment.hold_expires_at)


    def test_cross_practice_patient_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "The patient does not belong to this practice.",
        ):
            self.create_booking(patient=self.other_patient)

    def test_past_appointment_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Choose a future appointment time.",
        ):
            self.create_booking(
                starts_at=timezone.now() - timedelta(minutes=1),
            )

    def test_overlapping_active_booking_is_rejected(self):
        self.create_booking()

        with self.assertRaisesMessage(
            ValidationError,
            "That appointment time is no longer available.",
        ):
            self.create_booking(
                starts_at=self.starts_at + timedelta(minutes=15),
            )

    def test_cross_practice_practitioner_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "The practitioner is not active in this practice.",
        ):
            self.create_booking(practitioner=self.other_doctor)