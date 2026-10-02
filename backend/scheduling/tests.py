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


class SchedulingApiTests(APITestCase):
    def setUp(self):
        self.practice_a = Practice.objects.create(name="Practice A")
        self.practice_b = Practice.objects.create(name="Practice B")

        self.doctor_a = User.objects.create_user(
            username="doctor_a",
            password="test-password-a",
        )
        self.doctor_b = User.objects.create_user(
            username="doctor_b",
            password="test-password-b",
        )

        Membership.objects.create(
            practice=self.practice_a,
            user=self.doctor_a,
            role=Membership.Role.DOCTOR,
        )
        Membership.objects.create(
            practice=self.practice_b,
            user=self.doctor_b,
            role=Membership.Role.DOCTOR,
        )

        self.patient_a = Patient.objects.create(
            practice=self.practice_a,
            file_number="A-001",
            given_name="Alice",
            family_name="Example",
        )
        self.patient_b = Patient.objects.create(
            practice=self.practice_b,
            file_number="B-001",
            given_name="Bob",
            family_name="Example",
        )

        self.service_a = Service.objects.create(
            practice=self.practice_a,
            name="Consultation A",
            duration_minutes=30,
        )
        self.service_b = Service.objects.create(
            practice=self.practice_b,
            name="Consultation B",
            duration_minutes=30,
        )

        self.starts_at = timezone.now() + timedelta(days=1)
        self.ends_at = self.starts_at + timedelta(minutes=30)

        self.appointment_a = Appointment.objects.create(
            practice=self.practice_a,
            patient=self.patient_a,
            practitioner=self.doctor_a,
            service=self.service_a,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
        )
        self.appointment_b = Appointment.objects.create(
            practice=self.practice_b,
            patient=self.patient_b,
            practitioner=self.doctor_b,
            service=self.service_b,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
        )

        self.appointment_url = reverse("appointment-list")
        self.service_url = reverse("service-list")
        self.client.force_authenticate(user=self.doctor_a)

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice_a.id),
        }

    def test_only_selected_practice_appointments_are_returned(self):
        response = self.client.get(
            self.appointment_url,
            **self.practice_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["id"],
            self.appointment_a.id,
        )

    def test_only_selected_practice_services_are_returned(self):
        response = self.client.get(
            self.service_url,
            **self.practice_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["id"],
            self.service_a.id,
        )

    def test_cross_practice_patient_is_rejected(self):
        response = self.client.post(
            self.appointment_url,
            {
                "patient": str(self.patient_b.id),
                "practitioner": self.doctor_a.id,
                "service": self.service_a.id,
                "starts_at": self.starts_at.isoformat(),
                "ends_at": self.ends_at.isoformat(),
                "status": Appointment.Status.CONFIRMED,
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("patient", response.data)

    def test_end_before_start_is_rejected(self):
        response = self.client.post(
            self.appointment_url,
            {
                "patient": str(self.patient_a.id),
                "practitioner": self.doctor_a.id,
                "service": self.service_a.id,
                "starts_at": self.ends_at.isoformat(),
                "ends_at": self.starts_at.isoformat(),
                "status": Appointment.Status.CONFIRMED,
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("ends_at", response.data)

    def test_valid_appointment_uses_selected_practice(self):
        new_start = self.starts_at + timedelta(hours=1)
        new_end = new_start + timedelta(minutes=30)

        response = self.client.post(
            self.appointment_url,
            {
                "patient": str(self.patient_a.id),
                "practitioner": self.doctor_a.id,
                "service": self.service_a.id,
                "starts_at": new_start.isoformat(),
                "ends_at": new_end.isoformat(),
                "status": Appointment.Status.CONFIRMED,
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        appointment = Appointment.objects.get(
            id=response.data["id"],
        )
        self.assertEqual(
            appointment.practice,
            self.practice_a,
        )
