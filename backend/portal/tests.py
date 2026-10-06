from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone
from clinical.models import Encounter, Prescription
from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership, Practice


class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.practice = Practice.objects.create(name="Dr Tshabalala")
        cls.other = Practice.objects.create(name="Other clinic")
        cls.owner = get_user_model().objects.create_user(username="owner", password="test-password")
        cls.doctor = get_user_model().objects.create_user(username="Goodwill", password="test-password")
        cls.reception = get_user_model().objects.create_user(username="reception", password="test-password")
        cls.patient_user = get_user_model().objects.create_user(username="patient", password="test-password")
        cls.other_doctor = get_user_model().objects.create_user(username="otherdoctor")
        for user, role, practice in [(cls.owner,"owner",cls.practice), (cls.doctor,"doctor",cls.practice),
            (cls.reception,"reception",cls.practice), (cls.patient_user,"patient",cls.practice), (cls.other_doctor,"doctor",cls.other)]:
            Membership.objects.create(user=user, practice=practice, role=role)
        cls.patient = Patient.objects.create(practice=cls.practice, given_name="Demo", family_name="Patient", file_number="P-1", portal_user=cls.patient_user)
        cls.secret = Patient.objects.create(practice=cls.other, given_name="Secret", family_name="OtherClinic", file_number="S-1")
        cls.service = Service.objects.create(practice=cls.practice, name="Consultation", duration_minutes=30)
        cls.starts_at = timezone.now() + timedelta(days=1)
        cls.appointment = Appointment.objects.create(practice=cls.practice, patient=cls.patient, practitioner=cls.doctor,
            service=cls.service, starts_at=cls.starts_at, ends_at=cls.starts_at+timedelta(minutes=30))

    def login(self, user):
        self.client.force_login(user)

    def test_root_and_anonymous_dashboard_redirect_to_login(self):
        self.assertRedirects(self.client.get("/"), "/app/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/app/doctor/").status_code, 302)
        self.assertContains(self.client.get("/app/login/"), "Sign in securely")

    def test_each_role_is_routed_to_its_workspace(self):
        for user, route in [(self.owner,"admin"),(self.doctor,"doctor"),(self.reception,"reception"),(self.patient_user,"patient")]:
            self.login(user)
            self.assertRedirects(self.client.get("/app/"), f"/app/{route}/?practice={self.practice.pk}", fetch_redirect_response=False)
            response=self.client.get(f"/app/{route}/")
            self.assertEqual(response.status_code,200)
            self.assertContains(response, "Dr Tshabalala")
            self.assertNotContains(response,"OtherClinic")
            self.assertIn("no-store", response["Cache-Control"])

    def test_doctor_cannot_open_owner_workspace(self):
        self.login(self.doctor)
        self.assertEqual(self.client.get("/app/admin/").status_code,403)

    def test_other_practice_cannot_be_selected_in_get_or_post(self):
        self.login(self.doctor)
        self.assertEqual(self.client.get(f"/app/doctor/?practice={self.other.pk}").status_code,404)
        self.assertEqual(self.client.post("/app/new/booking/", {"practice":self.other.pk}).status_code,404)

    def test_invalid_practice_is_denied(self):
        self.login(self.doctor)
        self.assertEqual(self.client.get("/app/?practice=invalid").status_code,403)

    def test_inactive_membership_and_practice_remove_access(self):
        self.login(self.doctor)
        Membership.objects.filter(user=self.doctor).update(active=False)
        self.assertContains(self.client.get("/app/"), "active practice membership")
        Membership.objects.filter(user=self.doctor).update(active=True)
        self.practice.active=False
        self.practice.save()
        self.assertContains(self.client.get("/app/"), "active practice membership")

    def test_doctor_requests_booking_with_server_calculated_end(self):
        self.login(self.doctor)
        starts=self.starts_at+timedelta(hours=2)
        response=self.client.post("/app/new/booking/",dict(practice=self.practice.pk, patient=self.patient.pk,
            practitioner=self.doctor.pk,service=self.service.pk,starts_at=starts.isoformat()))
        self.assertEqual(response.status_code,302)
        appointment=Appointment.objects.get(starts_at=starts)
        self.assertEqual(appointment.status,"requested")
        self.assertEqual(appointment.ends_at,starts+timedelta(minutes=30))

    def test_cross_practice_patient_is_invalid_choice(self):
        self.login(self.doctor)
        response=self.client.post("/app/new/booking/",dict(practice=self.practice.pk,patient=self.secret.pk,
            practitioner=self.doctor.pk,service=self.service.pk,starts_at=self.starts_at.isoformat()))
        self.assertContains(response,"Select a valid choice")
        self.assertEqual(Appointment.objects.count(),1)

    def test_only_reception_or_owner_can_approve(self):
        self.login(self.doctor)
        url=f"/app/appointments/{self.appointment.pk}/approve/"
        self.assertEqual(self.client.post(url,{"practice":self.practice.pk}).status_code,403)
        self.login(self.reception)
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.client.post(url,{"practice":self.practice.pk}).status_code,302)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,"held")

    def test_rejection_requires_reason(self):
        self.login(self.reception)
        url=f"/app/appointments/{self.appointment.pk}/reject/"
        self.client.post(url,{"practice":self.practice.pk,"reason":""})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,"requested")
        self.client.post(url,{"practice":self.practice.pk,"reason":"Unavailable"})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,"rejected")

    def test_doctor_cannot_start_unapproved_consultation(self):
        self.login(self.doctor)
        self.assertEqual(self.client.post(f"/app/appointments/{self.appointment.pk}/encounter/", {"practice":self.practice.pk}).status_code,403)
        self.assertFalse(Encounter.objects.exists())

    def test_consultation_draft_and_issue_workflow(self):
        self.appointment.status="held"
        self.appointment.save()
        self.login(self.doctor)
        url=f"/app/appointments/{self.appointment.pk}/encounter/"
        self.assertEqual(self.client.post(url,{"practice":self.practice.pk}).status_code,302)
        self.client.post(url,{"practice":self.practice.pk})
        self.assertEqual(Encounter.objects.count(),1)
        encounter=Encounter.objects.get()
        self.assertEqual(self.client.post("/app/new/prescription/",dict(practice=self.practice.pk, encounter=encounter.pk,
            medication_name="Demo medication", dosage="Demo dosage", frequency="Demo frequency")).status_code,302)
        rx=Prescription.objects.get()
        self.assertEqual(rx.status,"draft")
        self.login(self.reception)
        self.assertEqual(self.client.post(f"/app/prescriptions/{rx.pk}/issue/", {"practice":self.practice.pk}).status_code,403)
        self.login(self.doctor)
        self.client.post(f"/app/prescriptions/{rx.pk}/issue/", {"practice":self.practice.pk})
        rx.refresh_from_db()
        self.assertEqual(rx.status,"draft")
        self.assertEqual(self.client.post(f"/app/prescriptions/{rx.pk}/issue/", {"practice":self.practice.pk,"reviewed":"yes"}).status_code,302)
        rx.refresh_from_db()
        self.assertEqual(rx.status,"issued")

    def test_patient_only_sees_own_appointments(self):
        other_patient=Patient.objects.create(practice=self.practice,given_name="Unrelated",family_name="Confidential",file_number="P-2")
        Appointment.objects.create(practice=self.practice,patient=other_patient,practitioner=self.doctor,service=self.service,
            starts_at=self.starts_at,ends_at=self.starts_at+timedelta(minutes=30))
        self.login(self.patient_user)
        response=self.client.get("/app/patient/")
        self.assertContains(response,"Demo Patient")
        self.assertNotContains(response,"Confidential")
        self.assertEqual(self.client.get("/app/new/booking/").status_code,403)

    def test_mutations_require_csrf_and_logout_requires_post(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.reception)
        self.assertEqual(client.post(f"/app/appointments/{self.appointment.pk}/approve/", {"practice":self.practice.pk}).status_code,403)
        self.assertEqual(client.get("/app/logout/").status_code,405)

    def test_owner_can_create_patient_and_service(self):
        self.login(self.owner)
        self.assertEqual(self.client.post("/app/new/patient/",dict(practice=self.practice.pk, file_number="NEW", given_name="New", family_name="Patient")).status_code,302)
        self.assertEqual(Patient.objects.get(file_number="NEW").practice_id,self.practice.pk)
        self.assertEqual(self.client.post("/app/new/service/",dict(practice=self.practice.pk,name="New service",duration_minutes=45,price_cents=0,deposit_cents=0)).status_code,302)
        self.assertEqual(Service.objects.get(name="New service").practice_id,self.practice.pk)
        self.login(self.doctor)
        self.assertEqual(self.client.get("/app/new/service/").status_code,403)

    def test_duplicate_patient_file_number_shows_error(self):
        self.client.force_login(self.owner)
        response = self.client.post("/app/new/patient/", {"practice": self.practice.pk,
            "file_number": self.patient.file_number, "given_name": "Duplicate", "family_name": "Patient"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(Patient.objects.filter(practice=self.practice, file_number=self.patient.file_number).count(), 1)

    def test_doctor_cannot_access_another_doctors_consultation(self):
        colleague = get_user_model().objects.create_user(username="colleague")
        Membership.objects.create(user=colleague, practice=self.practice, role="doctor")
        self.appointment.practitioner = colleague
        self.appointment.status = "held"
        self.appointment.save()
        encounter = Encounter.objects.create(practice=self.practice, patient=self.patient,
            practitioner=colleague, appointment=self.appointment, started_at=timezone.now())
        self.login(self.doctor)
        self.assertNotContains(self.client.get("/app/doctor/"), "Demo Patient")
        self.assertEqual(self.client.post(f"/app/appointments/{self.appointment.pk}/encounter/",
            {"practice":self.practice.pk}).status_code, 403)
        response = self.client.post("/app/new/prescription/", {"practice":self.practice.pk,
            "encounter":encounter.pk, "medication_name":"Example", "dosage":"Example", "frequency":"Example"})
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(Prescription.objects.exists())

    def test_patient_download_requires_own_clean_released_document(self):
        from unittest.mock import patch
        from documents.models import PrescriptionDocument
        encounter = Encounter.objects.create(practice=self.practice, patient=self.patient,
            practitioner=self.doctor, appointment=self.appointment, started_at=timezone.now())
        rx = Prescription.objects.create(encounter=encounter, prescribed_by=self.doctor)
        document = PrescriptionDocument.objects.create(practice=self.practice, prescription=rx,
            uploaded_by=self.doctor, original_name="prescription.pdf", object_key="test/document.pdf",
            content_type="application/pdf", size_bytes=8, sha256="0"*64)
        self.login(self.patient_user)
        url = f"/app/documents/{document.pk}/download/"
        self.assertEqual(self.client.get(url).status_code, 404)
        document.scan_status="clean"
        document.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        document.released_to_patient_at=timezone.now()
        document.save()
        with patch("documents.storage.get_document_storage") as storage:
            storage.return_value.read.return_value=b"%PDF-1.7"
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content,b"%PDF-1.7")
            self.assertIn("no-store",response["Cache-Control"])
            self.patient.portal_user=None
            self.patient.save()
            self.assertEqual(self.client.get(url).status_code,404)
