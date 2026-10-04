from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership, Practice

from .models import DepositPayment


class DepositPaymentStatusApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()

        self.user = user_model.objects.create_user(
            username="payment-status-user",
            password="safe-test-password",
        )

        self.practice = Practice.objects.create(
            name="Payment Status Practice",
        )

        self.other_practice = Practice.objects.create(
            name="Other Practice",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.user,
            role=Membership.Role.OWNER,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="STATUS-001",
            given_name="Status",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="Status consultation",
            duration_minutes=30,
            price_cents=90000,
            deposit_cents=30000,
        )

        starts_at = timezone.now() + timedelta(days=1)

        self.appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.user,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.HELD,
        )

        self.payment = DepositPayment.objects.create(
            practice=self.practice,
            appointment=self.appointment,
            provider="sandbox",
            provider_reference="sandbox-status-reference",
            amount_cents=30000,
            currency="ZAR",
            status=DepositPayment.Status.PENDING,
            checkout_url="http://testserver/sandbox/",
        )

        self.url = reverse(
            "payments:deposit-payment-status",
            kwargs={"payment_id": self.payment.id},
        )

        self.client = APIClient()

    def authenticate(self):
        self.client.force_authenticate(user=self.user)

    def test_authentication_is_required(self):
        response = self.client.get(
            self.url,
            HTTP_X_PRACTICE_ID=str(self.practice.id),
        )

        self.assertIn(response.status_code, {401, 403})

    def test_practice_header_is_required(self):
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_status_is_returned_for_authorised_practice(self):
        self.authenticate()

        response = self.client.get(
            self.url,
            HTTP_X_PRACTICE_ID=str(self.practice.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["id"],
            str(self.payment.id),
        )
        self.assertEqual(
            response.data["status"],
            DepositPayment.Status.PENDING,
        )
        self.assertEqual(response.data["amount_cents"], 30000)
        self.assertEqual(response.data["currency"], "ZAR")
        self.assertEqual(response.data["provider"], "sandbox")

    def test_payment_from_another_practice_is_hidden(self):
        self.authenticate()

        other_patient = Patient.objects.create(
            practice=self.other_practice,
            file_number="OTHER-001",
            given_name="Other",
            family_name="Patient",
        )

        other_service = Service.objects.create(
            practice=self.other_practice,
            name="Other consultation",
            duration_minutes=30,
            price_cents=70000,
            deposit_cents=20000,
        )

        starts_at = timezone.now() + timedelta(days=2)

        other_appointment = Appointment.objects.create(
            practice=self.other_practice,
            patient=other_patient,
            practitioner=self.user,
            service=other_service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.HELD,
        )

        other_payment = DepositPayment.objects.create(
            practice=self.other_practice,
            appointment=other_appointment,
            provider="sandbox",
            provider_reference="sandbox-other-reference",
            amount_cents=20000,
            currency="ZAR",
            status=DepositPayment.Status.PENDING,
        )

        other_url = reverse(
            "payments:deposit-payment-status",
            kwargs={"payment_id": other_payment.id},
        )

        response = self.client.get(
            other_url,
            HTTP_X_PRACTICE_ID=str(self.practice.id),
        )

        self.assertEqual(response.status_code, 404)