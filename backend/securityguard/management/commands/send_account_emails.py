from datetime import timedelta
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from securityguard.accounts import mail_ready
from securityguard.models import EmailTask


class Command(BaseCommand):
    help = 'Deliver queued account emails; erase sent or expired message bodies.'

    def handle(self, **options):
        now = timezone.now()
        EmailTask.objects.filter(created_at__lt=now-timedelta(hours=24)).delete()
        if not mail_ready():
            self.stdout.write('Account email delivery is not configured.')
            return
        sent = 0
        for pk in EmailTask.objects.filter(sent_at__isnull=True, attempts__lt=5).values_list('pk', flat=True)[:50]:
            with transaction.atomic():
                task = EmailTask.objects.select_for_update().get(pk=pk)
                if task.sent_at or task.attempts >= 5:
                    continue
                task.attempts += 1
                try:
                    send_mail(task.subject, task.body, None, [task.recipient], fail_silently=False)
                except Exception:
                    # Never log SMTP credentials, invitation URLs or recipients.
                    self.stderr.write('Account email delivery failed; check SMTP configuration.')
                else:
                    task.sent_at = timezone.now()
                    task.body = ''
                    sent += 1
                task.save(update_fields=['attempts', 'sent_at', 'body'])
        from securityguard.models import OperationalHeartbeat
        OperationalHeartbeat.objects.update_or_create(name="account-email", defaults={"last_success": timezone.now()})
        self.stdout.write(f'Delivered {sent} account email(s).')
