from datetime import timedelta
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Appointment, Service
from .services import approve_booking


User = get_user_model()


class AppointmentApprovalServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Approval Practice",
        )

        self.receptionist = User.objects.create_user(
            username="approval-receptionist",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )

        self.doctor = User.objects.create_user(
            username="approval-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="APPROVAL-001",
            given_name="Approval",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="General consultation",
            duration_minutes=30,
        )

        self.starts_at = timezone.now() + timedelta(days=1)

        self.appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            service=self.service,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(minutes=30),
            status=Appointment.Status.REQUESTED,
            hold_expires_at=None,
        )

    def test_active_doctor_cannot_approve_booking(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Only active reception or owner staff may approve bookings.",
        ):
            approve_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=self.doctor,
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(
            self.appointment.reviewed_by,
        )
        self.assertIsNone(
            self.appointment.reviewed_at,
        )
        self.assertIsNone(
            self.appointment.hold_expires_at,
        )

    def test_active_owner_can_approve_requested_booking(self):
        owner = User.objects.create_user(
            username="approval-owner",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=owner,
            role=Membership.Role.OWNER,
            active=True,
        )

        approved = approve_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=owner,
        )

        self.assertEqual(
            approved.status,
            Appointment.Status.HELD,
        )
        self.assertEqual(
            approved.reviewed_by,
            owner,
        )
        self.assertIsNotNone(
            approved.reviewed_at,
        )
        self.assertIsNotNone(
            approved.hold_expires_at,
        )

    def test_active_receptionist_can_approve_requested_booking(self):
        before_approval = timezone.now()

        approved = approve_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        after_approval = timezone.now()

        self.assertEqual(
            approved.status,
            Appointment.Status.HELD,
        )
        self.assertEqual(
            approved.reviewed_by,
            self.receptionist,
        )
        self.assertGreaterEqual(
            approved.reviewed_at,
            before_approval,
        )
        self.assertLessEqual(
            approved.reviewed_at,
            after_approval,
        )
        self.assertGreaterEqual(
            approved.hold_expires_at,
            before_approval + timedelta(minutes=10),
        )
        self.assertLessEqual(
            approved.hold_expires_at,
            after_approval + timedelta(minutes=10),
        )
    def test_inactive_receptionist_cannot_approve_booking(self):
        inactive_receptionist = User.objects.create_user(
            username="inactive-receptionist",
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
            "Only active reception or owner staff may approve bookings.",
        ):
            approve_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=inactive_receptionist,
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(self.appointment.reviewed_by)
        self.assertIsNone(self.appointment.reviewed_at)
        self.assertIsNone(self.appointment.hold_expires_at)

    def test_cross_practice_receptionist_cannot_approve_booking(self):
        other_practice = Practice.objects.create(
            name="Other Approval Practice",
        )

        other_receptionist = User.objects.create_user(
            username="other-practice-receptionist",
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
            approve_booking(
                appointment_id=self.appointment.id,
                practice=other_practice,
                actor=other_receptionist,
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(self.appointment.reviewed_by)

    def test_held_booking_cannot_be_approved_again(self):
        first_approval = approve_booking(
            appointment_id=self.appointment.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        original_reviewed_at = first_approval.reviewed_at
        original_hold_expires_at = first_approval.hold_expires_at

        with self.assertRaisesMessage(
            ValidationError,
            "Only requested appointments may be approved.",
        ):
            approve_booking(
                appointment_id=self.appointment.id,
                practice=self.practice,
                actor=self.receptionist,
            )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.HELD,
        )
        self.assertEqual(
            self.appointment.reviewed_at,
            original_reviewed_at,
        )
        self.assertEqual(
            self.appointment.hold_expires_at,
            original_hold_expires_at,
        )
