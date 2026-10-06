from django.conf import settings
from django.db import models


class MobileSession(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    practice = models.ForeignKey("tenancy.Practice", on_delete=models.PROTECT)
    workspace = models.CharField(max_length=16)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PushDevice(models.Model):
    session = models.ForeignKey(MobileSession, on_delete=models.CASCADE, related_name="devices")
    token = models.CharField(max_length=250, unique=True)
    platform = models.CharField(max_length=16)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class PushDelivery(models.Model):
    notification = models.ForeignKey("notifications.Notification", on_delete=models.CASCADE)
    device = models.ForeignKey(PushDevice, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    ticket_id = models.CharField(max_length=160, blank=True)
    last_error = models.CharField(max_length=160, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["notification", "device"], name="unique_mobile_push_delivery")]
