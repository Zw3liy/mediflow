from datetime import datetime, timedelta, timezone as dt_timezone
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail
from django.db import connection
from django.utils import timezone
from documents.models import PrescriptionDocument
from securityguard.accounts import mail_ready
from securityguard.models import EmailTask, OperationalHeartbeat


def operation_failures():
    now = timezone.now()
    failures = []
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    heartbeat = OperationalHeartbeat.objects.filter(name='document-scanner').first()
    if not heartbeat or now-heartbeat.last_success > timedelta(minutes=5):
        failures.append('Document scanner heartbeat is missing or stale.')
    if PrescriptionDocument.objects.filter(scan_status='pending', created_at__lt=now-timedelta(minutes=10)).exists():
        failures.append('Documents are waiting too long for scanning.')
    if PrescriptionDocument.objects.filter(scan_status='failed').exists():
        failures.append('Failed document scans require operator review before release.')
    if EmailTask.objects.filter(sent_at__isnull=True, created_at__lt=now-timedelta(minutes=10)).exists():
        failures.append('Account emails are pending or failed.')
    backups = sorted(settings.BACKUP_ROOT.glob('20??????T??????Z'))
    fresh = False
    if backups:
        try:
            timestamp = datetime.strptime(backups[-1].name, '%Y%m%dT%H%M%SZ').replace(tzinfo=dt_timezone.utc)
            fresh = (timedelta(0) <= now-timestamp < timedelta(hours=26) and
                all((backups[-1]/name).is_file() for name in ['database.dump', 'private_documents.tar.gz', 'SHA256SUMS']))
        except ValueError:
            pass
    if not fresh:
        failures.append('A complete recent local backup is missing.')
    if settings.OFFSITE_BACKUP_REQUIRED:
        marker = settings.BACKUP_ROOT/'.offsite-success'
        if not marker.exists() or now.timestamp()-marker.stat().st_mtime > 26*3600:
            failures.append('Encrypted offsite backup success marker is missing or stale.')
    return failures


class Command(BaseCommand):
    help = 'Check DB, scanner, account email backlog and recent backup evidence.'

    def add_arguments(self, parser):
        parser.add_argument('--alert', action='store_true')

    def handle(self, **options):
        try:
            failures = operation_failures()
        except Exception:
            failures = ['Operational checks could not reach the database or storage.']
        if failures:
            if options['alert'] and mail_ready() and settings.OPERATIONS_EMAIL:
                now = timezone.now()
                last = OperationalHeartbeat.objects.filter(name='last-alert').first()
                if not last or now-last.last_success > timedelta(hours=1):
                    try:
                        send_mail('MediFlow operational attention required', '\n'.join(failures), None,
                            [settings.OPERATIONS_EMAIL], fail_silently=False)
                        OperationalHeartbeat.objects.update_or_create(name='last-alert', defaults={'last_success': now})
                    except Exception:
                        self.stderr.write('Operational alert delivery failed.')
            raise CommandError('\n'.join(failures))
        self.stdout.write('Operational checks passed.')
