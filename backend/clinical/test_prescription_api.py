from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Encounter, Prescription, PrescriptionItem


User = get_user_model()


class PrescriptionApiTests(APITestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Prescription API Practice",
        )

        self.doctor = User.objects.create_user(
            username="prescription-api-doctor",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="prescription-api-patient",
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
            user=self.patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            portal_user=self.patient_user,
            file_number="PRESCRIPTION-API-001",
            given_name="Prescription",
            family_name="API Patient",
        )

        self.encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )

        self.client.force_authenticate(
            user=self.doctor,
        )

    def practice_headers(self):
        return {
            "HTTP_X_PRACTICE_ID": str(self.practice.id),
        }

    def test_responsible_doctor_can_create_prescription(self):
        response = self.client.post(
            reverse("prescription-list"),
            {
                "encounter": str(self.encounter.id),
                "general_instructions": "Take medication after food.",
                "items": [
                    {
                        "medication_name": "Amoxicillin",
                        "dosage": "500 mg",
                        "route": "Oral",
                        "frequency": "Three times daily",
                        "duration": "5 days",
                        "quantity": "15 capsules",
                        "instructions": "Complete the full course.",
                    },
                ],
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            response.data["status"],
            Prescription.Status.DRAFT,
        )
        self.assertEqual(
            response.data["prescribed_by"],
            self.doctor.id,
        )
        self.assertEqual(
            len(response.data["items"]),
            1,
        )
        self.assertEqual(
            response.data["items"][0]["medication_name"],
            "Amoxicillin",
        )

        prescription = Prescription.objects.get()

        self.assertEqual(
            prescription.encounter,
            self.encounter,
        )
        self.assertEqual(
            prescription.prescribed_by,
            self.doctor,
        )

    def test_prescribing_doctor_can_issue_prescription(self):
        create_response = self.client.post(
            reverse("prescription-list"),
            {
                "encounter": str(self.encounter.id),
                "general_instructions": "Take after food.",
                "items": [
                    {
                        "medication_name": "Amoxicillin",
                        "dosage": "500 mg",
                        "route": "Oral",
                        "frequency": "Three times daily",
                        "duration": "5 days",
                        "quantity": "15 capsules",
                        "instructions": "Complete the full course.",
                    },
                ],
            },
            format="json",
            **self.practice_headers(),
        )

        prescription_id = create_response.data["id"]

        issue_response = self.client.post(
            reverse(
                "prescription-issue",
                kwargs={"pk": prescription_id},
            ),
            {},
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            issue_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            issue_response.data["status"],
            Prescription.Status.ISSUED,
        )
        self.assertIsNotNone(
            issue_response.data["issued_at"],
        )

        prescription = Prescription.objects.get(
            id=prescription_id,
        )

        self.assertEqual(
            prescription.status,
            Prescription.Status.ISSUED,
        )
        self.assertIsNotNone(
            prescription.issued_at,
        )

    def test_patient_cannot_see_draft_prescription(self):
        Prescription.objects.create(
            encounter=self.encounter,
            prescribed_by=self.doctor,
            status=Prescription.Status.DRAFT,
        )

        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.get(
            reverse("prescription-list"),
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data),
            0,
        )

    def test_patient_can_see_own_issued_prescription(self):
        prescription = Prescription.objects.create(
            encounter=self.encounter,
            prescribed_by=self.doctor,
            status=Prescription.Status.ISSUED,
            general_instructions="Take after food.",
            issued_at=timezone.now(),
        )

        PrescriptionItem.objects.create(
            prescription=prescription,
            medication_name="Amoxicillin",
            dosage="500 mg",
            route="Oral",
            frequency="Three times daily",
            duration="5 days",
            quantity="15 capsules",
        )

        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.get(
            reverse("prescription-list"),
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
            prescription.id,
        )
        self.assertEqual(
            response.data[0]["items"][0]["medication_name"],
            "Amoxicillin",
        )

    def test_patient_cannot_see_another_patients_prescription(self):
        prescription = Prescription.objects.create(
            encounter=self.encounter,
            prescribed_by=self.doctor,
            status=Prescription.Status.ISSUED,
            issued_at=timezone.now(),
        )

        other_patient_user = User.objects.create_user(
            username="other-prescription-api-patient",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=other_patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )

        Patient.objects.create(
            practice=self.practice,
            portal_user=other_patient_user,
            file_number="PRESCRIPTION-API-002",
            given_name="Other",
            family_name="Patient",
        )

        self.client.force_authenticate(
            user=other_patient_user,
        )

        response = self.client.get(
            reverse("prescription-list"),
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data),
            0,
        )

        self.assertTrue(
            Prescription.objects.filter(
                id=prescription.id,
            ).exists()
        )

    def test_patient_cannot_create_prescription(self):
        self.client.force_authenticate(
            user=self.patient_user,
        )

        response = self.client.post(
            reverse("prescription-list"),
            {
                "encounter": str(self.encounter.id),
                "general_instructions": "Unauthorized prescription.",
                "items": [
                    {
                        "medication_name": "Amoxicillin",
                        "dosage": "500 mg",
                        "frequency": "Three times daily",
                    },
                ],
            },
            format="json",
            **self.practice_headers(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            Prescription.objects.count(),
            0,
        )
