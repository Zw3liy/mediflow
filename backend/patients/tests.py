from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from tenancy.models import Membership, Practice

from .models import Patient


User = get_user_model()


class PatientApiTests(APITestCase):
    def setUp(self):
        self.practice_a = Practice.objects.create(name="Practice A")
        self.practice_b = Practice.objects.create(name="Practice B")

        self.user_a = User.objects.create_user(
            username="doctor_a",
            password="test-password-a",
        )
        self.user_b = User.objects.create_user(
            username="doctor_b",
            password="test-password-b",
        )

        Membership.objects.create(
            practice=self.practice_a,
            user=self.user_a,
            role=Membership.Role.DOCTOR,
        )
        Membership.objects.create(
            practice=self.practice_b,
            user=self.user_b,
            role=Membership.Role.DOCTOR,
        )

        self.patient_a = Patient.objects.create(
            practice=self.practice_a,
            file_number="A-001",
            given_name="Alice",
            family_name="Example",
        )
        self.patient_b = Patient.objects.create(
            practice=self.practice_b,
            file_number="B-001",
            given_name="Bob",
            family_name="Example",
        )

        self.url = reverse("patient-list")

    def test_authentication_is_required(self):
        response = self.client.get(self.url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_practice_header_is_required(self):
        self.client.force_authenticate(user=self.user_a)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_user_only_sees_patients_from_selected_practice(self):
        self.client.force_authenticate(user=self.user_a)

        response = self.client.get(
            self.url,
            HTTP_X_PRACTICE_ID=str(self.practice_a.id),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["id"],
            str(self.patient_a.id),
        )

    def test_user_cannot_access_another_practice(self):
        self.client.force_authenticate(user=self.user_a)

        response = self.client.get(
            self.url,
            HTTP_X_PRACTICE_ID=str(self.practice_b.id),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_created_patient_uses_membership_practice(self):
        self.client.force_authenticate(user=self.user_a)

        response = self.client.post(
            self.url,
            {
                "file_number": "A-002",
                "given_name": "Carol",
                "family_name": "Example",
                "email": "carol@example.test",
            },
            format="json",
            HTTP_X_PRACTICE_ID=str(self.practice_a.id),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        created_patient = Patient.objects.get(
            id=response.data["id"],
        )
        self.assertEqual(
            created_patient.practice,
            self.practice_a,
        )
