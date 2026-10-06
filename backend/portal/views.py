from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
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
from scheduling.services import book, approve_booking, reject_booking, doctor_approve_booking, record_intake, complete_consultation
from tenancy.models import Membership, Practice
from .forms import BookingForm, PatientForm, PrescriptionForm, ServiceForm, IntakeForm, PatientAccountForm


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
        appointments = appointments.filter(practitioner=request.user).exclude(status="requested")
        patients = patients.filter(encounters__practitioner=request.user).distinct()
        prescriptions = prescriptions.filter(prescribed_by=request.user)
    elif role == "patient":
        appointments = appointments.filter(patient__portal_user=request.user)
        patients = patients.filter(portal_user=request.user)
        prescriptions = prescriptions.filter(encounter__patient__portal_user=request.user, status="issued")
    next_patient = appointments.filter(status__in=["held", "confirmed", "arrived"], starts_at__date__gte=timezone.localdate()).order_by("starts_at", "pk").first() if role == "doctor" else None
    context = dict(practice=practice, practices=practices, role=role, workspace=workspace,
        today=timezone.localdate(),
        can_review=Membership.objects.filter(user=request.user, practice=practice, active=True, role__in=["owner", "reception"]).exists(),
        title={"admin": "Practice overview", "doctor": "Clinical workspace", "reception": "Reception workspace", "patient": "Your care"}[workspace],
        appointments=appointments[:50], patient_count=patients.count(),
        next_patient=next_patient,
        next_patient_notified=Notification.objects.filter(appointment=next_patient, kind="doctor_ready").exists() if next_patient else False,
        unread_count=Notification.objects.filter(practice=practice, recipient=request.user, read_at__isnull=True, **({"appointment__patient__portal_user":request.user} if role == "patient" else {})).count(),
        appointment_count=appointments.filter(starts_at__date=timezone.localdate()).count(),
        pending_count=appointments.filter(status__in=["held", "confirmed", "arrived"], doctor_approved_at__isnull=True).count() if role == "doctor" else appointments.filter(status="requested").count(),
        prescriptions=prescriptions[:30] if role in ["doctor", "patient"] else [],
        prescription_count=prescriptions.count() if role in ["doctor", "patient"] else None,
        patients=patients.order_by("family_name")[:30] if role in ["owner", "reception"] else [],
        staff=Membership.objects.filter(practice=practice, active=True).select_related("user") if role == "owner" else [],
        services=Service.objects.filter(practice=practice),
        notices=Notification.objects.filter(practice=practice, recipient=request.user, **({"appointment__patient__portal_user":request.user} if role == "patient" else {})).order_by("-created_at")[:8],
        documents=PrescriptionDocument.objects.filter(practice=practice, prescription__encounter__patient__portal_user=request.user,
            scan_status="clean", released_to_patient_at__isnull=False) if role == "patient" else [],
    )
    response = render(request, "portal/dashboard.html", context)
    response["Cache-Control"] = "no-store, private"
    return response


@never_cache
@login_required
def form_view(request, kind):
    roles = {"patient": ["owner", "reception"], "service": ["owner"], "booking": ["owner", "reception", "doctor", "nurse", "patient"], "prescription": ["doctor"]}
    if kind not in roles:
        raise PermissionDenied()
    practice, role, practices = scope(request, roles[kind])
    if not practice:
        raise PermissionDenied("Practice membership required.")
    classes = {"patient": PatientForm, "service": ServiceForm, "booking": BookingForm, "prescription": PrescriptionForm}
    kwargs = {"practice": practice, "user": request.user}
    if kind == "booking":
        kwargs["role"] = role
    if kind == "patient":
        kwargs = {"practice": practice}
    elif kind == "service":
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
                    if role == "patient":
                        Practice.objects.select_for_update().get(pk=practice.pk)
                        if not Patient.objects.filter(pk=form.cleaned_data["patient"].pk, practice=practice,
                            portal_user=request.user, active=True).exists():
                            raise PermissionDenied("This patient record is no longer linked to your account.")
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
        elif operation in ["doctor-approve", "call"]:
            doctor_approve_booking(appointment_id=pk, practice=practice, actor=request.user, ready_now=operation == "call")
        elif operation == "complete":
            complete_consultation(appointment_id=pk, practice=practice, actor=request.user)
        elif operation == "encounter":
            with transaction.atomic():
                Practice.objects.select_for_update().get(pk=practice.pk)
                appointment = Appointment.objects.select_for_update().get(pk=pk, practice=practice)
                if appointment.practitioner_id != request.user.pk or appointment.status not in ["held", "confirmed", "arrived", "completed"] or appointment.doctor_approved_at is None:
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


@never_cache
def login_choices(request):
    if request.user.is_authenticated:
        return redirect("portal-home")
    return render(request, "portal/login_choices.html", {"title": "Choose your sign in"})


@never_cache
@login_required
def intake(request, pk):
    practice, role, practices = scope(request, ["owner", "reception", "nurse"])
    appointment = get_object_or_404(Appointment, pk=pk, practice=practice)
    form = IntakeForm(request.POST if request.method == "POST" else None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        try:
            record_intake(appointment_id=pk, practice=practice, actor=request.user, values=form.cleaned_data)
            messages.success(request, "Patient intake saved. The assigned doctor can review it.")
            return redirect(f"/app/{ROLE_PATHS[role]}/?practice={practice.pk}")
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, "portal/form.html", {"form":form, "practice":practice, "practices":practices,
        "role":role, "workspace":ROLE_PATHS[role], "kind":"intake", "title":f"Patient intake · {appointment.patient.given_name} {appointment.patient.family_name}"})


@never_cache
@login_required
def notification_feed(request):
    practice, role, practices = scope(request)
    if not practice:
        raise PermissionDenied()
    notices = Notification.objects.filter(practice=practice, recipient=request.user)
    if role == "patient":
        notices = notices.filter(appointment__patient__portal_user=request.user)
    next_visit = None
    if role == "doctor":
        visit = Appointment.objects.filter(practice=practice, practitioner=request.user,
            status__in=["held", "confirmed", "arrived"], starts_at__date__gte=timezone.localdate()).select_related("patient", "service").order_by("starts_at", "pk").first()
        if visit:
            next_visit = {"id":visit.pk, "patient":f"{visit.patient.given_name} {visit.patient.family_name}",
                "time":timezone.localtime(visit.starts_at).strftime("%d %b %Y, %H:%M SAST"),
                "service":visit.service.name, "symptoms":visit.reason_for_visit or "Not yet recorded",
                "bp":f"{visit.blood_pressure_systolic}/{visit.blood_pressure_diastolic} mmHg" if visit.blood_pressure_systolic else "Not yet measured",
                "approved":visit.doctor_approved_at is not None, "called":visit.called_at is not None,
                "can_call":visit.doctor_approved_at is not None and visit.called_at is None and timezone.localtime(visit.starts_at).date() == timezone.localdate()}
    return JsonResponse({"next_patient":next_visit, "unread":notices.filter(read_at__isnull=True).count(), "notifications":[
        {"id":n.pk, "title":n.title, "message":n.message, "read":n.read_at is not None,
         "time":timezone.localtime(n.created_at).strftime("%d %b, %H:%M SAST")}
        for n in notices.order_by("-created_at")[:20]]})


@never_cache
@login_required
@require_POST
def notification_read(request, pk):
    practice, role, practices = scope(request)
    query = Notification.objects.filter(practice=practice, recipient=request.user)
    if role == "patient":
        query = query.filter(appointment__patient__portal_user=request.user)
    notice = get_object_or_404(query, pk=pk)
    if notice.read_at is None:
        notice.read_at = timezone.now()
        notice.save(update_fields=["read_at"])
    return JsonResponse({"read":True})


@never_cache
@login_required
def patient_account(request, pk):
    practice, role, practices = scope(request, ["owner", "reception"])
    patient = get_object_or_404(Patient, pk=pk, practice=practice, active=True)
    form = PatientAccountForm(request.POST if request.method == "POST" else None, instance=patient, practice=practice)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            Practice.objects.select_for_update().get(pk=practice.pk)
            patient = Patient.objects.select_for_update().get(pk=patient.pk, practice=practice)
            patient.portal_user = form.cleaned_data["portal_user"]
            patient.save(update_fields=["portal_user", "updated_at"])
            from notifications.services import notify_doctor_ready
            for visit in Appointment.objects.filter(patient=patient, practice=practice, doctor_approved_at__isnull=False,
                status__in=["held", "confirmed", "arrived"], starts_at__gte=timezone.now()).select_related("patient", "practitioner", "practice"):
                notify_doctor_ready(appointment=visit)
                if visit.called_at and timezone.localtime(visit.called_at).date() == timezone.localdate():
                    notify_doctor_ready(appointment=visit, ready_now=True)
            record_audit_event(practice=practice, actor=request.user, action="patient.app_account_linked",
                object_type="patient", object_id=patient.pk, purpose="Link patient's own app account", outcome="success")
        messages.success(request, "Patient app account updated. Check that this account belongs to this patient.")
        return redirect(f"/app/{ROLE_PATHS[role]}/?practice={practice.pk}#patients")
    return render(request, "portal/form.html", {"form":form, "practice":practice, "practices":practices,
        "role":role, "workspace":ROLE_PATHS[role], "kind":"account", "title":f"App account · {patient.given_name} {patient.family_name}"})
