import base64
import io
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from patients.models import Patient
from portal import tests as fixtures
from .models import PatientDocumentScan
from .ocr import OCRUnavailable, recognize_image, suggest_patient_details


class RecognitionTests(SimpleTestCase):
    def test_suggestions_use_labels_and_omit_ambiguous_fields(self):
        result = suggest_patient_details('First name: Demo\nSurname: Patient\nDOB: 03/04/1990\nMobile: 0712345678\nEmail: demo@example.com\nAddress: 12 Example Road')
        self.assertEqual(result['given_name'], 'Demo')
        self.assertEqual(result['address'], '12 Example Road')
        self.assertNotIn('date_of_birth', result)
        self.assertNotIn('given_name', suggest_patient_details('First name: One\nFirst name: Two'))
        self.assertEqual(suggest_patient_details('Date of birth: 1990-04-03')['date_of_birth'], '1990-04-03')

    def test_bad_base64_and_oversized_input_are_rejected(self):
        for encoded in ('!!', '', None, 'a' * 11_184_816):
            with self.assertRaises(ValidationError):
                recognize_image(encoded)

    @patch('documents.ocr.get_document_scanner')
    def test_malware_and_unavailable_scanner_fail_closed(self, scanner):
        encoded = base64.b64encode(b'not an image').decode()
        scanner.return_value.scan.return_value = 'infected'
        with self.assertRaises(ValidationError):
            recognize_image(encoded)
        scanner.return_value.scan.side_effect = RuntimeError('unavailable')
        with self.assertRaises(OCRUnavailable):
            recognize_image(encoded)

    @patch('documents.ocr.get_document_scanner')
    def test_real_ocr_produces_searchable_pdf_and_preserves_original(self, scanner):
        if not shutil.which('tesseract'):
            self.skipTest('Tesseract is not installed in this environment')
        scanner.return_value.scan.return_value = 'clean'
        image = Image.new('RGB', (1600, 700), 'white')
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        font = ImageFont.truetype(font_path, 42) if shutil.which('fc-list') else ImageFont.load_default(size=42)
        ImageDraw.Draw(image).multiline_text((70, 70), 'First name: Demo\nSurname: Patient\nDOB: 1990-04-03\nMobile: 0712345678', font=font, fill='black', spacing=20)
        data = io.BytesIO(); image.save(data, format='PNG')
        output = recognize_image(base64.b64encode(data.getvalue()).decode())
        self.assertEqual(output['original'], data.getvalue())
        self.assertTrue(output['pdf'].startswith(b'%PDF'))
        self.assertIn('Demo', output['text'])
        self.assertEqual(output['suggestions']['family_name'], 'Patient')
        self.assertIn(b'/Font', output['pdf'])


@override_settings(ADMIN_MFA_REQUIRED=False)
class ScanWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.PortalTests.setUpTestData.__func__(cls)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(DOCUMENT_STORAGE_ROOT=self.directory.name)
        self.settings_override.enable(); self.addCleanup(self.settings_override.disable)
        self.api = APIClient()
        self.login()

    def login(self, username='reception', workspace='reception'):
        self.api.credentials()
        response = self.api.post('/api/mobile/login/', {'username':username, 'password':'test-password', 'workspace':workspace}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['token'])

    def draft(self):
        output = {'original': b'image', 'pdf': b'%PDF-test', 'content_type': 'image/jpeg', 'sha256': 'a'*64,
                  'text': 'First name: Demo', 'suggestions': {'given_name': 'Demo'}}
        with patch('mobile_api.document_scans.recognize_image', return_value=output):
            response = self.api.post('/api/mobile/document-scans/', {'image_base64':'test'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return PatientDocumentScan.objects.get(pk=response.data['id'])

    def review(self, **overrides):
        data = dict(confirmed=True, title='Intake form', reviewed_text='Reviewed text', patient_details=dict(
            file_number='NEW-1', given_name='Reviewed', family_name='Patient', date_of_birth='1990-01-01',
            mobile='0712345678', email='demo@example.com', address='12 Example Road'))
        data.update(overrides)
        return data

    def test_upload_only_creates_draft_until_reviewed(self):
        count = Patient.objects.count(); scan = self.draft()
        self.assertIsNone(scan.patient_id); self.assertEqual(Patient.objects.count(), count)
        self.assertEqual(self.api.get('/api/mobile/document-scans/').data['documents'], [])
        response = self.api.post(f'/api/mobile/document-scans/{scan.pk}/', self.review(confirmed=False), format='json')
        self.assertEqual(response.status_code, 400)
        response = self.api.post(f'/api/mobile/document-scans/{scan.pk}/', self.review(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        scan.refresh_from_db(); self.assertEqual(scan.patient.given_name, 'Reviewed')
        self.assertEqual(scan.patient.address, '12 Example Road')
        self.assertIsNotNone(scan.reviewed_at)
        self.api.post(f'/api/mobile/document-scans/{scan.pk}/', self.review(), format='json')
        self.assertEqual(Patient.objects.count(), count + 1)
        self.assertEqual(len(self.api.get('/api/mobile/document-scans/').data['documents']), 1)

    def test_existing_patient_update_requires_current_version_and_preserves_login(self):
        scan = self.draft(); data = self.review(patient_id=str(self.patient.pk))
        data['patient_details']['file_number'] = self.patient.file_number
        self.assertEqual(self.api.post(f'/api/mobile/document-scans/{scan.pk}/', data, format='json').status_code, 400)
        data['expected_patient_updated_at'] = self.patient.updated_at.isoformat()
        response = self.api.post(f'/api/mobile/document-scans/{scan.pk}/', data, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.patient.refresh_from_db(); self.assertEqual(self.patient.portal_user, self.patient_user)
        self.assertEqual(self.patient.given_name, 'Reviewed')

    def test_other_practice_patient_and_scan_are_inaccessible(self):
        scan = self.draft(); data = self.review(patient_id=str(self.secret.pk))
        self.assertEqual(self.api.post(f'/api/mobile/document-scans/{scan.pk}/', data, format='json').status_code, 404)
        PatientDocumentScan.objects.filter(pk=scan.pk).update(practice=self.other)
        for suffix in ('', 'download/pdf/', 'download/original/'):
            self.assertEqual(self.api.get(f'/api/mobile/document-scans/{scan.pk}/{suffix}').status_code, 404)

    def test_doctors_and_patients_cannot_scan_review_download_or_list(self):
        scan = self.draft()
        for username, workspace in [('patient','patient'), ('Goodwill','doctor')]:
            self.login(username, workspace)
            self.assertEqual(self.api.get('/api/mobile/document-scans/').status_code, 403)
            self.assertEqual(self.api.post('/api/mobile/document-scans/', {}, format='json').status_code, 403)
            self.assertEqual(self.api.post(f'/api/mobile/document-scans/{scan.pk}/', self.review(), format='json').status_code, 403)
            self.assertEqual(self.api.get(f'/api/mobile/document-scans/{scan.pk}/download/pdf/').status_code, 403)

    def test_duplicate_file_and_invalid_details_do_not_attach_draft(self):
        scan = self.draft(); data = self.review()
        data['patient_details']['file_number'] = self.patient.file_number
        self.assertEqual(self.api.post(f'/api/mobile/document-scans/{scan.pk}/', data, format='json').status_code, 400)
        data['patient_details']['email'] = 'bad'
        self.assertEqual(self.api.post(f'/api/mobile/document-scans/{scan.pk}/', data, format='json').status_code, 400)
        scan.refresh_from_db(); self.assertIsNone(scan.patient_id)

    def test_original_and_pdf_private_download_and_discard(self):
        scan = self.draft()
        response = self.api.get(f'/api/mobile/document-scans/{scan.pk}/download/pdf/')
        self.assertEqual(base64.b64decode(response.data['base64']), b'%PDF-test')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.api.delete(f'/api/mobile/document-scans/{scan.pk}/').status_code, 204)
        from pathlib import Path
        self.assertFalse((Path(self.directory.name)/scan.pdf_key).exists())
        self.assertFalse(PatientDocumentScan.objects.filter(pk=scan.pk).exists())

    def test_expired_draft_cleanup_never_removes_reviewed_document(self):
        expired = self.draft(); saved = self.draft()
        self.api.post(f'/api/mobile/document-scans/{saved.pk}/', self.review(), format='json')
        PatientDocumentScan.objects.update(created_at=timezone.now()-timedelta(days=2))
        self.assertEqual(self.api.get(f'/api/mobile/document-scans/{expired.pk}/').status_code, 400)
        call_command('cleanup_document_scans', stdout=io.StringIO())
        self.assertFalse(PatientDocumentScan.objects.filter(pk=expired.pk).exists())
        self.assertTrue(PatientDocumentScan.objects.filter(pk=saved.pk).exists())

    def test_ocr_failure_creates_no_record(self):
        with patch('mobile_api.document_scans.recognize_image', side_effect=OCRUnavailable('Try again')):
            response = self.api.post('/api/mobile/document-scans/', {'image_base64':'test'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(PatientDocumentScan.objects.exists())
