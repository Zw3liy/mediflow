from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from patients.models import Patient
from tenancy.models import Membership, Practice

from .policies import require_patient_access


User = get_user_model()


class ClinicalPatientAccessPolicyTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Clinical Policy Practice",
        )

        self.doctor = User.objects.create_user(
            username="policy-doctor",
            password="safe-test-password",
        )
        self.receptionist = User.objects.create_user(
            username="policy-receptionist",
            password="safe-test-password",
        )
        self.patient_user = User.objects.create_user(
            username="policy-patient",
            password="safe-test-password",
        )
        self.other_patient_user = User.objects.create_user(
            username="other-policy-patient",
            password="safe-test-password",
        )

        self.doctor_membership = Membership.objects.create(
            practice=self.practice,
            user=self.doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )
        self.reception_membership = Membership.objects.create(
            practice=self.practice,
            user=self.receptionist,
            role=Membership.Role.RECEPTION,
            active=True,
        )
        self.patient_membership = Membership.objects.create(
            practice=self.practice,
            user=self.patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )
        self.other_patient_membership = Membership.objects.create(
            practice=self.practice,
            user=self.other_patient_user,
            role=Membership.Role.PATIENT,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            portal_user=self.patient_user,
            file_number="POLICY-001",
            given_name="Policy",
            family_name="Patient",
        )

    def test_doctor_has_clinical_patient_access(self):
        require_patient_access(
            membership=self.doctor_membership,
            patient=self.patient,
            clinical=True,
        )

    def test_receptionist_has_no_clinical_patient_access(self):
        with self.assertRaisesMessage(
            PermissionDenied,
            "Clinical access denied.",
        ):
            require_patient_access(
                membership=self.reception_membership,
                patient=self.patient,
                clinical=True,
            )

    def test_patient_can_access_only_own_record(self):
        require_patient_access(
            membership=self.patient_membership,
            patient=self.patient,
        )

        with self.assertRaisesMessage(
            PermissionDenied,
            "Patient access denied.",
        ):
            require_patient_access(
                membership=self.other_patient_membership,
                patient=self.patient,
            )
