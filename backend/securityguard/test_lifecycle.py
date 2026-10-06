import re
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings, Client
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from tenancy.models import Membership, Practice
from patients.models import Patient
from .accounts import queue_invitation
from .models import AccountInvitation, EmailTask, RecoveryCode


class LifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.practice = Practice.objects.create(name='Lifecycle clinic')
        cls.owner = get_user_model().objects.create_user(username='lifecycle-owner', password='Initial-'+'c4D7e9F2'*2)
        cls.patient = get_user_model().objects.create_user(username='lifecycle-patient', email='patient@example.invalid')
        cls.patient.set_unusable_password()
        cls.patient.save()
        Membership.objects.create(user=cls.owner, practice=cls.practice, role='owner')
        cls.member = Membership.objects.create(user=cls.patient, practice=cls.practice, role='patient')

    def token(self):
        with override_settings(EMAIL_ENABLED=True, PUBLIC_BASE_URL='https://clinic.example.invalid', EMAIL_HOST='mail.invalid',
                EMAIL_HOST_USER='mailer', EMAIL_HOST_PASSWORD='test-'+'a4b7c9'*4, DEFAULT_FROM_EMAIL='clinic@example.invalid'):
            queue_invitation(self.patient, self.practice)
        return re.search(r'/app/invite/([^/]+)/', EmailTask.objects.last().body)[1]

    def test_invitation_is_single_use_and_invalidates_old_links(self):
        old = self.token()
        token = self.token()
        self.assertEqual(self.client.get('/app/invite/'+old+'/').status_code, 400)
        password = 'Chosen-'+'x7Y4z2N9'*2
        response = self.client.post('/app/invite/'+token+'/', {'new_password1':password, 'new_password2':password})
        self.assertEqual(response.status_code, 302)
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.check_password(password))
        self.assertEqual(self.client.get('/app/invite/'+token+'/').status_code, 400)
        self.assertNotIn(token, AccountInvitation.objects.last().token_digest)

    def test_disabled_membership_and_expired_invitation_rejected(self):
        token = self.token()
        self.member.active = False
        self.member.save()
        self.assertEqual(self.client.get('/app/invite/'+token+'/').status_code, 400)
        self.member.active = True
        self.member.save()
        AccountInvitation.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/app/invite/'+token+'/').status_code, 400)

    def test_disable_is_scoped_and_audited(self):
        other = Practice.objects.create(name='Second clinic')
        other_member = Membership.objects.create(user=self.patient, practice=other, role='patient')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(f'/app/accounts/{self.member.pk}/disable/', {'practice':self.practice.pk}).status_code, 302)
        self.member.refresh_from_db()
        other_member.refresh_from_db()
        self.assertFalse(self.member.active)
        self.assertTrue(other_member.active)
        self.assertEqual(self.client.post(f'/app/accounts/{other_member.pk}/disable/', {'practice':self.practice.pk}).status_code, 404)

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_mfa_gates_admin_and_api_not_patient(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get('/app/admin/'), '/app/security/mfa/', fetch_redirect_response=False)
        self.assertRedirects(self.client.get('/admin/'), '/app/security/mfa/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/api/patients/').status_code, 403)
        self.client.force_login(self.patient)
        self.assertNotEqual(self.client.get('/app/patient/').get('Location'), '/app/security/mfa/')

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_mfa_enrolment_password_codes_and_single_use_recovery(self):
        self.client.force_login(self.owner)
        self.client.get('/app/security/mfa/setup/')
        device = TOTPDevice.objects.get(user=self.owner)
        code = f"{totp(device.bin_key):06d}"
        response = self.client.post('/app/security/mfa/setup/', {'code':code, 'password':'Initial-'+'c4D7e9F2'*2})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Save your recovery codes')
        self.assertEqual(RecoveryCode.objects.filter(user=self.owner).count(), 10)
        code = re.findall(r'<code>([A-F0-9]+)</code>', response.content.decode())[0]
        self.assertFalse(RecoveryCode.objects.filter(digest=code).exists())
        self.assertEqual(self.client.get('/app/admin/').status_code, 200)
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post('/app/security/mfa/', {'code':code}).status_code, 302)
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertContains(self.client.post('/app/security/mfa/', {'code':code}), 'Invalid or already used')

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_mfa_replay_and_wrong_enrolment_password(self):
        self.client.force_login(self.owner)
        self.client.get('/app/security/mfa/setup/')
        device = TOTPDevice.objects.get(user=self.owner)
        code = f"{totp(device.bin_key):06d}"
        self.assertContains(self.client.post('/app/security/mfa/setup/', {'code':code, 'password':'wrong'}), 'Current password is incorrect')
        device.refresh_from_db()
        self.assertFalse(device.confirmed)
        self.client.post('/app/security/mfa/setup/', {'code':code, 'password':'Initial-'+'c4D7e9F2'*2})
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertContains(self.client.post('/app/security/mfa/', {'code':code}), 'Invalid or already used')

    @override_settings(EMAIL_ENABLED=True, PUBLIC_BASE_URL='https://clinic.example.invalid', EMAIL_HOST='mail.invalid',
        EMAIL_HOST_USER='mailer', EMAIL_HOST_PASSWORD='test-'+'a4b7c9'*4, DEFAULT_FROM_EMAIL='clinic@example.invalid',
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_worker_erases_secret_body(self):
        token = self.token()
        call_command('send_account_emails', verbosity=0)
        task = EmailTask.objects.last()
        self.assertEqual(task.body, '')
        self.assertIsNotNone(task.sent_at)
        from django.core import mail
        self.assertIn(token, mail.outbox[-1].body)

    @override_settings(EMAIL_ENABLED=False)
    def test_unknown_reset_same_response_and_mfa_csrf(self):
        self.assertEqual(self.client.post('/app/password/reset/', {'email':'unknown@example.invalid'}).status_code, 302)
        self.assertFalse(EmailTask.objects.exists())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post('/app/security/mfa/setup/', {'code':'123456', 'password':'wrong'}).status_code, 403)

    @override_settings(EMAIL_ENABLED=True, PUBLIC_BASE_URL='https://clinic.example.invalid', EMAIL_HOST='mail.invalid',
        EMAIL_HOST_USER='mailer', EMAIL_HOST_PASSWORD='test-'+'a4b7c9'*4, DEFAULT_FROM_EMAIL='clinic@example.invalid')
    def test_password_reset_queues_link_and_changes_password_once(self):
        self.patient.set_password('Initial-'+'k2M5n8R4'*2)
        self.patient.save()
        response = self.client.post('/app/password/reset/', {'email':self.patient.email})
        self.assertEqual(response.status_code, 302)
        task = EmailTask.objects.last()
        path = re.search(r'https://clinic.example.invalid(/app/password/reset/[^\s]+)', task.body)[1]
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        safe_path = response['Location']
        password = 'Reset-'+'t7V2w9Z3'*2
        self.assertEqual(self.client.post(safe_path, {'new_password1':password, 'new_password2':password}).status_code, 302)
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.check_password(password))
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertContains(self.client.get(path), 'unsuccessful')

    def test_operations_flags_stale_workers_and_missing_backup(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from .management.commands.check_operations import operation_failures
        from .models import OperationalHeartbeat
        with TemporaryDirectory() as root, override_settings(BACKUP_ROOT=Path(root), OFFSITE_BACKUP_REQUIRED=True):
            failures = operation_failures()
            self.assertTrue(any('scanner' in item for item in failures))
            self.assertTrue(any('local backup' in item for item in failures))
            self.assertTrue(any('offsite' in item for item in failures))
            OperationalHeartbeat.objects.create(name='document-scanner', last_success=timezone.now())
            directory = Path(root)/timezone.now().strftime('%Y%m%dT%H%M%SZ')
            directory.mkdir()
            for name in ['database.dump', 'private_documents.tar.gz', 'SHA256SUMS']:
                (directory/name).write_bytes(b'test')
            (Path(root)/'.offsite-success').write_bytes(b'test')
            self.assertEqual(operation_failures(), [])

    def test_logging_redacts_account_links(self):
        import logging
        from .logging import SecretPathFilter
        record = logging.LogRecord('csrf', logging.WARNING, '', 0,
            'Forbidden: %s', ('/app/invite/secret-token/',), None)
        SecretPathFilter().filter(record)
        self.assertNotIn('secret-token', record.getMessage())

    @override_settings(PUBLIC_BASE_URL='https://demo.trycloudflare.com', EMAIL_ENABLED=False,
        ADMIN_MFA_REQUIRED=False, PRIVACY_CONTACT='', PRACTICE_OPERATOR='', RETENTION_NOTICE='')
    def test_release_gate_reports_configuration_and_operational_gaps_together(self):
        from io import StringIO
        from unittest.mock import patch
        from django.core.management.base import CommandError
        with patch('securityguard.management.commands.check_release_readiness.call_command',
                side_effect=[None, CommandError('Backup evidence missing.')]):
            with self.assertRaises(CommandError) as caught:
                call_command('check_release_readiness', stdout=StringIO())
        self.assertIn('permanent HTTPS', str(caught.exception))
        self.assertIn('SMTP', str(caught.exception))
        self.assertIn('Backup evidence missing', str(caught.exception))


    def test_shared_email_cannot_receive_account_invitation(self):
        from django.core.exceptions import ImproperlyConfigured
        get_user_model().objects.create_user(username='shared-address', email=self.patient.email)
        with self.assertRaises(ImproperlyConfigured):
            self.token()
        self.assertFalse(AccountInvitation.objects.exists())


    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_mfa_setup_can_sign_out_without_verification_and_keeps_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.get('/app/security/mfa/setup/')
        self.assertContains(response, 'Sign out and return to sign-in')
        self.assertContains(response, 'action="/app/logout/"')
        self.assertEqual(client.post('/app/logout/').status_code, 403)
        response = client.post('/app/logout/', {'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertRedirects(response, '/app/login/')
        self.assertNotIn('_auth_user_id', client.session)
        self.assertContains(client.get('/app/login/'), 'Reception')

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_mfa_setup_rejects_username_as_code_without_enrolling(self):
        self.client.force_login(self.owner)
        response = self.client.post('/app/security/mfa/setup/', {
            'code': self.owner.username, 'password': 'Initial-'+'c4D7e9F2'*2})
        self.assertContains(response, 'Six-digit code from your authenticator app')
        self.assertFalse(TOTPDevice.objects.get(user=self.owner).confirmed)
        self.assertFalse(RecoveryCode.objects.filter(user=self.owner).exists())
