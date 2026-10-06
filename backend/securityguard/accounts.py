import secrets
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import AccountInvitation, EmailTask


def digest_token(value):
    return salted_hmac('mediflow.invitation', value, algorithm='sha256').hexdigest()


def mail_ready():
    return (settings.EMAIL_ENABLED and settings.PUBLIC_BASE_URL.startswith('https://')
            and settings.EMAIL_HOST and settings.EMAIL_HOST_USER
            and settings.EMAIL_HOST_PASSWORD and settings.DEFAULT_FROM_EMAIL)


@transaction.atomic
def queue_invitation(user, practice):
    from django.contrib.auth import get_user_model
    if (not mail_ready() or not user.email
            or get_user_model().objects.filter(email__iexact=user.email).exclude(pk=user.pk).exists()):
        raise ImproperlyConfigured('Configure HTTPS and SMTP before sending invitations.')
    now = timezone.now()
    AccountInvitation.objects.filter(user=user, accepted_at__isnull=True).update(expires_at=now)
    token = secrets.token_urlsafe(32)
    AccountInvitation.objects.create(user=user, practice=practice,
        token_digest=digest_token(token), expires_at=now + timedelta(hours=24))
    url = settings.PUBLIC_BASE_URL + '/app/invite/' + token + '/'
    EmailTask.objects.create(recipient=user.email, subject='Your MediFlow account invitation',
        body=f'Your practice has invited you to MediFlow.\nUsername: {user.username}\n'
             f'Set your password using this link within 24 hours:\n{url}\n'
             'If you did not expect this invitation, contact your practice.\n')
