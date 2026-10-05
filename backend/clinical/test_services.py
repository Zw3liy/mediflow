import hashlib

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from tenancy.models import Membership, Practice

from .models import ClinicalNote, Encounter
from .services import sign_note


User = get_user_model()


class ClinicalNoteServiceTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Clinical Practice",
        )

        self.doctor = User.objects.create_user(
            username="clinical-doctor",
            password="safe-test-password",
        )
        self.other_doctor = User.objects.create_user(
            username="other-clinical-doctor",
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
            user=self.other_doctor,
            role=Membership.Role.DOCTOR,
            active=True,
        )

        self.patient = Patient.objects.create(
            practice=self.practice,
            file_number="CLINICAL-001",
            given_name="Clinical",
            family_name="Patient",
        )

        self.encounter = Encounter.objects.create(
            practice=self.practice,
            patient=self.patient,
            practitioner=self.doctor,
            started_at=timezone.now(),
        )

        self.note = ClinicalNote.objects.create(
            encounter=self.encounter,
        )

    def test_responsible_practitioner_can_sign_note(self):
        body = "Patient assessed and treatment discussed."

        version = sign_note(
            note_id=self.note.id,
            actor=self.doctor,
            body=body,
            reason="Initial consultation.",
        )

        self.note.refresh_from_db()

        self.assertEqual(version.version, 1)
        self.assertEqual(version.body, body)
        self.assertEqual(version.authored_by, self.doctor)
        self.assertIsNotNone(version.signed_at)
        self.assertEqual(
            version.content_sha256,
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(self.note.current_version, 1)

    def test_other_practitioner_cannot_sign_note(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Only the responsible practitioner may sign.",
        ):
            sign_note(
                note_id=self.note.id,
                actor=self.other_doctor,
                body="Unauthorized clinical note.",
            )

        self.note.refresh_from_db()

        self.assertEqual(self.note.current_version, 0)
        self.assertEqual(self.note.versions.count(), 0)
