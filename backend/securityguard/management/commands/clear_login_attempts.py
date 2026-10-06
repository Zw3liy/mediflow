from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from securityguard.models import LoginAttemptBucket, AccountInvitation


class Command(BaseCommand):
    help = "Remove expired login-attempt buckets; run daily alongside clearsessions."

    def handle(self, *args, **options):
        count, _ = LoginAttemptBucket.objects.filter(
            started_at__lt=timezone.now() - timedelta(seconds=settings.LOGIN_ATTEMPT_WINDOW)
        ).delete()
        AccountInvitation.objects.filter(expires_at__lt=timezone.now()-timedelta(days=2)).delete()
        self.stdout.write(f"Removed {count} expired login-attempt buckets.")
