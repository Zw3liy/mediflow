import logging
from datetime import timedelta


class OperationalErrorHandler(logging.Handler):
    """Queue a generic alert. Never include request paths, payloads or traceback data."""
    def emit(self, record):
        try:
            from django.conf import settings
            from django.utils import timezone
            from .accounts import mail_ready
            from .models import EmailTask
            subject = 'MediFlow application error requires attention'
            if mail_ready() and settings.OPERATIONS_EMAIL and not EmailTask.objects.filter(
                    subject=subject, created_at__gt=timezone.now()-timedelta(minutes=15)).exists():
                EmailTask.objects.create(recipient=settings.OPERATIONS_EMAIL, subject=subject,
                    body='MediFlow recorded a server error. Review the protected server logs. No patient data is included in this alert.')
        except Exception:
            # DB outage must not recursively fail the request or logging stack.
            pass


class SecretPathFilter(logging.Filter):
    def filter(self, record):
        import re
        message = record.getMessage()
        message = re.sub(r"/app/invite/[^\s/]+/", "/app/invite/[redacted]/", message)
        message = re.sub(r"/app/password/reset/[^\s/]+/[^\s/]+/", "/app/password/reset/[redacted]/", message)
        record.msg, record.args = message, ()
        return True
