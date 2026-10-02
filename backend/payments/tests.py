from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Practice

from .gateways import HostedCheckout
from .models import DepositPayment
from .services import create_deposit_checkout


User = get_user_model()


class FakeGateway:
    provider_name = "fake-sandbox"

    def __init__(self):
        self.calls = 0

    def create_checkout(self, *, payment):
        self.calls += 1

        return HostedCheckout(
            provider_reference=f"sandbox-{payment.id}",
            checkout_url=(
                f"https://payments.example.test/checkout/{payment.id}"
            ),
        )


class FailingGateway:
    provider_name = "failing-sandbox"

    def create_checkout(self, *, payment):
        raise RuntimeError("Sandbox provider unavailable.")


class DepositPaymentServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(name="Practice A")
        self.other_practice = Practice.objects.create(
            name="Practice B"
        )
        self.doctor = User.objects.create_user(
            username="doctor",
            password="test-password",
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

    def test_deposit_amount_comes_from_service(self):
        gateway = FakeGateway()

        payment = create_deposit_checkout(
            appointment_id=self.appointment.id,
            practice=self.practice,
            gateway=gateway,
        )

        self.assertEqual(payment.amount_cents, 20000)
        self.assertEqual(payment.currency, "ZAR")
        self.assertEqual(
            payment.status,
            DepositPayment.Status.PENDING,
        )
        self.assertTrue(payment.checkout_url)
        self.assertEqual(gateway.calls, 1)

    def test_duplicate_checkout_is_not_created(self):
        gateway = FakeGateway()

        first = create_deposit_checkout(
            appointment_id=self.appointment.id,
            practice=self.practice,
            gateway=gateway,
        )
        second = create_deposit_checkout(
            appointment_id=self.appointment.id,
            practice=self.practice,
            gateway=gateway,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(gateway.calls, 1)
        self.assertEqual(
            DepositPayment.objects.filter(
                appointment=self.appointment,
            ).count(),
            1,
        )

    def test_cross_practice_request_is_rejected(self):
        gateway = FakeGateway()

        with self.assertRaises(ValidationError):
            create_deposit_checkout(
                appointment_id=self.appointment.id,
                practice=self.other_practice,
                gateway=gateway,
            )

        self.assertEqual(gateway.calls, 0)

    def test_zero_deposit_is_rejected(self):
        self.service.deposit_cents = 0
        self.service.save(update_fields=["deposit_cents"])

        with self.assertRaises(ValidationError):
            create_deposit_checkout(
                appointment_id=self.appointment.id,
                practice=self.practice,
                gateway=FakeGateway(),
            )

    def test_provider_failure_marks_payment_failed(self):
        with self.assertRaises(RuntimeError):
            create_deposit_checkout(
                appointment_id=self.appointment.id,
                practice=self.practice,
                gateway=FailingGateway(),
            )

        payment = DepositPayment.objects.get(
            appointment=self.appointment,
        )
        self.assertEqual(
            payment.status,
            DepositPayment.Status.FAILED,
        )
