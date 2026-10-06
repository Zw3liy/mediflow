from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone
from notifications.models import Notification
from scheduling.models import Appointment
from scheduling.services import approve_booking, doctor_approve_booking, record_intake
from tenancy.models import Membership
from . import tests as fixtures


class ReceptionDoctorPatientTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.PortalTests.setUpTestData.__func__(cls)

    def test_three_distinct_login_pages_and_role_checks(self):
        for area, title in [("reception","Reception &amp; secretary sign in"),("doctor","Doctor sign in"),("patient","Patient sign in")]:
            self.assertContains(self.client.get(f"/app/login/{area}/"),title)
        denied=self.client.post("/app/login/doctor/", {"username":"reception","password":"test-password"})
        self.assertContains(denied,"does not have active access")
        self.assertNotIn("_auth_user_id",self.client.session)
        valid=self.client.post("/app/login/doctor/", {"username":"Goodwill","password":"test-password"})
        self.assertEqual(valid.status_code,302)
        self.assertRedirects(self.client.get("/app/"),f"/app/doctor/?practice={self.practice.pk}",fetch_redirect_response=False)

    def test_patient_login_cannot_use_staff_account(self):
        self.assertContains(self.client.post("/app/login/patient/",{"username":"owner","password":"test-password"}),"does not have active access")
        response=self.client.post("/app/login/patient/",{"username":"patient","password":"test-password"})
        self.assertEqual(response.status_code,302)
        self.assertRedirects(self.client.get("/app/"),f"/app/patient/?practice={self.practice.pk}",fetch_redirect_response=False)

    def test_patient_can_request_own_visit_but_not_another_patient(self):
        self.client.force_login(self.patient_user)
        values={"practice":self.practice.pk,"patient":self.patient.pk,"practitioner":self.doctor.pk,
            "service":self.service.pk,"starts_at":(self.starts_at+timedelta(hours=2)).isoformat(),"reason_for_visit":"Patient-reported headache"}
        self.assertEqual(self.client.post("/app/new/booking/",values).status_code,302)
        visit=Appointment.objects.get(reason_for_visit="Patient-reported headache")
        self.assertEqual(visit.status,"requested")
        values["patient"]=self.secret.pk
        self.assertContains(self.client.post("/app/new/booking/",values),"Select a valid choice")
        self.assertEqual(Appointment.objects.count(),2)

    def test_doctor_receives_details_only_after_reception_approval(self):
        self.client.force_login(self.doctor)
        self.assertNotContains(self.client.get("/app/doctor/"),"Demo Patient")
        record_intake(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception,
            values={"reason_for_visit":"Patient-reported dizziness","blood_pressure_systolic":120,"blood_pressure_diastolic":80})
        self.assertFalse(Notification.objects.exists())
        approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception)
        notification=Notification.objects.get(recipient=self.doctor)
        self.assertIn("Demo Patient",notification.message)
        self.assertIn("Patient-reported dizziness",notification.message)
        self.assertIn("120/80 mmHg",notification.message)
        self.assertIn("SAST",notification.message)
        self.assertFalse(Notification.objects.filter(recipient=self.patient_user).exists())
        self.assertContains(self.client.get("/app/doctor/"),"Demo Patient")

    def test_doctor_approval_sends_personal_notification_once(self):
        approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception)
        self.client.force_login(self.doctor)
        url=f"/app/appointments/{self.appointment.pk}/doctor-approve/"
        self.client.post(url,{"practice":self.practice.pk})
        self.client.post(url,{"practice":self.practice.pk})
        self.appointment.refresh_from_db()
        self.assertIsNotNone(self.appointment.doctor_approved_at)
        notice=Notification.objects.get(recipient=self.patient_user,kind="doctor_ready")
        self.assertIn("Hello Demo",notice.message)
        self.assertIn("Dr Goodwill",notice.message)
        self.assertIn("Dr Tshabalala",notice.message)
        self.assertIn("SAST",notice.message)
        self.assertNotIn("blood pressure",notice.message.lower())

    def test_doctor_cannot_approve_before_reception_or_for_colleague(self):
        self.client.force_login(self.doctor)
        self.client.post(f"/app/appointments/{self.appointment.pk}/doctor-approve/",{"practice":self.practice.pk})
        self.appointment.refresh_from_db()
        self.assertIsNone(self.appointment.doctor_approved_at)
        self.assertFalse(Notification.objects.exists())
        self.appointment.status="held"
        self.appointment.practitioner=self.other_doctor
        self.appointment.save()
        self.client.post(f"/app/appointments/{self.appointment.pk}/doctor-approve/",{"practice":self.practice.pk})
        self.appointment.refresh_from_db()
        self.assertIsNone(self.appointment.doctor_approved_at)

    def test_reception_and_patient_cannot_send_doctor_readiness(self):
        self.appointment.status="held"
        self.appointment.save()
        for user in [self.reception,self.patient_user]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(f"/app/appointments/{self.appointment.pk}/doctor-approve/",{"practice":self.practice.pk}).status_code,403)
        self.assertFalse(Notification.objects.filter(kind="doctor_ready").exists())

    def test_optional_bp_requires_pair_and_preserves_recording_actor(self):
        self.client.force_login(self.reception)
        url=f"/app/appointments/{self.appointment.pk}/intake/"
        self.assertContains(self.client.post(url,{"practice":self.practice.pk,"blood_pressure_systolic":120}),"Enter both blood pressure")
        self.assertEqual(self.client.post(url,{"practice":self.practice.pk,"reason_for_visit":"Cough"}).status_code,302)
        self.appointment.refresh_from_db()
        self.assertIsNone(self.appointment.blood_pressure_recorded_at)
        self.assertEqual(self.client.post(url,{"practice":self.practice.pk,"reason_for_visit":"Cough",
            "blood_pressure_systolic":120,"blood_pressure_diastolic":80}).status_code,302)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.blood_pressure_recorded_by,self.reception)
        self.assertIsNotNone(self.appointment.blood_pressure_recorded_at)

    def test_intake_cannot_change_after_doctor_review(self):
        self.appointment.status="held"
        self.appointment.doctor_approved_at=timezone.now()
        self.appointment.save()
        self.client.force_login(self.reception)
        response=self.client.post(f"/app/appointments/{self.appointment.pk}/intake/",{"practice":self.practice.pk,"reason_for_visit":"Changed"})
        self.assertContains(response,"before doctor approval")
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.reason_for_visit,"")

    def test_ready_now_is_today_next_patient_only_and_completion_advances_queue(self):
        self.appointment.starts_at=timezone.now()+timedelta(minutes=10)
        self.appointment.ends_at=self.appointment.starts_at+timedelta(minutes=30)
        self.appointment.status="held"
        self.appointment.doctor_approved_at=timezone.now()
        self.appointment.save()
        second=Appointment.objects.create(practice=self.practice,patient=self.patient,practitioner=self.doctor,
            service=self.service,starts_at=self.appointment.ends_at,ends_at=self.appointment.ends_at+timedelta(minutes=30),status="held",doctor_approved_at=timezone.now())
        self.client.force_login(self.doctor)
        self.client.post(f"/app/appointments/{second.pk}/call/",{"practice":self.practice.pk})
        second.refresh_from_db()
        self.assertIsNone(second.called_at)
        url=f"/app/appointments/{self.appointment.pk}/call/"
        self.client.post(url,{"practice":self.practice.pk})
        self.client.post(url,{"practice":self.practice.pk})
        self.assertEqual(Notification.objects.filter(appointment=self.appointment,kind="patient_called").count(),1)
        self.client.post(f"/app/appointments/{self.appointment.pk}/encounter/",{"practice":self.practice.pk})
        self.client.post(f"/app/appointments/{self.appointment.pk}/complete/",{"practice":self.practice.pk})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,"completed")
        self.assertIsNotNone(self.appointment.encounter.ended_at)
        response=self.client.get("/app/doctor/")
        self.assertEqual(response.context["next_patient"].pk,second.pk)

    def test_notification_feed_and_read_are_personal_and_csrf_protected(self):
        notice=Notification.objects.create(practice=self.practice,recipient=self.doctor,appointment=self.appointment,
            kind="appointment_approved",title="Private doctor notice",message="Private intake details")
        self.client.force_login(self.patient_user)
        response=self.client.get("/app/notifications/")
        self.assertNotContains(response,"Private intake details")
        self.assertIn("no-store",response["Cache-Control"])
        self.assertEqual(self.client.post(f"/app/notifications/{notice.pk}/read/",{"practice":self.practice.pk}).status_code,404)
        self.client.force_login(self.doctor)
        self.assertContains(self.client.get("/app/notifications/"),"Private intake details")
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.doctor)
        self.assertEqual(csrf.post(f"/app/notifications/{notice.pk}/read/",{"practice":self.practice.pk}).status_code,403)
        self.client.post(f"/app/notifications/{notice.pk}/read/",{"practice":self.practice.pk})
        notice.refresh_from_db();self.assertIsNotNone(notice.read_at)

    def test_patient_account_linking_is_scoped_to_patient_members(self):
        self.client.force_login(self.reception)
        url=f"/app/patients/{self.patient.pk}/account/"
        self.assertContains(self.client.post(url,{"practice":self.practice.pk,"portal_user":self.other_doctor.pk}),"Select a valid choice")
        self.assertEqual(self.client.post(url,{"practice":self.practice.pk,"portal_user":self.patient_user.pk}).status_code,302)
        self.client.force_login(self.patient_user)
        self.assertEqual(self.client.get(url).status_code,403)

    def test_separate_login_post_requires_csrf(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/app/login/doctor/",{"username":"Goodwill","password":"test-password"}).status_code,403)

    def test_future_appointment_cannot_receive_ready_now_alert(self):
        self.appointment.status="held"
        self.appointment.doctor_approved_at=timezone.now()
        self.appointment.save()
        self.client.force_login(self.doctor)
        self.client.post(f"/app/appointments/{self.appointment.pk}/call/",{"practice":self.practice.pk})
        self.appointment.refresh_from_db()
        self.assertIsNone(self.appointment.called_at)
        self.assertFalse(Notification.objects.filter(kind="patient_called").exists())

    def test_intake_update_refreshes_doctor_notification_without_duplication(self):
        approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception)
        record_intake(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception,
            values={"reason_for_visit":"Updated symptom report","blood_pressure_systolic":110,"blood_pressure_diastolic":70})
        notice=Notification.objects.get(recipient=self.doctor,kind="appointment_approved")
        self.assertIn("Updated symptom report",notice.message)
        self.assertIn("110/70 mmHg",notice.message)
        self.assertIsNone(notice.read_at)

    def test_portal_booking_input_uses_sast_and_is_stored_in_utc(self):
        from datetime import timezone as utc
        self.client.force_login(self.reception)
        local=(timezone.now()+timedelta(days=3)).date()
        self.client.post("/app/new/booking/",{"practice":self.practice.pk,"patient":self.patient.pk,
            "practitioner":self.doctor.pk,"service":self.service.pk,"starts_at":f"{local.isoformat()}T15:00","reason_for_visit":"Time zone test"})
        visit=Appointment.objects.get(reason_for_visit="Time zone test")
        self.assertEqual(visit.starts_at.astimezone(utc.utc).hour,13)
        self.assertContains(self.client.get("/app/reception/"),"15:00")

    def test_live_doctor_queue_excludes_other_practitioners_and_patient_feed_has_no_queue(self):
        self.appointment.status="held"
        self.appointment.save()
        self.client.force_login(self.doctor)
        feed=self.client.get("/app/notifications/").json()
        self.assertEqual(feed["next_patient"]["patient"],"Demo Patient")
        self.client.force_login(self.other_doctor)
        self.assertIsNone(self.client.get("/app/notifications/").json()["next_patient"])
        self.client.force_login(self.patient_user)
        self.assertIsNone(self.client.get("/app/notifications/").json()["next_patient"])

    def test_doctor_approval_api_enforces_role_and_readonly_fields(self):
        from rest_framework.test import APIClient
        api=APIClient()
        self.appointment.status="held"
        self.appointment.save()
        headers={"HTTP_X_PRACTICE_ID":str(self.practice.pk)}
        api.force_authenticate(self.reception)
        response=api.post(f"/api/appointments/{self.appointment.pk}/doctor-approve/",{},format="json",**headers)
        self.assertEqual(response.status_code,400)
        api.force_authenticate(self.doctor)
        response=api.post(f"/api/appointments/{self.appointment.pk}/doctor-approve/",{},format="json",**headers)
        self.assertEqual(response.status_code,200)
        self.assertIsNotNone(response.data["doctor_approved_at"])
