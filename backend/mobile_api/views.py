import hashlib
import re
import secrets
from uuid import UUID
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.throttling import ScopedRateThrottle
from auditlog.services import record_audit_event
from clinical.models import Encounter, Prescription
from clinical.serializers import PrescriptionSerializer
from clinical.services import create_prescription, issue_prescription
from portal.forms import PrescriptionForm
from notifications.models import Notification
from notifications.serializers import NotificationSerializer
from patients.models import Patient
from scheduling.models import Appointment, Service
from scheduling.services import book, approve_booking, reject_booking, doctor_approve_booking, record_intake, complete_consultation
from tenancy.models import Practice, Membership
from portal.forms import IntakeForm, PatientForm
from .authentication import MobileTokenAuthentication, WORKSPACES
from .models import MobileSession, PushDevice

SAST = ZoneInfo("Africa/Johannesburg")


def session_info(session, role):
    return {"user":session.user.get_full_name() or session.user.username, "role":role,
        "workspace":session.workspace, "practice":{"id":str(session.practice_id),"name":session.practice.name},
        "expires_at":session.expires_at.isoformat()}


def appointment_info(visit):
    return {"id":visit.pk,"patient":f"{visit.patient.given_name} {visit.patient.family_name}",
        "file_number":visit.patient.file_number,"doctor":visit.practitioner.get_full_name() or visit.practitioner.username,
        "service":visit.service.name,"time":timezone.localtime(visit.starts_at,SAST).strftime("%d %b %Y, %H:%M SAST"),
        "starts_at":visit.starts_at.isoformat(),"status":visit.status,"symptoms":visit.reason_for_visit,
        "bp":f"{visit.blood_pressure_systolic}/{visit.blood_pressure_diastolic} mmHg" if visit.blood_pressure_systolic else "Not yet measured",
        "doctor_approved":visit.doctor_approved_at is not None,"called":visit.called_at is not None,
        "can_call":visit.doctor_approved_at is not None and visit.called_at is None and timezone.localtime(visit.starts_at,SAST).date()==timezone.localdate(timezone=SAST),
        "blood_pressure_systolic":visit.blood_pressure_systolic, "blood_pressure_diastolic":visit.blood_pressure_diastolic,
        "has_consultation":Encounter.objects.filter(appointment=visit).exists(),"patient_app_linked":visit.patient.portal_user_id is not None}


class MobileBase(APIView):
    authentication_classes = [MobileTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request,response,*args,**kwargs)
        response["Cache-Control"]="no-store, private"
        return response

    def roles(self, request, allowed):
        if request.auth.current_role not in allowed:
            raise PermissionDenied("This action is not available to your role.")

    def visits(self, request):
        visits=Appointment.objects.filter(practice=request.auth.practice).select_related("patient","practitioner","service")
        if request.auth.current_role=="patient":
            visits=visits.filter(patient__portal_user=request.user)
        elif request.auth.current_role=="doctor":
            visits=visits.filter(practitioner=request.user).exclude(status="requested")
        return visits

    def notices(self, request):
        notices=Notification.objects.filter(practice=request.auth.practice,recipient=request.user)
        if request.auth.current_role=="patient":
            notices=notices.filter(appointment__patient__portal_user=request.user)
        return notices


class MobileLogin(MobileBase):
    authentication_classes=[]
    permission_classes=[AllowAny]
    throttle_classes=[ScopedRateThrottle]
    throttle_scope="mobile_login"

    def get_authenticate_header(self, request):
        return "Bearer"

    def post(self, request):
        workspace=request.data.get("workspace")
        username=request.data.get("username", "")
        password=request.data.get("password", "")
        if not isinstance(workspace,str) or workspace not in WORKSPACES or not isinstance(username,str) or not isinstance(password,str) or len(username)>150 or not password or len(password)>1024:
            raise ValidationError("Choose your sign-in area and enter your username and password.")
        user=authenticate(request,username=username,password=password)
        if user is None or not user.is_active:
            raise AuthenticationFailed("Unable to sign in. Check your account and sign-in area.")
        memberships=Membership.objects.filter(user=user,active=True,practice__active=True,
            role__in=WORKSPACES[workspace]).select_related("practice").order_by("practice__name")
        practice_id=request.data.get("practice")
        if practice_id:
            try:practice_id=UUID(str(practice_id))
            except (ValueError,TypeError):raise ValidationError("Choose a valid practice.")
        if user.is_superuser and workspace=="reception":
            practices=Practice.objects.filter(active=True).order_by("name")
            practice=get_object_or_404(practices,pk=practice_id) if practice_id else practices.first()
            role="owner"
        else:
            if user.is_superuser or not memberships.exists():
                raise AuthenticationFailed("Unable to sign in. Check your account and sign-in area.")
            member=get_object_or_404(memberships,practice_id=practice_id) if practice_id else memberships.first()
            practice,role=member.practice,member.role
        if practice is None:
            raise AuthenticationFailed("An active practice membership is required.")
        token=secrets.token_urlsafe(48)
        session=MobileSession.objects.create(user=user,practice=practice,workspace=workspace,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=timezone.now()+timedelta(days=7))
        record_audit_event(practice=practice,actor=user,action="mobile.signed_in",object_type="mobile_session",
            object_id=session.pk,purpose="Sign in to mobile workspace",outcome="success")
        return Response({"token":token,"session":session_info(session,role)})


class MobileLogout(MobileBase):
    def post(self, request):
        request.auth.revoked_at=timezone.now()
        request.auth.save(update_fields=["revoked_at"])
        request.auth.devices.update(active=False)
        return Response({"signed_out":True})


class MobileDashboard(MobileBase):
    def get(self, request):
        visits=self.visits(request)
        role=request.auth.current_role
        notices=self.notices(request)
        next_visit=visits.filter(status__in=["held","confirmed","arrived"],starts_at__gte=timezone.now().astimezone(SAST).replace(hour=0,minute=0,second=0,microsecond=0)).order_by("starts_at","pk").first() if role=="doctor" else None
        prescriptions=Prescription.objects.filter(encounter__practice=request.auth.practice).select_related("encounter__patient").prefetch_related("items")
        if role=="doctor": prescriptions=prescriptions.filter(prescribed_by=request.user)
        elif role=="patient": prescriptions=prescriptions.filter(encounter__patient__portal_user=request.user,status="issued")
        else: prescriptions=prescriptions.none()
        today=timezone.now().astimezone(SAST).replace(hour=0,minute=0,second=0,microsecond=0)
        # Upcoming bookings precede a separate, short recent history.
        upcoming=list(visits.filter(starts_at__gte=timezone.now()).order_by("starts_at","pk")[:75])
        recent=list(visits.filter(starts_at__lt=timezone.now()).order_by("-starts_at","-pk")[:25])
        return Response({"session":session_info(request.auth,role),"appointments":[appointment_info(v) for v in upcoming+recent],
            "next_patient":appointment_info(next_visit) if next_visit else None,
            "today_count":visits.filter(starts_at__gte=today,starts_at__lt=today+timedelta(days=1)).count(),
            "unread":notices.filter(read_at__isnull=True).count(),"notifications":NotificationSerializer(notices.order_by("-created_at")[:30],many=True).data,
            "encounters":[{"id":str(e.pk),"name":f"{e.patient.given_name} {e.patient.family_name}"} for e in Encounter.objects.filter(practice=request.auth.practice,practitioner=request.user).select_related("patient").order_by("-started_at")[:100]] if role=="doctor" else [],
            "prescriptions":[{**dict(PrescriptionSerializer(rx).data),"patient":f"{rx.encounter.patient.given_name} {rx.encounter.patient.family_name}"} for rx in prescriptions.order_by("-created_at")[:30]]})


class MobileBookingOptions(MobileBase):
    def get(self, request):
        practice=request.auth.practice
        patients=Patient.objects.filter(practice=practice,active=True)
        if request.auth.current_role=="patient":patients=patients.filter(portal_user=request.user)
        doctors=get_user_model().objects.filter(is_active=True,membership__practice=practice,membership__active=True,membership__role="doctor").distinct()
        if request.auth.current_role=="doctor":doctors=doctors.filter(pk=request.user.pk)
        return Response({"patients":[{"id":str(p.pk),"name":f"{p.given_name} {p.family_name}","file_number":p.file_number} for p in patients.order_by("family_name")[:500]],
            "doctors":[{"id":u.pk,"name":u.get_full_name() or u.username} for u in doctors],
            "services":[{"id":s.pk,"name":s.name,"duration":s.duration_minutes} for s in Service.objects.filter(practice=practice)]})


class MobileBooking(MobileBase):
    def post(self, request):
        from portal.forms import BookingForm
        form=BookingForm(request.data,practice=request.auth.practice,user=request.user,role=request.auth.current_role)
        with timezone.override(SAST):
            valid=form.is_valid()
        if not valid:raise ValidationError(form.errors.get_json_data())
        try:
            with transaction.atomic():
                Practice.objects.select_for_update().get(pk=request.auth.practice_id)
                if request.auth.current_role=="patient" and not Patient.objects.filter(pk=form.cleaned_data["patient"].pk,
                    practice=request.auth.practice,portal_user=request.user,active=True).exists():
                    raise PermissionDenied("This patient record is not linked to your account.")
                visit=book(practice=request.auth.practice,**form.cleaned_data)
        except DjangoValidationError as error:raise ValidationError(error.messages) from error
        return Response({"id":visit.pk,"status":visit.status},status=201)


class MobileAppointmentAction(MobileBase):
    def post(self, request, pk, operation):
        practice=request.auth.practice
        visit=get_object_or_404(self.visits(request),pk=pk)
        try:
            with timezone.override(SAST):
                if operation in ["approve","reject","intake"]:
                    self.roles(request,["owner","reception"])
                    if operation=="approve":approve_booking(appointment_id=pk,practice=practice,actor=request.user)
                    elif operation=="reject":reject_booking(appointment_id=pk,practice=practice,actor=request.user,reason=request.data.get("reason", ""))
                    else:
                        form=IntakeForm(request.data,instance=visit)
                        if not form.is_valid():raise ValidationError(form.errors.get_json_data())
                        record_intake(appointment_id=pk,practice=practice,actor=request.user,values=form.cleaned_data)
                else:
                    self.roles(request,["doctor"])
                    if operation in ["doctor-approve","call"]:doctor_approve_booking(appointment_id=pk,practice=practice,actor=request.user,ready_now=operation=="call")
                    elif operation=="complete":complete_consultation(appointment_id=pk,practice=practice,actor=request.user)
                    elif operation=="encounter":
                        with transaction.atomic():
                            Practice.objects.select_for_update().get(pk=practice.pk)
                            visit=Appointment.objects.select_for_update().get(pk=pk,practice=practice,practitioner=request.user)
                            if not visit.doctor_approved_at or visit.status not in ["held","confirmed","arrived","completed"]:raise ValidationError("Approve this consultation first.")
                            encounter,created=Encounter.objects.get_or_create(appointment=visit,defaults={"practice":practice,"patient":visit.patient,"practitioner":request.user,"started_at":timezone.now()})
                            if created:record_audit_event(practice=practice,actor=request.user,action="encounter.started",object_type="encounter",object_id=encounter.pk,purpose="Open mobile consultation",outcome="success")
                    else:raise ValidationError("Unknown appointment action.")
        except DjangoValidationError as error:raise ValidationError(error.messages) from error
        return Response({"updated":True})


class MobileNotificationRead(MobileBase):
    def post(self, request, pk):
        notice=get_object_or_404(self.notices(request),pk=pk)
        if not notice.read_at:
            notice.read_at=timezone.now();notice.save(update_fields=["read_at"])
        return Response({"read":True})


class MobileDevices(MobileBase):
    def post(self, request):
        token=request.data.get("token", "")
        platform=request.data.get("platform")
        if not isinstance(token,str) or not re.fullmatch(r"(?:Expo|Exponent)PushToken\[[A-Za-z0-9_-]{10,200}\]",token) or platform not in ["android","ios"]:
            raise ValidationError("Invalid push device.")
        PushDevice.objects.update_or_create(token=token,defaults={"session":request.auth,"platform":platform,"active":True})
        return Response({"registered":True})

    def delete(self, request):
        request.auth.devices.update(active=False)
        return Response({"disabled":True})


class MobilePatientCreate(MobileBase):
    def post(self, request):
        self.roles(request,["owner","reception"])
        form=PatientForm(request.data,practice=request.auth.practice)
        form.instance.practice=request.auth.practice
        if not form.is_valid():raise ValidationError(form.errors.get_json_data())
        try:
            with transaction.atomic():
                patient=form.save()
                record_audit_event(practice=request.auth.practice,actor=request.user,action="patient.created",object_type="patient",
                    object_id=patient.pk,purpose="Register patient from mobile reception",outcome="success")
        except IntegrityError as error:raise ValidationError("A patient with this file number already exists.") from error
        return Response({"id":str(patient.pk)},status=201)


class MobilePrescriptionCreate(MobileBase):
    def post(self, request):
        self.roles(request,["doctor"])
        form=PrescriptionForm(request.data,practice=request.auth.practice,user=request.user)
        if not form.is_valid():raise ValidationError(form.errors.get_json_data())
        values=form.cleaned_data.copy()
        encounter=values.pop("encounter")
        instructions=values.pop("instructions")
        try:prescription=create_prescription(encounter_id=encounter.pk,actor=request.user,items=[values],general_instructions=instructions)
        except DjangoValidationError as error:raise ValidationError(error.messages) from error
        return Response({"id":prescription.pk},status=201)


class MobilePrescriptionIssue(MobileBase):
    def post(self, request, pk):
        self.roles(request,["doctor"])
        prescription=get_object_or_404(Prescription,pk=pk,encounter__practice=request.auth.practice,prescribed_by=request.user)
        if request.data.get("reviewed") is not True:raise ValidationError("Confirm review before issuing the prescription.")
        try:issue_prescription(prescription_id=prescription.pk,actor=request.user)
        except DjangoValidationError as error:raise ValidationError(error.messages) from error
        return Response({"issued":True})
