import json
from datetime import timedelta
from urllib.request import Request, urlopen
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from tenancy.models import Membership
from .models import PushDelivery
from .authentication import WORKSPACES, session_security_valid


def dispatch_pushes(limit=50):
    """Opt-in outbox worker. Provider acceptance is not a device-delivery guarantee."""
    if not settings.MOBILE_PUSH_ENABLED or not settings.EXPO_ACCESS_TOKEN:
        return 0
    processed=0
    for _ in range(limit):
        with transaction.atomic():
            delivery=PushDelivery.objects.select_for_update().filter(status__in=["pending","retry"],attempts__lt=5).filter(
                Q(next_attempt_at__isnull=True) |
                Q(next_attempt_at__lte=timezone.now())).order_by("pk").first()
            if delivery is None:break
            device=delivery.device
            session=device.session
            notice=delivery.notification
            membership=Membership.objects.filter(user=session.user,practice=session.practice,active=True,
                role__in=WORKSPACES.get(session.workspace, [])).first()
            valid=session_security_valid(session) and device.active and session.user.is_active and session.practice.active and not session.revoked_at and session.expires_at>timezone.now() and membership is not None and notice.recipient_id==session.user_id and notice.practice_id==session.practice_id
            if valid and membership.role=="patient": valid=notice.appointment.patient.portal_user_id==session.user_id
            if not valid:
                delivery.status="cancelled";delivery.save(update_fields=["status"]);continue
            # Keep the DB lock through this short bounded provider request to prevent competing workers claiming the same delivery.
            delivery.attempts+=1
            payload={"to":device.token,"title":"MediFlow update","body":"Open MediFlow to view your personal appointment update.",
                "sound":"default","channelId":"appointments","data":{"notification_id":notice.pk}}
            request=Request("https://exp.host/--/api/v2/push/send",data=json.dumps(payload).encode(),method="POST",
                headers={"Content-Type":"application/json","Authorization":f"Bearer {settings.EXPO_ACCESS_TOKEN}"})
            try:
                with urlopen(request,timeout=10) as response:
                    result=json.loads(response.read(65536))
                ticket=result.get("data",{})
                if isinstance(ticket,list):ticket=ticket[0] if ticket else {}
                if ticket.get("status")=="ok":
                    delivery.status="sent";delivery.ticket_id=ticket.get("id","");delivery.last_error=""
                else:
                    code=ticket.get("details",{}).get("error","ProviderRejected")
                    delivery.last_error=str(code)[:160]
                    if code=="DeviceNotRegistered":device.active=False;device.save(update_fields=["active"])
                    delivery.status="failed" if code=="DeviceNotRegistered" or delivery.attempts>=5 else "retry"
            except Exception:
                delivery.last_error="Push provider unavailable"
                delivery.status="failed" if delivery.attempts>=5 else "retry"
            delivery.next_attempt_at=timezone.now()+timedelta(seconds=30*2**delivery.attempts)
            delivery.save(update_fields=["attempts","status","ticket_id","last_error","next_attempt_at"])
            processed+=1
    return processed
