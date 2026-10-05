from django.conf import settings
from django.db import models

from .exceptions import AuditChainError


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditChainError(
            "Audit events are append-only."
        )

    def delete(self):
        raise AuditChainError(
            "Audit events are append-only."
        )


class AuditEvent(models.Model):
    practice = models.ForeignKey(
        "tenancy.Practice",
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    action = models.CharField(
        max_length=120,
    )
    object_type = models.CharField(
        max_length=120,
    )
    object_id = models.CharField(
        max_length=160,
    )
    purpose = models.CharField(
        max_length=240,
    )
    outcome = models.CharField(
        max_length=40,
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
    )
    occurred_at = models.DateTimeField()
    previous_hash = models.CharField(
        max_length=64,
        blank=True,
    )
    event_hash = models.CharField(
        max_length=64,
        unique=True,
    )

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = [
            "id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "practice",
                    "id",
                ],
                name="audit_practice_event_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditChainError(
                "Audit events are append-only."
            )

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditChainError(
            "Audit events are append-only."
        )
