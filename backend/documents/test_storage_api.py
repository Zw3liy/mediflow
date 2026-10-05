import tempfile
from pathlib import Path

from auditlog.models import AuditEvent
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from clinical.models import Encounter, Prescription
from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import PrescriptionDocument


User = get_user_model()


class PrescriptionDocumentStorageApiTests(APITestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

        self.settings_override = override_settings(
            DOCUMENT_STORAGE_ROOT=Path(
                self.temporary_directory.name,
            )
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.practice = Practice.objects.create(
            name="Storage API Practice",
        )

        self.doctor = User.objects.create_user(
            username="storage-api-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="storage-api-receptionist",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="storage-api-patient",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )
        Membership.objects.create(
            practice=self.practice,
            user=self.receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )
        Membership.objects.create(
            practice=self.practice,
            user=self.patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            portal_user=self.patient_user,
            file_number="STORAGE-API-001",
            given_name="Storage",
            family_name="API Patient",
        )

        self.encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )

        self.prescription = Prescription.objects.create(
            encounter=self.encounter,
            prescribed_by=self.doctor,
            status=Prescription.Status.ISSUED,
            issued_at=timezone.now(),
        )

        self.pdf_content = b"%PDF-1.7\npatient prescription"

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def upload_document(self):
        self.client.force_authenticate(
            user=self.receptionist,
        )

        return self.client.post(
            reverse("prescription-document-upload"),
            {
                "prescription": self.prescription.id,
                "file": SimpleUploadedFile(
                    "prescription.pdf",
                    self.pdf_content,
                    content_type="application/pdf",
                ),
            },
            format="multipart",
            **self.practice_headers(),
        )

    def test_receptionist_uploads_pdf_to_private_storage(self):
        response = self.upload_document()

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        document = PrescriptionDocument.objects.get()

        stored_path = (
            Path(self.temporary_directory.name)
            / document.object_key
        )

        self.assertTrue(stored_path.exists())
        self.assertEqual(
            stored_path.read_bytes(),
            self.pdf_content,
        )

    def test_patient_download_token_returns_exact_pdf_bytes(self):
        upload_response = self.upload_document()
        document = PrescriptionDocument.objects.get(
            id=upload_response.data["id"],
        )
        document.scan_status = PrescriptionDocument.ScanStatus.CLEAN
        document.released_to_patient_at = timezone.now()
        document.save(
            update_fields=[
                "scan_status",
                "released_to_patient_at",
            ]
        )

        self.client.force_authenticate(
            user=self.patient_user,
        )

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


        audit_event = AuditEvent.objects.get(
            action="document.downloaded",
        )
        self.assertEqual(
            audit_event.actor,
            self.patient_user,
        )
        self.assertEqual(
            audit_event.object_id,
            str(document.id),
        )
        self.assertEqual(
            audit_event.outcome,
            "success",
        )

    def test_pending_document_has_no_patient_download_token(self):
        upload_response = self.upload_document()
        document = PrescriptionDocument.objects.get(
            id=upload_response.data["id"],
        )

        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.post(
            reverse(
                "prescription-document-download-token",
                kwargs={"pk": document.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_patient_cannot_upload_prescription_document(self):
        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.post(
            reverse("prescription-document-upload"),
            {
                "prescription": self.prescription.id,
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
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            PrescriptionDocument.objects.count(),
            0,
        )
