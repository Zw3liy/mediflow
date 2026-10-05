from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from patients.models import Patient
from tenancy.models import Membership, Practice
from .models import Appointment, Service
from .services import book, approve_booking, update_booking


def fixtures(test):
    test.practice = Practice.objects.create(name="Regression practice")
    test.doctor = get_user_model().objects.create_user(username="regression-doctor")
    test.receptionist = get_user_model().objects.create_user(username="regression-reception")
    for user, role in [(test.doctor, Membership.Role.DOCTOR), (test.receptionist, Membership.Role.RECEPTION)]:
        Membership.objects.create(practice=test.practice, user=user, role=role)
    test.patient = Patient.objects.create(practice=test.practice, file_number="REG-1", given_name="Test", family_name="Patient")
    test.other_patient = Patient.objects.create(practice=test.practice, file_number="REG-2", given_name="Other", family_name="Patient")
    test.service = Service.objects.create(practice=test.practice, name="Consultation", duration_minutes=30)
    test.starts_at = timezone.now() + timedelta(days=2)


def booking(test, starts_at=None):
    return book(practice=test.practice, patient=test.patient, practitioner=test.doctor, service=test.service, starts_at=starts_at or test.starts_at)


class BookingUpdateRegressionTests(APITestCase):
    def setUp(self):
        fixtures(self)
        self.appointment = booking(self)
        self.client.force_authenticate(self.doctor)
        self.url = reverse("appointment-detail", kwargs={"pk": self.appointment.pk})
        self.headers = {"HTTP_X_PRACTICE_ID": str(self.practice.pk)}

    def patch(self, **data):
        return self.client.patch(self.url, data, format="json", **self.headers)

    def test_approved_patient_practitioner_service_and_time_cannot_change(self):
        approve_booking(appointment_id=self.appointment.pk, practice=self.practice, actor=self.receptionist)
        doctor = get_user_model().objects.create_user(username="second-doctor")
        Membership.objects.create(practice=self.practice, user=doctor, role=Membership.Role.DOCTOR)
        service = Service.objects.create(practice=self.practice, name="Extended", duration_minutes=60)
        for actor in [self.doctor, self.receptionist]:
            self.client.force_authenticate(actor)
            for data in [{"patient": self.other_patient.pk}, {"practitioner": doctor.pk}, {"service": service.pk}, {"starts_at": (self.starts_at + timedelta(days=1)).isoformat()}]:
                with self.subTest(actor=actor.pk, data=data):
                    self.assertEqual(self.patch(**data).status_code, 400)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.patient_id, self.patient.pk)
        self.assertEqual(self.appointment.practitioner_id, self.doctor.pk)
        self.assertEqual(self.appointment.service_id, self.service.pk)
        self.assertEqual(self.appointment.starts_at, self.starts_at)
        self.assertEqual(self.appointment.status, Appointment.Status.HELD)
        self.assertEqual(self.appointment.reviewed_by_id, self.receptionist.pk)

    def test_requested_reschedule_recalculates_end_even_after_previous_end(self):
        new_start = self.starts_at + timedelta(days=1)
        response = self.patch(starts_at=new_start.isoformat())
        self.assertEqual(response.status_code, 200, response.data)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.ends_at, new_start + timedelta(minutes=30))
        self.assertEqual(self.appointment.status, Appointment.Status.REQUESTED)

    def test_requested_service_change_recalculates_duration(self):
        service = Service.objects.create(practice=self.practice, name="Extended", duration_minutes=60)
        response = self.patch(service=service.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.ends_at, self.starts_at + timedelta(minutes=60))

    def test_reschedule_into_occupied_slot_is_rejected(self):
        occupied = self.starts_at + timedelta(hours=1)
        booking(self, occupied)
        self.assertEqual(self.patch(starts_at=occupied.isoformat()).status_code, 400)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.starts_at, self.starts_at)

    def test_duration_extension_into_occupied_slot_is_rejected(self):
        booking(self, self.starts_at + timedelta(minutes=45))
        service = Service.objects.create(practice=self.practice, name="Extended", duration_minutes=60)
        self.assertEqual(self.patch(service=service.pk).status_code, 400)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.service_id, self.service.pk)

    def test_past_reschedule_is_rejected(self):
        self.assertEqual(self.patch(starts_at=(timezone.now() - timedelta(days=1)).isoformat()).status_code, 400)

    def test_noop_update_does_not_conflict_with_itself(self):
        self.assertEqual(self.patch(starts_at=self.starts_at.isoformat()).status_code, 200)


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class ConcurrentBookingRegressionTests(TransactionTestCase):
    def setUp(self):
        fixtures(self)

    def test_simultaneous_requests_for_empty_slot_create_only_one_booking(self):
        barrier = Barrier(2)
        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    booking(self)
                    return "created"
                except ValidationError as error:
                    self.assertIn("That appointment time is no longer available.", error.messages)
                    return "rejected"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ["created", "rejected"])
        self.assertEqual(Appointment.objects.filter(practice=self.practice).count(), 1)


    def test_booking_and_reschedule_cannot_claim_same_slot(self):
        appointment = booking(self)
        destination = self.starts_at + timedelta(hours=2)
        barrier = Barrier(2)
        def attempt(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    if operation == "create":
                        booking(self, destination)
                    else:
                        update_booking(
                            appointment_id=appointment.pk, practice=self.practice,
                            actor=self.doctor, changes={"starts_at": destination},
                        )
                    return "success"
                except ValidationError as error:
                    self.assertIn("That appointment time is no longer available.", error.messages)
                    return "rejected"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, ["create", "update"]))
        self.assertCountEqual(results, ["success", "rejected"])
        self.assertEqual(Appointment.objects.filter(
            practice=self.practice, starts_at=destination,
        ).count(), 1)
