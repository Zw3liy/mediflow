from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import Encounter, Prescription, PrescriptionItem
from .services import issue_prescription


User = get_user_model()


class PrescriptionIssuanceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Prescription Issuance Practice",
        )

        self.doctor = User.objects.create_user(
            username="issuing-doctor",
            password="safe-test-password",
        )

        Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="ISSUE-001",
            given_name="Issuance",
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
            status=Prescription.Status.DRAFT,
            general_instructions="Take after food.",
        )

        PrescriptionItem.objects.create(
            prescription=self.prescription,
            medication_name="Amoxicillin",
            dosage="500 mg",
            route="Oral",
            frequency="Three times daily",
            duration="5 days",
            quantity="15 capsules",
        )

    def test_prescribing_doctor_can_issue_draft(self):
        before_issuing = timezone.now()

        issued = issue_prescription(
            prescription_id=self.prescription.id,
            actor=self.doctor,
        )

        after_issuing = timezone.now()

        self.assertEqual(
            issued.status,
            Prescription.Status.ISSUED,
        )
        self.assertGreaterEqual(
            issued.issued_at,
            before_issuing,
        )
        self.assertLessEqual(
            issued.issued_at,
            after_issuing,
        )

    def test_inactive_doctor_cannot_issue_prescription(self):
        Membership.objects.filter(
            practice=self.practice,
            user=self.doctor,
        ).update(
            active=False,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only an active doctor may issue prescriptions.",
        ):
            issue_prescription(
                prescription_id=self.prescription.id,
                actor=self.doctor,
            )

    def test_other_doctor_cannot_issue_prescription(self):
        other_doctor = User.objects.create_user(
            username="other-issuing-doctor",
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
            "Only the prescribing doctor may issue this prescription.",
        ):
            issue_prescription(
                prescription_id=self.prescription.id,
                actor=other_doctor,
            )

    def test_issued_prescription_cannot_be_issued_again(self):
        self.prescription.status = Prescription.Status.ISSUED
        self.prescription.issued_at = timezone.now()
        self.prescription.save(
            update_fields=[
                "status",
                "issued_at",
            ]
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Only draft prescriptions may be issued.",
        ):
            issue_prescription(
                prescription_id=self.prescription.id,
                actor=self.doctor,
            )

    def test_empty_prescription_cannot_be_issued(self):
        self.prescription.items.all().delete()

        with self.assertRaisesMessage(
            ValidationError,
            "A prescription must contain at least one item.",
        ):
            issue_prescription(
                prescription_id=self.prescription.id,
                actor=self.doctor,
            )

        self.prescription.refresh_from_db()

        self.assertEqual(
            self.prescription.status,
            Prescription.Status.DRAFT,
        )
        self.assertIsNone(
            self.prescription.issued_at,
        )
