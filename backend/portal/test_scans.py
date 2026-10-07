import io
import tempfile
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from portal import tests as fixtures
from documents.models import PatientDocumentScan
from rest_framework.test import APIClient


@override_settings(ADMIN_MFA_REQUIRED=False)
class BrowserScanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.PortalTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        setting=override_settings(DOCUMENT_STORAGE_ROOT=self.directory.name);setting.enable();self.addCleanup(setting.disable)
        self.client=Client();self.client.force_login(self.reception)
        self.base=f'/app/scans/api/?practice={self.practice.pk}'

    def draft(self):
        output={'original':b'original','pdf':b'%PDF-test','content_type':'image/jpeg','sha256':'a'*64,'text':'First name: Demo','suggestions':{'given_name':'Demo'}}
        with patch('mobile_api.document_scans.recognize_image',return_value=output):
            result=self.client.post(self.base,{'image_base64':'test'},content_type='application/json')
        self.assertEqual(result.status_code,201,result.content)
        return PatientDocumentScan.objects.get(pk=result.json()['id'])

    def test_screen_shows_scanner_and_dashboard_links(self):
        response=self.client.get(f'/app/scans/?practice={self.practice.pk}')
        self.assertContains(response,'Approve &amp; save to patient file')
        self.assertContains(response,'portal/scans.js')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertContains(self.client.get('/app/reception/'),'Scan patient document')

    def test_browser_capture_review_original_and_pdf(self):
        scan=self.draft()
        values={'confirmed':True,'title':'Intake','reviewed_text':'Reviewed',
          'patient_details':{'file_number':'NEW-1','given_name':'Demo','family_name':'Patient','address':'12 Example Road'}}
        result=self.client.post(f'/app/scans/api/{scan.pk}/?practice={self.practice.pk}',values,content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        scan.refresh_from_db();self.assertEqual(scan.patient.address,'12 Example Road')
        response=self.client.get(f'/app/scans/api/{scan.pk}/download/pdf/?practice={self.practice.pk}')
        self.assertEqual(response.content,b'%PDF-test');self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertIn('attachment',response['Content-Disposition'])
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get(f'/app/scans/api/{scan.pk}/download/original/').content,b'original')

    def test_csrf_required_for_browser_upload_and_mobile_bearer_not_accepted(self):
        api=APIClient(enforce_csrf_checks=True);api.force_login(self.reception)
        self.assertEqual(api.post(self.base,{'image_base64':'test'},format='json').status_code,403)
        response=api.get(f'/app/scans/?practice={self.practice.pk}')
        token=response.cookies['csrftoken'].value
        with patch('mobile_api.document_scans.recognize_image',side_effect=__import__('documents.ocr',fromlist=['OCRUnavailable']).OCRUnavailable('Offline')):
            self.assertEqual(api.post(self.base,{'image_base64':'test'},format='json',HTTP_X_CSRFTOKEN=token).status_code,503)
        api.logout();api.credentials(HTTP_AUTHORIZATION='Bearer invalid')
        self.assertEqual(api.get(self.base).status_code,403)

    def test_patient_doctor_and_other_practice_are_denied(self):
        scan=self.draft()
        for user in [self.doctor,self.patient_user]:
            self.client.force_login(user)
            self.assertEqual(self.client.get('/app/scans/').status_code,403)
            self.assertEqual(self.client.get(self.base).status_code,403)
            self.assertEqual(self.client.get(f'/app/scans/api/{scan.pk}/download/pdf/').status_code,403)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(f'/app/scans/api/?practice={self.other.pk}').status_code,404)
        PatientDocumentScan.objects.filter(pk=scan.pk).update(practice=self.other)
        self.assertEqual(self.client.get(f'/app/scans/api/{scan.pk}/').status_code,404)
