from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from clinical.models import Encounter
from clinical.services import (
    create_prescription,
    issue_prescription,
)
from documents.scanning import scan_prescription_document
from documents.services import release_prescription_document
from documents.storage_services import upload_prescription_document
from patients.models import Patient
from scheduling.models import Appointment, Service
from scheduling.services import approve_booking, reject_booking
from tenancy.models import Membership, Practice

from .models import AuditEvent
from .services import verify_audit_chain


User = get_user_model()


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def save(self, *, object_key, content):
        self.objects[object_key] = content

    def delete(self, *, object_key):
        self.objects.pop(object_key, None)

    def read(self, *, object_key):
        return self.objects[object_key]


class CleanScanner:
    def scan(self, *, content):
        return "clean"


class AuditIntegrationTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Integrated Audit Practice",
        )
        self.doctor = User.objects.create_user(
            username="integrated-audit-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="integrated-audit-reception",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="integrated-audit-patient",
            password="safe-test-password",
        )

        for user, role in [
            (self.doctor, Membership.Role.DOCTOR),
            (self.receptionist, Membership.Role.RECEPTION),
            (self.patient_user, Membership.Role.PATIENT),
        ]:
            Membership.objects.create(
                practice=self.practice,
                user=user,
                role=role,
                active=True,
            )

        self.patient = Patient.objects.create(
            practice=self.practice,
            portal_user=self.patient_user,
            file_number="AUDIT-001",
            given_name="Audit",
            family_name="Patient",
        )
        self.service = Service.objects.create(
            practice=self.practice,
            name="Audit consultation",
            duration_minutes=30,
        )
        self.starts_at = timezone.now() + timedelta(days=1)
        self.storage = FakeStorage()

    def make_requested_appointment(self, *, offset_hours=0):
        starts_at = self.starts_at + timedelta(
            hours=offset_hours,
        )

        return Appointment.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            service=self.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.REQUESTED,
        )

    def test_clinical_workflow_writes_valid_ordered_audit_chain(self):
        approved_appointment = self.make_requested_appointment()
        rejected_appointment = self.make_requested_appointment(
            offset_hours=2,
        )

        approve_booking(
            appointment_id=approved_appointment.id,
            practice=self.practice,
            actor=self.receptionist,
        )
        reject_booking(
            appointment_id=rejected_appointment.id,
            practice=self.practice,
            actor=self.receptionist,
            reason="Requested time unavailable.",
        )

        encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            appointment=approved_appointment,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )
        prescription = create_prescription(
            encounter_id=encounter.id,
            actor=self.doctor,
            items=[
                {
                    "medication_name": "Audit medicine",
                    "dosage": "10 mg",
                    "frequency": "Once daily",
                },
            ],
        )
        prescription = issue_prescription(
            prescription_id=prescription.id,
            actor=self.doctor,
        )

        document = upload_prescription_document(
            prescription_id=prescription.id,
            practice=self.practice,
            actor=self.receptionist,
            uploaded_file=SimpleUploadedFile(
                "prescription.pdf",
                b"%PDF-1.7\nintegrated audit prescription",
                content_type="application/pdf",
            ),
            storage=self.storage,
        )
        document = scan_prescription_document(
            document_id=document.id,
            storage=self.storage,
            scanner=CleanScanner(),
        )
        release_prescription_document(
            document_id=document.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        events = list(
            AuditEvent.objects.filter(
                practice=self.practice,
            ).order_by("id")
        )

        self.assertEqual(
            [event.action for event in events],
            [
                "appointment.approved",
                "appointment.rejected",
                "prescription.created",
                "prescription.issued",
                "document.uploaded",
                "document.scan_clean",
                "document.released",
            ],
        )
        self.assertEqual(
            [event.actor for event in events],
            [
                self.receptionist,
                self.receptionist,
                self.doctor,
                self.doctor,
                self.receptionist,
                None,
                self.receptionist,
            ],
        )
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )

    def test_repeated_release_does_not_duplicate_audit_event(self):
        encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )
        prescription = create_prescription(
            encounter_id=encounter.id,
            actor=self.doctor,
            items=[
                {
                    "medication_name": "Medicine",
                    "dosage": "5 mg",
                    "frequency": "Daily",
                },
            ],
        )
        prescription = issue_prescription(
            prescription_id=prescription.id,
            actor=self.doctor,
        )
        document = upload_prescription_document(
            prescription_id=prescription.id,
            practice=self.practice,
            actor=self.receptionist,
            uploaded_file=SimpleUploadedFile(
                "prescription.pdf",
                b"%PDF-1.7\nrelease audit",
                content_type="application/pdf",
            ),
            storage=self.storage,
        )
        scan_prescription_document(
            document_id=document.id,
            storage=self.storage,
            scanner=CleanScanner(),
        )

        release_prescription_document(
            document_id=document.id,
            practice=self.practice,
            actor=self.receptionist,
        )
        release_prescription_document(
            document_id=document.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        self.assertEqual(
            AuditEvent.objects.filter(
                action="document.released",
            ).count(),
            1,
        )
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )
