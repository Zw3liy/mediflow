import hashlib
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import ClinicalNote, ClinicalNoteVersion
@transaction.atomic
def sign_note(*, note_id, actor, body, reason=""):
note = (
ClinicalNote.objects.select_for_update()
.select_related("encounter")
.get(pk=note_id)
)
if note.encounter.practitioner_id != actor.id:
raise ValidationError(
"Only␣the␣responsible␣practitioner␣may␣sign.")
version = note.current_version + 1
item = ClinicalNoteVersion.objects.create(
note=note, version=version, body=body, reason=reason,
authored_by=actor, signed_at=timezone.now(),
content_sha256=hashlib.sha256(
body.encode("utf-8")).hexdigest())
note.current_version = version
note.save(update_fields=["current_version"])
return item
class Allergy(models.Model):
patient = models.ForeignKey(
"patients.Patient", on_delete=models.PROTECT,
related_name="allergies")
substance = models.CharField(max_length=160)
reaction = models.CharField(max_length=240, blank=True)
severity = models.CharField(max_length=20, blank=True)
active = models.BooleanField(default=True)
class Medication(models.Model):
patient = models.ForeignKey(
"patients.Patient", on_delete=models.PROTECT,
related_name="medications")
name = models.CharField(max_length=180)
dose = models.CharField(max_length=100, blank=True)
route = models.CharField(max_length=60, blank=True)
frequency = models.CharField(max_length=100, blank=True)
started_on = models.DateField(null=True, blank=True)
ended_on = models.DateField(null=True, blank=True)
class Result(models.Model):
encounter = models.ForeignKey(
Encounter, on_delete=models.PROTECT)
title = models.CharField(max_length=180)
summary = models.TextField(blank=True)
status = models.CharField(max_length=20, default="draft")
released_to_patient_at = models.DateTimeField(
null=True, blank=True)
released_by = models.ForeignKey(
settings.AUTH_USER_MODEL, null=True,
on_delete=models.PROTECT)
class ClinicalDocument(models.Model):
id = models.UUIDField(
primary_key=True, default=uuid.uuid4, editable=False)
practice = models.ForeignKey(
"tenancy.Practice", on_delete=models.PROTECT)
patient = models.ForeignKey(
"patients.Patient", on_delete=models.PROTECT)
category = models.CharField(max_length=40)
original_name = models.CharField(max_length=255)
object_key = models.CharField(max_length=500, unique=True)
content_type = models.CharField(max_length=100)
size_bytes = models.PositiveBigIntegerField()
sha256 = models.CharField(max_length=64)
scan_status = models.CharField(max_length=20, default="pending")
uploaded_by = models.ForeignKey(
settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
released_to_patient_at = models.DateTimeField(
null=True, blank=True)
class AuditEvent(models.Model):
practice_id = models.UUIDField(db_index=True)
actor_id = models.BigIntegerField(null=True)
action = models.CharField(max_length=80)
object_type = models.CharField(max_length=80)
object_id = models.CharField(max_length=80)
purpose = models.CharField(max_length=160)
occurred_at = models.DateTimeField(
auto_now_add=True, db_index=True)
outcome = models.CharField(max_length=20)
request_id = models.UUIDField()
previous_hash = models.CharField(max_length=64, blank=True)
event_hash = models.CharField(max_length=64)
