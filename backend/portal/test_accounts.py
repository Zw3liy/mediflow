from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from patients.models import Patient
from tenancy.models import Membership, Practice


class AccountRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.practice = Practice.objects.create(name='Account clinic')
        cls.other = Practice.objects.create(name='Other clinic')
        cls.reception = get_user_model().objects.create_user(username='registrar')
        cls.doctor = get_user_model().objects.create_user(username='existing-doctor')
        Membership.objects.create(practice=cls.practice, user=cls.reception, role='reception')
        Membership.objects.create(practice=cls.practice, user=cls.doctor, role='doctor')
        cls.patient = Patient.objects.create(practice=cls.practice, file_number='A1', given_name='Test', family_name='Patient')
        cls.foreign = Patient.objects.create(practice=cls.other, file_number='B1', given_name='Other', family_name='Patient')

    def setUp(self):
        self.client.force_login(self.reception)

    def payload(self, **extra):
        password = 'Clinic-' + 'a7B9x2Q4' * 2
        return dict(username='new-account', first_name='Test', last_name='Account',
                    password1=password, password2=password, practice=str(self.practice.pk), **extra)

    def test_reception_creates_doctor_without_admin_privileges(self):
        response = self.client.post('/app/accounts/new/doctor/', self.payload(is_staff='true', is_superuser='true', role='owner'))
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='new-account')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(self.payload()['password1']))
        self.assertEqual(Membership.objects.get(user=user).role, 'doctor')
        self.client.logout()
        response = self.client.post('/app/login/doctor/', {'username':user.username, 'password':self.payload()['password1']})
        self.assertEqual(response.status_code, 302)

    def test_patient_creation_links_own_record(self):
        self.assertEqual(self.client.post('/app/accounts/new/patient/', self.payload(patient=str(self.patient.pk))).status_code, 302)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.portal_user.username, 'new-account')
        self.assertEqual(Membership.objects.get(user=self.patient.portal_user).role, 'patient')

    def test_foreign_patient_and_practice_rejected(self):
        self.assertEqual(self.client.post('/app/accounts/new/patient/', self.payload(patient=str(self.foreign.pk))).status_code, 200)
        values = self.payload()
        values['practice'] = str(self.other.pk)
        self.assertEqual(self.client.post('/app/accounts/new/doctor/', values).status_code, 404)
        self.assertFalse(get_user_model().objects.filter(username='new-account').exists())

    def test_doctor_cannot_register_or_escalate(self):
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.post('/app/accounts/new/patient/', self.payload(patient=str(self.patient.pk))).status_code, 403)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.post('/app/accounts/new/owner/', self.payload()).status_code, 403)

    def test_weak_password_duplicate_and_linked_record_rejected(self):
        values = self.payload()
        values.update(password1='short', password2='short')
        self.assertEqual(self.client.post('/app/accounts/new/doctor/', values).status_code, 200)
        self.client.post('/app/accounts/new/patient/', self.payload(patient=str(self.patient.pk)))
        values = self.payload(patient=str(self.patient.pk))
        values['username'] = 'second-account'
        self.assertEqual(self.client.post('/app/accounts/new/patient/', values).status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='second-account').exists())
        self.assertEqual(self.client.post('/app/accounts/new/doctor/', self.payload()).status_code, 200)

    def test_registration_requires_csrf_and_buttons_visible(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reception)
        self.assertEqual(client.post('/app/accounts/new/doctor/', self.payload()).status_code, 403)
        self.assertContains(self.client.get('/app/reception/'), 'Add doctor account')
        self.assertContains(self.client.get('/app/reception/'), 'Add patient account')
