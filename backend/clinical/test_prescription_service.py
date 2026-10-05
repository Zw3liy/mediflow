from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Encounter, Prescription
from .services import create_prescription


User = get_user_model()


class PrescriptionServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Prescription Practice",
        )

        self.doctor = User.objects.create_user(
            username="prescription-doctor",
            password="safe-test-password",
        )
        self.nurse = User.objects.create_user(
            username="prescription-nurse",
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
            user=self.nurse,
            role=Membership.Role.NURSE,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="PRESCRIPTION-001",
            given_name="Prescription",
            family_name="Patient",
        )

        self.encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )

    def test_active_responsible_doctor_can_create_prescription(self):
        prescription = create_prescription(
            encounter_id=self.encounter.id,
            actor=self.doctor,
            general_instructions="Take medication after food.",
            items=[
                {
                    "medication_name": "Amoxicillin",
                    "dosage": "500 mg",
                    "route": "Oral",
                    "frequency": "Three times daily",
                    "duration": "5 days",
                    "quantity": "15 capsules",
                    "instructions": "Complete the full course.",
                },
                {
                    "medication_name": "Paracetamol",
                    "dosage": "500 mg",
                    "route": "Oral",
                    "frequency": "When required",
                    "duration": "3 days",
                    "quantity": "12 tablets",
                    "instructions": "Do not exceed the prescribed dose.",
                },
            ],
        )

        self.assertEqual(
            prescription.encounter,
            self.encounter,
        )
        self.assertEqual(
            prescription.prescribed_by,
            self.doctor,
        )
        self.assertEqual(
            prescription.status,
            Prescription.Status.DRAFT,
        )
        self.assertEqual(
            prescription.general_instructions,
            "Take medication after food.",
        )
        self.assertEqual(
            prescription.items.count(),
            2,
        )
        self.assertEqual(
            prescription.items.first().medication_name,
            "Amoxicillin",
        )

    def test_nurse_cannot_create_prescription(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Only an active doctor may create prescriptions.",
        ):
            create_prescription(
                encounter_id=self.encounter.id,
                actor=self.nurse,
                items=[
                    {
                        "medication_name": "Paracetamol",
                        "dosage": "500 mg",
                        "frequency": "Twice daily",
                    },
                ],
            )

        self.assertEqual(Prescription.objects.count(), 0)

    def test_inactive_doctor_cannot_create_prescription(self):
        Membership.objects.filter(
            practice=self.practice,
            user=self.doctor,
        ).update(
            active=False,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only an active doctor may create prescriptions.",
        ):
            create_prescription(
                encounter_id=self.encounter.id,
                actor=self.doctor,
                items=[
                    {
                        "medication_name": "Paracetamol",
                        "dosage": "500 mg",
                        "frequency": "Twice daily",
                    },
                ],
            )

        self.assertEqual(Prescription.objects.count(), 0)

    def test_other_doctor_cannot_prescribe_for_encounter(self):
        other_doctor = User.objects.create_user(
            username="other-prescription-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=other_doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only the responsible doctor may prescribe.",
        ):
            create_prescription(
                encounter_id=self.encounter.id,
                actor=other_doctor,
                items=[
                    {
                        "medication_name": "Paracetamol",
                        "dosage": "500 mg",
                        "frequency": "Twice daily",
                    },
                ],
            )

        self.assertEqual(Prescription.objects.count(), 0)

    def test_prescription_requires_at_least_one_item(self):
        with self.assertRaisesMessage(
            ValidationError,
            "At least one prescription item is required.",
        ):
            create_prescription(
                encounter_id=self.encounter.id,
                actor=self.doctor,
                items=[],
            )

        self.assertEqual(Prescription.objects.count(), 0)

    def test_required_medication_fields_are_validated(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Medication name, dosage, and frequency are required.",
        ):
            create_prescription(
                encounter_id=self.encounter.id,
                actor=self.doctor,
                items=[
                    {
                        "dosage": "500 mg",
                        "frequency": "Twice daily",
                    },
                ],
            )

        self.assertEqual(Prescription.objects.count(), 0)
