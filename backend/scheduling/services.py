from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Appointment
@transaction.atomic
def book(*, practice, patient, practitioner, service, starts_at):
if patient.practice_id != practice.id:
raise ValidationError("Cross-practice␣booking␣denied.")
if service.practice_id != practice.id:
raise ValidationError("Cross-practice␣booking␣denied.")
if starts_at <= timezone.now():
raise ValidationError("Choose␣a␣future␣time.")
ends_at = starts_at + timedelta(
minutes=service.duration_minutes)
clash = (
Appointment.objects.select_for_update()
.filter(
practice=practice,
practitioner=practitioner,
status__in=["held", "confirmed", "arrived"],
starts_at__lt=ends_at,
ends_at__gt=starts_at)
.exists()
)
if clash:
raise ValidationError("That␣time␣is␣no␣longer␣available.")
return Appointment.objects.create(
practice=practice, patient=patient,
practitioner=practitioner, service=service,
starts_at=starts_at, ends_at=ends_at,
hold_expires_at=timezone.now() + timedelta(minutes=10))
