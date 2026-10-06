from urllib.parse import urlsplit
from django.conf import settings
from django.db.models import Q
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django_otp.plugins.otp_totp.models import TOTPDevice
from tenancy.models import Membership
from securityguard.accounts import mail_ready


class Command(BaseCommand):
    help = 'Fail the real-patient release gate until external services and administrator MFA are ready.'

    def handle(self, **options):
        call_command('check_production')
        failures = []
        origin = urlsplit(settings.PUBLIC_BASE_URL)
        if (origin.scheme != 'https' or not origin.hostname or origin.path not in ['', '/']
                or origin.hostname.endswith(('.trycloudflare.com', '.invalid', '.example.com'))
                or origin.hostname in ['localhost', '127.0.0.1']):
            failures.append('Configure a permanent HTTPS origin in MEDIFLOW_PUBLIC_URL.')
        if not mail_ready():
            failures.append('Configure SMTP and verify real invitation/reset delivery.')
        if not settings.ADMIN_MFA_REQUIRED:
            failures.append('Administrator MFA must be required.')
        privileged = get_user_model().objects.filter(is_active=True).filter(
            Q(is_staff=True) | Q(is_superuser=True) |
            Q(membership__active=True, membership__role__in=['owner', 'reception'])).distinct()
        if not privileged.exists():
            failures.append('Create and enrol an administrator account.')
        if privileged.exclude(pk__in=TOTPDevice.objects.filter(confirmed=True).values('user_id')).exists():
            failures.append('Every active administrator/reception account must enrol an authenticator.')
        if not settings.PRIVACY_CONTACT or not settings.PRACTICE_OPERATOR or not settings.RETENTION_NOTICE:
            failures.append('Configure the practice operator, privacy contact and approved retention notice.')
        if not settings.OPERATIONS_EMAIL or not settings.EXTERNAL_MONITOR_CONFIGURED:
            failures.append('Configure and test operational alerts and independent uptime monitoring.')
        if not settings.OFFSITE_BACKUP_REQUIRED:
            failures.append('Enable and verify encrypted offsite backups.')
        try:
            call_command('check_operations')
        except CommandError as error:
            failures.append(str(error))
        if failures:
            raise CommandError('\n'.join(failures))
        self.stdout.write('Automated release gates passed. Signed workflow/recovery/privacy acceptance is still required.')
