from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from clinical.models import Encounter, Prescription
from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import PrescriptionDocument
from .services import register_prescription_document, release_prescription_document


User = get_user_model()


class PrescriptionDocumentServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Document Practice",
        )

        self.doctor = User.objects.create_user(
            username="document-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="document-receptionist",
            password="safe-test-password",
        )
        self.owner = User.objects.create_user(
            username="document-owner",
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
            user=self.owner,
            role=Membership.Role.OWNER,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="DOCUMENT-001",
            given_name="Document",
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

        self.sha256 = "a" * 64
        self.object_key = (
            f"practices/{self.practice.id}/"
            f"prescriptions/{self.prescription.id}/"
            "prescription.pdf"
        )

    def test_active_receptionist_can_register_prescription_file(self):
        document = register_prescription_document(
            prescription_id=self.prescription.id,
            practice=self.practice,
            actor=self.receptionist,
            original_name="prescription.pdf",
            object_key=self.object_key,
            content_type="application/pdf",
            size_bytes=2048,
            sha256=self.sha256,
        )

        self.assertEqual(
            document.practice,
            self.practice,
        )
        self.assertEqual(
            document.prescription,
            self.prescription,
        )
        self.assertEqual(
            document.uploaded_by,
            self.receptionist,
        )
        self.assertEqual(
            document.original_name,
            "prescription.pdf",
        )
        self.assertEqual(
            document.object_key,
            self.object_key,
        )
        self.assertEqual(
            document.content_type,
            "application/pdf",
        )
        self.assertEqual(
            document.size_bytes,
            2048,
        )
        self.assertEqual(
            document.sha256,
            self.sha256,
        )
        self.assertEqual(
            document.scan_status,
            PrescriptionDocument.ScanStatus.PENDING,
        )
        self.assertIsNone(
            document.released_to_patient_at,
        )

    def register_document(self, **overrides):
        values = {
            "prescription_id": self.prescription.id,
            "practice": self.practice,
            "actor": self.receptionist,
            "original_name": "prescription.pdf",
            "object_key": self.object_key,
            "content_type": "application/pdf",
            "size_bytes": 2048,
            "sha256": self.sha256,
        }
        values.update(overrides)

        return register_prescription_document(**values)

    def test_active_owner_can_register_prescription_file(self):
        document = self.register_document(
            actor=self.owner,
        )

        self.assertEqual(
            document.uploaded_by,
            self.owner,
        )

    def test_doctor_cannot_register_prescription_file(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Only active reception or owner staff may register files.",
        ):
            self.register_document(
                actor=self.doctor,
            )

        self.assertEqual(
            PrescriptionDocument.objects.count(),
            0,
        )

    def test_inactive_receptionist_cannot_register_file(self):
        Membership.objects.filter(
            practice=self.practice,
            user=self.receptionist,
        ).update(
            active=False,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only active reception or owner staff may register files.",
        ):
            self.register_document()

        self.assertEqual(
            PrescriptionDocument.objects.count(),
            0,
        )

    def test_draft_prescription_cannot_receive_file(self):
        self.prescription.status = Prescription.Status.DRAFT
        self.prescription.issued_at = None
        self.prescription.save(
            update_fields=[
                "status",
                "issued_at",
            ]
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only issued prescriptions may receive files.",
        ):
            self.register_document()

    def test_cross_practice_prescription_is_rejected(self):
        other_practice = Practice.objects.create(
            name="Other Document Practice",
        )
        other_receptionist = User.objects.create_user(
            username="other-document-receptionist",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=other_practice,
            user=other_receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Prescription was not found in this practice.",
        ):
            self.register_document(
                practice=other_practice,
                actor=other_receptionist,
            )

    def test_invalid_checksum_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "A valid SHA-256 checksum is required.",
        ):
            self.register_document(
                sha256="not-a-checksum",
            )

    def test_non_pdf_file_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Only PDF prescription files are allowed.",
        ):
            self.register_document(
                content_type="application/x-msdownload",
            )

    def test_oversized_file_is_rejected(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Prescription file size must be between 1 byte and 10 MB.",
        ):
            self.register_document(
                size_bytes=(10 * 1024 * 1024) + 1,
            )

    def test_storage_key_must_match_prescription(self):
        with self.assertRaisesMessage(
            ValidationError,
            "The storage key does not belong to this prescription.",
        ):
            self.register_document(
                object_key="untrusted/prescription.pdf",
            )

    def test_clean_file_can_be_released_to_patient(self):
        document = self.register_document()
        document.scan_status = PrescriptionDocument.ScanStatus.CLEAN
        document.save(
            update_fields=[
                "scan_status",
            ]
        )

        before_release = timezone.now()

        released = release_prescription_document(
            document_id=document.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        after_release = timezone.now()

        self.assertGreaterEqual(
            released.released_to_patient_at,
            before_release,
        )
        self.assertLessEqual(
            released.released_to_patient_at,
            after_release,
        )

    def test_pending_file_cannot_be_released(self):
        document = self.register_document()

        with self.assertRaisesMessage(
            ValidationError,
            "Only clean files may be released to patients.",
        ):
            release_prescription_document(
                document_id=document.id,
                practice=self.practice,
                actor=self.receptionist,
            )

        document.refresh_from_db()

        self.assertIsNone(document.released_to_patient_at)

    def test_infected_file_cannot_be_released(self):
        document = self.register_document()
        document.scan_status = PrescriptionDocument.ScanStatus.INFECTED
        document.save(
            update_fields=[
                "scan_status",
            ]
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only clean files may be released to patients.",
        ):
            release_prescription_document(
                document_id=document.id,
                practice=self.practice,
                actor=self.receptionist,
            )

        document.refresh_from_db()

        self.assertIsNone(document.released_to_patient_at)

    def test_doctor_cannot_release_prescription_file(self):
        document = self.register_document()
        document.scan_status = PrescriptionDocument.ScanStatus.CLEAN
        document.save(
            update_fields=[
                "scan_status",
            ]
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only active reception or owner staff may release files.",
        ):
            release_prescription_document(
                document_id=document.id,
                practice=self.practice,
                actor=self.doctor,
            )

    def test_releasing_file_twice_preserves_original_timestamp(self):
        document = self.register_document()
        document.scan_status = PrescriptionDocument.ScanStatus.CLEAN
        document.save(
            update_fields=[
                "scan_status",
            ]
        )

        first_release = release_prescription_document(
            document_id=document.id,
            practice=self.practice,
            actor=self.receptionist,
        )
        original_timestamp = first_release.released_to_patient_at

        second_release = release_prescription_document(
            document_id=document.id,
            practice=self.practice,
            actor=self.receptionist,
        )

        self.assertEqual(
            second_release.released_to_patient_at,
            original_timestamp,
        )
