from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from clinical.models import Encounter, Prescription
from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import PrescriptionDocument


User = get_user_model()


class PrescriptionDocumentApiTests(APITestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Document API Practice",
        )

        self.doctor = User.objects.create_user(
            username="document-api-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="document-api-receptionist",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="document-api-patient",
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
            file_number="DOCUMENT-API-001",
            given_name="Document",
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

        self.object_key = (
            f"practices/{self.practice.id}/"
            f"prescriptions/{self.prescription.id}/"
            "prescription.pdf"
        )

        self.client.force_authenticate(
            user=self.receptionist,
        )

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def test_metadata_only_registration_endpoint_is_disabled(self):
        response = self.client.post(
            reverse("prescription-document-list"),
            {
                "prescription": self.prescription.id,
                "original_name": "prescription.pdf",
                "object_key": self.object_key,
                "content_type": "application/pdf",
                "size_bytes": 2048,
                "sha256": "a" * 64,
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            PrescriptionDocument.objects.count(),
            0,
        )

    def test_receptionist_can_release_clean_document(self):
        document = PrescriptionDocument.objects.create(
            practice=self.practice,
            prescription=self.prescription,
            uploaded_by=self.receptionist,
            original_name="prescription.pdf",
            object_key=self.object_key,
            content_type="application/pdf",
            size_bytes=2048,
            sha256="a" * 64,
            scan_status=PrescriptionDocument.ScanStatus.CLEAN,
        )

        response = self.client.post(
            reverse(
                "prescription-document-release",
                kwargs={"pk": document.id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIsNotNone(
            response.data["released_to_patient_at"],
        )

    def test_patient_sees_only_clean_released_document(self):
        released_document = PrescriptionDocument.objects.create(
            practice=self.practice,
            prescription=self.prescription,
            uploaded_by=self.receptionist,
            original_name="released-prescription.pdf",
            object_key=(
                f"practices/{self.practice.id}/"
                f"prescriptions/{self.prescription.id}/"
                "released-prescription.pdf"
            ),
            content_type="application/pdf",
            size_bytes=2048,
            sha256="a" * 64,
            scan_status=PrescriptionDocument.ScanStatus.CLEAN,
            released_to_patient_at=timezone.now(),
        )

        PrescriptionDocument.objects.create(
            practice=self.practice,
            prescription=self.prescription,
            uploaded_by=self.receptionist,
            original_name="pending-prescription.pdf",
            object_key=(
                f"practices/{self.practice.id}/"
                f"prescriptions/{self.prescription.id}/"
                "pending-prescription.pdf"
            ),
            content_type="application/pdf",
            size_bytes=2048,
            sha256="b" * 64,
            scan_status=PrescriptionDocument.ScanStatus.PENDING,
        )

        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.get(
            reverse("prescription-document-list"),
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
            str(released_document.id),
        )
        self.assertNotIn("object_key", response.data[0])
        self.assertNotIn("sha256", response.data[0])
        self.assertNotIn("uploaded_by", response.data[0])

    def test_patient_cannot_use_metadata_registration_endpoint(self):
        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.post(
            reverse("prescription-document-list"),
            {
                "prescription": self.prescription.id,
                "original_name": "prescription.pdf",
                "object_key": self.object_key,
                "content_type": "application/pdf",
                "size_bytes": 2048,
                "sha256": "a" * 64,
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            PrescriptionDocument.objects.count(),
            0,
        )
