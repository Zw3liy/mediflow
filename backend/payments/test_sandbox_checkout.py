from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Practice

from .models import DepositPayment, PaymentWebhookEvent


@override_settings(DEBUG=True)
class SandboxCheckoutTests(TestCase):
    def setUp(self):
        user_model = get_user_model()

        self.doctor = user_model.objects.create_user(
            username="sandbox-doctor",
            password="safe-test-password",
        )

        self.practice = Practice.objects.create(
            name="MediFlow Test Practice",
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="PAT-001",
            given_name="Demo",
            family_name="Patient",
        )

        self.service = Service.objects.create(
            practice=self.practice,
            name="General consultation",
            duration_minutes=30,
            price_cents=80000,
            deposit_cents=25000,
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

        self.payment = DepositPayment.objects.create(
            practice=self.practice,
            appointment=self.appointment,
            provider="sandbox",
            provider_reference="sandbox-test-reference",
            amount_cents=25000,
            currency="ZAR",
            status=DepositPayment.Status.PENDING,
            checkout_url="http://testserver/api/payments/sandbox/test/",
        )

        self.url = reverse(
            "payments:sandbox-checkout",
            kwargs={"payment_id": self.payment.id},
        )

    def test_checkout_page_displays_payment_information(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "General consultation")
        self.assertContains(response, "R250.00")
        self.assertContains(response, "Pay deposit")
        self.assertContains(response, "Cancel payment")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_pay_marks_payment_paid_and_confirms_appointment(self):
        response = self.client.post(
            self.url,
            {"action": "pay"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("result=paid", response["Location"])

        self.payment.refresh_from_db()
        self.appointment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            DepositPayment.Status.PAID,
        )
        self.assertIsNotNone(self.payment.paid_at)
        self.assertEqual(
            self.appointment.status,
            Appointment.Status.CONFIRMED,
        )

        event = PaymentWebhookEvent.objects.get(
            provider="sandbox",
            event_id=f"sandbox-paid-{self.payment.id}",
        )

        self.assertTrue(event.signature_verified)
        self.assertTrue(event.processed)
        self.assertEqual(event.event_type, "checkout.paid")

    def test_cancel_marks_payment_cancelled(self):
        response = self.client.post(
            self.url,
            {"action": "cancel"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("result=cancelled", response["Location"])

        self.payment.refresh_from_db()
        self.appointment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            DepositPayment.Status.CANCELLED,
        )
        self.assertEqual(
            self.appointment.status,
            Appointment.Status.HELD,
        )

    def test_completed_payment_cannot_be_processed_twice(self):
        self.payment.status = DepositPayment.Status.PAID
        self.payment.paid_at = timezone.now()
        self.payment.save(
            update_fields=[
                "status",
                "paid_at",
                "updated_at",
            ]
        )

        response = self.client.post(
            self.url,
            {"action": "cancel"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("result=unchanged", response["Location"])

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            DepositPayment.Status.PAID,
        )

    def test_unknown_action_is_rejected(self):
        response = self.client.post(
            self.url,
            {"action": "unexpected"},
        )

        self.assertEqual(response.status_code, 400)

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            DepositPayment.Status.PENDING,
        )

    @override_settings(DEBUG=False)
    def test_sandbox_is_unavailable_when_debug_is_disabled(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)