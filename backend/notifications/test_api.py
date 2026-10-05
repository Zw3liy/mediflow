from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership, Practice

from .models import Notification


User = get_user_model()


class NotificationApiTests(APITestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Notification API Practice",
        )

        self.doctor = User.objects.create_user(
            username="notification-api-doctor",
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
            file_number="NOTIFICATION-API-001",
            given_name="Notification",
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
            status=Appointment.Status.HELD,
            hold_expires_at=timezone.now() + timedelta(minutes=10),
        )

        self.notification = Notification.objects.create(
            practice=self.practice,
            recipient=self.doctor,
            appointment=self.appointment,
            kind=Notification.Kind.APPOINTMENT_APPROVED,
            title="Appointment approved",
            message=f"Appointment {self.appointment.id} was approved.",
        )

        self.client.force_authenticate(
            user=self.doctor,
        )

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def test_doctor_can_list_own_notifications(self):
        response = self.client.get(
            reverse("notification-list"),
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
            self.notification.id,
        )
        self.assertEqual(
            response.data[0]["kind"],
            Notification.Kind.APPOINTMENT_APPROVED,
        )
        self.assertIsNone(
            response.data[0]["read_at"],
        )

    def test_doctor_cannot_see_another_doctors_notifications(self):
        other_doctor = User.objects.create_user(
            username="other-notification-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=other_doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        starts_at = timezone.now() + timedelta(days=2)

        other_appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=other_doctor,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.HELD,
            hold_expires_at=timezone.now() + timedelta(minutes=10),
        )

        Notification.objects.create(
            practice=self.practice,
            recipient=other_doctor,
            appointment=other_appointment,
            kind=Notification.Kind.APPOINTMENT_APPROVED,
            title="Appointment approved",
            message=f"Appointment {other_appointment.id} was approved.",
        )

        response = self.client.get(
            reverse("notification-list"),
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
            self.notification.id,
        )

    def test_doctor_can_mark_own_notification_as_read(self):
        before_marking = timezone.now()

        response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": self.notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        after_marking = timezone.now()

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIsNotNone(
            response.data["read_at"],
        )

        self.notification.refresh_from_db()

        self.assertGreaterEqual(
            self.notification.read_at,
            before_marking,
        )
        self.assertLessEqual(
            self.notification.read_at,
            after_marking,
        )

    def test_mark_read_is_idempotent(self):
        first_response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": self.notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        original_read_at = first_response.data["read_at"]

        second_response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": self.notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            second_response.data["read_at"],
            original_read_at,
        )

    def test_doctor_cannot_mark_another_doctors_notification_as_read(self):
        other_doctor = User.objects.create_user(
            username="protected-notification-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=other_doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        starts_at = timezone.now() + timedelta(days=2)

        other_appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=other_doctor,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.HELD,
            hold_expires_at=timezone.now() + timedelta(minutes=10),
        )

        other_notification = Notification.objects.create(
            practice=self.practice,
            recipient=other_doctor,
            appointment=other_appointment,
            kind=Notification.Kind.APPOINTMENT_APPROVED,
            title="Appointment approved",
            message=f"Appointment {other_appointment.id} was approved.",
        )

        response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": other_notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        other_notification.refresh_from_db()

        self.assertIsNone(
            other_notification.read_at,
        )

    def test_mark_read_is_idempotent(self):
        first_response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": self.notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        original_read_at = first_response.data["read_at"]

        second_response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": self.notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            second_response.data["read_at"],
            original_read_at,
        )

    def test_doctor_cannot_mark_another_doctors_notification_as_read(self):
        other_doctor = User.objects.create_user(
            username="protected-notification-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=other_doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        starts_at = timezone.now() + timedelta(days=2)

        other_appointment = Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=other_doctor,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.HELD,
            hold_expires_at=timezone.now() + timedelta(minutes=10),
        )

        other_notification = Notification.objects.create(
            practice=self.practice,
            recipient=other_doctor,
            appointment=other_appointment,
            kind=Notification.Kind.APPOINTMENT_APPROVED,
            title="Appointment approved",
            message=f"Appointment {other_appointment.id} was approved.",
        )

        response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"pk": other_notification.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        other_notification.refresh_from_db()

        self.assertIsNone(
            other_notification.read_at,
        )
