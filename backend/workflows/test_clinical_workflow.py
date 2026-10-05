from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from auditlog.models import AuditEvent
from auditlog.services import verify_audit_chain
from clinical.models import Encounter, Prescription
from documents.models import PrescriptionDocument
from documents.scanning import scan_prescription_document
from documents.storage import LocalDocumentStorage
from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership, Practice


User = get_user_model()


class CleanScanner:
    def scan(self, *, content):
        return "clean"


class CompleteClinicalWorkflowTests(APITestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

        self.settings_override = override_settings(
            DOCUMENT_STORAGE_ROOT=Path(
                self.temporary_directory.name,
            ),
            DOCUMENT_DOWNLOAD_TOKEN_MAX_AGE=300,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.practice = Practice.objects.create(
            name="End-to-End Practice",
        )
        self.doctor = User.objects.create_user(
            username="e2e-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="e2e-receptionist",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="e2e-patient",
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
            file_number="E2E-001",
            given_name="End-to-End",
            family_name="Patient",
        )
        self.service = Service.objects.create(
            practice=self.practice,
            name="End-to-End consultation",
            duration_minutes=30,
        )
        self.starts_at = timezone.now() + timedelta(days=1)
        self.pdf_content = (
            b"%PDF-1.7\nMediFlow end-to-end prescription"
        )

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_complete_approved_prescription_document_workflow(self):
        # Doctor submits an appointment request.
        self.authenticate(self.doctor)

        booking_response = self.client.post(
            reverse("appointment-list"),
            {
                "patient": str(self.patient.id),
                "practitioner": self.doctor.id,
                "service": self.service.id,
                "starts_at": self.starts_at.isoformat(),
                "ends_at": (
                    self.starts_at + timedelta(minutes=30)
                ).isoformat(),
                "status": Appointment.Status.CONFIRMED,
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            booking_response.status_code,
            status.HTTP_201_CREATED,
        )

        appointment = Appointment.objects.get(
            pk=booking_response.data["id"],
        )
        self.assertEqual(
            appointment.status,
            Appointment.Status.REQUESTED,
        )

        # Reception approves the requested appointment.
        self.authenticate(self.receptionist)

        approval_response = self.client.post(
            reverse(
                "appointment-approve",
                kwargs={"pk": appointment.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            approval_response.status_code,
            status.HTTP_200_OK,
        )

        appointment.refresh_from_db()
        self.assertEqual(
            appointment.status,
            Appointment.Status.HELD,
        )

        # The approved appointment becomes a clinical encounter.
        encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            appointment=appointment,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )

        # The responsible doctor creates and issues a prescription.
        self.authenticate(self.doctor)

        prescription_response = self.client.post(
            reverse("prescription-list"),
            {
                "encounter": str(encounter.id),
                "general_instructions": "Take after food.",
                "items": [
                    {
                        "medication_name": "Amoxicillin",
                        "dosage": "500 mg",
                        "route": "Oral",
                        "frequency": "Three times daily",
                        "duration": "5 days",
                        "quantity": "15 capsules",
                        "instructions": "Complete the course.",
                    },
                ],
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            prescription_response.status_code,
            status.HTTP_201_CREATED,
        )

        prescription = Prescription.objects.get(
            pk=prescription_response.data["id"],
        )
        self.assertEqual(
            prescription.status,
            Prescription.Status.DRAFT,
        )

        issue_response = self.client.post(
            reverse(
                "prescription-issue",
                kwargs={"pk": prescription.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            issue_response.status_code,
            status.HTTP_200_OK,
        )

        prescription.refresh_from_db()
        self.assertEqual(
            prescription.status,
            Prescription.Status.ISSUED,
        )

        # Reception uploads the generated PDF into private storage.
        self.authenticate(self.receptionist)

        upload_response = self.client.post(
            reverse("prescription-document-upload"),
            {
                "prescription": prescription.id,
                "file": SimpleUploadedFile(
                    "prescription.pdf",
                    self.pdf_content,
                    content_type="application/pdf",
                ),
            },
            format="multipart",
            **self.practice_headers(),
        )

        self.assertEqual(
            upload_response.status_code,
            status.HTTP_201_CREATED,
        )

        document = PrescriptionDocument.objects.get(
            pk=upload_response.data["id"],
        )
        self.assertEqual(
            document.scan_status,
            PrescriptionDocument.ScanStatus.PENDING,
        )

        # The scanner marks the private file clean.
        storage = LocalDocumentStorage(
            root=self.temporary_directory.name,
        )
        document = scan_prescription_document(
            document_id=document.id,
            storage=storage,
            scanner=CleanScanner(),
        )

        self.assertEqual(
            document.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )

        # Reception releases the clean document.
        release_response = self.client.post(
            reverse(
                "prescription-document-release",
                kwargs={"pk": document.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            release_response.status_code,
            status.HTTP_200_OK,
        )

        document.refresh_from_db()
        self.assertIsNotNone(
            document.released_to_patient_at,
        )

        # The correct patient obtains a token and downloads exact bytes.
        self.authenticate(self.patient_user)

        token_response = self.client.post(
            reverse(
                "prescription-document-download-token",
                kwargs={"pk": document.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            token_response.status_code,
            status.HTTP_200_OK,
        )

        download_response = self.client.get(
            reverse(
                "prescription-document-download",
                kwargs={"pk": document.id},
            ),
            {
                "token": token_response.data["token"],
            },
            **self.practice_headers(),
        )

        self.assertEqual(
            download_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            download_response.content,
            self.pdf_content,
        )
        self.assertEqual(
            download_response["Content-Type"],
            "application/pdf",
        )

        # Every protected transition forms one valid audit chain.
        events = list(
            AuditEvent.objects.filter(
                practice=self.practice,
            ).order_by("id")
        )

        self.assertEqual(
            [event.action for event in events],
            [
                "appointment.approved",
                "prescription.created",
                "prescription.issued",
                "document.uploaded",
                "document.scan_clean",
                "document.released",
                "document.downloaded",
            ],
        )
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )
