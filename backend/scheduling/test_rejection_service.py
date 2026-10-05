from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Appointment, Service
from .services import reject_booking


User = get_user_model()


class AppointmentRejectionServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Rejection Practice",
        )

        self.receptionist = User.objects.create_user(
            username="rejection-receptionist",
            password="safe-test-password",
        )
        self.doctor = User.objects.create_user(
            username="rejection-doctor",
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
            file_number="REJECTION-001",
            given_name="Rejection",
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

    def test_active_receptionist_can_reject_requested_booking(self):
        before_rejection = timezone.now()

        rejected = reject_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=self.receptionist,
            reason="Practitioner unavailable.",
        )

        after_rejection = timezone.now()

        self.assertEqual(
            rejected.status,
            Appointment.Status.REJECTED,
        )
        self.assertEqual(
            rejected.decision_reason,
            "Practitioner unavailable.",
        )
        self.assertEqual(
            rejected.reviewed_by,
            self.receptionist,
        )
        self.assertGreaterEqual(
            rejected.reviewed_at,
            before_rejection,
        )
        self.assertLessEqual(
            rejected.reviewed_at,
            after_rejection,
        )
        self.assertIsNone(
            rejected.hold_expires_at,
        )

    def test_blank_rejection_reason_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "A rejection reason is required.",
        ):
            reject_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=self.receptionist,
                reason="   ",
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(self.appointment.reviewed_by)
        self.assertEqual(self.appointment.decision_reason, "")

    def test_doctor_cannot_reject_requested_booking(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Only active reception or owner staff may reject bookings.",
        ):
            reject_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=self.doctor,
                reason="Practitioner unavailable.",
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(self.appointment.reviewed_by)
        self.assertEqual(self.appointment.decision_reason, "")

    def test_active_owner_can_reject_requested_booking(self):
        owner = User.objects.create_user(
            username="rejection-owner",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=owner,
            role=Membership.Role.OWNER,
            active=True,
        )

        rejected = reject_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=owner,
            reason="Practice schedule changed.",
        )

        self.assertEqual(
            rejected.status,
            Appointment.Status.REJECTED,
        )
        self.assertEqual(
            rejected.reviewed_by,
            owner,
        )
        self.assertEqual(
            rejected.decision_reason,
            "Practice schedule changed.",
        )

    def test_held_booking_cannot_be_rejected(self):
        self.appointment.status = Appointment.Status.HELD
        self.appointment.hold_expires_at = (
            timezone.now() + timedelta(minutes=10)
        )
        self.appointment.save(
            update_fields=[
                "status",
                "hold_expires_at",
            ]
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only requested appointments may be rejected.",
        ):
            reject_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=self.receptionist,
                reason="Attempted late rejection.",
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.HELD,
        )
        self.assertIsNone(self.appointment.reviewed_by)
        self.assertEqual(self.appointment.decision_reason, "")

    def test_inactive_receptionist_cannot_reject_booking(self):
        inactive_receptionist = User.objects.create_user(
            username="inactive-rejection-receptionist",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=inactive_receptionist,
            role=Membership.Role.RECEPTION,
            active=False,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only active reception or owner staff may reject bookings.",
        ):
            reject_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=inactive_receptionist,
                reason="Practitioner unavailable.",
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(self.appointment.reviewed_by)

    def test_cross_practice_receptionist_cannot_reject_booking(self):
        other_practice = Practice.objects.create(
            name="Other Rejection Practice",
        )

        other_receptionist = User.objects.create_user(
            username="other-rejection-receptionist",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=other_practice,
            user=other_receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Appointment was not found in this practice.",
        ):
            reject_booking(
                appointment_id=self.appointment.id,
                practice=other_practice,
                actor=other_receptionist,
                reason="Invalid cross-practice rejection.",
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(self.appointment.reviewed_by)
