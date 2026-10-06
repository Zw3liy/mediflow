from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase
from notifications.models import Notification
from portal import tests as fixtures
from .services import doctor_approve_booking


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class ConcurrentDoctorApprovalTests(TransactionTestCase):
    def setUp(self):
        fixtures.PortalTests.setUpTestData.__func__(self)
        self.appointment.status="held"
        self.appointment.save()

    def test_simultaneous_doctor_approvals_notify_patient_once(self):
        barrier=Barrier(2)
        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return doctor_approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.doctor).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:attempt(),range(2)))
        self.assertEqual(results,[self.appointment.pk,self.appointment.pk])
        self.assertEqual(Notification.objects.filter(appointment=self.appointment,recipient=self.patient_user,kind="doctor_ready").count(),1)
