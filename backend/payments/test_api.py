from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership, Practice

from .models import DepositPayment


User = get_user_model()


class DepositCheckoutApiTests(APITestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Practice A")
        self.other_practice = Practice.objects.create(
            name="Practice B"
        )
        self.doctor = User.objects.create_user(
            username="doctor",
            password="test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="A-001",
            given_name="Alice",
            family_name="Example",
        )
        self.service = Service.objects.create(
            practice=self.practice,
            name="Consultation",
            duration_minutes=30,
            price_cents=80000,
            deposit_cents=20000,
        )

        starts_at = timezone.now() + timedelta(days=1)

        self.appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.HELD,
        )

        self.url = reverse(
            "payments:create-deposit-checkout"
        )

    def headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def test_authentication_is_required(self):
        response = self.client.post(
            self.url,
            {"appointment_id": self.appointment.id},
            format="json",
            **self.headers(),
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_practice_header_is_required(self):
        self.client.force_authenticate(user=self.doctor)

        response = self.client.post(
            self.url,
            {"appointment_id": self.appointment.id},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_checkout_uses_trusted_deposit_amount(self):
        self.client.force_authenticate(user=self.doctor)

        response = self.client.post(
            self.url,
            {"appointment_id": self.appointment.id},
            format="json",
            **self.headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["amount_cents"], 20000)
        self.assertEqual(response.data["currency"], "ZAR")
        self.assertEqual(response.data["provider"], "sandbox")
        self.assertEqual(
            response.data["status"],
            DepositPayment.Status.PENDING,
        )
        self.assertIn(
            "/api/payments/sandbox/",
            response.data["checkout_url"],
        )

    def test_cross_practice_access_is_rejected(self):
        self.client.force_authenticate(user=self.doctor)

        response = self.client.post(
            self.url,
            {"appointment_id": self.appointment.id},
            format="json",
            HTTP_X_PRACTICE_ID=str(self.other_practice.id),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_repeated_request_reuses_payment(self):
        self.client.force_authenticate(user=self.doctor)

        first = self.client.post(
            self.url,
            {"appointment_id": self.appointment.id},
            format="json",
            **self.headers(),
        )
        second = self.client.post(
            self.url,
            {"appointment_id": self.appointment.id},
            format="json",
            **self.headers(),
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(DepositPayment.objects.count(), 1)