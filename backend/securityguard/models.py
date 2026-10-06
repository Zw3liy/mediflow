from django.db import models


class LoginAttemptBucket(models.Model):
    # HMAC digests avoid retaining usernames or client addresses in this table.
    key = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
