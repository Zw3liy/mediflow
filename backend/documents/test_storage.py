from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from clinical.models import Encounter, Prescription
from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import PrescriptionDocument
from .storage import DocumentStorageError
from .storage_services import (
    create_patient_download_token,
    resolve_patient_download_token,
    upload_prescription_document,
)


User = get_user_model()


class FakeDocumentStorage:
    def __init__(self, *, fail_on_save=False):
        self.objects = {}
        self.fail_on_save = fail_on_save

    def save(self, *, object_key, content):
        if self.fail_on_save:
            raise DocumentStorageError("Storage unavailable.")

        self.objects[object_key] = content

    def delete(self, *, object_key):
        self.objects.pop(object_key, None)


class PrescriptionDocumentStorageTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Storage Practice",
        )

        self.doctor = User.objects.create_user(
            username="storage-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="storage-receptionist",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="storage-patient",
            password="safe-test-password",
        )
        self.other_patient_user = User.objects.create_user(
            username="other-storage-patient",
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
        Membership.objects.create(
            practice=self.practice,
            user=self.other_patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            portal_user=self.patient_user,
            file_number="STORAGE-001",
            given_name="Storage",
            family_name="Patient",
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

        self.storage = FakeDocumentStorage()

    def make_pdf(self, *, content=b"%PDF-1.7\nsafe test document"):
        return SimpleUploadedFile(
            "prescription.pdf",
            content,
            content_type="application/pdf",
        )

    def upload_document(self, **overrides):
        values = {
            "prescription_id": self.prescription.id,
            "practice": self.practice,
            "actor": self.receptionist,
            "uploaded_file": self.make_pdf(),
            "storage": self.storage,
        }
        values.update(overrides)

        return upload_prescription_document(**values)

    def test_pdf_upload_saves_bytes_and_metadata(self):
        document = self.upload_document()

        self.assertEqual(PrescriptionDocument.objects.count(), 1)
        self.assertIn(document.object_key, self.storage.objects)
        self.assertEqual(
            self.storage.objects[document.object_key],
            b"%PDF-1.7\nsafe test document",
        )
        self.assertEqual(document.content_type, "application/pdf")
        self.assertEqual(document.size_bytes, 27)
        self.assertEqual(len(document.sha256), 64)

    def test_non_pdf_upload_is_rejected_before_storage(self):
        uploaded_file = SimpleUploadedFile(
            "malware.exe",
            b"MZ unsafe executable",
            content_type="application/x-msdownload",
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only PDF prescription files are allowed.",
        ):
            self.upload_document(
                uploaded_file=uploaded_file,
            )

        self.assertEqual(self.storage.objects, {})
        self.assertEqual(PrescriptionDocument.objects.count(), 0)

    def test_oversized_upload_is_rejected_before_storage(self):
        uploaded_file = self.make_pdf(
            content=b"x" * ((10 * 1024 * 1024) + 1),
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Prescription file size must be between 1 byte and 10 MB.",
        ):
            self.upload_document(
                uploaded_file=uploaded_file,
            )

        self.assertEqual(self.storage.objects, {})
        self.assertEqual(PrescriptionDocument.objects.count(), 0)

    def test_storage_failure_creates_no_database_record(self):
        failing_storage = FakeDocumentStorage(
            fail_on_save=True,
        )

        with self.assertRaisesMessage(
            DocumentStorageError,
            "Storage unavailable.",
        ):
            self.upload_document(
                storage=failing_storage,
            )

        self.assertEqual(PrescriptionDocument.objects.count(), 0)

    def test_released_clean_document_token_resolves_for_patient(self):
        document = self.upload_document()
        document.scan_status = PrescriptionDocument.ScanStatus.CLEAN
        document.released_to_patient_at = timezone.now()
        document.save(
            update_fields=[
                "scan_status",
                "released_to_patient_at",
            ]
        )

        token = create_patient_download_token(
            document=document,
            user=self.patient_user,
        )

        resolved = resolve_patient_download_token(
            token=token,
            user=self.patient_user,
            max_age=300,
        )

        self.assertEqual(resolved, document)

    def test_download_is_denied_when_unreleased_or_wrong_patient(self):
        document = self.upload_document()
        document.scan_status = PrescriptionDocument.ScanStatus.CLEAN
        document.save(
            update_fields=[
                "scan_status",
            ]
        )

        with self.assertRaisesMessage(
            PermissionDenied,
            "Document is not available to this patient.",
        ):
            create_patient_download_token(
                document=document,
                user=self.patient_user,
            )

        document.released_to_patient_at = timezone.now()
        document.save(
            update_fields=[
                "released_to_patient_at",
            ]
        )

        with self.assertRaisesMessage(
            PermissionDenied,
            "Document is not available to this patient.",
        ):
            create_patient_download_token(
                document=document,
                user=self.other_patient_user,
            )

    def test_spoofed_pdf_content_is_rejected(self):
        uploaded_file = SimpleUploadedFile(
            "fake.pdf",
            b"MZ executable content",
            content_type="application/pdf",
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Uploaded file is not a valid PDF.",
        ):
            self.upload_document(
                uploaded_file=uploaded_file,
            )

        self.assertEqual(self.storage.objects, {})
        self.assertEqual(PrescriptionDocument.objects.count(), 0)
