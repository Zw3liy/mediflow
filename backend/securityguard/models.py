from django.db import models


class LoginAttemptBucket(models.Model):
    # HMAC digests avoid retaining usernames or client addresses in this table.
    key = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)


class AccountInvitation(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    practice = models.ForeignKey('tenancy.Practice', on_delete=models.PROTECT)
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RecoveryCode(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    digest = models.CharField(max_length=64)


class EmailTask(models.Model):
    recipient = models.EmailField()
    subject = models.CharField(max_length=180)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)


class OperationalHeartbeat(models.Model):
    name = models.CharField(max_length=40, unique=True)
    last_success = models.DateTimeField()
