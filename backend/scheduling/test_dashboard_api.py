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


class AppointmentDashboardApiTests(APITestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Dashboard Practice",
        )

        self.doctor_a = User.objects.create_user(
            username="dashboard-doctor-a",
            password="safe-test-password",
        )
        self.doctor_b = User.objects.create_user(
            username="dashboard-doctor-b",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="dashboard-receptionist",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor_a,
            role=Membership.Role.DOCTOR,
            active=True,
        )
        Membership.objects.create(
            practice=self.practice,
            user=self.doctor_b,
            role=Membership.Role.DOCTOR,
            active=True,
        )
        Membership.objects.create(
            practice=self.practice,
            user=self.receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="DASHBOARD-001",
            given_name="Dashboard",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="General consultation",
            duration_minutes=30,
        )

        starts_at = timezone.now() + timedelta(days=1)

        self.appointment_a = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor_a,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.REQUESTED,
        )
        self.appointment_b = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor_b,
            service=self.service,
            starts_at=starts_at + timedelta(hours=1),
            ends_at=starts_at + timedelta(hours=1, minutes=30),
            status=Appointment.Status.REQUESTED,
        )

        self.appointment_url = reverse("appointment-list")

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def test_doctor_sees_only_assigned_appointments(self):
        self.client.force_authenticate(
            user=self.doctor_a,
        )

        response = self.client.get(
            self.appointment_url,
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data),
            1,
        )
        self.assertEqual(
            response.data[0]["id"],
            self.appointment_a.id,
        )

    def test_receptionist_sees_entire_practice_queue(self):
        self.client.force_authenticate(
            user=self.receptionist,
        )

        response = self.client.get(
            self.appointment_url,
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data),
            2,
        )
        self.assertEqual(
            {
                item["id"]
                for item in response.data
            },
            {
                self.appointment_a.id,
                self.appointment_b.id,
            },
        )

    def test_receptionist_can_filter_requested_queue(self):
        self.appointment_b.status = Appointment.Status.CONFIRMED
        self.appointment_b.save(
            update_fields=[
                "status",
            ]
        )

        self.client.force_authenticate(
            user=self.receptionist,
        )

        response = self.client.get(
            self.appointment_url,
            {
                "status": Appointment.Status.REQUESTED,
            },
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data),
            1,
        )
        self.assertEqual(
            response.data[0]["id"],
            self.appointment_a.id,
        )

    def test_invalid_status_filter_is_rejected(self):
        self.client.force_authenticate(
            user=self.receptionist,
        )

        response = self.client.get(
            self.appointment_url,
            {
                "status": "not-a-real-status",
            },
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            str(response.data["status"]),
            "Invalid appointment status.",
        )
