from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from auditlog.services import record_audit_event
from clinical.models import Encounter, Prescription
from clinical.services import create_prescription, issue_prescription
from documents.models import PrescriptionDocument
from notifications.models import Notification
from patients.models import Patient
from scheduling.models import Appointment, Service
from scheduling.services import book, approve_booking, reject_booking
from tenancy.models import Membership, Practice
from .forms import BookingForm, PatientForm, PrescriptionForm, ServiceForm


ROLE_PATHS = {"owner": "admin", "doctor": "doctor", "nurse": "doctor", "reception": "reception", "patient": "patient"}


def scope(request, roles=None):
    memberships = Membership.objects.filter(user=request.user, active=True, practice__active=True).select_related("practice")
    practices = Practice.objects.filter(active=True).order_by("name") if request.user.is_superuser else Practice.objects.filter(
        membership__in=memberships).distinct().order_by("name")
    selected = request.POST.get("practice") or request.GET.get("practice") or request.session.get("portal_practice")
    if selected:
        try:
            selected = UUID(str(selected))
        except (ValueError, TypeError):
            raise PermissionDenied("Invalid practice.")
        practice = get_object_or_404(practices, pk=selected)
    else:
        practice = practices.first()
    if practice is None:
        return None, None, practices
    membership = memberships.filter(practice=practice).first()
    role = "owner" if request.user.is_superuser else membership.role
    if roles and role not in roles:
        raise PermissionDenied("This workspace is not available to your role.")
    request.session["portal_practice"] = str(practice.pk)
    return practice, role, practices


@never_cache
@login_required
def home(request):
    practice, role, practices = scope(request)
    if not practice:
        return render(request, "portal/no_access.html")
    return redirect(f"/app/{ROLE_PATHS[role]}/?practice={practice.pk}")


@never_cache
@login_required
def dashboard(request, workspace):
    allowed = {"admin": ["owner"], "doctor": ["doctor", "nurse"], "reception": ["reception"], "patient": ["patient"]}
    if workspace not in allowed:
        raise PermissionDenied()
    practice, role, practices = scope(request, allowed[workspace])
    if not practice:
        return render(request, "portal/no_access.html")
    appointments = Appointment.objects.filter(practice=practice).select_related("patient", "practitioner", "service").order_by("starts_at")
    patients = Patient.objects.filter(practice=practice, active=True)
    prescriptions = Prescription.objects.filter(encounter__practice=practice).select_related("encounter__patient").prefetch_related("items")
    if role in ["doctor", "nurse"]:
        appointments = appointments.filter(practitioner=request.user)
        patients = patients.filter(encounters__practitioner=request.user).distinct()
        prescriptions = prescriptions.filter(prescribed_by=request.user)
    elif role == "patient":
        appointments = appointments.filter(patient__portal_user=request.user)
        patients = patients.filter(portal_user=request.user)
        prescriptions = prescriptions.filter(encounter__patient__portal_user=request.user, status="issued")
    context = dict(practice=practice, practices=practices, role=role, workspace=workspace,
        can_review=Membership.objects.filter(user=request.user, practice=practice, active=True, role__in=["owner", "reception"]).exists(),
        title={"admin": "Practice overview", "doctor": "Clinical workspace", "reception": "Reception workspace", "patient": "Your care"}[workspace],
        appointments=appointments[:50], patient_count=patients.count(),
        appointment_count=appointments.filter(starts_at__date=timezone.localdate()).count(),
        pending_count=appointments.filter(status="requested").count(),
        prescriptions=prescriptions[:30] if role in ["doctor", "patient"] else [],
        prescription_count=prescriptions.count() if role in ["doctor", "patient"] else None,
        patients=patients.order_by("family_name")[:30] if role in ["owner", "reception"] else [],
        staff=Membership.objects.filter(practice=practice, active=True).select_related("user") if role == "owner" else [],
        services=Service.objects.filter(practice=practice),
        notices=Notification.objects.filter(practice=practice, recipient=request.user).order_by("-created_at")[:8],
        documents=PrescriptionDocument.objects.filter(practice=practice, prescription__encounter__patient__portal_user=request.user,
            scan_status="clean", released_to_patient_at__isnull=False) if role == "patient" else [],
    )
    response = render(request, "portal/dashboard.html", context)
    response["Cache-Control"] = "no-store, private"
    return response


@never_cache
@login_required
def form_view(request, kind):
    roles = {"patient": ["owner", "reception"], "service": ["owner"], "booking": ["owner", "reception", "doctor", "nurse"], "prescription": ["doctor"]}
    if kind not in roles:
        raise PermissionDenied()
    practice, role, practices = scope(request, roles[kind])
    if not practice:
        raise PermissionDenied("Practice membership required.")
    classes = {"patient": PatientForm, "service": ServiceForm, "booking": BookingForm, "prescription": PrescriptionForm}
    kwargs = {"practice": practice, "user": request.user}
    if kind == "booking":
        kwargs["role"] = role
    if kind not in ["booking", "prescription"]:
        kwargs = {}
    form = classes[kind](request.POST if request.method == "POST" else None, **kwargs)
    if kind in ["patient", "service"]:
        form.instance.practice = practice
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if kind in ["patient", "service"]:
                    obj = form.save()
                    record_audit_event(practice=practice, actor=request.user, action=f"{kind}.created", object_type=kind,
                        object_id=obj.pk, purpose=f"Create {kind}", outcome="success")
                elif kind == "booking":
                    book(practice=practice, **form.cleaned_data)
                else:
                    values = form.cleaned_data.copy()
                    encounter = values.pop("encounter")
                    instructions = values.pop("instructions")
                    create_prescription(encounter_id=encounter.pk, actor=request.user, items=[values], general_instructions=instructions)
            messages.success(request, "Saved successfully.")
            return redirect(f"/app/{ROLE_PATHS[role]}/?practice={practice.pk}")
        except IntegrityError:
            form.add_error(None, "A record with these details already exists. Check the patient file number.")
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, "portal/form.html", dict(form=form, kind=kind, practice=practice, role=role, practices=practices,
        workspace=ROLE_PATHS[role], title={"patient": "Add patient", "service": "Add consultation service", "booking": "Request appointment", "prescription": "Create prescription draft"}[kind]))


@never_cache
@login_required
@require_POST
def appointment_action(request, pk, operation):
    roles = ["owner", "reception"] if operation in ["approve", "reject"] else ["doctor"]
    practice, role, practices = scope(request, roles)
    appointment = get_object_or_404(Appointment, practice=practice, pk=pk)
    try:
        if operation == "approve":
            approve_booking(appointment_id=pk, practice=practice, actor=request.user)
        elif operation == "reject":
            reject_booking(appointment_id=pk, practice=practice, actor=request.user, reason=request.POST.get("reason", ""))
        elif operation == "encounter":
            with transaction.atomic():
                Practice.objects.select_for_update().get(pk=practice.pk)
                appointment = Appointment.objects.select_for_update().get(pk=pk, practice=practice)
                if appointment.practitioner_id != request.user.pk or appointment.status not in ["held", "confirmed", "arrived", "completed"]:
                    raise PermissionDenied("Only your approved appointments can start a consultation.")
                encounter, created = Encounter.objects.get_or_create(appointment=appointment, defaults=dict(
                    practice=practice, patient=appointment.patient, practitioner=request.user, started_at=timezone.now()))
                if created:
                    record_audit_event(practice=practice, actor=request.user, action="encounter.started", object_type="encounter",
                        object_id=encounter.pk, purpose="Start consultation", outcome="success")
        else:
            raise PermissionDenied()
        messages.success(request, "Appointment updated." if operation != "encounter" else "Consultation opened. You can now create a prescription draft.")
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    return redirect(f"/app/{ROLE_PATHS[role]}/?practice={practice.pk}")


@never_cache
@login_required
@require_POST
def issue(request, pk):
    practice, role, practices = scope(request, ["doctor"])
    prescription = get_object_or_404(Prescription, pk=pk, encounter__practice=practice, prescribed_by=request.user)
    if request.POST.get("reviewed") != "yes":
        messages.error(request, "Confirm that you reviewed this prescription before issuing it.")
        return redirect(f"/app/doctor/?practice={practice.pk}")
    try:
        issue_prescription(prescription_id=prescription.pk, actor=request.user)
        messages.success(request, "Prescription issued.")
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    return redirect(f"/app/doctor/?practice={practice.pk}")


@never_cache
@login_required
def document_download(request, pk):
    from django.http import HttpResponse
    from django.utils.http import content_disposition_header
    from documents.storage import get_document_storage, DocumentStorageError
    practice, role, practices = scope(request, ["patient"])
    document = get_object_or_404(PrescriptionDocument, pk=pk, practice=practice,
        prescription__encounter__patient__portal_user=request.user,
        scan_status="clean", released_to_patient_at__isnull=False)
    try:
        content = get_document_storage().read(object_key=document.object_key)
    except DocumentStorageError:
        return HttpResponse("Document storage is temporarily unavailable.", status=503)
    record_audit_event(practice=practice, actor=request.user, action="document.downloaded", object_type="prescription_document",
        object_id=document.pk, purpose="Download released prescription document", outcome="success")
    response = HttpResponse(content, content_type=document.content_type)
    response["Content-Disposition"] = content_disposition_header(True, document.original_name)
    response["Cache-Control"] = "no-store, private"
    return response
