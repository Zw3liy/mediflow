from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Appointment, Service


User = get_user_model()


class AppointmentApprovalApiTests(APITestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Approval API Practice",
        )

        self.receptionist = User.objects.create_user(
            username="approval-api-receptionist",
            password="safe-test-password",
        )
        self.doctor = User.objects.create_user(
            username="approval-api-doctor",
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
            file_number="APPROVAL-API-001",
            given_name="Approval",
            family_name="API Patient",
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

        self.client.force_authenticate(
            user=self.receptionist,
        )

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def test_receptionist_can_approve_requested_appointment(self):
        response = self.client.post(
            reverse(
                "appointment-approve",
                kwargs={"pk": self.appointment.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.HELD,
        )
        self.assertEqual(
            self.appointment.reviewed_by,
            self.receptionist,
        )
        self.assertIsNotNone(
            self.appointment.reviewed_at,
        )
        self.assertIsNotNone(
            self.appointment.hold_expires_at,
        )

    def test_doctor_cannot_approve_requested_appointment(self):
        self.client.force_authenticate(
            user=self.doctor,
        )

        response = self.client.post(
            reverse(
                "appointment-approve",
                kwargs={"pk": self.appointment.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "Only active reception or owner staff may approve bookings.",
            response.data["detail"],
        )

        self.appointment.refresh_from_db()

        self.assertEqual(
            self.appointment.status,
            Appointment.Status.REQUESTED,
        )
        self.assertIsNone(
            self.appointment.reviewed_by,
        )

    def test_approval_response_contains_read_only_audit_fields(self):
        response = self.client.post(
            reverse(
                "appointment-approve",
                kwargs={"pk": self.appointment.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["reviewed_by"],
            self.receptionist.id,
        )
        self.assertIsNotNone(
            response.data["reviewed_at"],
        )
        self.assertEqual(
            response.data["decision_reason"],
            "",
        )
