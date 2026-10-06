from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from portal import tests as fixtures
from scheduling.services import approve_booking, doctor_approve_booking
from notifications.models import Notification
from tenancy.models import Membership
from .models import MobileSession, PushDevice, PushDelivery
from .push import dispatch_pushes


class NativeMobileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.PortalTests.setUpTestData.__func__(cls)

    def setUp(self):
        cache.clear()
        self.api=APIClient()

    def login(self, username="patient", workspace="patient"):
        response=self.api.post('/api/mobile/login/',{'username':username,'password':'test-password','workspace':workspace},format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer '+response.data['token'])
        return response.data

    def test_mobile_login_hashes_token_and_scopes_role(self):
        data=self.login()
        session=MobileSession.objects.get()
        self.assertNotEqual(session.token_hash,data['token'])
        self.assertEqual(len(session.token_hash),64)
        self.assertEqual(data['session']['role'],'patient')
        self.assertIn('no-store',self.api.get('/api/mobile/dashboard/')['Cache-Control'])

    def test_wrong_workspace_and_password_are_rejected(self):
        for values in [{'username':'Goodwill','password':'test-password','workspace':'patient'},
            {'username':'patient','password':'wrong-password','workspace':'patient'}]:
            self.assertEqual(self.api.post('/api/mobile/login/',values,format='json').status_code,401)
        self.assertFalse(MobileSession.objects.exists())

    def test_login_is_throttled(self):
        for _ in range(5):self.api.post('/api/mobile/login/',{'workspace':'invalid'},format='json')
        self.assertEqual(self.api.post('/api/mobile/login/',{'workspace':'invalid'},format='json').status_code,429)

    def test_mobile_endpoints_require_bearer_not_browser_session(self):
        self.api.force_login(self.patient_user)
        self.assertEqual(self.api.get('/api/mobile/dashboard/').status_code,401)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer malformed')
        self.assertEqual(self.api.get('/api/mobile/dashboard/').status_code,401)

    def test_expired_or_inactive_membership_revokes_access(self):
        self.login()
        MobileSession.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.api.get('/api/mobile/dashboard/').status_code,401)
        self.api.credentials();self.login()
        Membership.objects.filter(user=self.patient_user).update(active=False)
        self.assertEqual(self.api.get('/api/mobile/dashboard/').status_code,401)

    def test_logout_revokes_session_and_push_device(self):
        self.login()
        self.api.post('/api/mobile/devices/',{'token':'ExpoPushToken[test_token_1234567890]','platform':'android'},format='json')
        self.assertEqual(self.api.post('/api/mobile/logout/',{},format='json').status_code,200)
        self.assertEqual(self.api.get('/api/mobile/dashboard/').status_code,401)
        self.assertFalse(PushDevice.objects.get().active)

    def test_patient_booking_options_and_dashboard_are_personal(self):
        self.login()
        options=self.api.get('/api/mobile/booking-options/').data
        self.assertEqual([p['id'] for p in options['patients']],[str(self.patient.pk)])
        dashboard=self.api.get('/api/mobile/dashboard/').data
        self.assertNotIn('OtherClinic',str(dashboard))
        self.assertIsNone(dashboard['next_patient'])
        self.assertEqual(self.api.post('/api/mobile/appointments/',{'patient':str(self.secret.pk),'practitioner':self.doctor.pk,
            'service':self.service.pk,'starts_at':(self.starts_at+timedelta(hours=2)).isoformat(),'reason_for_visit':'Example'},format='json').status_code,400)

    def test_patient_requests_own_visit_and_cannot_approve_it(self):
        self.login()
        response=self.api.post('/api/mobile/appointments/',{'patient':str(self.patient.pk),'practitioner':self.doctor.pk,
            'service':self.service.pk,'starts_at':(self.starts_at+timedelta(hours=2)).isoformat(),'reason_for_visit':'Reported cough'},format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(self.api.post(f'/api/mobile/appointments/{response.data["id"]}/approve/',{},format='json').status_code,403)

    def test_full_native_reception_doctor_patient_notification_workflow(self):
        self.login('reception','reception')
        intake=self.api.post(f'/api/mobile/appointments/{self.appointment.pk}/intake/',
            {'reason_for_visit':'Reported symptoms','blood_pressure_systolic':120,'blood_pressure_diastolic':80},format='json')
        self.assertEqual(intake.status_code,200,intake.data)
        self.assertEqual(self.api.post(f'/api/mobile/appointments/{self.appointment.pk}/approve/',{},format='json').status_code,200)
        self.api.credentials();self.login('Goodwill','doctor')
        next_visit=self.api.get('/api/mobile/dashboard/').data['next_patient']
        self.assertEqual(next_visit['patient'],'Demo Patient')
        self.assertEqual(next_visit['bp'],'120/80 mmHg')
        self.assertEqual(self.api.post(f'/api/mobile/appointments/{self.appointment.pk}/doctor-approve/',{},format='json').status_code,200)
        self.api.credentials();self.login()
        inbox=self.api.get('/api/mobile/dashboard/').data['notifications']
        self.assertEqual(len(inbox),1)
        self.assertIn('Hello Demo',inbox[0]['message'])
        self.assertIn('SAST',inbox[0]['message'])

    def test_patient_cannot_read_doctor_notification_or_register_staff_record(self):
        approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception)
        notice=Notification.objects.get(recipient=self.doctor)
        self.login()
        self.assertEqual(self.api.post(f'/api/mobile/notifications/{notice.pk}/read/',{},format='json').status_code,404)
        self.assertEqual(self.api.post('/api/mobile/patients/',{'file_number':'NEW'},format='json').status_code,403)

    def test_notifications_enqueue_generic_push_and_provider_acceptance(self):
        self.login()
        self.api.post('/api/mobile/devices/',{'token':'ExpoPushToken[test_token_1234567890]','platform':'ios'},format='json')
        self.appointment.status='held';self.appointment.save()
        doctor_approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.doctor)
        self.assertEqual(PushDelivery.objects.count(),1)
        with override_settings(MOBILE_PUSH_ENABLED=True,EXPO_ACCESS_TOKEN='test-only-token'),patch('mobile_api.push.urlopen') as send:
            reply=MagicMock();reply.read.return_value=b'{"data":{"status":"ok","id":"test-ticket"}}';send.return_value.__enter__.return_value=reply
            self.assertEqual(dispatch_pushes(),1)
            payload=send.call_args[0][0].data.decode()
            self.assertNotIn('Demo',payload);self.assertNotIn('120/80',payload)
            self.assertIn('Open MediFlow',payload)
        self.assertEqual(PushDelivery.objects.get().status,'sent')

    def test_push_worker_disabled_by_default(self):
        with patch('mobile_api.push.urlopen') as send:
            self.assertEqual(dispatch_pushes(),0)
            send.assert_not_called()

    def test_relinked_patient_cannot_receive_or_view_old_update(self):
        self.login()
        self.api.post('/api/mobile/devices/',{'token':'ExpoPushToken[test_token_1234567890]','platform':'android'},format='json')
        self.appointment.status='held';self.appointment.save()
        doctor_approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.doctor)
        self.patient.portal_user=None;self.patient.save()
        self.assertEqual(self.api.get('/api/mobile/dashboard/').data['notifications'],[])
        with override_settings(MOBILE_PUSH_ENABLED=True,EXPO_ACCESS_TOKEN='test-only-token'),patch('mobile_api.push.urlopen') as send:
            dispatch_pushes();send.assert_not_called()
        self.assertEqual(PushDelivery.objects.get().status,'cancelled')

    def test_malformed_practice_id_returns_validation_error(self):
        response=self.api.post('/api/mobile/login/',{'username':'patient','password':'test-password',
            'workspace':'patient','practice':'not-a-uuid'},format='json')
        self.assertEqual(response.status_code,400)
        self.assertFalse(MobileSession.objects.exists())

    @override_settings(MOBILE_PUSH_ENABLED=True,EXPO_ACCESS_TOKEN='test-provider-token')
    @patch('mobile_api.push.urlopen')
    def test_changed_workspace_role_cancels_pending_push(self, provider):
        self.login()
        self.api.post('/api/mobile/devices/',{'token':'ExpoPushToken[test_token_1234567890]','platform':'android'},format='json')
        approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception)
        doctor_approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.doctor)
        Membership.objects.filter(user=self.patient_user,practice=self.practice).update(role='doctor')
        dispatch_pushes()
        self.assertEqual(PushDelivery.objects.get().status,'cancelled')
        provider.assert_not_called()

    def test_structured_workspace_does_not_crash_login(self):
        response=self.api.post('/api/mobile/login/',{'username':'patient','password':'test-password','workspace':{}},format='json')
        self.assertEqual(response.status_code,400)

    def test_native_prescription_requires_doctor_and_explicit_review(self):
        approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.reception)
        doctor_approve_booking(appointment_id=self.appointment.pk,practice=self.practice,actor=self.doctor)
        self.login('Goodwill','doctor')
        self.assertEqual(self.api.post(f'/api/mobile/appointments/{self.appointment.pk}/encounter/',{},format='json').status_code,200)
        encounter=self.api.get('/api/mobile/dashboard/').data['encounters'][0]['id']
        created=self.api.post('/api/mobile/prescriptions/',{'encounter':encounter,'medication_name':'Test medication',
            'dosage':'Example dose','frequency':'Example frequency'},format='json')
        self.assertEqual(created.status_code,201,created.data)
        url=f'/api/mobile/prescriptions/{created.data["id"]}/issue/'
        self.assertEqual(self.api.post(url,{},format='json').status_code,400)
        self.api.credentials();self.login()
        self.assertEqual(self.api.get('/api/mobile/dashboard/').data['prescriptions'],[])
        self.assertEqual(self.api.post(url,{'reviewed':True},format='json').status_code,403)
        self.api.credentials();self.login('Goodwill','doctor')
        self.assertEqual(self.api.post(url,{'reviewed':True},format='json').status_code,200)
        self.api.credentials();self.login()
        self.assertEqual(self.api.get('/api/mobile/dashboard/').data['prescriptions'][0]['id'],created.data['id'])
