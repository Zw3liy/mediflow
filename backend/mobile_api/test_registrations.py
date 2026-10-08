from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory,force_authenticate
from patients.models import Patient
from tenancy.models import Practice,Membership
from .registrations import PatientRegistration,AccountRegistration,Registrations
class RegistrationTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_user('admin-demo')
        self.user=get_user_model().objects.create_user('patient-demo')
        self.practice=Practice.objects.create(name='Demo')
        self.patient=Patient.objects.create(practice=self.practice,portal_user=self.user,file_number='1',given_name='Demo',family_name='Old')
        self.member=Membership.objects.create(practice=self.practice,user=self.user,role='patient')
    def call(self,view,role,data=None,**kwargs):
        request=APIRequestFactory().patch('/',data or {},format='json')
        force_authenticate(request,self.admin,SimpleNamespace(practice=self.practice,current_role=role))
        return view.as_view()(request,**kwargs)
    def test_edit_and_preserve_login(self):
        response=self.call(PatientRegistration,'owner',{'family_name':'New','address':'Demo Road'},pk=self.patient.pk)
        self.assertEqual(response.status_code,200,response.data)
        self.patient.refresh_from_db();self.assertEqual(self.patient.family_name,'New');self.assertEqual(self.patient.portal_user,self.user)
    def test_patient_cannot_manage(self):
        self.assertEqual(self.call(PatientRegistration,'patient',{'family_name':'No'},pk=self.patient.pk).status_code,403)
    def test_archive_retains_and_disables(self):
        self.assertEqual(self.call(PatientRegistration,'owner',{'active':False},pk=self.patient.pk).status_code,200)
        self.member.refresh_from_db();self.assertFalse(self.member.active);self.assertTrue(Patient.objects.filter(pk=self.patient.pk).exists())
    def test_other_practice_hidden(self):
        other=Practice.objects.create(name='Other');Patient.objects.filter(pk=self.patient.pk).update(practice=other)
        self.assertEqual(self.call(PatientRegistration,'owner',{'address':'No'},pk=self.patient.pk).status_code,404)
    def test_shared_account_edit_blocked(self):
        Membership.objects.create(practice=Practice.objects.create(name='Other'),user=self.user,role='patient')
        self.assertEqual(self.call(AccountRegistration,'owner',{'last_name':'No'},pk=self.member.pk).status_code,400)
    def test_account_disable(self):
        self.assertEqual(self.call(AccountRegistration,'owner',{'active':False},pk=self.member.pk).status_code,200)
        self.member.refresh_from_db();self.assertFalse(self.member.active)
