from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from clinical.models import HealthEntry
from patients.models import Patient
from auditlog.services import record_audit_event
from .views import MobileBase

FIELDS = {
    "vitals": {"systolic": (40, 300), "diastolic": (20, 200), "heart_rate": (20, 250), "temperature": (25, 45), "oxygen": (1, 100), "weight": (1, 500)},
    "wellness": {"walk_minutes": (0, 1440), "exercise_minutes": (0, 1440), "meditation_minutes": (0, 1440), "sleep_hours": (0, 24)},
}
class EntryInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["vitals", "wellness", "report"])
    recorded_at = serializers.DateTimeField(default=timezone.now)
    data = serializers.JSONField()
    def validate(self, value):
        data = value["data"]
        if not isinstance(data, dict): raise serializers.ValidationError("Enter valid fields.")
        allowed = set(FIELDS.get(value["kind"], {})) | ({"nutrition", "notes"} if value["kind"] == "wellness" else {"notes"})
        if value["kind"] == "report": allowed = {"category", "title", "summary"}
        if set(data) - allowed: raise serializers.ValidationError("Unknown fields.")
        clean = {}
        for key, item in data.items():
            if item in (None, ""): continue
            if key in FIELDS.get(value["kind"], {}):
                try: number = float(item)
                except (ValueError, TypeError): raise serializers.ValidationError(f"Invalid {key}.")
                low, high = FIELDS[value["kind"]][key]
                if isinstance(item, bool) or not low <= number <= high: raise serializers.ValidationError(f"{key} must be between {low} and {high}.")
                clean[key] = number
            else:
                if not isinstance(item, str) or len(item) > 2000: raise serializers.ValidationError("Text must be at most 2000 characters.")
                clean[key] = item.strip()
        if not clean: raise serializers.ValidationError("Enter at least one result.")
        if value["kind"] == "vitals":
            if ("systolic" in clean) != ("diastolic" in clean): raise serializers.ValidationError("Enter both blood pressure values.")
            if "systolic" in clean and clean["systolic"] <= clean["diastolic"]: raise serializers.ValidationError("Systolic must exceed diastolic.")
        if value["kind"] == "report" and not clean.get("title"): raise serializers.ValidationError("Enter a report title.")
        if value["recorded_at"] > timezone.now(): raise serializers.ValidationError("Measurement time cannot be in the future.")
        value["data"] = clean
        return value

def patients(request):
    if request.auth.current_role not in ["owner", "doctor", "reception", "patient"]: raise PermissionDenied("Health access is not available to your role.")
    result = Patient.objects.filter(practice=request.auth.practice, active=True)
    if request.auth.current_role == "patient": result = result.filter(portal_user=request.user)
    return result.order_by("family_name", "given_name")

def entry_data(entry):
    return {"id":entry.pk,"kind":entry.kind,"data":entry.data,"recorded_at":entry.recorded_at.isoformat(),"reviewed":bool(entry.reviewed_by_id),"source":"Staff entry" if entry.kind != "wellness" else "Daily log"}

class HealthPatients(MobileBase):
    def get(self, request):
        return Response([{"id":str(p.pk),"name":f"{p.given_name} {p.family_name}","file_number":p.file_number} for p in patients(request)])

class HealthEntries(MobileBase):
    def get(self, request, patient_id):
        patient = get_object_or_404(patients(request), pk=patient_id)
        entries = list(patient.health_entries.select_related("reviewed_by").all()[:200])
        vitals = [e for e in entries if e.kind == "vitals"]
        trends = {}
        for field in FIELDS["vitals"]:
            values = [e.data[field] for e in vitals if field in e.data]
            if values: trends[field] = {"latest":values[0],"change":round(values[0]-values[1],2) if len(values)>1 else None}
        today = timezone.localdate()
        logged = any(e.kind == "wellness" and timezone.localtime(e.recorded_at).date() == today for e in entries)
        return Response({"entries":[entry_data(e) for e in entries],"trends":trends,"reminders":([] if logged else ["Complete today's wellness log."])+([] if vitals else ["No staff measurements recorded yet."]),"summary":"Trends compare the two most recent recorded values. They do not establish a diagnosis."})
    @transaction.atomic
    def post(self, request, patient_id):
        patient = get_object_or_404(patients(request), pk=patient_id)
        serializer = EntryInput(data=request.data); serializer.is_valid(raise_exception=True)
        if request.auth.current_role == "patient" and serializer.validated_data["kind"] != "wellness": raise PermissionDenied("Clinical results are entered by your care team.")
        entry = HealthEntry.objects.create(patient=patient, recorded_by=request.user, **serializer.validated_data)
        record_audit_event(actor=request.user, practice=request.auth.practice, action="health.entry.created", object_type="HealthEntry", object_id=str(entry.pk), purpose="Patient health record", outcome="success")
        return Response(entry_data(entry), status=201)

class HealthEntryEdit(MobileBase):
    @transaction.atomic
    def patch(self, request, patient_id, pk):
        patient = get_object_or_404(patients(request), pk=patient_id)
        entry = get_object_or_404(HealthEntry.objects.select_for_update(), patient=patient, pk=pk)
        if request.auth.current_role == "patient" and (entry.kind != "wellness" or entry.recorded_by_id != request.user.pk): raise PermissionDenied("Only your daily logs can be edited.")
        if request.data.get("review") is True:
            self.roles(request, ["owner", "doctor"])
            entry.reviewed_by = request.user
        else:
            serializer = EntryInput(data={"kind":entry.kind,"recorded_at":request.data.get("recorded_at",entry.recorded_at),"data":request.data.get("data",entry.data)})
            serializer.is_valid(raise_exception=True)
            entry.data = serializer.validated_data["data"]; entry.recorded_at = serializer.validated_data["recorded_at"]; entry.reviewed_by = None
        entry.save()
        record_audit_event(actor=request.user, practice=request.auth.practice, action="health.entry.updated", object_type="HealthEntry", object_id=str(entry.pk), purpose="Patient health record", outcome="success")
        return Response(entry_data(entry))
