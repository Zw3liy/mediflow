from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from tenancy.models import Practice
from patients.models import Patient
from clinical.models import HealthEntry
from .health import HealthEntries, HealthEntryEdit

class HealthTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('health-user')
        self.other=get_user_model().objects.create_user('other-user')
        self.practice=Practice.objects.create(name='Health Practice')
        self.patient=Patient.objects.create(practice=self.practice,portal_user=self.user,file_number='H1',given_name='Demo',family_name='Patient')
        self.other_patient=Patient.objects.create(practice=self.practice,portal_user=self.other,file_number='H2',given_name='Other',family_name='Patient')
        self.factory=APIRequestFactory()
    def request(self, role, method, body=None, patient=None, pk=None):
        request=getattr(self.factory,method)('/',body or {},format='json')
        force_authenticate(request,self.user,SimpleNamespace(practice=self.practice,current_role=role))
        view=HealthEntryEdit if pk else HealthEntries
        kwargs={'patient_id':(patient or self.patient).pk}
        if pk: kwargs['pk']=pk
        return view.as_view()(request,**kwargs)
    def test_patient_isolation(self):
        self.assertEqual(self.request('patient','get',patient=self.other_patient).status_code,404)
    def test_patient_cannot_enter_clinical_results(self):
        self.assertEqual(self.request('patient','post',{'kind':'vitals','data':{'heart_rate':70}}).status_code,403)
    def test_daily_log_persists(self):
        self.assertEqual(self.request('patient','post',{'kind':'wellness','data':{'walk_minutes':25,'nutrition':'Lunch logged'}}).status_code,201)
        self.assertEqual(HealthEntry.objects.count(),1)
    def test_vitals_validation(self):
        for data in [{'systolic':120},{'oxygen':101},{'heart_rate':'nan'},{'systolic':70,'diastolic':90}]:
            self.assertEqual(self.request('owner','post',{'kind':'vitals','data':data}).status_code,400)
    def test_review_and_edit_clears_review(self):
        created=self.request('reception','post',{'kind':'vitals','data':{'heart_rate':70}})
        self.assertEqual(created.status_code,201)
        pk=created.data['id']
        self.assertEqual(self.request('reception','patch',{'review':True},pk=pk).status_code,403)
        self.assertTrue(self.request('doctor','patch',{'review':True},pk=pk).data['reviewed'])
        self.assertFalse(self.request('reception','patch',{'data':{'heart_rate':72}},pk=pk).data['reviewed'])
    def test_trends(self):
        for value in [70,75]: self.request('owner','post',{'kind':'vitals','data':{'heart_rate':value}})
        self.assertEqual(self.request('patient','get').data['trends']['heart_rate']['change'],5)
