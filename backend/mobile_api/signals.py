from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from notifications.models import Notification
from tenancy.models import Membership
from .models import PushDelivery, PushDevice


@receiver(post_save, sender=Notification)
def enqueue_notification_push(sender, instance, created, **kwargs):
    if not created:
        return
    devices = PushDevice.objects.filter(active=True, session__user=instance.recipient,
        session__practice=instance.practice, session__revoked_at__isnull=True,
        session__expires_at__gt=timezone.now(), session__user__is_active=True)
    for device in devices:
        membership = Membership.objects.filter(practice=instance.practice, user=instance.recipient, active=True,
            role__in=["doctor", "patient"]).first()
        if membership is None:
            continue
        if membership.role == "patient" and instance.appointment.patient.portal_user_id != instance.recipient_id:
            continue
        PushDelivery.objects.get_or_create(notification=instance, device=device)
