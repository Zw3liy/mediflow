from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from clinical.models import Encounter, Prescription
from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import PrescriptionDocument
from .scanning import scan_prescription_document
from .storage import DocumentStorageError
from .storage_services import upload_prescription_document


User = get_user_model()


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.read_count = 0

    def save(self, *, object_key, content):
        self.objects[object_key] = content

    def delete(self, *, object_key):
        self.objects.pop(object_key, None)

    def read(self, *, object_key):
        self.read_count += 1

        try:
            return self.objects[object_key]
        except KeyError as error:
            raise DocumentStorageError(
                "Document storage read failed."
            ) from error


class FakeScanner:
    def __init__(self, *, result="clean", error=None):
        self.result = result
        self.error = error
        self.scanned_content = []

    def scan(self, *, content):
        self.scanned_content.append(content)

        if self.error:
            raise self.error

        return self.result


class PrescriptionDocumentScanningTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Scanning Practice",
        )
        self.doctor = User.objects.create_user(
            username="scanning-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="scanning-receptionist",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="scanning-patient",
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
            file_number="SCAN-001",
            given_name="Scan",
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

        self.storage = FakeStorage()
        self.document = upload_prescription_document(
            prescription_id=self.prescription.id,
            practice=self.practice,
            actor=self.receptionist,
            uploaded_file=SimpleUploadedFile(
                "prescription.pdf",
                b"%PDF-1.7\nsafe prescription",
                content_type="application/pdf",
            ),
            storage=self.storage,
        )

    def scan(self, *, scanner):
        return scan_prescription_document(
            document_id=self.document.id,
            storage=self.storage,
            scanner=scanner,
        )

    def test_uploaded_document_starts_pending(self):
        self.assertEqual(
            self.document.scan_status,
            PrescriptionDocument.ScanStatus.PENDING,
        )
        self.assertIsNone(
            self.document.released_to_patient_at,
        )

    def test_clean_scan_marks_pending_document_clean(self):
        scanner = FakeScanner(result="clean")

        scanned = self.scan(scanner=scanner)

        self.assertEqual(
            scanned.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )
        self.assertEqual(
            scanner.scanned_content,
            [b"%PDF-1.7\nsafe prescription"],
        )

    def test_infected_scan_marks_document_infected(self):
        scanned = self.scan(
            scanner=FakeScanner(result="infected"),
        )

        self.assertEqual(
            scanned.scan_status,
            PrescriptionDocument.ScanStatus.INFECTED,
        )
        self.assertIsNone(scanned.released_to_patient_at)

    def test_scanner_error_marks_document_failed(self):
        scanned = self.scan(
            scanner=FakeScanner(
                error=RuntimeError("Scanner unavailable."),
            ),
        )

        self.assertEqual(
            scanned.scan_status,
            PrescriptionDocument.ScanStatus.FAILED,
        )
        self.assertIsNone(scanned.released_to_patient_at)

    def test_missing_stored_object_marks_document_failed(self):
        self.storage.objects.clear()

        scanned = self.scan(
            scanner=FakeScanner(),
        )

        self.assertEqual(
            scanned.scan_status,
            PrescriptionDocument.ScanStatus.FAILED,
        )
        self.assertIsNone(scanned.released_to_patient_at)

    def test_terminal_scan_status_is_not_scanned_again(self):
        self.document.scan_status = (
            PrescriptionDocument.ScanStatus.CLEAN
        )
        self.document.save(
            update_fields=["scan_status"],
        )
        scanner = FakeScanner(result="infected")

        scanned = self.scan(scanner=scanner)

        self.assertEqual(
            scanned.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )
        self.assertEqual(scanner.scanned_content, [])
        self.assertEqual(self.storage.read_count, 0)

    def test_unknown_scanner_result_marks_document_failed(self):
        scanned = self.scan(
            scanner=FakeScanner(result="unknown"),
        )

        self.assertEqual(
            scanned.scan_status,
            PrescriptionDocument.ScanStatus.FAILED,
        )
        self.assertIsNone(scanned.released_to_patient_at)

    def test_management_command_scans_only_pending_documents(self):
        self.document.scan_status = (
            PrescriptionDocument.ScanStatus.CLEAN
        )
        self.document.save(
            update_fields=["scan_status"],
        )

        pending_document = upload_prescription_document(
            prescription_id=self.prescription.id,
            practice=self.practice,
            actor=self.receptionist,
            uploaded_file=SimpleUploadedFile(
                "second-prescription.pdf",
                b"%PDF-1.7\nsecond safe prescription",
                content_type="application/pdf",
            ),
            storage=self.storage,
        )
        scanner = FakeScanner(result="clean")
        output = StringIO()

        with (
            patch(
                "documents.management.commands.scan_documents."
                "get_document_storage",
                return_value=self.storage,
            ),
            patch(
                "documents.management.commands.scan_documents."
                "get_document_scanner",
                return_value=scanner,
            ),
        ):
            call_command(
                "scan_documents",
                stdout=output,
            )

        self.document.refresh_from_db()
        pending_document.refresh_from_db()

        self.assertEqual(
            self.document.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )
        self.assertEqual(
            pending_document.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )
        self.assertEqual(
            scanner.scanned_content,
            [b"%PDF-1.7\nsecond safe prescription"],
        )
        self.assertIn(
            "Scanned 1 pending document(s).",
            output.getvalue(),
        )

    def test_management_command_scans_only_pending_documents(self):
        self.document.scan_status = (
            PrescriptionDocument.ScanStatus.CLEAN
        )
        self.document.save(
            update_fields=["scan_status"],
        )

        pending_document = upload_prescription_document(
            prescription_id=self.prescription.id,
            practice=self.practice,
            actor=self.receptionist,
            uploaded_file=SimpleUploadedFile(
                "second-prescription.pdf",
                b"%PDF-1.7\nsecond safe prescription",
                content_type="application/pdf",
            ),
            storage=self.storage,
        )
        scanner = FakeScanner(result="clean")
        output = StringIO()

        with (
            patch(
                "documents.management.commands.scan_documents."
                "get_document_storage",
                return_value=self.storage,
            ),
            patch(
                "documents.management.commands.scan_documents."
                "get_document_scanner",
                return_value=scanner,
            ),
        ):
            call_command(
                "scan_documents",
                stdout=output,
            )

        self.document.refresh_from_db()
        pending_document.refresh_from_db()

        self.assertEqual(
            self.document.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )
        self.assertEqual(
            pending_document.scan_status,
            PrescriptionDocument.ScanStatus.CLEAN,
        )
        self.assertEqual(
            scanner.scanned_content,
            [b"%PDF-1.7\nsecond safe prescription"],
        )
        self.assertIn(
            "Scanned 1 pending document(s).",
            output.getvalue(),
        )
